"""
SIRS — A 股初始化数据导入脚本

数据源：通达信行情服务器（mootdx 直连 TCP 协议，不会被封 IP）

功能：
1. 创建 PostgreSQL 元数据表（stocks）
2. 创建 TDengine 数据库 + 超级表（kline_1d）
3. 从通达信获取全量 A 股列表 → 入库 stocks 表（~5200 只）
4. 逐只获取历史日K线数据（最近 800 个交易日）→ 入库 TDengine
5. 支持断点续传，中断后可跳过已完成的股票
6. 分批处理，避免压垮通达信服务器
"""

import time
import sys
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras
import requests
from tqdm import tqdm

from mootdx.quotes import Quotes

from config import (
    PG_CONFIG, TDENGINE_CONFIG,
    TDX_REQUEST_DELAY, TDX_BARS_LIMIT,
    TDX_BATCH_SIZE, TDX_BATCH_PAUSE,
    PG_BATCH_SIZE, CHECKPOINT_FILE,
    TDX_WORKERS, TDINSERT_BATCH_SIZE, TDSUBTABLE_BATCH_SIZE,
    TDX_SERVER_LIST,
)


# ── 全局通达信客户端（单连接复用）─────────────────────────────────────
_tdx_client = None

def get_tdx_client():
    """获取通达信客户端（惰性初始化，单连接复用）"""
    global _tdx_client
    if _tdx_client is None:
        _tdx_client = Quotes.factory(market='std')
    return _tdx_client


# ── 字符串清理 ────────────────────────────────────────────────────────
def clean_name(raw: str) -> str:
    """清理股票名称：去除 NUL 字符、首尾空白、不可打印字符"""
    if not raw:
        return ''
    # 移除 NUL (\0) 和其他控制字符（保留中文、字母、数字、常用符号）
    result = raw.replace(chr(0), '').strip()
    # 通达信数据偶尔在名称末尾带不可见字符，再做一层清洗
    result = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', result)
    return result


# ═══════════════════════════════════════════════════════════════════════
# PostgreSQL
# ═══════════════════════════════════════════════════════════════════════

def get_pg_conn():
    """获取 PostgreSQL 连接"""
    return psycopg2.connect(**PG_CONFIG)


def init_pg_tables():
    """创建 PostgreSQL 元数据表"""
    print("[PG] 创建 stocks 表...")
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id          BIGSERIAL PRIMARY KEY,
            code        VARCHAR(10)  NOT NULL UNIQUE,
            name        VARCHAR(50)  NOT NULL,
            exchange    VARCHAR(10),
            market      VARCHAR(20),
            industry    VARCHAR(50),
            listed_date DATE,
            is_active   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP
        );
    """)
    conn.commit()

    print("[PG] 创建 xdxr_events 表...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS xdxr_events (
            id          BIGSERIAL PRIMARY KEY,
            code        VARCHAR(10)  NOT NULL,
            ex_date     DATE         NOT NULL,
            category    INTEGER      NOT NULL,
            fenhong     DOUBLE PRECISION DEFAULT 0,
            songzhuangu DOUBLE PRECISION DEFAULT 0,
            peigu       DOUBLE PRECISION DEFAULT 0,
            peigujia    DOUBLE PRECISION DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE (code, ex_date, category)
        );
    """)
    conn.commit()

    # 幂等添加 pe_ttm 列（动态市盈率）
    cur.execute("ALTER TABLE stocks ADD COLUMN IF NOT EXISTS pe_ttm DOUBLE PRECISION;")
    conn.commit()

    cur.close()
    conn.close()
    print("[PG] stocks / xdxr_events 表就绪")


