"""
SIRS — 每日增量同步脚本

数据源：通达信行情服务器（mootdx 直连 TCP 协议）

功能：
1. 同步股票元数据（新股入库、名称变更、退市标记）
2. 获取最近交易日日K线 → 幂等写入 TDengine（不复权）
3. 同步除权除息事件
4. 由 crontab 调度：每个工作日 15:40 执行

用法：
    python daily_sync.py             # 同步最近交易日
    python daily_sync.py --date 2025-01-15  # 同步指定日期
"""

import time
import math
import argparse
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm
from mootdx.quotes import Quotes

from config import (
    TDX_REQUEST_DELAY, TDX_BARS_LIMIT,
    TDX_BATCH_SIZE, TDX_BATCH_PAUSE,
    TDX_WORKERS, TDX_SERVER_LIST,
)

# ── 复用 init_stocks 全部核心函数，避免代码冗余 ──
from init_stocks import (
    is_a_share, clean_name, get_tdx_client,
    create_kline_subtable,
    insert_kline_batch, get_pg_conn, td_rest_sql,
    insert_xdxr_events,  # 仅 _import_one_stock_history 新股导入时使用
    batch_create_subtables, batch_insert_daily, ping_tdx_servers,
)


# ═══════════════════════════════════════════════════════════════════════
# 交易日检测
# ═══════════════════════════════════════════════════════════════════════

def get_latest_trading_day(client) -> str:
    """用平安银行最近一条日K日期作为参考交易日"""
    try:
        df = client.bars(symbol='000001', frequency=9, market=0, start=0, offset=1)
        if df is not None and not df.empty:
            ts = df.index[-1]
            if hasattr(ts, 'strftime'):
                return ts.strftime("%Y-%m-%d")
            return str(ts)[:10]
    except Exception as e:
        print(f"[WARN] 获取交易日失败: {e}")

    today = date.today()
    if today.weekday() >= 5:
        today = today - timedelta(days=today.weekday() - 4)
    return today.isoformat()


# ═══════════════════════════════════════════════════════════════════════
# 新股检测 & 历史K线导入
# ═══════════════════════════════════════════════════════════════════════

def sync_stock_metadata(client):
    """
    对比通达信全量 A 股列表与 PG stocks 表，完成三项工作：
    1. 新股入库 + 拉取历史K线
    2. 名称变更更新（ST / *ST / 公司更名）
    3. 退市股票标记 is_active = FALSE
    """
    conn = get_pg_conn()
    cur = conn.cursor()

    # ── 收集通达信全量 A 股：{code: name} ──
    tdx_names = {}
    for market in (1, 0):
        df = client.stocks(market)
        for _, row in df.iterrows():
            code = str(row['code'])
            if is_a_share(code):
                tdx_names[code] = clean_name(str(row['name']))

    # ── 查询 PG 现有股票 ──
    cur.execute("SELECT code, name, is_active FROM stocks")
    pg_stocks = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    new_codes = []
    name_updates = []
    reactivated = []
    delisted = []

    for code, tdx_name in tdx_names.items():
        if code in pg_stocks:
            pg_name, is_active = pg_stocks[code]
            # 名称变更
            if pg_name != tdx_name:
                name_updates.append((code, pg_name, tdx_name))
            # 恢复上市（之前标记退市的股票重新出现）
            if not is_active:
                reactivated.append((code, pg_name, tdx_name))
        else:
            # 新股
            exchange = 'SH' if code.startswith('6') else 'SZ'
            new_codes.append((code, tdx_name, exchange))

    # 退市检测：PG 中有但 TDX 中没有的活跃股票
    for code, (pg_name, is_active) in pg_stocks.items():
        if is_active and code not in tdx_names:
            delisted.append((code, pg_name))

    # ── 1. 新股入库 ──
    if new_codes:
        print(f"[Meta] 新股: {len(new_codes)} 只")
        for code, name, exchange in new_codes:
            cur.execute(
                """INSERT INTO stocks (code, name, exchange, is_active)
                   VALUES (%s, %s, %s, TRUE)
                   ON CONFLICT (code) DO UPDATE
                       SET name = EXCLUDED.name, exchange = EXCLUDED.exchange,
                           updated_at = NOW()""",
                (code, name, exchange),
            )
        conn.commit()
        print(f"[Meta] 新股 PG 入库完成 — {len(new_codes)} 只")
    else:
        print("[Meta] 无新股")

    # ── 2. 名称变更 ──
    if name_updates:
        print(f"[Meta] 名称变更: {len(name_updates)} 只")
        for code, old_name, new_name in name_updates:
            cur.execute(
                "UPDATE stocks SET name = %s, updated_at = NOW() WHERE code = %s",
                (new_name, code),
            )
            print(f"  [Name] {code}: {old_name} → {new_name}")
        conn.commit()

    # ── 3. 恢复上市 ──
    if reactivated:
        for code, old_name, tdx_name in reactivated:
            cur.execute(
                "UPDATE stocks SET is_active = TRUE, name = %s, updated_at = NOW() WHERE code = %s",
                (tdx_name, code),
            )
            print(f"  [Reactivate] {code} {old_name} → 恢复上市 (新名: {tdx_name})")
        conn.commit()

    # ── 4. 退市标记 ──
    if delisted:
        print(f"[Meta] 退市: {len(delisted)} 只")
        for code, name in delisted:
            cur.execute(
                "UPDATE stocks SET is_active = FALSE, updated_at = NOW() WHERE code = %s",
                (code,),
            )
            print(f"  [Delist] {code} {name} → 已退市")
        conn.commit()

    if not name_updates and not delisted:
        print("[Meta] 名称无变更，无退市")

    cur.close()
    conn.close()

    # ── 5. 为新股拉取全量历史K线 ──
    if new_codes:
        print(f"\n[新股] 开始拉取历史K线...")
        ok = 0
        for code, name, _ in tqdm(new_codes, desc="新股历史日K"):
            if _import_one_stock_history(client, code, name):
                ok += 1
            time.sleep(TDX_REQUEST_DELAY)
        print(f"[新股] 历史K线完成 — 成功: {ok}/{len(new_codes)}")


