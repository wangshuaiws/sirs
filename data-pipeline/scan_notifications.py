"""
SIRS — 技术指标通知扫描脚本

扫描每个用户「自选股」分组中的股票，计算 ZXDQ / ZXDKX / KDJ 指标，
基于状态机检测 5 种通知信号并写入 PostgreSQL。

用法：
    python scan_notifications.py              # 扫描所有用户
    python scan_notifications.py --user 1     # 扫描指定用户
    python scan_notifications.py --dry-run    # 仅计算不写入，打印信号
"""

import os
import sys
import json
import argparse
import fcntl
from datetime import date, datetime, timedelta
from collections import defaultdict

import psycopg2
import psycopg2.extras

from config import (
    PG_CONFIG, TDENGINE_CONFIG,
    NOTIFICATION_NEAR_LINE_PCT,
    NOTIFICATION_KDJ_J_THRESHOLD,
    NOTIFICATION_KLINE_DAYS,
)

from init_stocks import get_pg_conn, td_rest_sql

LOCK_FILE = os.path.join(os.path.dirname(__file__), ".scan_notifications.lock")

# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

def acquire_lock():
    """文件锁 — 防止并发执行"""
    fp = open(LOCK_FILE, "w")
    try:
        fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[WARN] 已有 scan_notifications 正在运行，退出")
        sys.exit(0)
    return fp


# ═══════════════════════════════════════════════════════════════════════
# 通知检测 & 状态机
# ═══════════════════════════════════════════════════════════════════════

def near_line(close, line_val):
    """收盘价是否在指标线附近（上方 3% 以内）"""
    if line_val is None or line_val <= 0:
        return False
    ratio = close / line_val
    return 1.0 <= ratio <= (1.0 + NOTIFICATION_NEAR_LINE_PCT)


def transition(state_row, close, prev_close, zxdq, prev_zxdq, zxdkx, prev_zxdkx, j):
    """
    状态机核心 — 根据当前状态和最新指标计算信号转换。

    state_row: stock_signal_state 当前行 dict (含 white_buy_notified, yellow_buy_notified)
    返回 (new_state, notifications_list, new_white_notified, new_yellow_notified)

    notifications_list 中每条为: {type, message, detail}
    """
    state = state_row["signal_state"]
    new_state = state
    notifications = []
    new_white_notified = state_row.get("white_buy_notified", False)
    new_yellow_notified = state_row.get("yellow_buy_notified", False)

    if state == "NONE":
        # 检测金叉：prev_zxdq <= prev_zxdkx AND zxdq > zxdkx
        if (prev_zxdq is not None and prev_zxdkx is not None
                and zxdq is not None and zxdkx is not None
                and prev_zxdq <= prev_zxdkx and zxdq > zxdkx):
            new_state = "HAS_GOLDEN_CROSS"
            new_white_notified = False   # 新周期重置
            new_yellow_notified = False
            notifications.append({
                "type": "GOLDEN_CROSS",
                "message": f"ZXDQ ({zxdq:.2f}) 上穿 ZXDKX ({zxdkx:.2f})，金叉确认，关注 N 型上涨",
                "detail": {
                    "zxdq": zxdq,
                    "zxdkx": zxdkx,
                    "cross_date": str(date.today()),
                },
            })

    elif state == "HAS_GOLDEN_CROSS":
        # 白线买入：未通知过 + 收盘价靠近白线 + KDJ J < 20
        if (not state_row.get("white_buy_notified", False)
                and near_line(close, zxdq) and j is not None and j < NOTIFICATION_KDJ_J_THRESHOLD):
            new_white_notified = True
            notifications.append({
                "type": "WHITE_LINE_BUY",
                "message": f"回踩白线 ZXDQ ({zxdq:.2f})，KDJ J={j:.1f}<20，放量拉升缩量回调，买入机会",
                "detail": {
                    "zxdq": zxdq,
                    "close": close,
                    "j_value": round(j, 2),
                },
            })

        # 黄线买入：未通知过 + 收盘价靠近黄线 + KDJ J < 20
        if (not state_row.get("yellow_buy_notified", False)
                and near_line(close, zxdkx) and j is not None and j < NOTIFICATION_KDJ_J_THRESHOLD):
            new_yellow_notified = True
            notifications.append({
                "type": "YELLOW_LINE_BUY",
                "message": f"回踩黄线 ZXDKX ({zxdkx:.2f})，KDJ J={j:.1f}<20，放量拉升缩量回调，买入机会",
                "detail": {
                    "zxdkx": zxdkx,
                    "close": close,
                    "j_value": round(j, 2),
                },
            })

        # 跌破黄线 → BELOW_YELLOW_1
        if zxdkx is not None and close < zxdkx:
            new_state = "BELOW_YELLOW_1"

    elif state == "BELOW_YELLOW_1":
        if zxdkx is not None and close < zxdkx:
            # 连续第二天跌破 → 清仓
            new_state = "BELOW_YELLOW_2"
            notifications.append({
                "type": "CLEAR_POSITION",
                "message": f"连续 2 日收盘价 ({close:.2f}) 低于黄线 ZXDKX ({zxdkx:.2f})，清仓卖出",
                "detail": {
                    "close": close,
                    "zxdkx": zxdkx,
                    "days_below": 2,
                },
            })
        else:
            # 假跌破，回到金叉状态
            new_state = "HAS_GOLDEN_CROSS"

    elif state == "BELOW_YELLOW_2":
        if zxdkx is not None and close >= zxdkx:
            # 重新站上黄线
            new_state = "NONE"
            notifications.append({
                "type": "RE_ATTENTION",
                "message": f"收盘价 ({close:.2f}) 重新站上黄线 ZXDKX ({zxdkx:.2f})，再次关注",
                "detail": {
                    "close": close,
                    "zxdkx": zxdkx,
                },
            })
        # 仍然在黄线下方 → 保持 BELOW_YELLOW_2，不发通知

    return new_state, notifications, new_white_notified, new_yellow_notified