def insert_xdxr_events(code: str, xdxr_df, pg_conn):
    """将 mootdx xdxr DataFrame 中的除权事件批量写入 PG。
    返回 (total_attempted, newly_inserted)。"""
    if xdxr_df is None or xdxr_df.empty:
        return 0, 0
    cur = pg_conn.cursor()
    total = 0
    new_count = 0
    for _, row in xdxr_df.iterrows():
        try:
            ex_date = f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"
            category = int(row['category'])
            fenhong = float(row.get('fenhong', 0) or 0)
            song = float(row.get('songzhuangu', 0) or 0)
            peigu = float(row.get('peigu', 0) or 0)
            peijia = float(row.get('peigujia', 0) or 0)

            cur.execute("""
                INSERT INTO xdxr_events (code, ex_date, category, fenhong, songzhuangu, peigu, peigujia)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code, ex_date, category) DO NOTHING
            """, (code, ex_date, category, fenhong, song, peigu, peijia))
            total += 1
            if cur.rowcount > 0:
                new_count += 1
        except (ValueError, KeyError, TypeError):
            continue
    pg_conn.commit()
    cur.close()
    return total, new_count


# ═══════════════════════════════════════════════════════════════════════
# TDengine (REST API)
# ═══════════════════════════════════════════════════════════════════════

def td_rest_sql(sql: str) -> dict:
    """通过 taosAdapter REST API 执行 SQL"""
    url = f"http://{TDENGINE_CONFIG['host']}:{TDENGINE_CONFIG['port']}/rest/sql"
    resp = requests.post(
        url,
        data=sql.encode("utf-8"),
        auth=(TDENGINE_CONFIG["user"], TDENGINE_CONFIG["password"]),
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"TDengine REST error: {resp.status_code} {resp.text}")
    return resp.json()


def init_tdengine():
    """创建 TDengine 数据库 + 超级表"""
    print("[TD] 创建数据库 sirs...")
    td_rest_sql("CREATE DATABASE IF NOT EXISTS sirs KEEP 3650 DURATION 10 BUFFER 16;")
    print("[TD] 创建超级表 kline_1d...")
    td_rest_sql("""
        CREATE STABLE IF NOT EXISTS sirs.kline_1d (
            ts       TIMESTAMP,
            open     FLOAT,
            high     FLOAT,
            low      FLOAT,
            close    FLOAT,
            volume   BIGINT,
            amount   DOUBLE,
            turnover FLOAT
        ) TAGS (
            code VARCHAR(10),
            name VARCHAR(50)
        );
    """)
    print("[TD] 数据库和超级表就绪")


def create_kline_subtable(code: str, name: str):
    """为指定股票创建子表（如果不存在）"""
    tbl = f"k_1d_{code}"
    sql = (
        f"CREATE TABLE IF NOT EXISTS sirs.{tbl} "
        f"USING sirs.kline_1d TAGS ('{code}', '{name}');"
    )
    td_rest_sql(sql)
    return tbl


def insert_kline_batch(table_name: str, rows: list):
    """批量写入 K 线数据到 TDengine"""
    if not rows:
        return
    values_parts = []
    for r in rows:
        ts, o, h, l, c, v, amt, tor = r
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
        values_parts.append(
            f"('{ts_str}', {o}, {h}, {l}, {c}, {v}, {amt}, {tor})"
        )
    sql = (
        f"INSERT INTO sirs.{table_name} "
        f"(ts, open, high, low, close, volume, amount, turnover) "
        f"VALUES {' '.join(values_parts)};"
    )
    try:
        resp = td_rest_sql(sql)
        if resp.get("code") != 0:
            msg = str(resp).lower()
            if "duplicate" not in msg and "already exist" not in msg:
                print(f"  [WARN] TDengine: {resp}")
    except Exception as e:
        print(f"  [WARN] TDengine insert: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 断点续传
# ═══════════════════════════════════════════════════════════════════════

def load_checkpoint() -> set:
    """加载已完成股票代码集合"""
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())


def save_checkpoint(code: str):
    """追加一个完成的股票代码"""
    with open(CHECKPOINT_FILE, "a") as f:
        f.write(code + "\n")


