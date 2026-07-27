"""
前复权 K 线指标预计算 — HTTP REST 版
与 calc_indicators.py 计算逻辑一致，但写入使用 urllib.request HTTP REST，
每 500 行拼一条长 SQL，减少数据库交互次数。

用法：
  python calc_indicators_rest.py --init              # 确保超级表存在
  python calc_indicators_rest.py --code 000001        # 单只
  python calc_indicators_rest.py --all --dry-run      # 全量试算（不计时）
  python calc_indicators_rest.py --all --resume       # 全量+断点续传
"""

import argparse
import gc
import json
import os
import time
import urllib.error
import urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from config import PG_CONFIG, TDENGINE_CONFIG
from calc_indicators import (
    get_all_stocks,
    get_xdxr_events,
    apply_forward_adjustment,
    td_query_rest,
)

# ── 常量 ──────────────────────────────────────────────────────────────────

TD_REST = f"http://{TDENGINE_CONFIG['host']}:{TDENGINE_CONFIG['port']}/rest/sql"
TD_AUTH = "Basic " + b64encode(
    f"{TDENGINE_CONFIG['user']}:{TDENGINE_CONFIG['password']}".encode()
).decode()

INSERT_BATCH = 500          # 每条 INSERT 包含的行数
STOCK_BATCH = 50            # 每批读取的股票数
DEFAULT_WORKERS = 4
DEFAULT_CHECKPOINT = "checkpoint_indicators_rest.txt"


# ── REST 执行 ─────────────────────────────────────────────────────────────

def td_rest_execute(sql: str) -> dict:
    """通过 HTTP REST 执行 SQL，返回解析后的 JSON"""
    data = sql.encode("utf-8")
    req = urllib.request.Request(TD_REST, data=data, headers={"Authorization": TD_AUTH})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"TDengine HTTP error: {e}")
    if str(result.get("code", "")) != "0":
        raise RuntimeError(f"TDengine error: {result.get('desc', result)}")
    return result


# ── 批量读取 ──────────────────────────────────────────────────────────────

def batch_read_raw(codes: list[str]) -> dict[str, list[dict]]:
    """一次 REST 查询读取多只股票的原始数据，返回 {code: [bars]}"""
    tbnames = ", ".join(f"'k_1d_{c}'" for c in codes)
    sql = (
        f"SELECT tbname, ts, open, high, low, close, volume, amount, turnover "
        f"FROM sirs.kline_1d WHERE tbname IN ({tbnames}) ORDER BY tbname, ts"
    )
    rows = td_query_rest(sql)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        tn = r.get("tbname", "")
        code = tn.replace("k_1d_", "")
        groups.setdefault(code, []).append(r)
    return groups


# ── 断点续传 ──────────────────────────────────────────────────────────────