# ═══════════════════════════════════════════════════════════════════════
# 数据库操作
# ═══════════════════════════════════════════════════════════════════════

def get_or_create_state(cur, user_id, stock_code):
    """获取或创建 stock_signal_state 行，返回 dict"""
    cur.execute("""
        SELECT signal_state, golden_cross_date,
               white_buy_notified, yellow_buy_notified, state_date
        FROM stock_signal_state
        WHERE user_id = %s AND stock_code = %s
    """, (user_id, stock_code))
    row = cur.fetchone()
    if row:
        return {
            "signal_state": row[0],
            "golden_cross_date": row[1],
            "white_buy_notified": row[2],
            "yellow_buy_notified": row[3],
            "state_date": row[4],
        }
    # 不存在 → 插入默认行
    cur.execute("""
        INSERT INTO stock_signal_state (user_id, stock_code, signal_state)
        VALUES (%s, %s, 'NONE')
        ON CONFLICT (user_id, stock_code) DO NOTHING
    """, (user_id, stock_code))
    return {
        "signal_state": "NONE",
        "golden_cross_date": None,
        "white_buy_notified": False,
        "yellow_buy_notified": False,
        "state_date": None,
    }


def update_state(cur, user_id, stock_code, new_state, golden_cross_date,
                  white_buy_notified, yellow_buy_notified, state_date):
    """更新 stock_signal_state（state_date = 状态转移发生的交易日，用于同日幂等）"""
    cur.execute("""
        UPDATE stock_signal_state
        SET signal_state = %s,
            golden_cross_date = %s,
            white_buy_notified = %s,
            yellow_buy_notified = %s,
            state_date = %s,
            updated_at = NOW()
        WHERE user_id = %s AND stock_code = %s
    """, (new_state, golden_cross_date, white_buy_notified, yellow_buy_notified,
          state_date, user_id, stock_code))


