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
from datetime import date

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


def load_xdxr_checkpoint() -> dict:
    """加载已同步 xdxr 的股票 → {code: 同步日期 'YYYY-MM-DD' 或 None（旧格式无日期）}"""
    if not os.path.exists(CHECKPOINT_XDXR):
        return {}
    result = {}
    with open(CHECKPOINT_XDXR, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            code = parts[0]
            date_str = parts[1] if len(parts) > 1 and parts[1] else None
            result[code] = date_str
    return result


def write_xdxr_checkpoint(snapshot: dict):
    """一次性写回 checkpoint（新格式：code,YYYY-MM-DD），避免 append 膨胀"""
    tmp = CHECKPOINT_XDXR + ".tmp"
    with open(tmp, "w") as f:
        for code in sorted(snapshot):
            date_str = snapshot[code]
            f.write(f"{code},{date_str}\n" if date_str else f"{code}\n")
    os.replace(tmp, CHECKPOINT_XDXR)


def sync_all_stocks(client=None, force=False, max_age=30):
    """遍历所有活跃股票，拉取除权除息事件入库。
    返回有新增除权事件的股票代码列表。

    force: 忽略 checkpoint，全量重拉
    max_age: 超过 N 天未同步的股票重新拉取（checkpoint 旧格式无日期视为需重拉）
    """
    if client is None:
        client = get_tdx_client()

    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT code, name FROM stocks WHERE is_active = TRUE ORDER BY code")
    stocks = cur.fetchall()
    cur.close()
    conn.close()

    checkpoint = load_xdxr_checkpoint()

    if force:
        remaining = stocks
    else:
        today = date.today()
        remaining = [
            s for s in stocks
            if s["code"] not in checkpoint
            or checkpoint[s["code"]] is None
            or (today - date.fromisoformat(checkpoint[s["code"]])).days > max_age
        ]

    print(f"[XDXR] 总数: {len(stocks)}, 已完成: {len(checkpoint)}, 剩余: {len(remaining)}")

    if not remaining:
        print("[XDXR] 所有股票已同步，无需处理")
        return []

    success = 0
    fail = 0
    empty = 0
    affected = []
    today = date.today().isoformat()

    for i, stock in enumerate(tqdm(remaining, desc="同步除权事件")):
        code = stock["code"]

        try:
            xdxr_df = client.xdxr(symbol=code)

            if xdxr_df is None or xdxr_df.empty:
                checkpoint[code] = today
                empty += 1
                time.sleep(TDX_REQUEST_DELAY)
                continue

            conn = get_pg_conn()
            total, new_cnt = insert_xdxr_events(code, xdxr_df, conn)
            conn.close()

            checkpoint[code] = today
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

    # 一次性写回 checkpoint（新格式带日期，旧格式在此全部转换）
    write_xdxr_checkpoint(checkpoint)

    print(f"[XDXR] 同步完成 — 成功: {success}, 空事件: {empty}, 失败: {fail}")
    if affected:
        print(f"[XDXR] {len(affected)} 只有新增除权事件: {affected}")
    return affected


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SIRS 除权除息事件同步")
    parser.add_argument("--code", type=str, default=None, help="仅同步指定股票")
    parser.add_argument("--force", action="store_true", help="忽略 checkpoint，全量重拉")
    parser.add_argument("--max-age", type=int, default=30, help="超过 N 天未同步的股票重拉 (default: 30)")
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
            # 更新 checkpoint（标记该股票今天已同步）
            checkpoint = load_xdxr_checkpoint()
            checkpoint[code] = date.today().isoformat()
            write_xdxr_checkpoint(checkpoint)
        except Exception as e:
            print(f"[ERROR] {code}: {e}")
            sys.exit(1)
    else:
        sync_all_stocks(client, force=args.force, max_age=args.max_age)

    print("\n[DONE] 除权事件同步完成")


if __name__ == "__main__":
    main()