# ═══════════════════════════════════════════════════════════════════════
# A 股过滤
# ═══════════════════════════════════════════════════════════════════════

# 沪市 A 股: 600–609, 688 (科创板)
RE_SH_A = re.compile(r'^6(0[0-9]|8[0-9])\d{3}$')
# 深市 A 股: 000–004, 300–301 (创业板), 002 (中小板)
RE_SZ_A = re.compile(r'^(00[0-4]|30[0-1])\d{3}$')


def is_a_share(code: str) -> bool:
    """判断是否为 A 股（排除指数、B股、基金、债券等）"""
    return bool(RE_SH_A.match(code) or RE_SZ_A.match(code))


def get_exchange(code: str) -> str:
    """根据代码判断交易所"""
    if code.startswith('6'):
        return 'SH'
    return 'SZ'


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: 股票列表导入
# ═══════════════════════════════════════════════════════════════════════

def fetch_and_insert_stock_list():
    """从通达信获取全量 A 股列表并入库 PG"""
    client = get_tdx_client()

    all_stocks = []

    # 沪市 (market=1)
    print("[TDX] 获取沪市股票列表...")
    df_sh = client.stocks(1)
    sh_a = df_sh[df_sh['code'].apply(is_a_share)]
    for _, row in sh_a.iterrows():
        all_stocks.append((str(row['code']), clean_name(str(row['name'])), 'SH'))
    print(f"[TDX] 沪市 A 股: {len(sh_a)} 只")

    # 深市 (market=0)
    print("[TDX] 获取深市股票列表...")
    df_sz = client.stocks(0)
    sz_a = df_sz[df_sz['code'].apply(is_a_share)]
    for _, row in sz_a.iterrows():
        all_stocks.append((str(row['code']), clean_name(str(row['name'])), 'SZ'))
    print(f"[TDX] 深市 A 股: {len(sz_a)} 只")

    print(f"[TDX] A 股总计: {len(all_stocks)} 只")

    # 批量写入 PG
    conn = get_pg_conn()
    cur = conn.cursor()
    inserted = 0

    for i in range(0, len(all_stocks), PG_BATCH_SIZE):
        batch = all_stocks[i:i + PG_BATCH_SIZE]
        for code, name, exchange in batch:
            name = clean_name(name)
            cur.execute(
                """
                INSERT INTO stocks (code, name, exchange, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (code) DO UPDATE
                    SET name = EXCLUDED.name,
                        exchange = EXCLUDED.exchange,
                        updated_at = NOW()
                """,
                (code, name, exchange),
            )
        conn.commit()
        inserted += len(batch)
        print(f"  [PG] 已写入 {inserted}/{len(all_stocks)}")

    cur.close()
    conn.close()
    print(f"[PG] 股票列表入库完成 — 共 {inserted} 只")


# ═══════════════════════════════════════════════════════════════════════
# 前复权计算
# ═══════════════════════════════════════════════════════════════════════

