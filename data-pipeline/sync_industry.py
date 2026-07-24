"""
SIRS — 行业分类数据同步脚本

数据源：新浪财经 API（申万二级 + 新浪行业双源合并）
功能：
1. 获取申万二级 + 新浪行业分类节点
2. 遍历每个行业获取成分股
3. 合并双源数据（申万优先），更新 stocks 表的 industry 字段
"""

import json
import time
import sys
import urllib.request
import urllib.parse

import psycopg2
import psycopg2.extras
from tqdm import tqdm

from config import PG_CONFIG

BATCH_SIZE = 200          # 每批更新的股票数
REQUEST_DELAY = 0.5       # 请求间隔（秒）
API_TIMEOUT = 15          # 请求超时（秒）
PAGE_SIZE = 500           # 每页股票数

SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

SINA_NODES_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/Market_Center.getHQNodes"
)
SINA_NODE_DATA_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
    "/Market_Center.getHQNodeData"
)


def get_pg_conn():
    """获取 PostgreSQL 连接"""
    return psycopg2.connect(**PG_CONFIG)


def ensure_industry_column():
    """确保 stocks 表有 industry 列（兼容旧表）"""
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'stocks' AND column_name = 'industry'
            ) THEN
                ALTER TABLE stocks ADD COLUMN industry VARCHAR(50);
            END IF;
        END $$;
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("[PG] industry 列检查完成")


def sina_fetch(url: str) -> list | dict:
    """调用新浪 API 并返回解析后的 JSON"""
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def fetch_industry_nodes(layer_name: str) -> list[tuple[str, str]]:
    """
    从新浪获取指定行业分类节点列表
    layer_name: "申万二级" | "新浪行业"
    """
    print(f"[Sina] 获取 {layer_name} 分类节点...")
    data = sina_fetch(SINA_NODES_URL)

    nodes: list[tuple[str, str]] = []
    try:
        a_stock_group = data[1][0][1]
        for group in a_stock_group:
            if isinstance(group, list) and len(group) >= 3 and group[0] == layer_name:
                children = group[1] if len(group) > 1 else []
                for node in children:
                    if isinstance(node, list) and len(node) >= 3:
                        name, code = node[0], node[2]
                        if code and name:
                            nodes.append((code, name))
                break
    except (IndexError, TypeError) as e:
        print(f"[Sina] 解析节点失败: {e}")
        sys.exit(1)

    print(f"[Sina] {layer_name}: {len(nodes)} 个分类")
    return nodes


def fetch_stocks_by_node(node_code: str) -> list[dict]:
    """分页获取某个行业节点的所有股票"""
    all_stocks = []
    page = 1

    while True:
        params = urllib.parse.urlencode({
            "page": page,
            "num": PAGE_SIZE,
            "sort": "symbol",
            "asc": "1",
            "node": node_code,
        })
        url = f"{SINA_NODE_DATA_URL}?{params}"
        data = sina_fetch(url)

        if not data or not isinstance(data, list) or len(data) == 0:
            break

        all_stocks.extend(data)

        if len(data) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.3)

    return all_stocks


def fetch_map_from_nodes(nodes: list[tuple[str, str]], desc: str) -> dict[str, str]:
    """从节点列表获取 code → industry 映射"""
    code_industry: dict[str, str] = {}
    failed: list[str] = []

    for node_code, industry_name in tqdm(nodes, desc=desc):
        try:
            stocks = fetch_stocks_by_node(node_code)
            for s in stocks:
                code = s.get("code", "")
                if code:
                    if code not in code_industry:
                        code_industry[code] = industry_name
        except Exception as e:
            failed.append(f"{industry_name}({e})")
            continue
        time.sleep(REQUEST_DELAY)

    if failed:
        print(f"[Sina] {desc}: {len(failed)} 个获取失败")

    return code_industry


def fetch_industry_map() -> dict[str, str]:
    """获取合并后的 code → industry 映射（申万优先，新浪行业补充）"""
    # 1. 申万二级（优先，更权威）
    sw_nodes = fetch_industry_nodes("申万二级")
    sw_map = fetch_map_from_nodes(sw_nodes, "申万二级")
    print(f"[Sina] 申万二级覆盖: {len(sw_map)} 只")

    # 2. 新浪行业（补充申万未覆盖的）
    xl_nodes = fetch_industry_nodes("新浪行业")
    xl_map = fetch_map_from_nodes(xl_nodes, "新浪行业")
    print(f"[Sina] 新浪行业覆盖: {len(xl_map)} 只")

    # 合并：申万优先
    merged = dict(xl_map)   # 先放新浪行业
    merged.update(sw_map)   # 申万覆盖（优先）
    print(f"[Sina] 合并后总计: {len(merged)} 只")

    return merged


def update_industries(code_industry: dict):
    """批量更新 stocks 表的 industry 字段"""
    conn = get_pg_conn()
    cur = conn.cursor()

    codes = list(code_industry.keys())
    total = len(codes)
    updated = 0

    for i in tqdm(range(0, total, BATCH_SIZE), desc="更新数据库"):
        batch = codes[i:i + BATCH_SIZE]
        data = [(code, code_industry[code]) for code in batch]
        psycopg2.extras.execute_values(
            cur,
            """
            UPDATE stocks SET
                industry = data.industry,
                updated_at = NOW()
            FROM (VALUES %s) AS data(code, industry)
            WHERE stocks.code = data.code
            """,
            data,
            template="(%s, %s)",
            page_size=BATCH_SIZE,
        )
        updated += cur.rowcount
        conn.commit()

    cur.close()
    conn.close()
    print(f"[PG] 更新完成: {updated} 条记录")


def show_summary():
    """打印行业分布摘要"""
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) AS total,
               COUNT(industry) AS with_industry,
               ROUND(COUNT(industry) * 100.0 / NULLIF(COUNT(*), 0), 1) AS coverage
        FROM stocks WHERE is_active = TRUE
    """)
    row = cur.fetchone()
    if row:
        print(f"\n行业覆盖: {row[2]}% ({row[1]}/{row[0]} 只活跃股票)")

    cur.execute("""
        SELECT industry, COUNT(*) AS cnt
        FROM stocks
        WHERE is_active = TRUE AND industry IS NOT NULL
        GROUP BY industry
        ORDER BY cnt DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    if rows:
        print("\nTop 10 行业分布:")
        for r in rows:
            print(f"  {r[0]:<16s} {r[1]:>4d}")

    cur.close()
    conn.close()


def main():
    print("=" * 50)
    print("SIRS — 行业分类数据同步（申万二级 + 新浪行业）")
    print("=" * 50)

    ensure_industry_column()
    code_industry = fetch_industry_map()
    update_industries(code_industry)
    show_summary()
    print("\n行业数据同步完成。")


if __name__ == "__main__":
    main()
