# API 层

FastAPI 对外暴露的 HTTP 接口层，内部调用 `app.graph.builder.graph`。

## 在线文档

启动后自动生成：

| 地址 | 说明 |
|---|---|
| `GET /docs` | Swagger UI（交互测试） |
| `GET /redoc` | ReDoc（只读文档） |
| `GET /openapi.json` | OpenAPI 3.1 Schema |

```bash
python run.py api
# 浏览器打开 http://localhost:8000/docs
```

全新数据库首次启动 API 时需要配置 `ADMIN_PASSWORD`，用于自动创建初始管理员。

## 接口列表

### 1. 健康检查

```
GET /health
```

**描述**：返回服务运行状态和当前模型名称，适合作为 K8s liveness probe。

**请求参数**：无

**响应 200**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | `"ok"` 表示正常 |
| `model` | string | 当前配置的模型名，如 `"deepseek-chat"` |

**示例**：

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "model": "deepseek-chat"}
```

---

### 2. 用户登录

```
POST /auth/login
```

**描述**：使用用户名和密码登录，返回后续接口使用的 Bearer Token。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `username` | string | ✅ | 用户名 |
| `password` | string | ✅ | 密码 |

**示例**：

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "你的管理员密码"}'
```

**响应 200**：

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "...",
    "username": "admin",
    "display_name": "Bootstrap Admin",
    "role": "admin",
    "is_active": true,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

---

### 3. Agent 对话

```
POST /chat
```

**描述**：向 Agent 发送一条消息，返回生成的回复。Agent 会根据问题内容自动决定是否调用工具（天气、台风等）。接口需要 `Authorization: Bearer <token>` 鉴权，聊天上下文和永久历史都会绑定到当前用户。

#### 请求体

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `message` | string | ✅ | — | 用户消息，长度 1-4096 |
| `thread_id` | string | ❌ | 自动生成 | 会话 ID，相同 ID 共享上下文 |
| `system` | string | ❌ | 使用默认 | 自定义系统提示（覆盖默认 SYSTEM_PROMPT） |

**示例**：

```json
{
  "message": "查下深圳今天天气"
}
```

多轮会话：

```bash
# 第一轮
curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer 你的 access_token" \
  -H "Content-Type: application/json" \
  -d '{"message": "我叫小明"}'

# 第二轮（带上一轮的 thread_id）
curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer 你的 access_token" \
  -H "Content-Type: application/json" \
  -d '{"message": "我刚才说我叫什么？", "thread_id": "上一轮返回的 thread_id"}'
```

#### 响应

| 字段 | 类型 | 说明 |
|---|---|---|
| `reply` | string | Agent 最终回复文本 |
| `thread_id` | string | 本次会话 ID（用于后续多轮对话） |
| `tool_calls` | array | 本次调用的工具列表（可能为空） |
| `history_saved` | boolean | 聊天业务历史是否已经成功保存；待确认时为 `false` |
| `history_status` | string | `saved`、`pending` 或 `failed` |

**tool_calls 元素**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 工具名，如 `get_weather` |
| `args` | object | 传给工具的参数 |

**工具被调用时的示例**：

```json
{
  "reply": "深圳今天多云，气温 26-32°C，降水概率较低。",
  "thread_id": "7a5d613e193a...",
  "history_saved": true,
  "history_status": "saved",
  "tool_calls": [
    {"name": "get_weather", "args": {"city": "深圳"}}
  ]
}
```

**未调用工具时的示例**：

```json
{
  "reply": "你好！有什么可以帮你的吗？",
  "thread_id": "99e3c1d4252...",
  "history_saved": true,
  "history_status": "saved",
  "tool_calls": []
}
```

#### 错误响应

| 状态码 | 场景 |
|---|---|
| `422` | 请求体校验失败（message 为空、超长等） |
| `401` | 缺少、无效或过期的 Bearer Token |
| `403` | 用户已禁用 |
| `500` | LLM / 工具调用异常 |

---

### 4. 聊天历史

