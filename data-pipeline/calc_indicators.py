"""
前复权 K 线指标预计算模块

用法：
  python calc_indicators.py --code 000001            # 单只股票
  python calc_indicators.py --all                     # 全部股票
  python calc_indicators.py --code 000001 --dry-run   # 只算不写
"""

import argparse
import json
import threading
import time
import urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras
import taosws

from config import PG_CONFIG, TDENGINE_CONFIG

# ── TDengine 连接 ──────────────────────────────────────────────────────

TD_REST = f"http://{TDENGINE_CONFIG['host']}:{TDENGINE_CONFIG['port']}/rest/sql"
TD_AUTH = "Basic " + b64encode(
    f"{TDENGINE_CONFIG['user']}:{TDENGINE_CONFIG['password']}".encode()
).decode()
TD_DSN = f"taosws://{TDENGINE_CONFIG['user']}:{TDENGINE_CONFIG['password']}@{TDENGINE_CONFIG['host']}:{TDENGINE_CONFIG['port']}"

# REST 读大结果集（一次返回比 WS 逐行迭代快）
def td_query_rest(sql: str) -> list[dict]:
    data = sql.encode("utf-8")
    req = urllib.request.Request(TD_REST, data=data, headers={"Authorization": TD_AUTH})
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    if str(result.get("code", "")) != "0":
        raise RuntimeError(f"TDengine error: {result}")
    col_names = [str(c[0]) for c in result.get("column_meta", []) if isinstance(c, list)]
    rows = []
    for row in result.get("data", []):
        d = {}
        for i, val in enumerate(row):
            name = col_names[i] if i < len(col_names) else f"col{i}"
            if name == "ts" and isinstance(val, str) and len(val) > 10:
                val = val[:10]
            d[name] = val
        rows.append(d)
    return rows

# WS 写大批量 INSERT（无 HTTP 连接开销）
_ws_local = threading.local()

def _ws():
    if not hasattr(_ws_local, "conn"):
        _ws_local.conn = taosws.connect(TD_DSN)
    return _ws_local.conn

def td_execute(sql: str) -> bool:
    try:
        _ws().execute(sql)
        return True
    except Exception as e:
        print(f"  TDengine error: {e}")
        return False


# ── PG 工具 ────────────────────────────────────────────────────────────

def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def get_xdxr_events(code: str) -> list[dict]:
    """获取某只股票的除权除息事件，按 ex_date DESC 排序"""
    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT ex_date, category, fenhong, songzhuangu, peigu, peigujia "
        "FROM xdxr_events WHERE code = %s ORDER BY ex_date DESC",
        (code,),
    )
    events = cur.fetchall()
    cur.close()
    conn.close()
    return events


# ── 指标计算 ───────────────────────────────────────────────────────────

def calc_ma(values: list[float], n: int) -> list[float | None]:
    """简单移动平均 MA(N)"""
    result = [None] * len(values)
    for i in range(n - 1, len(values)):
        s = sum(values[i - n + 1 : i + 1])
        result[i] = round(s / n, 2)
    return result


def _ema_of(values: list[float], n: int) -> list[float | None]:
    """EMA(N) — 首日收盘价初始化，前 N-1 为 None"""
    result = [None] * len(values)
    k = 2.0 / (n + 1)
    for i in range(len(values)):
        if i < n - 1:
            continue
        if i == n - 1:
            result[i] = values[i]
        else:
            result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def calc_macd(closes: list[float]):
    """MACD(12,26,9) → dif, dea, hist"""
    ema12 = _ema_of(closes, 12)
    ema26 = _ema_of(closes, 26)
    length = len(closes)

    dif = [None] * length
    for i in range(length):
        if ema12[i] is not None and ema26[i] is not None:
            dif[i] = round(ema12[i] - ema26[i], 4)

    # 提取有效 dif 值算 DEA
    vals = [v for v in dif if v is not None]
    idxs = [i for i, v in enumerate(dif) if v is not None]
    dea_vals = _ema_of(vals, 9)
    dea = [None] * length
    hist = [None] * length
    for j, idx in enumerate(idxs):
        if dea_vals[j] is not None:
            dea[idx] = round(dea_vals[j], 4)
            hist[idx] = round((dif[idx] - dea[idx]) * 2, 4)

    return dif, dea, hist


def calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    """KDJ(9,3,3) → k, d, j"""
    length = len(closes)
    k = [None] * length
    d = [None] * length
    j = [None] * length

    for i in range(n - 1, length):
        start = i - n + 1
        h_max = max(highs[start : i + 1])
        l_min = min(lows[start : i + 1])
        rsv = 50.0 if h_max == l_min else (closes[i] - l_min) / (h_max - l_min) * 100.0

        prev_k = 50.0 if i == n - 1 else (k[i - 1] if k[i - 1] is not None else 50.0)
        prev_d = 50.0 if i == n - 1 else (d[i - 1] if d[i - 1] is not None else 50.0)

        cur_k = (2.0 / m1) * prev_k + (1.0 / m1) * rsv
        cur_d = (2.0 / m2) * prev_d + (1.0 / m2) * cur_k
        cur_j = 3.0 * cur_k - 2.0 * cur_d

        k[i] = round(cur_k, 2)
        d[i] = round(cur_d, 2)
        j[i] = round(cur_j, 2)

    return k, d, j


def calc_zxdq(closes):
    """ZXDQ: EMA(EMA(C,10),10)"""
    ema10 = _ema_of(closes, 10)
    vals = [v for v in ema10 if v is not None]
    idxs = [i for i, v in enumerate(ema10) if v is not None]
    ema2 = _ema_of(vals, 10)
    result = [None] * len(closes)
    for j, idx in enumerate(idxs):
        if ema2[j] is not None:
            result[idx] = round(ema2[j], 2)
    return result


def calc_zxdkx(closes):
    """ZXDKX: (MA14+MA28+MA57+MA114)/4"""
    m14 = calc_ma(closes, 14)
    m28 = calc_ma(closes, 28)
    m57 = calc_ma(closes, 57)
    m114 = calc_ma(closes, 114)
    result = [None] * len(closes)
    for i in range(len(closes)):
        if all(x[i] is not None for x in (m14, m28, m57, m114)):
            result[i] = round((m14[i] + m28[i] + m57[i] + m114[i]) / 4, 2)
    return result


def compute_all_indicators(opens, highs, lows, closes):
    """一次计算所有指标，返回各指标数组"""
    mas = {
        5: calc_ma(closes, 5),
        10: calc_ma(closes, 10),
        20: calc_ma(closes, 20),
        30: calc_ma(closes, 30),
        60: calc_ma(closes, 60),
        120: calc_ma(closes, 120),
        233: calc_ma(closes, 233),
    }
    macd_dif, macd_dea, macd_hist = calc_macd(closes)
    kdj_k, kdj_d, kdj_j = calc_kdj(highs, lows, closes)
    zxdq = calc_zxdq(closes)
    zxdkx = calc_zxdkx(closes)
    return mas, macd_dif, macd_dea, macd_hist, kdj_k, kdj_d, kdj_j, zxdq, zxdkx


# ── 前复权计算（纯 Python，匹配 Java 算法）───────────────────────────────

def apply_forward_adjustment(bars: list[dict], events: list[dict]) -> list[dict]:
    """对 OHLC 应用前复权，返回调整后的 bars 列表（volume/amount 不变）"""
    if not events:
        return bars

    # 保存原始收盘价（用于计算现金分红因子）
    raw_close = {}
    for bar in bars:
        ts = bar.get("ts", "")
        raw_close[ts] = float(bar.get("close", 0) or 0)

    # 按 ex_date DESC 排序（从新到旧）
    events_sorted = sorted(events, key=lambda e: str(e.get("ex_date", "")), reverse=True)

    for evt in events_sorted:
        ex_date = str(evt.get("ex_date", ""))
        cat = int(evt.get("category", 0))
        fen = float(evt.get("fenhong", 0) or 0)
        song = float(evt.get("songzhuangu", 0) or 0)
        pei = float(evt.get("peigu", 0) or 0)
        peijia = float(evt.get("peigujia", 0) or 0)

        if fen <= 0 and song <= 0 and pei <= 0:
            continue

        # 找除权日前最后一个 bar（从后往前找）
        last_before_idx = -1
        last_before_ts = None
        for i in range(len(bars) - 1, -1, -1):
            bar_ts = bars[i].get("ts", "")
            if bar_ts and bar_ts < ex_date:
                last_before_idx = i
                last_before_ts = bar_ts
                break
        if last_before_idx < 0:
            continue

        factor = 1.0

        # 现金分红
        if cat == 1 and fen > 0:
            orig_close = raw_close.get(last_before_ts, 0) if last_before_ts else 0
            fen_per_share = fen / 10.0
            if orig_close > 0:
                factor = (orig_close - fen_per_share) / orig_close

        # 送转股
        if song > 0:
            factor *= 1.0 / (1.0 + song / 10.0)

        # 配股
        if pei > 0 and peijia > 0:
            orig_close = raw_close.get(last_before_ts, 0) if last_before_ts else 0
            if orig_close > 0:
                pei_factor = (orig_close + peijia * pei / 10.0) / (
                    orig_close * (1.0 + pei / 10.0)
                )
                factor *= pei_factor

        # 应用到除权日之前的所有 bars
        if abs(factor - 1.0) > 0.0001:
            for i in range(last_before_idx + 1):
                for key in ("open", "high", "low", "close"):
                    bars[i][key] = float(bars[i].get(key, 0) or 0) * factor

    return bars


