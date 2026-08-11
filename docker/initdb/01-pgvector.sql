-- pgvector 扩展 + 长期记忆预留表
-- 仅在 postgres 容器首次启动时执行（/docker-entrypoint-initdb.d）

CREATE EXTENSION IF NOT EXISTS vector;

-- 长期记忆表（当前 app 代码还没接入，先占位）
CREATE TABLE IF NOT EXISTS memory_entries (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    content         text NOT NULL,
    embedding       vector(1536) NOT NULL,
    source_thread_id text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_entries_user_id_idx
    ON memory_entries (user_id);

CREATE INDEX IF NOT EXISTS memory_entries_embedding_cosine_idx
    ON memory_entries
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
