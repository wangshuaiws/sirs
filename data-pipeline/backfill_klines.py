"""
SIRS — K线历史数据补全脚本

数据源：通达信行情服务器（mootdx 直连 TCP 协议）

功能：
1. 对每只已入库的股票，从通达信拉取更早期的 K 线数据
2. 每次拉取 800 条（TDX_BARS_LIMIT），逐批回溯直到上市日或无更多数据
3. 幂等写入 TDengine（重复数据自动跳过）
4. 支持断点续传（独立 checkpoint 文件）
5. 多服务器并发，加速导入

背景：
init_stocks.py 导入了最近 ~800 个交易日的 K 线数据。本脚本补全从第 800 条
往后的全部历史数据，覆盖股票上市以来的完整区间。

用法：
    python backfill_klines.py                    # 补全所有股票的全部历史
    python backfill_klines.py --code 000001      # 仅补全指定股票
    python backfill_klines.py --max-chunks 3     # 每只股票最多拉取 3 批（3×800=2400 条）
    python backfill_klines.py --skip-recent 300  # 跳过最近 300 条再开始（如果 init 只导入了 300 条）
    python backfill_klines.py --dry-run          # 仅检测，不写入数据
"""

import time
import math
import os
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

import psycopg2
import psycopg2.extras
from mootdx.quotes import Quotes

from config import (
    PG_CONFIG, TDENGINE_CONFIG,
    TDX_REQUEST_DELAY, TDX_BARS_LIMIT,
    TDX_WORKERS, TDX_SERVER_LIST,
    TDINSERT_BATCH_SIZE, TDSUBTABLE_BATCH_SIZE,
)
from init_stocks import (
    get_pg_conn, td_rest_sql,
    create_kline_subtable, insert_kline_batch,
    ping_tdx_servers, clean_name,
)

BACKFILL_CHECKPOINT = "checkpoint_backfill.txt"


# ═══════════════════════════════════════════════════════════════════════
# 断点续传
# ═══════════════════════════════════════════════════════════════════════

