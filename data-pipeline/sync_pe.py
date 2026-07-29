"""
SIRS — 动态市盈率（PE TTM）同步脚本

数据源：腾讯财经（qt.gtimg.cn）

功能：
1. 从 PG 读取所有活跃股票
2. 每 50 只一批请求腾讯行情 API
3. 解析 ~ 分隔的返回，提取 field[52] 作为动态市盈率
4. 批量 UPDATE stocks 表 pe_ttm 字段

用法：
    python sync_pe.py                     # 全量同步
    python sync_pe.py --codes 000001,600519  # 仅同步指定股票

API 返回格式：
    v_sh600519="1~贵州茅台~...~...~15.15~..."
    field[52] = 动态市盈率（已核实：茅台 15.15，宁德 21.21）
"""

import re
import time
import argparse

import requests
import psycopg2
import psycopg2.extras

from config import PG_CONFIG

# ── 腾讯财经 API ────────────────────────────────────────────────────────

API_URL = "https://qt.gtimg.cn/q="
PE_FIELD_INDEX = 52  # 动态市盈率所在字段位置

HEADERS = {
    "Referer": "https://gu.qq.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

BATCH_SIZE_API = 50     # 每批查询的股票数
BATCH_SIZE_DB = 500     # 每批 UPDATE 的股票数
REQUEST_DELAY = 0.3     # 请求间隔（秒）
MAX_RETRIES = 2


def format_code(code: str) -> str:
    """将股票代码转换为腾讯 API 格式（SH→sh，SZ→sz）。"""
    if code.startswith('6'):
        return f"sh{code}"
    return f"sz{code}"


def parse_pe_response(text: str) -> dict[str, float | None]:
    """解析腾讯 API 返回的 ~ 分隔数据，提取 (code → pe) 映射。

    响应格式：
        v_sh600519="1~贵州茅台~...~...~15.15~..."
        v_sz000001="..."
    """
    result = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 提取引号内的内容
        match = re.search(r'"(.+)"', line)
        if not match:
            continue
        fields = match.group(1).split("~")
        if len(fields) <= PE_FIELD_INDEX:
            continue
        code = fields[2].strip()
        if not code:
            continue
        pe_raw = fields[PE_FIELD_INDEX].strip()
        if pe_raw and pe_raw != "-":
            try:
                result[code] = float(pe_raw)
            except ValueError:
                result[code] = None
        else:
            result[code] = None
    return result


def fetch_pe_batch(codes: list[str]) -> dict[str, float | None]:
    """请求一批股票的 PE 数据。"""
    query = ",".join(format_code(c) for c in codes)
    url = API_URL + query

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                print(f"  [WARN] HTTP {resp.status_code}，重试 {attempt}/{MAX_RETRIES}")
                time.sleep(1)
                continue
            return parse_pe_response(resp.text)
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] 请求异常: {e}，重试 {attempt}/{MAX_RETRIES}")
            time.sleep(1)

    return {}


def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)


def update_pe_batch(pe_data: list[tuple[str, float | None]]):
    """CASE 批量更新 stocks.pe_ttm。"""
    if not pe_data:
        return
    conn = get_pg_conn()
    cur = conn.cursor()
    for i in range(0, len(pe_data), BATCH_SIZE_DB):
        batch = pe_data[i:i + BATCH_SIZE_DB]
        whens = []
        codes = []
        for code, pe in batch:
            codes.append(code)
            whens.append(f"WHEN '{code}' THEN {pe}" if pe is not None else f"WHEN '{code}' THEN NULL")
        sql = (
            "UPDATE stocks SET pe_ttm = CASE code "
            f"{' '.join(whens)} END "
            f"WHERE code IN ({','.join(repr(c) for c in codes)})"
        )
        cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


def sync_all(codes: list[str] | None = None):
    """全量或指定股票同步。"""
    print("=" * 50)
    print("SIRS — 动态市盈率同步（数据源：腾讯财经）")
    print("=" * 50)

    # 获取股票列表
    if codes:
        stock_codes = codes
        print(f"[PE] 指定 {len(stock_codes)} 只股票")
    else:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("SELECT code FROM stocks WHERE is_active = TRUE ORDER BY code")
        stock_codes = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"[PE] 活跃股票: {len(stock_codes)} 只")

    # 分批次请求
    all_pe = {}
    total = len(stock_codes)
    batches = (total + BATCH_SIZE_API - 1) // BATCH_SIZE_API

    for batch_idx in range(batches):
        start = batch_idx * BATCH_SIZE_API
        end = min(start + BATCH_SIZE_API, total)
        batch_codes = stock_codes[start:end]

        if batch_idx > 0:
            time.sleep(REQUEST_DELAY)

        pe_map = fetch_pe_batch(batch_codes)
        all_pe.update(pe_map)

        ok = sum(1 for c in batch_codes if c in pe_map)
        print(f"  [批次{batch_idx + 1}/{batches}] {start + 1}-{end} 条，成功 {ok}/{len(batch_codes)}")

    # 统计
    valid = [(c, p) for c, p in all_pe.items() if p is not None]
    none_cnt = sum(1 for c in stock_codes if c in all_pe and all_pe[c] is None)
    miss_cnt = sum(1 for c in stock_codes if c not in all_pe)
    print(f"\n[PE] 共获取 {len(all_pe)} 只，有效: {len(valid)}，空值: {none_cnt}，缺失: {miss_cnt}")

    # 更新数据库
    if valid:
        print("[PG] 批量更新 pe_ttm...")
        t0 = time.time()
        update_pe_batch(valid)
        print(f"[PG] 更新完成 — {len(valid)} 条 ({time.time() - t0:.1f}s)")

        pe_vals = [p for _, p in valid]
        print(f"\n[统计] PE 范围: {min(pe_vals):.2f} ~ {max(pe_vals):.2f}")
        pos = sum(1 for p in pe_vals if p > 0)
        neg = sum(1 for p in pe_vals if p < 0)
        print(f"       正值(盈利): {pos} 只  负值(亏损): {neg} 只")

    print("\n[DONE] 动态市盈率同步完成")


def main():
    parser = argparse.ArgumentParser(description="SIRS 动态市盈率同步（腾讯财经）")
    parser.add_argument("--codes", type=str, default="",
                        help="仅同步指定股票，逗号分隔（测试用）")
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None
    sync_all(codes)


if __name__ == "__main__":
    main()