def _import_one_stock_history(client, code, name) -> bool:
    """为单只股票导入全量历史日K线（不复权原始数据）。"""
    market = 1 if code.startswith('6') else 0
    try:
        create_kline_subtable(code, name)

        raw = client.bars(symbol=code, frequency=9, market=market,
                          start=0, offset=TDX_BARS_LIMIT)
        if raw is None or raw.empty:
            return True  # 新上市股票可能暂无K线

        # 直接使用通达信原始不复权数据
        df = raw

        rows = []
        for idx, row in df.iterrows():
            try:
                ts = idx
                if not hasattr(ts, 'strftime'):
                    continue
                rows.append((
                    ts,
                    float(row['open']), float(row['high']),
                    float(row['low']), float(row['close']),
                    int(row.get('vol', row.get('volume', 0))),
                    float(row['amount']),
                    0.0,
                ))
            except (ValueError, KeyError, TypeError):
                continue

        if rows:
            insert_kline_batch(f"k_1d_{code}", rows)

        # 同步拉取除权除息事件
        try:
            xdxr_df = client.xdxr(code)
            if xdxr_df is not None and not xdxr_df.empty:
                conn = get_pg_conn()
                insert_xdxr_events(code, xdxr_df, conn)
                conn.close()
        except Exception as e:
            print(f"  [WARN] {code} xdxr: {e}")

        return True
    except Exception as e:
        print(f"\n[ERROR] 新股 {code} {name}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# 日K增量同步
# ═══════════════════════════════════════════════════════════════════════

def _fetch_chunk(stocks, server, target_date):
    """单个 worker：连接指定通达信服务器，串行获取一批股票的日K数据。

    每个 worker 内部行为和原来完全一致——串行 + sleep(TDX_REQUEST_DELAY)，
    只是连接到不同的通达信服务器，这样每台服务器看到的请求速率不变。

    Args:
        stocks: list of (code, name) tuples
        server: (host, port) tuple
        target_date: 目标交易日 YYYY-MM-DD

    Returns:
        list of tuples (code, ts_str, open, high, low, close, volume, amount)
    """
    host, port = server
    client = Quotes.factory(market='std', server=(host, port))
    results = []
    for code, name in stocks:
        market = 1 if code.startswith('6') else 0
        time.sleep(TDX_REQUEST_DELAY)

        try:
            raw = client.bars(symbol=code, frequency=9, market=market,
                              start=0, offset=5)
            if raw is None or raw.empty:
                continue

            for idx, row in raw.iterrows():
                ts_str = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10]
                if ts_str == target_date:
                    results.append((
                        code, ts_str,
                        float(row['open']), float(row['high']),
                        float(row['low']), float(row['close']),
                        int(row.get('vol', row.get('volume', 0))),
                        float(row['amount']),
                    ))
                    break
        except Exception:
            pass  # 单只失败不影响整批

    return results


# ═══════════════════════════════════════════════════════════════════════
# 日K增量同步（多服务器并发版）
# ═══════════════════════════════════════════════════════════════════════