def insert_notification(cur, user_id, stock_code, stock_name, notif, today):
    """插入一条通知 — 使用 ON CONFLICT DO NOTHING 防止同日重复"""
    detail_json = json.dumps(notif["detail"], ensure_ascii=False) if notif.get("detail") else None
    cur.execute("""
        INSERT INTO notifications (user_id, stock_code, stock_name, type, message, detail, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (user_id, stock_code, stock_name, notif["type"], notif["message"],
          detail_json, today))


def remove_from_non_watchlist_groups(cur, user_id, stock_code):
    """清仓时：将该股票从所有非「自选股」分组中移除"""
    cur.execute("""
        DELETE FROM group_stocks
        WHERE stock_code = %s
          AND group_id IN (
              SELECT id FROM groups
              WHERE user_id = %s AND name != '自选股'
          )
    """, (stock_code, user_id))


# ═══════════════════════════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════════════════════════

def get_watchlist_stocks(cur, user_id=None):
    """
    获取所有（或指定）用户的「自选股」分组中的股票。
    返回 {user_id: [(stock_code, stock_name), ...]}
    """
    if user_id:
        where = "AND u.id = %s"
        params = (user_id,)
    else:
        where = ""
        params = ()

    cur.execute(f"""
        SELECT DISTINCT u.id, gs.stock_code, s.name
        FROM users u
        JOIN groups g ON g.user_id = u.id AND g.name = '自选股'
        JOIN group_stocks gs ON gs.group_id = g.id
        JOIN stocks s ON s.code = gs.stock_code
        WHERE s.is_active = TRUE {where}
        ORDER BY u.id, gs.stock_code
    """, params)

    result = defaultdict(list)
    for row in cur.fetchall():
        uid, code, name = row
        result[uid].append((code, name))
    return dict(result)


def fetch_kline_data(code):
    """从 TDengine 获取最近 N 天的日K线及预计算指标"""
    sql = (
        f"SELECT ts, open, high, low, close, zxdq, zxdkx, kdj_j "
        f"FROM sirs.k_1d_adj_{code} "
        f"ORDER BY ts DESC LIMIT {NOTIFICATION_KLINE_DAYS}"
    )
    try:
        resp = td_rest_sql(sql)
    except Exception as e:
        print(f"  [WARN] {code} TDengine 查询失败: {e}")
        return []

    if resp.get("code") != 0:
        print(f"  [WARN] {code} TDengine 返回错误: {resp}")
        return []

    data_rows = resp.get("data", [])
    if not data_rows:
        return []

    # data_rows 按 ts DESC 返回，需要反转
    data_rows.reverse()

    klines = []
    for row in data_rows:
        # row[0]=ts, row[1]=open, row[2]=high, row[3]=low, row[4]=close,
        # row[5]=zxdq, row[6]=zxdkx, row[7]=kdj_j
        try:
            klines.append({
                "ts": str(row[0])[:10],
                "open": float(row[1]) if row[1] is not None else 0.0,
                "high": float(row[2]) if row[2] is not None else 0.0,
                "low": float(row[3]) if row[3] is not None else 0.0,
                "close": float(row[4]) if row[4] is not None else 0.0,
                "zxdq": float(row[5]) if row[5] is not None else None,
                "zxdkx": float(row[6]) if row[6] is not None else None,
                "kdj_j": float(row[7]) if row[7] is not None else None,
            })
        except (ValueError, TypeError, IndexError):
            continue
    return klines


# ═══════════════════════════════════════════════════════════════════════
# 全市场金叉扫描
# ═══════════════════════════════════════════════════════════════════════

def scan_market_golden_cross(cur, today_str, users, dry_run=False):
    """全市场扫描金叉（zxdq >= zxdkx 且昨日 <=），为每个用户生成发现通知"""
    from calc_indicators import td_query_rest

    # 取最近 7 天数据（确保足够覆盖到前一个交易日）
    from_dt = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    rows = td_query_rest(
        f"SELECT tbname, ts, zxdq, zxdkx FROM sirs.kline_1d_adj "
        f"WHERE ts >= '{from_dt}' ORDER BY tbname, ts"
    )
    if not rows:
        print("[Market] 无数据")
        return 0

    # 按股票分组，取最新 2 条
    stock_bars = {}
    for r in rows:
        tbname = r.get("tbname", "")
        code = tbname.replace("k_1d_adj_", "") if tbname.startswith("k_1d_adj_") else ""
        if not code:
            continue
        if code not in stock_bars:
            stock_bars[code] = []
        stock_bars[code].append((str(r["ts"])[:10], r.get("zxdq"), r.get("zxdkx")))

    # 获取股票名称映射
    import psycopg2
    from config import PG_CONFIG as _PG
    _conn = psycopg2.connect(**_PG)
    _c = _conn.cursor()
    _c.execute("SELECT code, name FROM stocks")
    code_name = {r[0]: r[1] for r in _c.fetchall()}
    _c.close(); _conn.close()

    printed_total = False
    today_golden = []

    for code, bars in stock_bars.items():
        if len(bars) < 2:
            continue
        bars.sort(key=lambda x: x[0])
        latest, prev = bars[-1], bars[-2]

        # 只判断今天的
        if latest[0] != today_str:
            continue

        z, x = latest[1], latest[2]
        pz, px = prev[1], prev[2]
        if any(v is None for v in (z, x, pz, px)):
            continue
        if not (float(pz) <= float(px) and float(z) >= float(x)):
            continue

        today_golden.append((code, float(z), float(x)))

    if not today_golden:
        print("[Market] 今日无金叉")
        return 0

    print(f"[Market] 今日金叉 {len(today_golden)} 只")
    if not printed_total:
        printed_total = True

    count = 0
    for code, z_val, x_val in today_golden:
        for uid, uname in users:
            state_row = get_or_create_state(cur, uid, code)
            if state_row["signal_state"] != "NONE":
                continue  # 已处理过，跳过

            if dry_run:
                print(f"\n[DRY-RUN] [Market] user={uid} {code} 金叉 (zxdq={z_val:.2f} zxdkx={x_val:.2f})")
                continue

            update_state(cur, uid, code, "HAS_GOLDEN_CROSS",
                         datetime.now().date(), False, False, datetime.now().date())
            stock_name = code_name.get(code, "")
            notif = {
                "type": "GOLDEN_CROSS",
                "message": "扫描该股票今日金叉确认，关注后续走势",
                "detail": {"zxdq": z_val, "zxdkx": x_val, "cross_date": today_str},
            }
            insert_notification(cur, uid, code, stock_name, notif, datetime.now())
            count += 1

    if dry_run:
        print(f"\n[DRY-RUN] [Market] 金叉扫描完成（未写入）")
    else:
        print(f"[Market] 金叉扫描完成，{count} 条新通知")
    return count


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

def scan_all_users(target_user_id=None, dry_run=False):
    """全市场金叉扫描 + 自选股状态机"""
    pg_conn = get_pg_conn()
    cur = pg_conn.cursor()

    today_str = datetime.now().strftime("%Y-%m-%d")

    # 0. 全市场金叉扫描（无论 dry_run 都执行，dry_run 仅打印）
    cur.execute("SELECT id, username FROM users ORDER BY id")
    all_users = cur.fetchall()
    scan_market_golden_cross(cur, today_str, all_users, dry_run=dry_run)
    if not dry_run:
        pg_conn.commit()

    # 1. 自选股状态机扫描
    watchlist_map = get_watchlist_stocks(cur, user_id=target_user_id)
    if not watchlist_map:
        print("[INFO] 没有找到任何用户的自选股数据")
        cur.close()
        pg_conn.close()
        return

    # 收集所有唯一股票代码
    all_codes = set()
    for uid, stocks in watchlist_map.items():
        for code, _ in stocks:
            all_codes.add(code)

    print(f"[INFO] 共 {len(watchlist_map)} 个用户，{len(all_codes)} 只唯一股票")

    # 逐只股票获取 K 线数据
    kline_cache = {}
    for code in sorted(all_codes):
        klines = fetch_kline_data(code)
        if klines and len(klines) >= 120:
            kline_cache[code] = klines
        else:
            if not klines:
                print(f"  [SKIP] {code} 无 K 线数据")
            else:
                print(f"  [SKIP] {code} K 线不足（{len(klines)}<120）")

    print(f"[INFO] 成功获取 {len(kline_cache)} 只股票的 K 线数据")

    today = datetime.now()
    total_notifications = 0

    # 逐用户处理
    for uid in sorted(watchlist_map.keys()):
        stocks = watchlist_map[uid]
        for code, stock_name in stocks:
            klines = kline_cache.get(code)
            if not klines:
                continue

            # 取最新两个值（直接从 adj 表预计算字段读取）
            latest_close = klines[-1]["close"]
            prev_close = klines[-2]["close"] if len(klines) >= 2 else None
            latest_zxdq = klines[-1]["zxdq"]
            prev_zxdq = klines[-2]["zxdq"] if len(klines) >= 2 else None
            latest_zxdkx = klines[-1]["zxdkx"]
            prev_zxdkx = klines[-2]["zxdkx"] if len(klines) >= 2 else None
            latest_j = klines[-1]["kdj_j"]

            # 获取当前状态
            state_row = get_or_create_state(cur, uid, code)

            # 幂等：状态今天已转移过 → 跳过（防止同一天重复运行把状态机推进多级）
            if state_row["state_date"] == today.date():
                continue

            # 执行状态机
            new_state, notifications, new_white, new_yellow = transition(
                state_row, latest_close, prev_close,
                latest_zxdq, prev_zxdq,
                latest_zxdkx, prev_zxdkx,
                latest_j,
            )

            golden_cross_date = state_row.get("golden_cross_date")
            if new_state == "HAS_GOLDEN_CROSS" and state_row["signal_state"] == "NONE":
                golden_cross_date = date.today()
            elif new_state == "NONE":
                golden_cross_date = None  # 周期结束，清除金叉日期

            if dry_run:
                if notifications:
                    print(f"\n[DRY-RUN] user={uid} {code} {stock_name} "
                          f"state: {state_row['signal_state']} → {new_state}")
                    for n in notifications:
                        print(f"  → [{n['type']}] {n['message']}")
                continue

            # 写入通知
            for n in notifications:
                insert_notification(cur, uid, code, stock_name, n, today)
                total_notifications += 1

                # 清仓时移除非自选股
                if n["type"] == "CLEAR_POSITION":
                    removed = remove_from_non_watchlist_groups(cur, uid, code)
                    print(f"  [CLEAR] user={uid} {code} {stock_name} 已移除非自选股分组")

            # 更新状态（state_date = 今天，标记今日已处理）
            if new_state != state_row["signal_state"] or new_white != state_row.get("white_buy_notified") or new_yellow != state_row.get("yellow_buy_notified"):
                update_state(cur, uid, code, new_state, golden_cross_date,
                             new_white, new_yellow, today.date())

    pg_conn.commit()
    cur.close()
    pg_conn.close()

    if dry_run:
        print(f"\n[DRY-RUN] 扫描完成（未写入数据库）")
    else:
        print(f"[DONE] 扫描完成，共产生 {total_notifications} 条新通知")


# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIRS 技术指标通知扫描")
    parser.add_argument("--user", type=int, default=None, help="仅扫描指定用户 ID")
    parser.add_argument("--dry-run", action="store_true", help="仅计算不写入，打印信号预览")
    args = parser.parse_args()

    lock_fp = acquire_lock()
    try:
        scan_all_users(target_user_id=args.user, dry_run=args.dry_run)
    finally:
        fcntl.lockf(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