# ── 主流程：单只股票 ────────────────────────────────────────────────────

def compute_for_stock(code: str, name: str = "", dry_run: bool = False) -> bool:
    """为单只股票计算前复权+指标，写入 kline_1d_adj"""
    t0 = time.time()

    # 1. 从 TDengine 读取原始日K线
    subtable = f"sirs.k_1d_{code}"
    bars = td_query_rest(f"SELECT ts, open, high, low, close, volume, amount, turnover FROM {subtable} ORDER BY ts")
    if not bars:
        print(f"  {code}: no raw data in TDengine, skip")
        return False

    # 2. 从 PG 读取除权事件
    events = get_xdxr_events(code)

    # 3. 应用前复权
    adj_bars = apply_forward_adjustment(bars, events)

    # 4. 提取 OHLC 数组
    opens = [float(b.get("open", 0) or 0) for b in adj_bars]
    highs = [float(b.get("high", 0) or 0) for b in adj_bars]
    lows = [float(b.get("low", 0) or 0) for b in adj_bars]
    closes = [float(b.get("close", 0) or 0) for b in adj_bars]

    # 5. 计算指标
    mas, dif, dea, hist, k, d, j, zxdq, zxdkx = compute_all_indicators(opens, highs, lows, closes)

    if dry_run:
        elapsed = time.time() - t0
        print(f"  {code} {name}: {len(adj_bars)} bars computed (dry-run, {elapsed:.1f}s)")
        return True

    # 6. 创建子表
    table_name = f"sirs.k_1d_adj_{code}"
    td_execute(f"DROP TABLE IF EXISTS {table_name}")
    td_execute(f"CREATE TABLE {table_name} USING sirs.kline_1d_adj TAGS ('{code}', '{name}')")

    # 7. 批量 INSERT（每批 3000 条，WS 执行）
    batch_size = 3000
    total = len(adj_bars)
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = adj_bars[start:end]
        values_parts = []
        for i in range(start, end):
            idx = i - start
            bar = batch[idx]
            ts = bar.get("ts", "")

            def fmt(v):
                if v is None:
                    return "NULL"
                return str(v)

            vals = (
                f"('{ts}',"
                f"{bar.get('open')},{bar.get('high')},{bar.get('low')},{bar.get('close')},"
                f"{bar.get('volume')},{bar.get('amount')},{bar.get('turnover')},"
                f"{fmt(mas[5][i])},{fmt(mas[10][i])},{fmt(mas[20][i])},{fmt(mas[30][i])},"
                f"{fmt(mas[60][i])},{fmt(mas[120][i])},{fmt(mas[233][i])},"
                f"{fmt(dif[i])},{fmt(dea[i])},{fmt(hist[i])},"
                f"{fmt(k[i])},{fmt(d[i])},{fmt(j[i])},"
                f"{fmt(zxdq[i])},{fmt(zxdkx[i])})"
            )
            values_parts.append(vals)

        sql = f"INSERT INTO {table_name} VALUES " + " ".join(values_parts)
        if not td_execute(sql):
            print(f"  {code}: INSERT failed at batch {start}-{end}")
            return False

    elapsed = time.time() - t0
    print(f"  {code} {name}: {total} bars done ({elapsed:.1f}s)")
    return True


# ── 批量处理 ───────────────────────────────────────────────────────────

def get_all_stocks():
    """从 PG 获取所有活跃股票"""
    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT code, name FROM stocks WHERE is_active = TRUE ORDER BY code")
    stocks = cur.fetchall()
    cur.close()
    conn.close()
    return stocks


