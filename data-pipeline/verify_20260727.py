"""
验证并修复所有股票 2026-07-27 的前复权技术指标。

逻辑：对每只有 2026-07-27 adj 数据的股票，读尾 233 条 + 今天 raw bar，
重新计算所有指标，与存储值对比 zxdq（最敏感的指标）。
如果偏差 >0.01，则 INSERT 覆盖整行（TDengine 同 ts 覆盖）。
"""
import sys
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

from calc_indicators import td_query_rest
from calc_indicators_rest import compute_all_np, td_rest_execute

TARGET = '2026-07-27'
THRESHOLD = 0.01
WORKERS = 8


def fmt(v):
    return "NULL" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.6f}"


def fmt_int(v):
    if v is None:
        return "NULL"
    if isinstance(v, float) and np.isnan(v):
        return "NULL"
    return str(int(v))


def check_and_fix(code: str, name: str) -> dict:
    """检查单只股票 2026-07-27 的 zxdq，不匹配则修复。"""
    result = {"code": code, "status": "ok", "fix": False}
    try:
        # 1. 读取存储的 adj 数据（2026-07-27 及之前）
        stored = td_query_rest(
            f"SELECT ts,open,high,low,close,zxdq "
            f"FROM sirs.k_1d_adj_{code} WHERE ts <= '{TARGET}' ORDER BY ts DESC LIMIT 234"
        )
        if not stored:
            result["status"] = "no_data"
            return result

        # 找出 2026-07-27 的位置
        today_idx = None
        for i, r in enumerate(stored):
            if r['ts'] == TARGET:
                today_idx = i
                break
        if today_idx is None:
            result["status"] = "no_target"
            return result

        # 已存储的 zxdq
        stored_zxdq = stored[today_idx].get('zxdq')
        if stored_zxdq is None:
            result["status"] = "zxdq_null"
            return result
        stored_zxdq = float(stored_zxdq)

        # 2. 读 2026-07-27 的 raw bar
        raw = td_query_rest(
            f"SELECT open,high,low,close,volume,amount,turnover "
            f"FROM sirs.k_1d_{code} WHERE ts = '{TARGET}'"
        )
        if not raw:
            result["status"] = "no_raw"
            return result
        bar = raw[0]

        # 3. 构建完整 OHLC 数组：tail (不包含今天) + 今天
        # stored 是倒序（最新在前），翻转成正序
        stored.reverse()
        # 去掉今天这一行，只取历史
        tail = stored[:-1]  # 去掉最后一个（就是今天）
        # 限制最多 233 条历史
        if len(tail) > 233:
            tail = tail[-233:]

        adj_open  = float(bar['open'])
        adj_high  = float(bar['high'])
        adj_low   = float(bar['low'])
        adj_close = float(bar['close'])

        opens  = np.array([float(r['open']) for r in tail]  + [adj_open],  dtype=np.float64)
        highs  = np.array([float(r['high']) for r in tail]  + [adj_high],  dtype=np.float64)
        lows   = np.array([float(r['low']) for r in tail]   + [adj_low],   dtype=np.float64)
        closes = np.array([float(r['close']) for r in tail] + [adj_close], dtype=np.float64)

        # 4. 计算指标
        mas, dif, dea, hist, k, d, j, zxdq, zxdkx = compute_all_np(opens, highs, lows, closes)

        # 5. 对比 zxdq
        i = len(opens) - 1  # 今天的位置
        computed_zxdq = zxdq[i]
        if computed_zxdq is None or np.isnan(computed_zxdq):
            result["status"] = "compute_failed"
            return result
        computed_zxdq = float(computed_zxdq)

        diff = abs(stored_zxdq - computed_zxdq)
        if diff <= THRESHOLD:
            result["status"] = "ok"
            return result

        # 6. 偏差超过阈值 → INSERT 覆盖
        turnover_val = bar.get("turnover", "NULL")
        if turnover_val is None:
            turnover_val = "NULL"
        sql = (
            f"INSERT INTO sirs.k_1d_adj_{code} VALUES ("
            f"'{TARGET}',"
            f"{adj_open},{adj_high},{adj_low},{adj_close},"
            f"{fmt_int(bar.get('volume'))},{bar.get('amount')},{turnover_val},"
            f"{fmt(mas[5][i])},{fmt(mas[10][i])},{fmt(mas[20][i])},{fmt(mas[30][i])},"
            f"{fmt(mas[60][i])},{fmt(mas[120][i])},{fmt(mas[233][i])},"
            f"{fmt(dif[i])},{fmt(dea[i])},{fmt(hist[i])},"
            f"{fmt(k[i])},{fmt(d[i])},{fmt(j[i])},"
            f"{fmt(zxdq[i])},{fmt(zxdkx[i])})"
        )
        td_rest_execute(sql)
        result["status"] = "fixed"
        result["fix"] = True
        result["stored"] = stored_zxdq
        result["computed"] = computed_zxdq
        result["diff"] = diff
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def main():
    t0 = time.time()

    # 1. 获取所有有 2026-07-27 adj 数据的股票
    print(f"[Scan] 查询有 {TARGET} adj 数据的股票...")
    all_adj = td_query_rest(
        f"SELECT tbname FROM sirs.kline_1d_adj WHERE ts = '{TARGET}'"
    )
    codes = []
    for r in all_adj:
        tbname = r.get("tbname", "")
        code = tbname.replace("k_1d_adj_", "") if tbname.startswith("k_1d_adj_") else ""
        if code:
            codes.append(code)

    total = len(codes)
    print(f"[Scan] 共 {total} 只股票")

    # 2. 获取名称
    import psycopg2
    from config import PG_CONFIG
    conn = psycopg2.connect(**PG_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT code, name FROM stocks")
    code_name = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()
    conn.close()

    # 3. 并发检查
    fixed = []
    errors = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        fut_map = {}
        batch_size = max(1, total // 20)
        for code in codes:
            fut = pool.submit(check_and_fix, code, code_name.get(code, ""))
            fut_map[fut] = code

        done = 0
        for f in as_completed(fut_map):
            done += 1
            r = f.result()
            if r["status"] == "fixed":
                fixed.append(r)
                print(f"  [FIX] {r['code']}: zxdq {r['stored']:.6f} → {r['computed']:.6f} (diff={r['diff']:.6f})")
            elif r["status"] == "error":
                errors.append(r)
                print(f"  [ERR] {r['code']}: {r.get('error','')}")
            if done % batch_size == 0 or done == total:
                pct = done * 100 // total
                print(f"  [进度] {done}/{total} ({pct}%), 修复 {len(fixed)}, 错误 {len(errors)}", flush=True)

    elapsed = time.time() - t0
    print(f"\n[完成] 检查 {total} 只, 修复 {len(fixed)}, 错误 {len(errors)}, 耗时 {elapsed:.0f}s")
    if fixed:
        print("\n修复列表:")
        for r in fixed:
            print(f"  {r['code']}: {r['stored']:.6f} → {r['computed']:.6f} (diff={r['diff']:.6f})")


if __name__ == "__main__":
    main()
