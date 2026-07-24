"""
SIRS 数据管道 — 数据库连接配置
数据源：通达信行情服务器（通过 mootdx 直连 TCP 协议）
"""

PG_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "sirs",
    "user": "sirs",
    "password": "sirs123",
}

TDENGINE_CONFIG = {
    "host": "localhost",
    "port": 6041,          # taosAdapter REST/WebSocket 端口
    "user": "root",
    "password": "taosdata",
    "database": "sirs",
}

# ── mootdx / 通达信配置 ──
TDX_REQUEST_DELAY = 0.15      # 每只股票请求间隔（秒），通达信 TCP 协议较宽容
TDX_BARS_LIMIT = 800          # 通达信单次最多返回的日K线条数
TDX_BATCH_PAUSE = 2.0         # 每 N 只股票后暂停（秒）
TDX_BATCH_SIZE = 200          # 每多少只股票暂停一次

# PG 批量写入大小
PG_BATCH_SIZE = 500

# 断点续传记录文件
CHECKPOINT_FILE = "checkpoint.txt"

# 向后兼容
REQUEST_INTERVAL = TDX_REQUEST_DELAY

# ── 多服务器并发 ──
TDX_WORKERS = 5               # 并发 worker 数（每个连不同通达信服务器）
TDINSERT_BATCH_SIZE = 100     # TDengine 批量 INSERT 的股票数
TDSUBTABLE_BATCH_SIZE = 200   # 批量创建子表数

# ── 通知扫描配置 ──
NOTIFICATION_NEAR_LINE_PCT = 0.03   # "靠近"白线/黄线的阈值（收盘价在线条上方 3% 以内）
NOTIFICATION_KDJ_J_THRESHOLD = 20   # KDJ J 值买入阈值
NOTIFICATION_KLINE_DAYS = 300       # 每次扫描取多少根日K线（至少 >114 以覆盖 MA114）

# 通达信行情服务器列表（经 bars() 实测可用的 tdxpy 服务器，2026-07-22 验证）
# 格式：(host, port)，分布：上海电信、杭州电信/联通、北京联通、国泰君安、华林，共 20 台
TDX_SERVER_LIST = [
    # 主站 — 上海电信
    ("180.153.18.170", 7709), ("180.153.18.172", 80),
    # 主站 — 北京联通
    ("202.108.253.139", 80),
    # 主站 — 杭州电信
    ("60.191.117.167", 7709), ("115.238.56.198", 7709),
    ("218.75.126.9", 7709), ("115.238.90.165", 7709),
    # 主站 — 杭州联通
    ("60.12.136.250", 7709),
    # 国泰君安
    ("117.34.114.13", 7709), ("117.34.114.14", 7709),
    ("117.34.114.15", 7709), ("117.34.114.16", 7709),
    ("117.34.114.17", 7709), ("117.34.114.18", 7709),
    ("117.34.114.20", 7709), ("117.34.114.27", 7709),
    # 华林
    ("218.106.92.182", 7709), ("218.106.92.183", 7709),
    ("220.178.55.71", 7709), ("220.178.55.86", 7709),
]