```
GET /chat/sessions
GET /chat/sessions/{thread_id}/messages
```

**描述**：查询当前用户的永久聊天历史。`/chat/sessions` 返回会话列表；`/chat/sessions/{thread_id}/messages` 返回某个会话下的用户消息、助手回复和工具调用信息。两个接口都需要 `Authorization: Bearer <token>`。

**示例**：

```bash
curl http://localhost:8000/chat/sessions \
  -H "Authorization: Bearer 你的 access_token"

curl http://localhost:8000/chat/sessions/上一轮返回的_thread_id/messages \
  -H "Authorization: Bearer 你的 access_token"
```

---

## 会话机制

基于 LangGraph 的 Checkpointer + `thread_id` 实现：

```
thread_id 作用域：整个请求-响应周期
             ↓
第一次请求（不传 thread_id）→ 生成新 UUID → 返回给客户端
             ↓
第二次请求（传同一个 thread_id）→ Checkpointer 恢复历史 messages → Agent 看到完整上下文
```

API 会把真实 checkpoint id 命名为 `user:{user_id}:thread:{thread_id}`。切换 `thread_id` 即切换当前用户的会话；不同用户即使传入相同 `thread_id`，也不会共享上下文。

永久聊天历史单独写入业务表：

| 表 | 用途 |
|---|---|
| `chat_sessions` | 当前用户的会话元信息，按 `user_id + thread_id` 唯一 |
| `chat_messages` | 用户消息、助手回复、工具调用，按会话分页查询 |

### 会话存储后端

由 `app/core/checkpointer.py` 工厂函数根据 `.env` 自动选择：

| 配置 | 后端 | 适用场景 |
|---|---|---|
| `CHECKPOINTER_TYPE=memory` | MemorySaver | 开发 / 单进程测试，重启即丢 |
| `CHECKPOINTER_TYPE=postgres` | AsyncPostgresSaver | **生产级**，持久化到 PostgreSQL |

生产切换步骤：

```bash
pip install langgraph-checkpoint-postgres psycopg[binary] psycopg_pool

# .env
CHECKPOINTER_TYPE=postgres
POSTGRES_URL=postgresql://user:pass@host:5432/myagent
```

AsyncPostgresSaver 首次启动时自动建表（`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`、`checkpoint_migrations`）。

如果会话 checkpoint 来自不兼容的旧状态版本，普通接口返回 HTTP 409，流式接口返回
`workflow_reset_required`；旧 checkpoint 和对应业务聊天历史会被清除，用户重新发送完整需求
即可。存在待确认的联网请求时返回 `pending_confirmation`，必须先调用 `/chat/confirm`。
普通与流式冲突都使用 `type`、`code`、`message`、`details` 字段；联网确认信息位于
`details.confirmation`。

---

## 当前已注册工具

| 工具名 | 触发场景 | 数据源 |
|---|---|---|
| `get_weather` | 用户问某城市天气、温度、降雨 | Open-Meteo（免费 API） |
| `get_typhoon` | 用户问台风、热带风暴、气旋路径 | 中央气象台 typhoon.nmc.cn |

新增工具：见 [app/tools/registry.py](../tools/registry.py) 注释。

---

## 技术实现

```
HTTP Request
    │
    ▼
FastAPI Router (routers/)
    │  Pydantic 校验
    ▼
handlers/ (chat / users / auth / system)
    │ 校验用户 + 组装 messages + config
    ▼
graph.builder.graph (LangGraph CompiledStateGraph)
    │  checkpointer 恢复历史
    │  chatbot node → LLM → ToolNode → chatbot node ...
    ▼
chat_history_service
    │  写入 chat_sessions / chat_messages
    ▼
HTTP Response
```

- **异步优先**：所有 handler 都是 `async def`，图用 `ainvoke`
- **连接复用**：工具层 HTTP 请求走 `app/utils/http.py` 的上下文管理器（复用 httpx.Client keep-alive）
- **LLM 单例**：`app/core/llm.py` 用 `lru_cache`，避免每次请求重建连接池
