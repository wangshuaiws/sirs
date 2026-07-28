"""全指标验证修复 2026-07-27"""
import sys, time, numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from calc_indicators import td_query_rest
from calc_indicators_rest import compute_all_np, td_rest_execute

TARGET = '2026-07-27'; THRESHOLD = 0.01; WORKERS = 8
ALL_METRICS = ['zxdq','zxdkx','ma5','ma10','ma20','ma30','ma60','ma120','ma233',
               'macd_dif','macd_dea','macd_hist','kdj_k','kdj_d','kdj_j']
def fmt(v):
    return "NULL" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.6f}"
def fmt_int(v):
    return "NULL" if v is None else str(int(v))

def check_and_fix(code, name):
    result = {"code": code, "fixed_metrics": []}
    try:
        stored = td_query_rest(
            f"SELECT ts,open,high,low,close,volume,amount,turnover,{','.join(ALL_METRICS)} "
            f"FROM sirs.k_1d_adj_{code} WHERE ts <= '{TARGET}' ORDER BY ts DESC LIMIT 234")
        if not stored: return result
        today_idx = next((i for i,r in enumerate(stored) if r['ts']==TARGET), None)
        if today_idx is None: return result
        stored.reverse()
        today_bar = stored[today_idx]
        tail = stored[:today_idx]
        if len(tail) > 233: tail = tail[-233:]
        o = np.array([float(r['open']) for r in tail] + [float(today_bar['open'])], dtype=np.float64)
        h = np.array([float(r['high']) for r in tail] + [float(today_bar['high'])], dtype=np.float64)
        l = np.array([float(r['low']) for r in tail] + [float(today_bar['low'])], dtype=np.float64)
        c = np.array([float(r['close']) for r in tail] + [float(today_bar['close'])], dtype=np.float64)
        mas, dif, dea, hist, k, d, j, zxdq, zxdkx = compute_all_np(o, h, l, c)
        i = len(c) - 1
        comp = {'zxdq':zxdq[i],'zxdkx':zxdkx[i],'ma5':mas[5][i],'ma10':mas[10][i],'ma20':mas[20][i],
                'ma30':mas[30][i],'ma60':mas[60][i],'ma120':mas[120][i],'ma233':mas[233][i],
                'macd_dif':dif[i],'macd_dea':dea[i],'macd_hist':hist[i],'kdj_k':k[i],'kdj_d':d[i],'kdj_j':j[i]}
        for m in ALL_METRICS:
            s, c = today_bar.get(m), comp[m]
            if s is not None and c is not None and not np.isnan(c) and abs(float(s)-float(c)) > THRESHOLD:
                result["fixed_metrics"].append(m)
        if not result["fixed_metrics"]: return result
        tv = today_bar.get("turnover","NULL")
        if tv is None: tv = "NULL"
        sql = (f"INSERT INTO sirs.k_1d_adj_{code} VALUES ('{TARGET}',"
               f"{float(today_bar['open'])},{float(today_bar['high'])},{float(today_bar['low'])},{float(today_bar['close'])},"
               f"{fmt_int(today_bar.get('volume'))},{today_bar.get('amount')},{tv},"
               f"{fmt(comp['ma5'])},{fmt(comp['ma10'])},{fmt(comp['ma20'])},{fmt(comp['ma30'])},"
               f"{fmt(comp['ma60'])},{fmt(comp['ma120'])},{fmt(comp['ma233'])},"
               f"{fmt(comp['macd_dif'])},{fmt(comp['macd_dea'])},{fmt(comp['macd_hist'])},"
               f"{fmt(comp['kdj_k'])},{fmt(comp['kdj_d'])},{fmt(comp['kdj_j'])},"
               f"{fmt(comp['zxdq'])},{fmt(comp['zxdkx'])})")
        td_rest_execute(sql)
        result["status"] = "fixed"
        return result
    except Exception as e:
        result["error"] = str(e); return result

def main():
    t0 = time.time()
    print("[Scan] 查询...")
    all_adj = td_query_rest(f"SELECT tbname FROM sirs.kline_1d_adj WHERE ts = '{TARGET}'")
    codes = [r['tbname'].replace('k_1d_adj_','') for r in all_adj if r['tbname'].startswith('k_1d_adj_')]
    total = len(codes)
    print(f"[Scan] 共 {total} 只")
    import psycopg2; from config import PG_CONFIG
    conn = psycopg2.connect(**PG_CONFIG); cur = conn.cursor()
    cur.execute("SELECT code, name FROM stocks")
    code_name = {r[0]: r[1] for r in cur.fetchall()}; cur.close(); conn.close()
    fixed = 0; errs = 0; metric_stats = {m: 0 for m in ALL_METRICS}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        fut_map = {pool.submit(check_and_fix, c, code_name.get(c,"")): c for c in codes}
        done = 0
        for f in as_completed(fut_map):
            done += 1; r = f.result()
            if r.get("status") == "fixed":
                fixed += 1
                for m in r.get("fixed_metrics", []): metric_stats[m] = metric_stats.get(m, 0) + 1
            if r.get("error"): errs += 1
            if done % 500 == 0 or done == total:
                print(f"  [{done}/{total}] 修复 {fixed}, 错误 {errs}", flush=True)
    print(f"\n[完成] {total} 只, 修复 {fixed}, 错误 {errs}, 耗时 {time.time()-t0:.0f}s")
    print("指标修复统计:")
    for m in ALL_METRICS:
        if metric_stats.get(m): print(f"  {m:10s}: {metric_stats[m]} 只")

if __name__ == "__main__":
    main()