def apply_forward_adjustment(bars, xdxr):
    """
    [DEPRECATED] 不再使用前复权，改为存储原始不复权数据。保留此函数供参考。

    对不复权的日K线 OHLC 数据应用前复权。

    通达信前复权算法：从最近一次除权除息向前逐次复权。
    - 现金分红（category=1）：factor = (前一日收盘 - 每股分红) / 前一日收盘
    - 送转股（category=2/3/4/5 等）：factor = 1 / (1 + 送转比例/10)
    - 配股：factor = (前一日收盘 + 配股价 × 配股比例/10) / (前一日收盘 × (1 + 配股比例/10))

    返回：调整后的 bars（OHLC 价格已前复权，volume/amount 不变）
    """
    import pandas as pd

    if xdxr is None or xdxr.empty:
        return bars

    adj = bars.copy()
    # 保存原始收盘价，用于计算现金分红因子（必须用原始价，否则累积会递减到负数）
    raw_close = adj['close'].copy()

    # 收集有效的除权除息事件
    events = []
    for _, r in xdxr.iterrows():
        try:
            d = pd.Timestamp(year=int(r['year']), month=int(r['month']), day=int(r['day']))
        except (ValueError, OverflowError):
            continue

        cat = int(r['category'])
        fen = float(r['fenhong']) if not pd.isna(r['fenhong']) else 0.0
        song = float(r['songzhuangu']) if not pd.isna(r['songzhuangu']) else 0.0
        pei = float(r['peigu']) if not pd.isna(r['peigu']) else 0.0
        peijia = float(r['peigujia']) if not pd.isna(r['peigujia']) else 0.0

        # 只处理有实际影响的除权除息事件
        if fen > 0 or song > 0 or pei > 0:
            events.append((d, cat, fen, song, pei, peijia))

    if not events:
        return bars

    # 按日期从新到旧排序
    events.sort(key=lambda x: x[0], reverse=True)

    for evt_date, cat, fen, song, pei, peijia in events:
        # 除权日之前的 K 线需要调整
        mask = adj.index < evt_date
        if not mask.any():
            continue

        factor = 1.0

        # 现金分红（category=1），fenhong 是每10股派息，需 /10；用原始收盘价计算因子
        if cat == 1 and fen > 0:
            prev_bars = raw_close[adj.index < evt_date]
            if prev_bars.empty:
                continue
            orig_cb = float(prev_bars.iloc[-1])
            fen_per_share = fen / 10.0
            if orig_cb > 0:
                factor = (orig_cb - fen_per_share) / orig_cb

        # 送转股（category 1-14 都可能包含，与现金分红不互斥）
        if song > 0:
            factor *= 1.0 / (1.0 + song / 10.0)

        # 配股（category 1-14 都可能包含，用原始收盘价）
        if pei > 0 and peijia > 0:
            prev_bars = raw_close[adj.index < evt_date]
            if not prev_bars.empty:
                orig_cb = float(prev_bars.iloc[-1])
                if orig_cb > 0:
                    pei_factor = (
                        (orig_cb + peijia * pei / 10.0) /
                        (orig_cb * (1.0 + pei / 10.0))
                    )
                    factor *= pei_factor

        # 应用复权因子
        if factor != 1.0:
            adj.loc[mask, ['open', 'high', 'low', 'close']] *= factor

    return adj


# ═══════════════════════════════════════════════════════════════════════
# Phase 4: 历史 K 线导入
# ═══════════════════════════════════════════════════════════════════════

def import_historical_klines():
    """逐只导入历史日K线（最近 800 个交易日，不复权原始数据）"""
    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT code, name FROM stocks WHERE is_active = TRUE ORDER BY code")
    stocks = cur.fetchall()
    cur.close()
    conn.close()

    completed = load_checkpoint()
    remaining = [s for s in stocks if s["code"] not in completed]

    print(f"[K线] 总数: {len(stocks)}, 已完成: {len(completed)}, 剩余: {len(remaining)}")

    if not remaining:
        print("[K线] 所有股票已完成，无需导入")
        return

    client = get_tdx_client()
    success = 0
    fail = 0

    for i, stock in enumerate(tqdm(remaining, desc="导入历史日K")):
        code = stock["code"]
        name = stock["name"]
        market = 1 if code.startswith('6') else 0

        try:
            # 确保子表存在
            create_kline_subtable(code, name)

            # 从通达信获取日K线（不复权原始数据）
            raw = client.bars(symbol=code, frequency=9, market=market,
                              start=0, offset=TDX_BARS_LIMIT)

            if raw is None or raw.empty:
                save_checkpoint(code)
                success += 1
                time.sleep(TDX_REQUEST_DELAY)
                continue

            # 直接使用通达信原始不复权数据
            df = raw

            if df is None or df.empty:
                save_checkpoint(code)
                success += 1
                time.sleep(TDX_REQUEST_DELAY)
                continue

            # 转换为 TDengine 插入格式
            rows = []
            for idx, row in df.iterrows():
                try:
                    ts = idx  # pandas Timestamp
                    if not hasattr(ts, 'strftime'):
                        continue

                    o = float(row['open'])
                    h = float(row['high'])
                    l = float(row['low'])
                    c = float(row['close'])
                    v = int(row.get('vol', row.get('volume', 0)))
                    amt = float(row['amount'])
                    tor = 0.0
                except (ValueError, KeyError, TypeError):
                    continue
                rows.append((ts, o, h, l, c, v, amt, tor))

            if rows:
                insert_kline_batch(f"k_1d_{code}", rows)

            save_checkpoint(code)
            success += 1

        except Exception as e:
            fail += 1
            print(f"\n[ERROR] {code} {name}: {e}")
            save_checkpoint(code)

        # 速率控制
        time.sleep(TDX_REQUEST_DELAY)

        # 每 N 只股票暂停一下
        if (i + 1) % TDX_BATCH_SIZE == 0:
            print(f"\n  ... 已处理 {i + 1}/{len(remaining)}，暂停 {TDX_BATCH_PAUSE}s ...")
            time.sleep(TDX_BATCH_PAUSE)

    print(f"[K线] 历史日K导入完成 — 成功: {success}, 失败: {fail}")


