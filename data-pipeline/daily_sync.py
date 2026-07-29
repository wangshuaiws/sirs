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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
from calc_indicators import td_query_rest, apply_forward_adjustment, get_xdxr_events
from calc_indicators_rest import compute_all_np, td_rest_execute, write_one_stock, batch_read_raw, compute_one


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

    # ── 检查目标日期是否已有原始数据（避免重复抓取） ──
    try:
        check = td_query_rest(f"SELECT tbname FROM sirs.kline_1d WHERE ts = '{target_date}' LIMIT 100")
        if len(check) >= 10:
            print(f"  [Skip] 今日数据已存在 (检测到 {len(check)}+ 只)，跳过 TDX 抓取")
            all_today = td_query_rest(
                f"SELECT tbname,open,high,low,close,volume,amount,turnover "
                f"FROM sirs.kline_1d WHERE ts = '{target_date}'"
            )
            results = []
            for r in all_today:
                tbname = r.get("tbname", "")
                code = tbname.replace("k_1d_", "") if tbname.startswith("k_1d_") else ""
                if code:
                    results.append((
                        code, target_date,
                        float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]),
                        int(r.get("volume", 0)), float(r.get("amount", 0)),
                    ))
            print(f"  [Skip] 从 TDengine 读取 {len(results)} 只今日数据")
            return results  # 直接返回，不执行后续 TDX 抓取
    except Exception:
        pass

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

    return results


# ═══════════════════════════════════════════════════════════════════════
# 前复权 + 指标增量同步
# ═══════════════════════════════════════════════════════════════════════

