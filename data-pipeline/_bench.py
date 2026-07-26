"""Benchmark: batch read 50, compute, REST INSERT 500/batch"""
import time, json, urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from calc_indicators import (
    get_all_stocks, td_query_rest, get_xdxr_events,
    apply_forward_adjustment, compute_all_indicators
)

TD_REST = 'http://localhost:6041/rest/sql'
TD_AUTH = 'Basic ' + b64encode(b'root:taosdata').decode()

def rest_execute(sql):
    req = urllib.request.Request(TD_REST, data=sql.encode(), headers={'Authorization': TD_AUTH})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def fmt(v):
    return "NULL" if v is None else str(v)

stocks = get_all_stocks()[:50]
codes = [s['code'] for s in stocks]
t0 = time.time()

# 1. Batch read
tbnames = ", ".join(f"'k_1d_{c}'" for c in codes)
rows = td_query_rest(
    f"SELECT tbname, ts, open, high, low, close, volume, amount, turnover "
    f"FROM sirs.kline_1d WHERE tbname IN ({tbnames}) ORDER BY tbname, ts"
)
groups = {}
for r in rows:
    code = r['tbname'].replace('k_1d_', '')
    groups.setdefault(code, []).append(r)
t1 = time.time()
total_rows = sum(len(v) for v in groups.values())
print(f"1. Batch read: {len(groups)} stocks, {total_rows} rows ({t1-t0:.1f}s)", flush=True)

# 2. Compute in parallel
def compute_one(code, bars):
    events = get_xdxr_events(code)
    adj = apply_forward_adjustment(bars, events)
    o = [float(b.get('open', 0) or 0) for b in adj]
    h = [float(b.get('high', 0) or 0) for b in adj]
    l = [float(b.get('low', 0) or 0) for b in adj]
    c = [float(b.get('close', 0) or 0) for b in adj]
    mas, dif, dea, hist, k, d, j, zxdq, zxdkx = compute_all_indicators(o, h, l, c)
    return (code, adj, mas, dif, dea, hist, k, d, j, zxdq, zxdkx)

results = {}
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = {pool.submit(compute_one, c, groups[c]): c for c in groups}
    for f in as_completed(futures):
        r = f.result()
        results[r[0]] = r
t2 = time.time()
print(f"2. Compute: {len(results)} stocks ({t2-t1:.1f}s)", flush=True)

# 3+4. REST DELETE + INSERT
t3 = time.time()
for code in results:
    (_, adj, mas, dif, dea, hist, k, d, j, zxdq, zxdkx) = results[code]
    tbl = f"sirs.k_1d_adj_{code}"
    rest_execute(f"DROP TABLE IF EXISTS {tbl}")
    rest_execute(f"CREATE TABLE {tbl} USING sirs.kline_1d_adj TAGS ('{code}', '{code}')")
    for start in range(0, len(adj), 500):
        end = min(start + 500, len(adj))
        vals = []
        for i in range(start, end):
            bar = adj[i]
            vals.append(
                f"('{bar['ts']}',{bar['open']},{bar['high']},{bar['low']},{bar['close']},"
                f"{bar['volume']},{bar['amount']},{bar['turnover']},"
                f"{fmt(mas[5][i])},{fmt(mas[10][i])},{fmt(mas[20][i])},{fmt(mas[30][i])},"
                f"{fmt(mas[60][i])},{fmt(mas[120][i])},{fmt(mas[233][i])},"
                f"{fmt(dif[i])},{fmt(dea[i])},{fmt(hist[i])},"
                f"{fmt(k[i])},{fmt(d[i])},{fmt(j[i])},"
                f"{fmt(zxdq[i])},{fmt(zxdkx[i])})"
            )
        rest_execute(f"INSERT INTO {tbl} VALUES " + " ".join(vals))
t4 = time.time()
print(f"3+4. REST write: {len(results)} stocks ({t4-t3:.1f}s)", flush=True)
print(f"\nTOTAL: {len(results)} stocks in {t4-t0:.1f}s", flush=True)
print(f"Estimate 5317 stocks: {t4-t0 / 50 * 5317 / 60:.0f} min", flush=True)