# ═══════════════════════════════════════════════════════════════════════
# 多服务器并发 & 批量操作（daily_sync.py 使用）
# ═══════════════════════════════════════════════════════════════════════

def ping_tdx_servers(hosts=None, port=7709, timeout=3, top_n=None):
    """TCP 连接测速，返回按延迟排序的服务器列表。

    模仿 resource/hosts.go 的 FastHosts 逻辑：对每个服务器发起 TCP
    连接并测量耗时，按从快到慢排序。

    Args:
        hosts: 服务器列表，可以是 (host, port) tuples 或纯 IP 字符串列表。
               默认使用 TDX_SERVER_LIST。
        port: 当 hosts 中元素为字符串时使用的默认端口
        timeout: 单次连接超时秒数
        top_n: 只返回最快的 N 个，默认返回全部

    Returns:
        list of (host, port) tuples，按延迟升序排列
    """
    if hosts is None:
        hosts = TDX_SERVER_LIST

    # 统一为 (host, port) 格式
    normalized = []
    for item in hosts:
        if isinstance(item, (tuple, list)):
            normalized.append((item[0], int(item[1])))
        else:
            normalized.append((item, port))

    results = {}

    def _test_one(host, p):
        try:
            start = time.time()
            sock = socket.create_connection((host, p), timeout=timeout)
            elapsed = time.time() - start
            sock.close()
            return (host, p, elapsed)
        except Exception:
            return (host, p, float('inf'))

    with ThreadPoolExecutor(max_workers=min(20, len(normalized))) as executor:
        futures = {executor.submit(_test_one, h, p): (h, p) for h, p in normalized}
        for f in as_completed(futures):
            host, p, elapsed = f.result()
            if elapsed != float('inf'):
                results[(host, p)] = elapsed

    sorted_servers = sorted(results.keys(), key=lambda k: results[k])
    if top_n:
        sorted_servers = sorted_servers[:top_n]

    return sorted_servers


def batch_create_subtables(stocks, chunk_size=None):
    """批量创建股票子表，减少 TDengine REST 调用次数。

    将多条 ``CREATE TABLE IF NOT EXISTS ... USING ... TAGS (...)``
    拼接为一条 SQL 发送。

    Args:
        stocks: list of (code, name) tuples
        chunk_size: 每条 SQL 最多创建的表的数量，默认 TDSUBTABLE_BATCH_SIZE
    """
    if chunk_size is None:
        chunk_size = TDSUBTABLE_BATCH_SIZE

    parts = []
    for code, name in stocks:
        safe_name = name.replace("'", "''")
        parts.append(
            f"CREATE TABLE IF NOT EXISTS sirs.k_1d_{code} "
            f"USING sirs.kline_1d TAGS ('{code}', '{safe_name}');"
        )

    total = len(parts)
    for i in range(0, total, chunk_size):
        chunk = parts[i:i + chunk_size]
        sql = " ".join(chunk)
        try:
            resp = td_rest_sql(sql)
            if resp.get("code") != 0:
                print(f"  [WARN] batch_create_subtables [{i}-{i+len(chunk)}]: {resp}")
        except Exception as e:
            print(f"  [WARN] batch_create_subtables [{i}-{i+len(chunk)}]: {e}")

    print(f"  [DDL] {total} 只股票子表已就绪")