def load_checkpoint(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return set(line.strip() for line in f if line.strip())


def save_checkpoint(code: str, path: str):
    with open(path, "a") as f:
        f.write(code + "\n")


# ── numpy 版指标计算（底层 C 操作，单只 3x 加速）──────────────────────────

def _ma_np(closes: np.ndarray, n: int) -> np.ndarray:
    result = np.full(len(closes), np.nan)
    if len(closes) >= n:
        result[n - 1 :] = np.convolve(closes, np.ones(n) / n, mode="valid")
    return result


def _ema_np(values: np.ndarray, n: int) -> np.ndarray:
    result = np.full(len(values), np.nan)
    ema = pd.Series(values).ewm(span=n, adjust=False, min_periods=n).mean()
    result[n - 1 :] = ema.values[n - 1 :]
    return result


def _macd_np(closes: np.ndarray):
    ema12 = _ema_np(closes, 12)
    ema26 = _ema_np(closes, 26)
    dif = ema12 - ema26
    valid = ~np.isnan(dif)
    valid_idx = np.where(valid)[0]
    dea = np.full(len(closes), np.nan)
    hist = np.full(len(closes), np.nan)
    if len(valid_idx) > 0:
        dif_valid = dif[valid_idx]
        dea_valid = pd.Series(dif_valid).ewm(span=9, adjust=False, min_periods=9).mean().values
        dea[valid_idx] = dea_valid
        hist[valid_idx] = (dif[valid_idx] - dea[valid_idx]) * 2
    return dif, dea, hist


def _kdj_np(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n=9, m1=3, m2=3):
    length = len(closes)
    k = np.full(length, np.nan)
    d = np.full(length, np.nan)
    j = np.full(length, np.nan)
    k_val, d_val = 50.0, 50.0
    for i in range(n - 1, length):
        h_max = np.max(highs[i - n + 1 : i + 1])
        l_min = np.min(lows[i - n + 1 : i + 1])
        rsv = 50.0 if h_max == l_min else (closes[i] - l_min) / (h_max - l_min) * 100.0
        if i == n - 1:
            k_val = (2.0 / m1) * 50.0 + (1.0 / m1) * rsv
            d_val = (2.0 / m2) * 50.0 + (1.0 / m2) * k_val
        else:
            k_val = (2.0 / m1) * k[i - 1] + (1.0 / m1) * rsv
            d_val = (2.0 / m2) * d[i - 1] + (1.0 / m2) * k_val
        k[i] = k_val
        d[i] = d_val
        j[i] = 3.0 * k_val - 2.0 * d_val
    return k, d, j


def _zxdq_np(closes: np.ndarray) -> np.ndarray:
    ema10 = _ema_np(closes, 10)
    valid = ~np.isnan(ema10)
    valid_idx = np.where(valid)[0]
    result = np.full(len(closes), np.nan)
    if len(valid_idx) > 0:
        ema2 = pd.Series(ema10[valid_idx]).ewm(span=10, adjust=False, min_periods=10).mean().values
        result[valid_idx] = ema2
    return result


def _zxdkx_np(closes: np.ndarray) -> np.ndarray:
    m14 = _ma_np(closes, 14)
    m28 = _ma_np(closes, 28)
    m57 = _ma_np(closes, 57)
    m114 = _ma_np(closes, 114)
    result = np.full(len(closes), np.nan)
    valid = ~(np.isnan(m14) | np.isnan(m28) | np.isnan(m57) | np.isnan(m114))
    result[valid] = (m14[valid] + m28[valid] + m57[valid] + m114[valid]) / 4
    return result


def compute_all_np(opens, highs, lows, closes):
    """一次计算所有指标（numpy 向量化版），返回与 calc_indicators.compute_all_indicators 相同结构"""
    mas = {
        5: _ma_np(closes, 5), 10: _ma_np(closes, 10),
        20: _ma_np(closes, 20), 30: _ma_np(closes, 30),
        60: _ma_np(closes, 60), 120: _ma_np(closes, 120),
        233: _ma_np(closes, 233),
    }
    dif, dea, hist = _macd_np(closes)
    k, d, j = _kdj_np(highs, lows, closes)
    zxdq = _zxdq_np(closes)
    zxdkx = _zxdkx_np(closes)
    return mas, dif, dea, hist, k, d, j, zxdq, zxdkx


# ── 计算阶段 ──────────────────────────────────────────────────────────────

def compute_one(code: str, name: str, bars: list[dict]):
    """单只股票：前复权 + numpy 指标计算"""
    events = get_xdxr_events(code)
    adj = apply_forward_adjustment(bars, events)
    opens  = np.array([float(b.get("open", 0) or 0) for b in adj], dtype=np.float64)
    highs  = np.array([float(b.get("high", 0) or 0) for b in adj], dtype=np.float64)
    lows   = np.array([float(b.get("low", 0) or 0) for b in adj], dtype=np.float64)
    closes = np.array([float(b.get("close", 0) or 0) for b in adj], dtype=np.float64)
    args = compute_all_np(opens, highs, lows, closes)
    return (code, name, adj, args)


# ── 写入阶段 ──────────────────────────────────────────────────────────────

def _fmt(v):
    if v is None:
        return "NULL"
    if isinstance(v, float) and np.isnan(v):
        return "NULL"
    return str(v)


def write_one_stock(code: str, name: str, adj: list[dict], args: tuple) -> bool:
    """DDL + 批量 INSERT（500 行/条），全部通过 HTTP REST"""
    tbl = f"sirs.k_1d_adj_{code}"
    safe_name = name.replace("'", "''")

    # DDL
    try:
        td_rest_execute(f"DROP TABLE IF EXISTS {tbl}")
        td_rest_execute(
            f"CREATE TABLE {tbl} USING sirs.kline_1d_adj TAGS ('{code}', '{safe_name}')"
        )
    except RuntimeError as e:
        print(f"    {code}: DDL error: {e}", flush=True)
        return False

    mas, dif, dea, hist, k, d, j, zxdq, zxdkx = args
    total = len(adj)

    # INSERT 分批
    for start in range(0, total, INSERT_BATCH):
        end = min(start + INSERT_BATCH, total)
        vals = []
        for i in range(start, end):
            bar = adj[i]
            vals.append(
                f"('{bar['ts']}',"
                f"{bar['open']},{bar['high']},{bar['low']},{bar['close']},"
                f"{bar['volume']},{bar['amount']},{bar['turnover']},"
                f"{_fmt(mas[5][i])},{_fmt(mas[10][i])},{_fmt(mas[20][i])},{_fmt(mas[30][i])},"
                f"{_fmt(mas[60][i])},{_fmt(mas[120][i])},{_fmt(mas[233][i])},"
                f"{_fmt(dif[i])},{_fmt(dea[i])},{_fmt(hist[i])},"
                f"{_fmt(k[i])},{_fmt(d[i])},{_fmt(j[i])},"
                f"{_fmt(zxdq[i])},{_fmt(zxdkx[i])})"
            )
        sql = f"INSERT INTO {tbl} VALUES " + " ".join(vals)
        try:
            td_rest_execute(sql)
        except RuntimeError as e:
            print(f"    {code}: INSERT batch [{start},{end}) error: {e}", flush=True)
            return False
    return True


# ── 单批处理（50 只股票）──────────────────────────────────────────────────

def process_batch(
    codes: list[str],
    code_name: dict[str, str],
    pool: ThreadPoolExecutor,
    dry_run: bool = False,
    checkpoint_path: str | None = None,
) -> tuple[int, int]:
    """处理一批股票：读 → 算 → 写，三阶段分别计时"""
    t0 = time.time()

    # ── Phase 1: 批量读取 ──
    raw_groups = batch_read_raw(codes)
    t1 = time.time()
    read_time = t1 - t0

    # ── Phase 2: 并行计算 ──
    futures = {}
    for code in codes:
        if code in raw_groups:
            f = pool.submit(compute_one, code, code_name.get(code, ""), raw_groups[code])
            futures[f] = code

    results: dict[str, tuple] = {}
    for f in as_completed(futures):
        code = futures[f]
        try:
            r = f.result()
            if r is not None:
                results[code] = r
        except Exception as e:
            print(f"    {code}: compute error: {e}", flush=True)
    t2 = time.time()
    compute_time = t2 - t1

    if dry_run:
        total_bars = sum(len(r[2]) for r in results.values())
        print(
            f"  [batch] read={read_time:.1f}s compute={compute_time:.1f}s "
            f"stocks={len(results)} bars={total_bars} (dry-run)",
            flush=True,
        )
        return (len(results), len(codes) - len(results))

    # ── Phase 3: 并行写入 ──
    wf = {}
    for code, r in results.items():
        _code, _name, adj, args = r
        f = pool.submit(write_one_stock, code, _name, adj, args)
        wf[f] = code

    ok = fail = 0
    for f in as_completed(wf):
        code = wf[f]
        try:
            if f.result():
                ok += 1
                if checkpoint_path:
                    save_checkpoint(code, checkpoint_path)
            else:
                fail += 1
        except Exception as e:
            print(f"    {code}: write error: {e}", flush=True)
            fail += 1
    t3 = time.time()
    write_time = t3 - t2

    total_bars = sum(len(results[c][2]) for c in results)
    print(
        f"  [batch] read={read_time:.1f}s compute={compute_time:.1f}s write={write_time:.1f}s "
        f"stocks={ok} bars={total_bars} ok={ok} fail={fail} "
        f"total={t3 - t0:.1f}s",
        flush=True,
    )
    return (ok, fail)


# ── 全量处理 ──────────────────────────────────────────────────────────────

def process_all(
    max_workers: int = DEFAULT_WORKERS,
    dry_run: bool = False,
    resume: bool = False,
    checkpoint_file: str | None = None,
    limit: int = 0,
):
    stocks = get_all_stocks()
    total_all = len(stocks)

    cp_path = None
    completed: set[str] = set()
    if resume:
        cp_path = checkpoint_file or DEFAULT_CHECKPOINT
        completed = load_checkpoint(cp_path)
        print(f"Checkpoint: {len(completed)} completed loaded from {cp_path}")
    elif checkpoint_file:
        cp_path = checkpoint_file
        completed = load_checkpoint(cp_path)

    if completed:
        stocks = [s for s in stocks if s["code"] not in completed]
        print(f"Resume: skip {len(completed)} done, {len(stocks)} remaining")

    if limit and limit < len(stocks):
        stocks = stocks[:limit]
        print(f"Limit: processing first {limit} stocks")

    total = len(stocks)
    t_start = time.time()
    ok_total = fail_total = 0

    for start in range(0, total, STOCK_BATCH):
        end = min(start + STOCK_BATCH, total)
        batch_codes = [s["code"] for s in stocks[start:end]]
        code_name = {s["code"]: s["name"] for s in stocks[start:end]}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            ok, fail = process_batch(batch_codes, code_name, pool, dry_run=dry_run, checkpoint_path=cp_path)

        ok_total += ok
        fail_total += fail
        gc.collect()  # 每批后释放内存
        elapsed = time.time() - t_start
        done = ok_total + fail_total
        pct = done * 100 // total if total > 0 else 0
        eta = (elapsed / done * (total - done)) if done > 0 else 0
        print(
            f"  [{done}/{total}] {pct}% ok={ok_total} fail={fail_total} "
            f"elapsed={elapsed:.0f}s eta={eta:.0f}s",
            flush=True,
        )

    total_time = time.time() - t_start
    print(f"\nDone: {ok_total} OK, {fail_total} FAIL in {total_time:.0f}s", flush=True)
    if ok_total > 0:
        avg = total_time / ok_total
        print(f"Per-stock: {avg:.2f}s | Est 5317 stocks: {avg * 5317 / 60:.0f} min", flush=True)


# ── 单只股票 ──────────────────────────────────────────────────────────────

def compute_for_stock(code: str, name: str = "", dry_run: bool = False) -> bool:
    import psycopg2
    import psycopg2.extras

    if not name:
        from calc_indicators import get_pg_conn
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT name FROM stocks WHERE code = %s", (code,))
        row = cur.fetchone()
        conn.close()
        if row:
            name = row["name"]

    t0 = time.time()
    raw = batch_read_raw([code])
    if code not in raw or not raw[code]:
        print(f"  {code}: no raw data, skip")
        return False

    bars = raw[code]
    result = compute_one(code, name, bars)
    if result is None:
        return False

    _code, _name, adj, args = result
    if dry_run:
        print(f"  {code} {name}: {len(adj)} bars computed (dry-run, {time.time()-t0:.1f}s)")
        return True

    ok = write_one_stock(code, _name, adj, args)
    elapsed = time.time() - t0
    if ok:
        print(f"  {code} {name}: {len(adj)} bars written via REST ({elapsed:.1f}s)")
    return ok


def init_supertable():
    print("[TD] Ensuring supertable sirs.kline_1d_adj exists ...")
    td_rest_execute("""
        CREATE STABLE IF NOT EXISTS sirs.kline_1d_adj (
            ts       TIMESTAMP,
            open     FLOAT,
            high     FLOAT,
            low      FLOAT,
            close    FLOAT,
            volume   BIGINT,
            amount   DOUBLE,
            turnover FLOAT,
            ma5      DOUBLE,
            ma10     DOUBLE,
            ma20     DOUBLE,
            ma30     DOUBLE,
            ma60     DOUBLE,
            ma120    DOUBLE,
            ma233    DOUBLE,
            macd_dif DOUBLE,
            macd_dea DOUBLE,
            macd_hist DOUBLE,
            kdj_k    DOUBLE,
            kdj_d    DOUBLE,
            kdj_j    DOUBLE,
            zxdq     DOUBLE,
            zxdkx    DOUBLE
        ) TAGS (code VARCHAR(10), name VARCHAR(50))
    """)
    print("[TD] Supertable ready.")


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="前复权 K线指标预计算 (HTTP REST)")
    parser.add_argument("--code", help="单只股票代码")
    parser.add_argument("--all", action="store_true", help="处理全部股票")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"并发数 (default: {DEFAULT_WORKERS})")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写入")
    parser.add_argument("--resume", action="store_true", help=f"断点续传 ({DEFAULT_CHECKPOINT})")
    parser.add_argument("--checkpoint", metavar="FILE", help="断点文件路径")
    parser.add_argument("--init", action="store_true", help="创建超级表")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 只（测试用）")
    args = parser.parse_args()

    if args.init:
        init_supertable()
    elif args.code:
        compute_for_stock(args.code, dry_run=args.dry_run)
    elif args.all:
        process_all(
            max_workers=args.workers,
            dry_run=args.dry_run,
            resume=args.resume,
            checkpoint_file=args.checkpoint,
            limit=args.limit,
        )
    else:
        parser.print_help()
