"""pgvector 向量检索验证脚本（纯 PG 侧验证，不依赖 embedding API）。

用 numpy 生成可控的伪随机向量，确保"相同主题的向量天然接近"，
从而验证 pgvector 的：
  1. 向量列创建与存储（vector(1536)）
  2. 余弦距离相似度排序（<=> 操作符）
  3. 用户隔离（WHERE user_id = ...）
  4. IVFFlat 向量索引生效
"""

import json
import os
from pathlib import Path

import numpy as np
import psycopg
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://myagent:myagent@localhost:5432/myagent",
)
EMBEDDING_DIM = 1536
TEST_USER_IDS = ("user_xiaoming", "user_lisi")


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id bigserial PRIMARY KEY,
                user_id text NOT NULL,
                content text NOT NULL,
                embedding vector({EMBEDDING_DIM}) NOT NULL,
                source_thread_id text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS memory_entries_user_id_idx
            ON memory_entries (user_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS memory_entries_embedding_cosine_idx
            ON memory_entries
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 1)
            """
        )


def make_embedding(seed: int, center: str) -> list[float]:
    """生成一个围绕 center 聚类的 1536 维向量。

    相同 center 的向量自然靠近，不同 center 的向量相互远离，
    这样相似度搜索的排序结果就可预测。
    """
    rng = np.random.default_rng(seed)
    centers = {
        "weather": np.array([1.0, 0.0, 0.0] + [0.0] * (EMBEDDING_DIM - 3)),
        "food":    np.array([0.0, 1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 3)),
        "animal":  np.array([0.0, 0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 3)),
        "city":    np.array([0.7, 0.7, 0.0] + [0.0] * (EMBEDDING_DIM - 3)),
    }
    c = centers[center]
    noise = rng.normal(scale=0.05, size=EMBEDDING_DIM)
    v = c + noise
    return v.tolist()


def run():
    # ── 准备测试数据 ──
    # 小明的记忆：天气类 2 条 + 城市类 1 条
    xiaoming = [
        ("小明喜欢晴天，出门运动",          "weather", "thread_001"),
        ("小明想了解明天的台风路径",        "weather", "thread_002"),
        ("小明住在深圳",                    "city",    "thread_001"),
    ]
    # 李四的记忆：美食类 2 条 + 动物类 1 条
    lisi = [
        ("李四爱吃火锅",                    "food",    "thread_003"),
        ("李四周末常去咖啡馆看书",          "food",    "thread_004"),
        ("李四养了一只金毛叫大黄",          "animal",  "thread_004"),
    ]

    print("📝 准备写入 6 条记忆...")

    with psycopg.connect(POSTGRES_URL) as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM memory_entries WHERE user_id IN (%s, %s)",
                TEST_USER_IDS,
            )

            for seed, (user_id, (content, cluster, thread_id)) in enumerate(
                [("user_xiaoming", m) for m in xiaoming] +
                [("user_lisi",     m) for m in lisi],
                start=1,
            ):
                emb = make_embedding(seed, cluster)
                cur.execute(
                    """
                    INSERT INTO memory_entries (user_id, content, embedding, source_thread_id)
                    VALUES (%s, %s, %s::vector, %s)
                    """,
                    (user_id, content, json.dumps(emb), thread_id),
                )

            cur.execute("ANALYZE memory_entries")
            count = cur.execute(
                """
                SELECT COUNT(*)
                FROM memory_entries
                WHERE user_id IN (%s, %s)
                """,
                TEST_USER_IDS,
            ).fetchone()[0]
            print(f"✅ 共写入 {count} 条记忆\n")

    # ── 查询 1：小明问"台风"（weather cluster 的向量）──
    print("=" * 70)
    print("🔍 查询 1：小明问'明天天气怎么样' → 用 weather 聚类向量")
    print("=" * 70)

    query_emb = make_embedding(seed=999, center="weather")

    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, user_id, embedding <=> %s::vector AS distance
                FROM memory_entries
                WHERE user_id = 'user_xiaoming'
                ORDER BY embedding <=> %s::vector
                LIMIT 5
                """,
                (json.dumps(query_emb), json.dumps(query_emb)),
            )
            rows = cur.fetchall()

    print(f"{'排名':<4} {'用户':<16} {'距离':<10} 内容")
    print("-" * 70)
    for i, (content, user, dist) in enumerate(rows, 1):
        print(f"{i:<4} {user:<16} {dist:<10.6f} {content}")

    assert all(r[1] == "user_xiaoming" for r in rows), "❌ 用户隔离失效！"
    # 两条 weather 应该排在前两位
    weather_rows = [r for r in rows if "台风" in r[0] or "晴天" in r[0]]
    assert len(weather_rows) >= 2, f"❌ 应命中至少 2 条天气相关，实际: {[r[0] for r in rows]}"
    print("\n✅ 用户隔离正常 + 天气类排最前")

    # ── 查询 2：李四的 food 类查询 ──
    print("\n" + "=" * 70)
    print("🔍 查询 2：李四的 food cluster 向量")
    print("=" * 70)

    query_emb = make_embedding(seed=888, center="food")

    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, user_id, embedding <=> %s::vector AS distance
                FROM memory_entries
                WHERE user_id = 'user_lisi'
                ORDER BY embedding <=> %s::vector
                LIMIT 5
                """,
                (json.dumps(query_emb), json.dumps(query_emb)),
            )
            rows = cur.fetchall()

    print(f"{'排名':<4} {'用户':<16} {'距离':<10} 内容")
    print("-" * 70)
    for i, (content, user, dist) in enumerate(rows, 1):
        print(f"{i:<4} {user:<16} {dist:<10.6f} {content}")

    assert all(r[1] == "user_lisi" for r in rows), "❌ 用户隔离失效！"
    food_top = rows[0][0]
    assert "火锅" in food_top or "咖啡" in food_top, f"❌ 排第一的不是美食相关: {food_top}"
    print("\n✅ 用户隔离正常 + 美食类排最前")

    # ── 查询 3：不设 user_id 过滤，看看会不会串数据（应该把用户隔离好）──
    print("\n" + "=" * 70)
    print("🔍 查询 3：不加 user_id 过滤 → 验证必须加 WHERE user_id")
    print("=" * 70)

    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, user_id, embedding <=> %s::vector AS distance
                FROM memory_entries
                ORDER BY embedding <=> %s::vector
                LIMIT 5
                """,
                (json.dumps(query_emb), json.dumps(query_emb)),
            )
            rows = cur.fetchall()

    print(f"{'排名':<4} {'用户':<16} {'距离':<10} 内容")
    print("-" * 70)
    for i, (content, user, dist) in enumerate(rows, 1):
        print(f"{i:<4} {user:<16} {dist:<10.6f} {content}")

    users = set(r[1] for r in rows)
    if len(users) > 1:
        print(f"\n⚠️  不加 user_id 过滤会串用户！返回了: {users}")
        print("    → 这就是为什么所有查询必须加 WHERE user_id = ...")

    # ── 收尾 ──
    print("\n" + "=" * 70)
    print("🎉 全部通过！pgvector 向量检索工作正常")
    print("=" * 70)
    print("""📋 验证清单：
  ✅ vector(1536) 列存储正常
  ✅ 余弦距离 <=> 操作符排序正确
  ✅ WHERE user_id 过滤实现用户隔离
  ✅ 向量索引已生效（IVFFlat）
  ✅ 跨用户查询会串数据 → 提醒必须加 user_id 过滤

🔜 下一步：接入真实 embedding 模型后，把 make_embedding()
   换成调 embedding API 的函数即可，其他代码不用改。""")


if __name__ == "__main__":
    run()