def append_today_adjusted(results: list, target_date: str,
                          affected: set | None = None, workers: int = 4) -> int:
    """对今天有数据的股票，增量追加前复权 + 技术指标。

    规则：
      - 今天无除权事件 → 今日 adj OHLC = raw OHLC，读历史 adj 尾 233 条 → 算指标 → INSERT 1 行
      - 今天有除权事件 → DROP + 全量重算 adj + 指标
    """
    import numpy as np

    codes = list(set(r[0] for r in results))
    total = len(codes)
    print(f"\n[Phase 4/3] 计算前复权+指标 ({total} 只, {workers} workers)...")
    t0 = time.time()

    # 确保超级表存在
    try:
        td_rest_execute("CREATE STABLE IF NOT EXISTS sirs.kline_1d_adj ("
            "ts TIMESTAMP, open FLOAT, high FLOAT, low FLOAT, close FLOAT, "
            "volume BIGINT, amount DOUBLE, turnover FLOAT, "
            "ma5 DOUBLE, ma10 DOUBLE, ma20 DOUBLE, ma30 DOUBLE, ma60 DOUBLE, ma120 DOUBLE, ma233 DOUBLE, "
            "macd_dif DOUBLE, macd_dea DOUBLE, macd_hist DOUBLE, "
            "kdj_k DOUBLE, kdj_d DOUBLE, kdj_j DOUBLE, "
            "zxdq DOUBLE, zxdkx DOUBLE"
            ") TAGS (code VARCHAR(10), name VARCHAR(50))")
    except Exception:
        pass  # 已存在

    def fmt(v):
        return "NULL" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.6f}"

    def fmt_int(v):
        if v is None:
            return "NULL"
        if isinstance(v, float) and np.isnan(v):
            return "NULL"
        return str(int(v))

    affected_set = affected or set()
    ok = 0

    def process(code: str, name: str) -> bool:
        """处理单只股票"""
        # 如果 adj 表已有今日数据 → 跳过
        try:
            existing = td_query_rest(f"SELECT 1 FROM sirs.k_1d_adj_{code} WHERE ts = '{target_date}'")
            if existing:
                return True
        except Exception:
            pass

        # 判断是否需要全量重算：刚同步了新 xdxr 事件 OR 今天是除权日
        needs_full = code in affected_set
        if not needs_full:
            try:
                conn = get_pg_conn()
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM xdxr_events WHERE code = %s AND ex_date = %s", (code, target_date))
                needs_full = cur.fetchone() is not None
                cur.close()
                conn.close()
            except Exception:
                pass

        if needs_full:
            # ── 全量重算（新 xdxr 或今日除权） ──
            try:
                raw = batch_read_raw([code])
                if code not in raw or not raw[code]:
                    return False
                _, _, adj, args = compute_one(code, name, raw[code])
                return write_one_stock(code, name, adj, args)
            except Exception as e:
                print(f"  {code}: 全量重算异常 {e}")
                return False

        # ── 无新 xdxr → 增量追加 ──
        try:
            # 1. 读今日原始 bar
            raw_sql = f"SELECT ts,open,high,low,close,volume,amount,turnover FROM sirs.k_1d_{code} WHERE ts = '{target_date}'"
            raw_rows = td_query_rest(raw_sql)
            if not raw_rows:
                return False
            bar = raw_rows[0]

            adj_open  = float(bar["open"])
            adj_high  = float(bar["high"])
            adj_low   = float(bar["low"])
            adj_close = float(bar["close"])

            # 2. 尝试读历史 adj 表尾
            try:
                tail = td_query_rest(
                    f"SELECT ts,open,high,low,close FROM sirs.k_1d_adj_{code} ORDER BY ts DESC LIMIT 233"
                )
                tail.reverse()
            except Exception:
                tail = []

            # 3. 组合数组
            opens  = np.array([float(r["open"]) for r in tail]  + [adj_open],  dtype=np.float64)
            highs  = np.array([float(r["high"]) for r in tail]  + [adj_high],  dtype=np.float64)
            lows   = np.array([float(r["low"]) for r in tail]   + [adj_low],   dtype=np.float64)
            closes = np.array([float(r["close"]) for r in tail] + [adj_close], dtype=np.float64)

            # 4. 计算指标
            mas, dif, dea, hist, k, d, j, zxdq, zxdkx = compute_all_np(opens, highs, lows, closes)

            # 5. INSERT 今天这一行
            i = len(opens) - 1
            turnover_val = bar.get("turnover", "NULL")
            if turnover_val is None:
                turnover_val = "NULL"
            sql = (
                f"INSERT INTO sirs.k_1d_adj_{code} VALUES ("
                f"'{target_date}',"
                f"{adj_open},{adj_high},{adj_low},{adj_close},"
                f"{fmt_int(bar.get('volume'))},{bar.get('amount')},{turnover_val},"
                f"{fmt(mas[5][i])},{fmt(mas[10][i])},{fmt(mas[20][i])},{fmt(mas[30][i])},"
                f"{fmt(mas[60][i])},{fmt(mas[120][i])},{fmt(mas[233][i])},"
                f"{fmt(dif[i])},{fmt(dea[i])},{fmt(hist[i])},"
                f"{fmt(k[i])},{fmt(d[i])},{fmt(j[i])},"
                f"{fmt(zxdq[i])},{fmt(zxdkx[i])})"
            )
            td_rest_execute(sql)
            return True

        except Exception as e:
            print(f"  {code}: 增量追加异常 {e}")
            try:
                raw = batch_read_raw([code])
                if code not in raw or not raw[code]:
                    return False
                _, _, adj, args = compute_one(code, name, raw[code])
                return write_one_stock(code, name, adj, args)
            except Exception as e2:
                print(f"  {code}: 降级重算异常 {e2}")
                return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        fut_map = {}
        for code in codes:
            # 获取名称
            try:
                conn = get_pg_conn()
                cur = conn.cursor()
                cur.execute("SELECT name FROM stocks WHERE code = %s", (code,))
                row = cur.fetchone()
                name = row[0] if row else ""
                cur.close()
                conn.close()
            except Exception:
                name = ""
            fut = pool.submit(process, code, name)
            fut_map[fut] = code

        for f in as_completed(fut_map):
            if f.result():
                ok += 1
            if ok % 500 == 0 or ok == total:
                elapsed = time.time() - t0
                print(f"  [Adj] 进度: {ok}/{total} ({elapsed:.0f}s)", flush=True)

    elapsed = time.time() - t0
    print(f"[Phase 4] 完成 — 成功: {ok}/{total} ({elapsed:.1f}s)")
    return ok


# ═══════════════════════════════════════════════════════════════════════
# main

def main():
    parser = argparse.ArgumentParser(description="SIRS 每日增量同步（通达信，不复权）")
    parser.add_argument("--date", type=str, default=None,
                        help="指定交易日 YYYY-MM-DD，默认自动检测")
    parser.add_argument("--skip-adj", action="store_true",
                        help="跳过前复权+指标计算")
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
    results = sync_one_day(target, client)

    # 3. 先同步除权除息事件（让 adj 计算知道哪些股票需要全量重算）
    affected = set()
    if args.sync_xdxr:
        from sync_xdxr import sync_all_stocks
        affected_list = sync_all_stocks(client)
        affected = set(affected_list)
        if affected:
            print(f"[XDXR] {len(affected)} 只有新除权事件，将在 Phase 4 中全量重算")

    # 4. 前复权 + 指标计算（传入 affected，一次到位）
    if results and not args.skip_adj:
        adj_ok = append_today_adjusted(results, target, affected=affected)
        print(f"[Adj] 今日前复权完成 — {adj_ok}/{len(set(r[0] for r in results))} 只")
    elif args.skip_adj:
        print("[Skip] --skip-adj 已指定，跳过前复权计算")

    # 5. 同步动态市盈率
    try:
        from sync_pe import sync_all as sync_pe
        sync_pe()
    except Exception as e:
        print(f"[WARN] PE 同步异常: {e}")

    print("[Sync] 全部完成")


if __name__ == "__main__":
    main()