def load_backfill_checkpoint() -> set:
    """加载已完成股票代码集合（格式：code 或 code:N，N 为已完成的 chunk 数）"""
    if not os.path.exists(BACKFILL_CHECKPOINT):
        return set()
    completed = set()
    with open(BACKFILL_CHECKPOINT, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                completed.add(line)
    return completed


def save_backfill_checkpoint(code: str, chunk_index: int = 0, total_chunks: int = 0):
    """追加已完成的股票代码（格式：code:chunk_index:total_chunks:timestamp）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(BACKFILL_CHECKPOINT, "a") as f:
        f.write(f"{code}:{chunk_index}:{total_chunks}:{ts}\n")


# ═══════════════════════════════════════════════════════════════════════
# 单只股票历史 K 线补全
# ═══════════════════════════════════════════════════════════════════════

def backfill_one_stock(
    client: Quotes,
    code: str,
    name: str,
    skip_recent: int = 800,
    max_chunks: int = None,
    dry_run: bool = False,
) -> dict:
    """补全单只股票的历史 K 线数据。

    从 skip_recent 位置开始，每次拉取 TDX_BARS_LIMIT 条，逐批回溯，
    直到服务器无更多数据返回或达到 max_chunks 上限。

    Args:
        client: mootdx Quotes 客户端
        code: 股票代码
        name: 股票名称
        skip_recent: 跳过最近多少条（这些数据 init_stocks 已导入）
        max_chunks: 最多拉取几批（None = 不限制，直到无数据）
        dry_run: 仅检测，不实际写入 TDengine

    Returns:
        {"chunks": int, "bars": int, "earliest": str, "newest": str, "error": str|None}
    """
    market = 1 if code.startswith('6') else 0
    start = skip_recent
    total_bars = 0
    chunks_done = 0
    earliest_date = None
    newest_date = None
    error = None

    while True:
        if max_chunks is not None and chunks_done >= max_chunks:
            break

        try:
            raw = client.bars(
                symbol=code, frequency=9, market=market,
                start=start, offset=TDX_BARS_LIMIT,
            )
        except Exception as e:
            error = f"chunk {chunks_done + 1} (start={start}): {e}"
            break

        if raw is None or raw.empty:
            break

        bar_count = len(raw)
        total_bars += bar_count

        # 记录本批次的最早日期（index[0] 是本批最早，会被后续更早的 chunk 覆盖）
        try:
            earliest_date = raw.index[0].strftime("%Y-%m-%d")
        except Exception:
            earliest_date = str(raw.index[0])[:10]

        # 记录第一批（最新）的最后一个日期，即与已有数据的交界处
        if newest_date is None:
            try:
                newest_date = raw.index[-1].strftime("%Y-%m-%d")
            except Exception:
                newest_date = str(raw.index[-1])[:10]

        if not dry_run:
            # 转换为 TDengine 插入格式
            rows = []
            for idx, row in raw.iterrows():
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

        chunks_done += 1

        # 如果返回的条数不足请求的条数，说明已经到达该股票最早的数据
        if bar_count < TDX_BARS_LIMIT:
            break

        start += TDX_BARS_LIMIT
        time.sleep(TDX_REQUEST_DELAY)

    return {
        "code": code,
        "chunks": chunks_done,
        "bars": total_bars,
        "earliest": earliest_date,
        "newest": newest_date,
        "error": error,
    }


# ═══════════════════════════════════════════════════════════════════════
# 串行模式（单服务器）
# ═══════════════════════════════════════════════════════════════════════

def backfill_sequential(
    stocks: List[Tuple[str, str]],
    skip_recent: int,
    max_chunks: int = None,
    dry_run: bool = False,
):
    """串行补全所有股票的历史 K 线（单客户端、单连接）。"""
    client = Quotes.factory(market='std')
    total = len(stocks)
    total_bars_all = 0

    for i, (code, name) in enumerate(stocks):
        print(f"\n[{i + 1}/{total}] {code} {name} ", end="", flush=True)

        # 确保子表存在
        if not dry_run:
            try:
                create_kline_subtable(code, name)
            except Exception as e:
                print(f"— 子表创建失败: {e}")
                save_backfill_checkpoint(code, 0, 0)
                continue

        result = backfill_one_stock(
            client, code, name,
            skip_recent=skip_recent,
            max_chunks=max_chunks,
            dry_run=dry_run,
        )

        total_bars_all += result["bars"]

        if result["error"]:
            print(f"— ❌ {result['error']}")
        elif result["chunks"] == 0:
            print(f"— ✓ 无需补全（无更早数据）")
        else:
            newest = result.get("newest") or "?"
            earliest = result.get("earliest") or "?"
            action = "将导入" if dry_run else "已导入"
            print(f"— {action} {result['bars']} 条 ({result['chunks']} 批), "
                  f"{newest} → {earliest}")

        save_backfill_checkpoint(code, result["chunks"], result["bars"])

        # 速率控制
        time.sleep(TDX_REQUEST_DELAY)

        # 每 N 只暂停
        if (i + 1) % 200 == 0:
            tag = "[DRY-RUN] " if dry_run else ""
            print(f"\n  ... {tag}已处理 {i + 1}/{total}, 累计 {total_bars_all} 条")

    return total_bars_all


# ═══════════════════════════════════════════════════════════════════════
# 并发模式（多服务器）
# ═══════════════════════════════════════════════════════════════════════

def _worker_backfill(
    stocks: List[Tuple[str, str]],
    server: Tuple[str, int],
    skip_recent: int,
    max_chunks: int = None,
    dry_run: bool = False,
    worker_id: int = 0,
):
    """单个 worker：连接指定通达信服务器，串行补全一批股票的历史 K 线。

    注意：不在此 worker 内做子表创建（DDL），子表已在主线程批量创建完毕。
    """
    host, port = server
    client = Quotes.factory(market='std', server=(host, port))
    results = []

    for code, name in stocks:
        result = backfill_one_stock(
            client, code, name,
            skip_recent=skip_recent,
            max_chunks=max_chunks,
            dry_run=dry_run,
        )
        results.append(result)

        # 每个请求后保存 checkpoint（便于监控进度）
        save_backfill_checkpoint(code, result["chunks"], result["bars"])

        # 速率控制
        time.sleep(TDX_REQUEST_DELAY)

    return results


def backfill_concurrent(
    stocks: List[Tuple[str, str]],
    skip_recent: int,
    max_chunks: int = None,
    dry_run: bool = False,
):
    """多服务器并发补全所有股票的历史 K 线。"""
    total = len(stocks)

    # ── Phase 0: 选最快的 N 个服务器 ──
    print(f"[Phase 0] 测速 {len(TDX_SERVER_LIST)} 个服务器...")
    fast_servers = ping_tdx_servers(TDX_SERVER_LIST, top_n=TDX_WORKERS)
    if len(fast_servers) < TDX_WORKERS:
        print(f"  [WARN] 仅 {len(fast_servers)}/{TDX_WORKERS} 个服务器可达")
    print(f"  [Servers] ({len(fast_servers)}): "
          f"{', '.join(f'{h}:{p}' for h, p in fast_servers)}")

    n_workers = len(fast_servers)

    # ── Phase 1: 批量创建子表 ──
    if not dry_run:
        print(f"[Phase 1] 批量创建子表（{total} 只）...")
        from init_stocks import batch_create_subtables
        batch_create_subtables(stocks)
    else:
        print(f"[Phase 1] [DRY-RUN] 跳过子表创建")

    # ── Phase 2: 多服务器并发补全 ──
    print(f"[Phase 2] 并发补全历史K线 ({n_workers} workers, "
          f"skip_recent={skip_recent}, max_chunks={max_chunks or '无限'})...")
    phase_start = time.time()

    all_results = []
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        chunk_size = math.ceil(total / n_workers)
        futures = {}
        for i, server in enumerate(fast_servers):
            chunk = stocks[i * chunk_size: (i + 1) * chunk_size]
            f = executor.submit(
                _worker_backfill, chunk, server,
                skip_recent, max_chunks, dry_run, i,
            )
            futures[f] = (i, server, len(chunk))

        for f in as_completed(futures):
            worker_id, server, stock_count = futures[f]
            try:
                results = f.result()
                all_results.extend(results)
            except Exception as e:
                print(f"  [ERROR] Worker {worker_id} ({server[0]}:{server[1]}): {e}")

    phase_elapsed = time.time() - phase_start

    # ── 汇总 ──
    total_bars = sum(r["bars"] for r in all_results)
    total_chunks = sum(r["chunks"] for r in all_results)
    empty = sum(1 for r in all_results if r["chunks"] == 0)
    errors = sum(1 for r in all_results if r["error"])

    print(f"\n[Phase 2] 完成 — 耗时: {phase_elapsed:.1f}s")
    print(f"  股票数: {len(all_results)}/{total}")
    print(f"  无需补全: {empty}")
    print(f"  总 chunk: {total_chunks}")
    print(f"  总 K 线条数: {total_bars}")
    if errors:
        print(f"  错误: {errors}")

    # 打印最早日期信息
    with_earliest = [r for r in all_results if r.get("earliest")]
    if with_earliest:
        earliest_overall = min(r["earliest"] for r in with_earliest)
        print(f"  覆盖最早日期: {earliest_overall}")

    return total_bars


# ═══════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SIRS — K线历史数据补全（通达信）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python backfill_klines.py                        # 补全所有股票的全部历史
  python backfill_klines.py --code 000001          # 仅补全 000001
  python backfill_klines.py --max-chunks 3         # 每只最多 3 批 (3×800=2400 条)
  python backfill_klines.py --skip-recent 300      # 跳过最近 300 条（适用于 init 只导入了 300 条的情况）
  python backfill_klines.py --dry-run              # 仅检测，不实际写入
  python backfill_klines.py --sequential           # 串行模式（单服务器，用于调试）
        """,
    )
    parser.add_argument(
        "--code", type=str, default=None,
        help="仅补全指定股票代码",
    )
    parser.add_argument(
        "--skip-recent", type=int, default=800,
        help="跳过最近 N 条 K 线（默认 800，与 init_stocks 的 TDX_BARS_LIMIT 一致）",
    )
    parser.add_argument(
        "--max-chunks", type=int, default=None,
        help="每只股票最多拉取几批（None = 不限，直到上市第一天）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅检测，不实际写入 TDengine",
    )
    parser.add_argument(
        "--sequential", action="store_true",
        help="串行模式（单服务器连接，用于调试）",
    )
    parser.add_argument(
        "--reset-checkpoint", action="store_true",
        help="清除断点续传记录，从头开始",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("SIRS — K线历史数据补全（数据源：通达信）")
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"跳过最近: {args.skip_recent} 条")
    print(f"每批大小: {TDX_BARS_LIMIT} 条")
    print(f"最大批次: {'不限' if args.max_chunks is None else args.max_chunks}")
    if args.dry_run:
        print("模式: DRY-RUN（仅检测，不写入）")
    print("=" * 60)

    # ── 清除 checkpoint ──
    if args.reset_checkpoint and os.path.exists(BACKFILL_CHECKPOINT):
        os.remove(BACKFILL_CHECKPOINT)
        print("[Checkpoint] 已清除断点续传记录")

    # ── 加载已完成的股票 ──
    completed_raw = load_backfill_checkpoint()
    # 解析 checkpoint：格式 "code:chunks:bars:timestamp"
    completed_codes = set()
    for entry in completed_raw:
        parts = entry.split(":")
        if parts:
            completed_codes.add(parts[0])

    # ── 查询待处理股票 ──
    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if args.code:
        cur.execute(
            "SELECT code, name FROM stocks WHERE code = %s AND is_active = TRUE",
            (args.code,),
        )
    else:
        cur.execute("SELECT code, name FROM stocks WHERE is_active = TRUE ORDER BY code")
    all_stocks = cur.fetchall()
    cur.close()
    conn.close()

    if not all_stocks:
        print("[ERROR] 未找到待处理的股票")
        return

    # 过滤已完成的
    if args.code:
        # 单股票模式：忽略 checkpoint，强制重跑
        remaining = [(s["code"], s["name"]) for s in all_stocks]
        print(f"[Info] 单股票模式: {remaining[0][0]} {remaining[0][1]}")
    else:
        remaining = [
            (s["code"], s["name"]) for s in all_stocks
            if s["code"] not in completed_codes
        ]
        print(f"[Info] 总数: {len(all_stocks)}, "
              f"已完成: {len(completed_codes)}, "
              f"剩余: {len(remaining)}")

    if not remaining:
        print("[DONE] 所有股票已完成补全，无需处理")
        return

    # ── 执行补全 ──
    if args.sequential or len(remaining) == 1:
        total_bars = backfill_sequential(
            remaining,
            skip_recent=args.skip_recent,
            max_chunks=args.max_chunks,
            dry_run=args.dry_run,
        )
    else:
        total_bars = backfill_concurrent(
            remaining,
            skip_recent=args.skip_recent,
            max_chunks=args.max_chunks,
            dry_run=args.dry_run,
        )

    print(f"\n[DONE] 补全完成 — 共导入 {total_bars} 条历史K线")


if __name__ == "__main__":
    main()