def sync_one_day(target_date: str, client=None):
    """增量追加最新交易日日K（不复权原始数据）。多服务器并发版。

    Args:
        target_date: YYYY-MM-DD
        client: 保留参数兼容旧调用方，不再使用
    """
    print(f"[Sync] 目标交易日: {target_date}")

    # ── 查询活跃股票 ──
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT code, name FROM stocks WHERE is_active = TRUE ORDER BY code")
    stocks = cur.fetchall()
    cur.close()
    conn.close()

    total = len(stocks)
    print(f"[Sync] 活跃股票数: {total}")

    # ── Phase 0: 选最快的 N 个服务器 ──
    print(f"[Phase 0] 测速 {len(TDX_SERVER_LIST)} 个服务器...")
    fast_servers = ping_tdx_servers(TDX_SERVER_LIST, top_n=TDX_WORKERS)
    if len(fast_servers) < TDX_WORKERS:
        print(f"  [WARN] 仅 {len(fast_servers)}/{TDX_WORKERS} 个服务器可达，使用可达服务器")
    print(f"  [Servers] 选中 ({len(fast_servers)}): {', '.join(f'{h}:{p}' for h,p in fast_servers)}")

    # ── Phase 1: 批量创建子表 ──
    print(f"[Phase 1/3] 批量创建子表...")
    batch_create_subtables(stocks)

    # ── Phase 2: 多服务器并发获取 ──
    n_workers = len(fast_servers)
    print(f"[Phase 2/3] 并发获取日K ({n_workers} workers)...")
    fetch_start = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        chunk_size = math.ceil(total / n_workers)
        futures = []
        for i, server in enumerate(fast_servers):
            chunk = stocks[i * chunk_size: (i + 1) * chunk_size]
            futures.append(
                executor.submit(_fetch_chunk, chunk, server, target_date)
            )
        for f in futures:
            results.extend(f.result())

    success = len(results)
    fetch_elapsed = time.time() - fetch_start
    print(f"  [Fetch] 成功: {success}, 跳过: {total - success} ({fetch_elapsed:.1f}s)")

    # ── Phase 3: 批量写入 TDengine ──
    if results:
        print(f"[Phase 3/3] 批量写入 TDengine...")
        insert_start = time.time()
        inserted = batch_insert_daily(results)
        insert_elapsed = time.time() - insert_start
        print(f"  [Insert] {inserted} 条写入 ({insert_elapsed:.1f}s)")
    else:
        print("[Phase 3/3] 无数据需要写入")

    total_elapsed = time.time() - fetch_start
    print(f"\n[Sync] 完成 — 成功: {success}, 总耗时: {total_elapsed:.1f}s")


# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SIRS 每日增量同步（通达信，不复权）")
    parser.add_argument("--date", type=str, default=None,
                        help="指定交易日 YYYY-MM-DD，默认自动检测")
    parser.add_argument("--sync-xdxr", action="store_true",
                        help="K 线同步完成后，顺带同步除权除息事件")
    args = parser.parse_args()

    print(f"[Sync] 开始 — {datetime.now().isoformat()}")
    print("=" * 50)

    client = Quotes.factory(market='std')

    target = args.date or get_latest_trading_day(client)
    print(f"[Sync] 目标交易日: {target}")

    # 1. 同步股票元数据（新股入库、名称变更、退市标记）
    sync_stock_metadata(client)

    # 2. 增量日K同步
    sync_one_day(target, client)

    # 3. 按需同步除权除息事件（相对低频，单独一个阶段）
    if args.sync_xdxr:
        print("\n[MODE] 同步除权除息事件...")
        from sync_xdxr import sync_all_stocks
        affected = sync_all_stocks(client)

        # 4. 复权事件变更 → 重算该股票的前复权指标
        if affected:
            print(f"\n[Recompute] {len(affected)} 只有新除权事件，重算前复权+指标...")
            from calc_indicators_rest import batch_read_raw, compute_one, write_one_stock
            recompute_ok = 0
            for code in affected:
                try:
                    raw = batch_read_raw([code])
                    if code not in raw or not raw[code]:
                        print(f"  {code}: 无原始数据，跳过")
                        continue
                    _, name, adj, args = compute_one(code, "", raw[code])
                    if write_one_stock(code, name, adj, args):
                        recompute_ok += 1
                        print(f"  {code} {name}: {len(adj)} bars 重算完成")
                    else:
                        print(f"  {code}: 写入失败")
                except Exception as e:
                    print(f"  {code}: 重算异常 {e}")
            print(f"[Recompute] 完成 — 成功: {recompute_ok}/{len(affected)}")

    print("[Sync] 全部完成")


if __name__ == "__main__":
    main()
