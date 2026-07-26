"""
SIRS — 除权除息事件同步脚本

从通达信拉取全量股票的除权除息记录，写入 PG xdxr_events 表。
可独立运行，也可被 init_stocks.py 调用。

用法：
    python sync_xdxr.py              # 同步所有活跃股票
    python sync_xdxr.py --code 000001  # 仅同步指定股票
"""

import time
import os
import sys

import psycopg2
import psycopg2.extras
from tqdm import tqdm

from mootdx.quotes import Quotes

from config import (
    PG_CONFIG,
    TDX_REQUEST_DELAY, TDX_BATCH_SIZE, TDX_BATCH_PAUSE,
)

# ── 复用 init_stocks 核心函数 ──
from init_stocks import (
    get_tdx_client, get_pg_conn, insert_xdxr_events,
)

CHECKPOINT_XDXR = "checkpoint_xdxr.txt"


def load_xdxr_checkpoint() -> set:
    """加载已同步 xdxr 的股票代码集合"""
    if not os.path.exists(CHECKPOINT_XDXR):
        return set()
    with open(CHECKPOINT_XDXR, "r") as f:
        return set(line.strip() for line in f if line.strip())


def save_xdxr_checkpoint(code: str):
    with open(CHECKPOINT_XDXR, "a") as f:
        f.write(code + "\n")


def sync_all_stocks(client=None):
    """遍历所有活跃股票，拉取除权除息事件入库。
    返回有新增除权事件的股票代码列表。"""
    if client is None:
        client = get_tdx_client()

    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT code, name FROM stocks WHERE is_active = TRUE ORDER BY code")
    stocks = cur.fetchall()
    cur.close()
    conn.close()

    completed = load_xdxr_checkpoint()
    remaining = [s for s in stocks if s["code"] not in completed]

    print(f"[XDXR] 总数: {len(stocks)}, 已完成: {len(completed)}, 剩余: {len(remaining)}")

    if not remaining:
        print("[XDXR] 所有股票已同步，无需处理")
        return []

    success = 0
    fail = 0
    empty = 0
    affected = []

    for i, stock in enumerate(tqdm(remaining, desc="同步除权事件")):
        code = stock["code"]

        try:
            xdxr_df = client.xdxr(symbol=code)

            if xdxr_df is None or xdxr_df.empty:
                save_xdxr_checkpoint(code)
                empty += 1
                time.sleep(TDX_REQUEST_DELAY)
                continue

            conn = get_pg_conn()
            total, new_cnt = insert_xdxr_events(code, xdxr_df, conn)
            conn.close()

            save_xdxr_checkpoint(code)
            success += 1

            if new_cnt > 0:
                tqdm.write(f"  [XDXR] {code} {stock['name']}: {new_cnt} 条新事件")
                affected.append(code)
            elif total > 0:
                tqdm.write(f"  [XDXR] {code} {stock['name']}: 无新事件（{total} 条已存在）")

        except Exception as e:
            fail += 1
            tqdm.write(f"\n[ERROR] {code} {stock['name']}: {e}")

        time.sleep(TDX_REQUEST_DELAY)

        if (i + 1) % TDX_BATCH_SIZE == 0:
            print(f"\n  ... 已处理 {i + 1}/{len(remaining)}，暂停 {TDX_BATCH_PAUSE}s ...")
            time.sleep(TDX_BATCH_PAUSE)

    print(f"[XDXR] 同步完成 — 成功: {success}, 空事件: {empty}, 失败: {fail}")
    if affected:
        print(f"[XDXR] {len(affected)} 只有新增除权事件: {affected}")
    return affected


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SIRS 除权除息事件同步")
    parser.add_argument("--code", type=str, default=None, help="仅同步指定股票")
    args = parser.parse_args()

    print("=" * 50)
    print("SIRS — 除权除息事件同步（数据源：通达信）")
    print("=" * 50)

    client = get_tdx_client()

    if args.code:
        code = args.code
        print(f"[XDXR] 同步 {code} ...")
        try:
            xdxr_df = client.xdxr(symbol=code)
            if xdxr_df is not None and not xdxr_df.empty:
                conn = get_pg_conn()
                total, new_cnt = insert_xdxr_events(code, xdxr_df, conn)
                conn.close()
                print(f"[XDXR] {code}: {new_cnt} 条新事件")
            else:
                print(f"[XDXR] {code}: 无除权事件")
        except Exception as e:
            print(f"[ERROR] {code}: {e}")
            sys.exit(1)
    else:
        sync_all_stocks(client)

    print("\n[DONE] 除权事件同步完成")


if __name__ == "__main__":
    main()