def batch_insert_daily(results, batch_size=None):
    """批量写入多只股票的日K数据到 TDengine。

    使用 TDengine 多表 INSERT 语法：
        INSERT INTO tbl1 VALUES (...) tbl2 VALUES (...) ...;

    Args:
        results: list of tuples (code, ts_str, open, high, low, close, volume, amount)
        batch_size: 每条 SQL 最多包含的股票数，默认 TDINSERT_BATCH_SIZE

    Returns:
        int: 成功写入的条数
    """
    if not results:
        return 0

    if batch_size is None:
        batch_size = TDINSERT_BATCH_SIZE

    inserted = 0
    for i in range(0, len(results), batch_size):
        batch = results[i:i + batch_size]
        parts = []
        for r in batch:
            code, ts_str, o, h, l, c, v, amt = r
            parts.append(
                f"sirs.k_1d_{code} VALUES "
                f"('{ts_str}', {o}, {h}, {l}, {c}, {v}, {amt}, 0.0)"
            )
        sql = f"INSERT INTO {' '.join(parts)};"
        try:
            resp = td_rest_sql(sql)
            if resp.get("code") != 0:
                msg = str(resp).lower()
                if "duplicate" not in msg and "already exist" not in msg:
                    print(f"  [WARN] batch_insert [{i}-{i+len(batch)}]: {resp}")
            else:
                inserted += len(batch)
        except Exception as e:
            print(f"  [WARN] batch_insert [{i}-{i+len(batch)}]: {e}")

    return inserted


# ═══════════════════════════════════════════════════════════════════════

def main():
    """主入口。支持 --kline-only / --sync-xdxr。"""
    import argparse
    parser = argparse.ArgumentParser(description="SIRS 初始化数据导入（通达信）")
    parser.add_argument("--kline-only", action="store_true",
                        help="仅重导 K 线，跳过 PG 建表和股票列表导入")
    parser.add_argument("--sync-xdxr", action="store_true",
                        help="仅同步除权除息事件（不重导 K 线）")
    args = parser.parse_args()

    print("=" * 50)
    print("SIRS — 初始化数据导入（数据源：通达信）")
    print("=" * 50)

    # --sync-xdxr 模式：仅同步除权事件
    if args.sync_xdxr:
        print("[MODE] 仅同步除权事件")
        init_pg_tables()  # 确保 xdxr_events 表存在（幂等）
        from sync_xdxr import sync_all_stocks
        sync_all_stocks()
        print("\n[DONE] 除权事件同步完成")
        return

    if not args.kline_only:
        # 1. PG 建表
        init_pg_tables()

        # 2. TDengine 建库 & 超级表
        init_tdengine()

        # 3. 导入 A 股列表
        fetch_and_insert_stock_list()
    else:
        print("[SKIP] 跳过建表和股票列表，仅导入 K 线")
        # 确保 TDengine 库和超级表存在
        init_tdengine()

    # 4. 导入历史 K 线
    import_historical_klines()

    # 5. 同步除权除息事件
    print("\n[MODE] 同步除权除息事件...")
    from sync_xdxr import sync_all_stocks
    sync_all_stocks()

    print("\n[DONE] 初始化数据导入全部完成")


if __name__ == "__main__":
    main()