def _batch_read_raw(codes):
    """一次 REST 查询读取多只股票的原始数据，返回 {code: [bars], ...}"""
    tbnames = ", ".join(f"'k_1d_{c}'" for c in codes)
    sql = (
        f"SELECT tbname, ts, open, high, low, close, volume, amount, turnover "
        f"FROM sirs.kline_1d WHERE tbname IN ({tbnames}) ORDER BY tbname, ts"
    )
    rows = td_query_rest(sql)
    groups = {}
    for r in rows:
        # tbname 格式: 'k_1d_000001' → code: '000001'
        tn = r.get("tbname", "")
        code = tn.replace("k_1d_", "")
        if code not in groups:
            groups[code] = []
        groups[code].append(r)
    return groups


def _process_and_write(code, name, raw_bars, dry_run=False):
    """单只股票：复权 → 算指标 → 写入 kline_1d_adj"""
    events = get_xdxr_events(code)
    adj = apply_forward_adjustment(raw_bars, events)
    opens  = [float(b.get("open", 0) or 0) for b in adj]
    highs  = [float(b.get("high", 0) or 0) for b in adj]
    lows   = [float(b.get("low", 0) or 0) for b in adj]
    closes = [float(b.get("close", 0) or 0) for b in adj]
    mas, dif, dea, hist, k, d, j, zxdq, zxdkx = compute_all_indicators(opens, highs, lows, closes)

    if dry_run:
        return True

    def fmt(v):
        return "NULL" if v is None else str(v)

    tbl = f"sirs.k_1d_adj_{code}"
    td_execute(f"DROP TABLE IF EXISTS {tbl}")
    td_execute(f"CREATE TABLE {tbl} USING sirs.kline_1d_adj TAGS ('{code}', '{name}')")
    total = len(adj)
    for start in range(0, total, 3000):
        end = min(start + 3000, total)
        vals = []
        for i in range(start, end):
            bar = adj[i]
            vals.append(
                f"('{bar.get('ts','')}',"
                f"{bar.get('open')},{bar.get('high')},{bar.get('low')},{bar.get('close')},"
                f"{bar.get('volume')},{bar.get('amount')},{bar.get('turnover')},"
                f"{fmt(mas[5][i])},{fmt(mas[10][i])},{fmt(mas[20][i])},{fmt(mas[30][i])},"
                f"{fmt(mas[60][i])},{fmt(mas[120][i])},{fmt(mas[233][i])},"
                f"{fmt(dif[i])},{fmt(dea[i])},{fmt(hist[i])},"
                f"{fmt(k[i])},{fmt(d[i])},{fmt(j[i])},"
                f"{fmt(zxdq[i])},{fmt(zxdkx[i])})"
            )
        td_execute(f"INSERT INTO {tbl} VALUES " + " ".join(vals))
    return True


def process_all(max_workers=4, dry_run=False):
    """批量读 + 并行算+写"""
    stocks = get_all_stocks()
    total = len(stocks)
    BATCH = 50
    t0 = time.time()
    ok = fail = 0

    for start in range(0, total, BATCH):
        end = min(start + BATCH, total)
        batch_codes = [s["code"] for s in stocks[start:end]]
        code_name = {s["code"]: s["name"] for s in stocks[start:end]}

        # 1. 批量读取原始数据
        raw_groups = _batch_read_raw(batch_codes)

        # 2. 并行处理+写入
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for code in batch_codes:
                if code in raw_groups:
                    futures[pool.submit(_process_and_write, code, code_name[code], raw_groups[code], dry_run)] = code
                else:
                    fail += 1
            for future in as_completed(futures):
                code = futures[future]
                try:
                    if future.result(): ok += 1
                    else: fail += 1
                except Exception as e:
                    print(f"  {code}: ERROR {e}", flush=True)
                    fail += 1

        elapsed = time.time() - t0
        eta = elapsed / end * (total - end) if end > 0 else 0
        print(f"  [{end}/{total}] {end*100//total}% ok={ok} fail={fail} elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)

    print(f"\nDone: {ok} OK, {fail} FAIL in {time.time()-t0:.0f}s", flush=True)


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="前复权 K 线指标预计算")
    parser.add_argument("--code", help="单只股票代码（如 000001）")
    parser.add_argument("--all", action="store_true", help="处理全部股票")
    parser.add_argument("--workers", type=int, default=4, help="并发数（默认 4）")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写入")
    args = parser.parse_args()

    if args.code:
        compute_for_stock(args.code, dry_run=args.dry_run)
    elif args.all:
        process_all(max_workers=args.workers, dry_run=args.dry_run)
    else:
        parser.print_help()
