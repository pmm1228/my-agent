# My-Agent

基于 **LangGraph + FastAPI + Streamlit** 的 Coordinator + 领域 Agent 应用。

## 特性

- 🔧 **工具可插拔**：新增工具只需在 `app/tools/` 下创建文件 + `registry.py` 注册
- 🔎 **按需联网**：Tavily 搜索 + 公开网页正文读取，仅在实时信息或外部查证确有必要时调用
- 🧳 **旅游规划工作流**：收集目的地、日期和人数，一次确认后搜索景点与酒店，并生成天气、每日行程、预算区间和备选项
- 🤖 **Coordinator 编排**：Coordinator 判断普通处理或创建 `AgentCall`，Executor 只调用注册的领域 Agent，结果回到 Coordinator 统一发布
- 🧯 **Agent 失败降级**：领域 Agent 普通异常转换为失败 `AgentResult`；最终综合模型不可用时使用结构化结果降级回复
- 💾 **会话持久化**：MemorySaver（开发）/ AsyncPostgresSaver（生产）可切换
- 🧾 **永久聊天历史**：业务表保存会话和消息，便于分页展示 / 审计
- 🌐 **FastAPI 接口**：提供 `/chat` 和 `/health`
- 🔐 **用户权限管理**：用户名密码登录 + Bearer Token 鉴权
- 🖥️ **Streamlit UI**：提供本地可视化聊天界面
- 🔑 **环境变量管理**：.env 集中配置，支持 Pydantic 校验

## 目录结构

```
my-agent/
├── run.py                     # 统一入口（CLI / API）
├── streamlit_app.py           # Streamlit 聊天界面
├── docker-compose.yml         # PostgreSQL + pgvector
├── requirements.txt           # 依赖（带版本下限）
├── .env                       # 环境变量（已 .gitignore）
│
├── scripts/                   # 运维 / 验证脚本
│   ├── init_database.py       # 幂等初始化与显式会话重置
│   └── test_memory_pgvector.py # pgvector 存储和隔离验证
│
└── app/
    ├── core/                  # 基础设施（不依赖上层）
    │   ├── config.py          # get_settings() 集中校验 .env
    │   ├── database.py        # app_users 初始化 + 连接池
    │   ├── security.py        # 密码哈希 / Token / API Key 兼容
    │   ├── llm.py             # ChatOpenAI 单例
    │   └── checkpointer.py    # 工厂：MemorySaver / AsyncPostgresSaver
    │
    ├── services/              # 业务服务层，供 CLI / API / UI 复用
    │   ├── chat_service.py    # chat() / health()
    │   ├── chat_history_service.py # 聊天会话 / 消息历史
    │   └── user_service.py    # 用户新增 / 删除 / 权限查询
    │
    ├── tools/                 # 所有工具
    │   ├── registry.py        # 按领域组合 all_tools / tool_groups
    │   ├── search/            # Tavily 搜索与安全网页正文读取
    │   └── weather/
    │       ├── current.py     # get_weather（Open-Meteo）
    │       ├── forecast.py    # 旅行日期天气预报
    │       ├── typhoon.py     # get_typhoon（中央气象台）
    │       ├── codes.py       # Open-Meteo 天气码映射
    │       └── registry.py    # weather_tools
    │
    ├── agents/                # Coordinator、Executor 与领域 Agent
    │   ├── contracts.py       # AgentCall / AgentResult / RootState / AgentSpec
    │   ├── executor.py        # 校验 AgentCall、失败转换、结果归一化
    │   ├── registry.py        # 领域 Agent 注册表
    │   ├── coordinator/       # 路由、通用处理、结果综合和发布
    │   └── travel/            # 自包含旅游 Agent：状态、节点、抽取、规划和渲染
    │
    ├── graph/                 # 根编排图与 Coordinator 的普通工具链
    │   ├── state.py           # RootState 兼容导出
    │   ├── prompts.py         # SYSTEM_PROMPT
    │   ├── nodes.py           # Coordinator 的 LLM + 普通工具绑定
    │   ├── web_confirmation.py # 普通工具执行与 Tavily 调用确认
    │   └── builder.py         # 组装 Coordinator、Executor、工具和子图循环
    │
    ├── api/                   # FastAPI 层
    │   ├── main.py            # FastAPI app 工厂
    │   ├── schemas/           # auth / chat / users / system 请求响应模型
    │   ├── mappers.py         # Service 对象到 API 响应的统一转换
    │   ├── dependencies/      # Bearer Token / API Key 鉴权依赖
    │   ├── routers/           # chat / users / auth / system 路由注册
    │   └── handlers/          # 按领域处理请求与转换 HTTP 异常
    │
    └── utils/
        ├── http.py             # httpx.Client 单例
        └── logging.py          # get_logger()
```

## 快速开始

### 1. 安装

```bash
cd my-agent
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制 .env（已包含默认值）
cat .env
```

必需：`DEEPSEEK_API_KEY`

可选：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1` | API 兼容端点 |
| `TAVILY_API_KEY` | — | Tavily 搜索密钥；启用通用联网搜索时必填 |
| `WEB_SEARCH_MAX_RESULTS` | `5` | 单次联网搜索允许返回的最大结果数（1–10） |
| `WEB_PAGE_MAX_BYTES` | `1000000` | 单个网页最多处理的字节数 |
| `WEB_ALLOWED_PROXY_CIDRS` | 空 | 允许作为公网传输代理的保留地址段；Docker Desktop compose 默认配置 `198.18.0.0/15` |
| `CHECKPOINTER_TYPE` | `memory` | `memory`（进程内）或 `postgres`（持久化到 PostgreSQL） |
| `POSTGRES_URL` | — | PostgreSQL 连接串，启用 `postgres` checkpointer 时必填 |
| `DATABASE_URL` | `POSTGRES_URL` | 用户权限表连接串；不配置时复用 `POSTGRES_URL` |
| `CONVERSATION_LOCK_TIMEOUT_SECONDS` | `30` | 同一进程等待相同会话锁的最大秒数 |
| `ADMIN_USERNAME` | `admin` | 启动时自动创建/更新的管理员用户名 |
| `ADMIN_PASSWORD` | — | 管理员登录密码；全新数据库首次启动必填 |
| `JWT_SECRET` | `ADMIN_API_KEY` 或本地默认值 | Bearer Token 签名密钥，生产环境请显式配置 |
| `JWT_EXPIRE_MINUTES` | `1440` | 登录 Token 有效分钟数 |
| `ADMIN_API_KEY` | — | 兼容旧 API Key 调用；用户名密码登录不依赖它 |
| `API_HOST` | `0.0.0.0` | API 监听地址 |
| `API_PORT` | `8000` | API 监听端口 |

> 如果启用了 `CHECKPOINTER_TYPE=postgres`，先启动数据库：
> ```bash
> docker compose up -d
> ```
> 详见 [数据库](#数据库) 章节。
>
> 全新数据库首次启动 API 时必须配置 `ADMIN_PASSWORD`，应用会自动创建可登录管理员。

### 3. 四种跑法

```bash
# CLI 单次对话
python run.py "现在有什么活跃台风？"

# CLI 交互模式（多轮会话，自动保持 thread_id）
python run.py

# FastAPI 服务
python run.py api
# 或
python run.py api --port 9001

# Streamlit 聊天界面
streamlit run streamlit_app.py
```

> **并发部署限制**：当前相同 `thread_id` 的串行控制使用进程内锁，API 必须以单 worker 运行。仓库内 Dockerfile 已固定为 `--workers 1`。在接入请求幂等和分布式会话队列前，不要增加 Gunicorn/Uvicorn worker 数，也不要横向扩容 API 实例。

### 4. HTTP 调用

```bash
# 健康检查
curl http://localhost:8000/health
# → {"status": "ok", "model": "deepseek-chat"}

# 登录，拿到 access_token
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "你的管理员密码"}'
# → {"access_token": "...", "token_type": "bearer", "expires_in": 86400, "user": {...}}

# 对话
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer 你的 access_token" \
  -H "Content-Type: application/json" \
  -d '{"message": "查下深圳今天天气"}'
# → {"reply": "...", "thread_id": "xxx", "tool_calls": [...], "history_saved": true, "history_status": "saved"}

# 带 thread_id 保持会话
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer 你的 access_token" \
  -H "Content-Type: application/json" \
  -d '{"message": "那明天呢？", "thread_id": "上一次返回的 thread_id"}'

# 当 search_web 将消耗 Tavily 搜索额度、响应 status=requires_confirmation 时确认或拒绝
curl -X POST http://localhost:8000/chat/confirm \
  -H "Authorization: Bearer 你的 access_token" \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "待确认的 thread_id", "approved": true}'

# 查看当前用户聊天会话
curl http://localhost:8000/chat/sessions \
  -H "Authorization: Bearer 你的 access_token"

# 查看某个会话的聊天消息
curl http://localhost:8000/chat/sessions/会话thread_id/messages \
  -H "Authorization: Bearer 你的 access_token"

# 新增用户（需要管理员权限）
curl -X POST http://localhost:8000/users \
  -H "Authorization: Bearer 管理员 access_token" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "alice12345", "display_name": "Alice"}'

# 删除用户（需要管理员权限）
curl -X DELETE http://localhost:8000/users/用户ID \
  -H "Authorization: Bearer 管理员 access_token"
```

## 旅游规划工作流

明确提出“旅行规划”“几日游”“旅游攻略”等请求时，Coordinator 会将本轮交给独立
Travel Agent 子图：

1. 收集并校验目的地、出发日期、返程日期和人数。
2. 生成景点与酒店研究计划，并通过现有 `/chat/confirm` 一次性确认 Tavily 调用。
3. 从搜索摘要中抽取有直接证据的具体景点和酒店；候选不足时读取少量必要页面，攻略标题不会直接成为行程地点。
4. 查询 Open-Meteo 天气；天气或部分搜索失败时继续生成降级方案。
5. 按搜索资料中可识别的行政区或商圈组织每日活动，根据实际活动、住宿和用户预算计算费用区间。
6. 输出每日备选项、来源与未核实事项。

候选名称、类型和目的地必须在同一段直接证据中建立关联；区域、地址、开放时间和价格也必须
与候选名称位于同一句来源原文，否则不会用于排程或预算。位置未核实的候选不会被假定为相邻。
完成规划后，可在已有核实候选中按天增加、删除或替换活动，也可修改预算、人数、房间数、
节奏和酒店档次；本地修改不会重复消耗 Tavily 配额，修改失败时原方案保持不变。
已有旅行上下文中单独发送“重新规划”会清空旧旅行字段并开始一份新方案。

Travel Agent 使用独立的子图 checkpoint namespace。旅行收集过程中插入普通问题时，会临时
handoff 回 Coordinator 的通用处理路径，完成后仍可继续原旅行；Travel Agent 内部产生的
Tavily interrupt 由根图透明传递，现有 `/chat/confirm` 接口无需区分具体 Agent。领域 Agent
完成后先返回结构化 `AgentResult`，Coordinator 再综合其中的方案、警告和错误并生成用户可见回复。

酒店价格、门票、餐饮和交通均为参考区间，不代表实时库存或最终成交价。预算输出会分别标记
“费用完整性”和“超预算风险”，即使部分价格缺失，也会根据已有依据识别明显超支并尝试调整；
超出可靠预报范围的日期不会生成虚假逐日天气。

## 如何添加新工具

### 方式 A：最小改动

简单工具可以直接在 `app/tools/` 下新建 `my_tool.py`：

```python
from langchain_core.tools import tool

@tool
def my_tool(query: str) -> str:
    """工具描述——模型根据这个决定何时调用"""
    return f"结果: {query}"
```

然后在 `app/tools/registry.py` 注册：

```python
from app.tools.my_tool import my_tool

my_tools = [my_tool]
all_tools = [*weather_tools, *my_tools]
```

改一下 `app/graph/prompts.py` 里的 SYSTEM_PROMPT，让模型知道有这个工具。完成。

### 方式 B：带外部数据源的工具

参考 `app/tools/weather/typhoon.py` 的结构——内部函数调数据源，`@tool` 函数做参数校验 + 结果格式化。数据源 HTTP 请求统一走 `app/utils/http.py` 的 `http_client()` 上下文管理器。

## Agent 架构

当前根图的实际执行链：

```text
START
  ↓
coordinator
  ├─ 普通回答 ───────────────────────────────────────→ END
  ├─ 普通 Tool Call → tools ─────────────────────────→ coordinator
  └─ AgentCall → agent_executor → domain_agent
                                   ↓
                         collect_agent_result
                                   ↓
                              coordinator
                        （综合并发布最终回复）
                                   ↓
                                  END
```

根图包含以下节点：

| 节点 | 职责 |
|---|---|
| `coordinator` | 判断本轮由通用处理路径直接处理还是委派领域 Agent；接收结果后生成唯一的最终回复 |
| `tools` | 执行天气、台风、搜索、网页读取等普通 LangChain Tool；Tavily 搜索前触发确认 |
| `agent_executor` | 消费并校验 `AgentCall`，根据注册表把调用派发给对应领域子图 |
| `<name>_agent` | 执行领域工作流；当前注册到根图的是 `travel_agent` |
| `collect_agent_result` | 规范化领域 Agent 输出、附加 `call_id`、累积 `agent_results`，再把控制权交还 Coordinator |

### 两类调用通道

系统明确区分普通工具和领域 Agent：

- 普通工具使用模型原生 Tool Call 和 LangGraph `ToolNode`，适合短时、无独立工作流的天气或搜索能力。
- 领域 Agent 使用项目内部的 `AgentCall → Agent Executor → AgentResult` 协议，适合拥有私有状态、多个步骤和 interrupt 的工作流。

因此，领域 Agent 在架构语义上作为 Coordinator 可调度的工作流，但不会伪装成普通 `ToolNode`。这样 Travel
Agent 可以继续持有独立 checkpoint namespace，并让联网确认中断穿过 Executor 后正常恢复。

### 调度和结果综合

注册的领域路由器返回 `RouteDecision`。协调器先区分本轮明确意图 `explicit` 和活跃工作流续办
`continuation`：明确意图优先，其次比较得分和 Agent 优先级；没有领域 Agent 达到阈值或出现
无法消解的冲突时，由 Coordinator 的通用处理路径直接处理。

领域 Agent 统一返回：

```python
AgentResult = {
    "agent": "travel",
    "status": "active | completed | cancelled | failed",
    "summary": "供 Coordinator 理解的结果摘要",
    "data": {},
    "warnings": [],
    "errors": [],
    "call_id": "对应 AgentCall 的 ID",
}
```

Coordinator 会将当前收集到的 `summary`、`data`、`warnings` 和 `errors` 一起交给综合模型，生成一条
用户可见回复。综合失败时，系统使用结构化摘要、警告和错误生成降级回复。领域子图产生的内部
AI 消息会在最终发布前从本轮根消息中移除，避免把领域 Agent 中间输出重复展示给用户。

领域 Agent 的普通异常会被 Executor 转换为 `status=failed` 的 `AgentResult`，再由 Coordinator 解释；
LangGraph 的 interrupt 不会被当成失败捕获。会话存在待确认联网请求时，普通 `/chat` 和
`/chat/stream` 请求会返回 `pending_confirmation` 冲突，必须先调用 `/chat/confirm` 确认或拒绝。

> 当前根状态版本为 `5`。旧 checkpoint 不做迁移；首次访问时会清除对应 checkpoint，并返回
> `workflow_reset_required`。通过 HTTP API 访问时还会同步清除当前用户对应的业务会话历史；
> 直接调用 Service 且未提供 `on_state_reset` 回调时只清除 checkpoint。

### 添加新的领域 Agent

1. 在 `app/agents/<name>/` 创建独立 StateGraph；领域字段放在自己的 State 中，不加入 `RootState`。
2. 子图退出节点必须投影统一的 `AgentResult`，并设置必要的 `workflow_agent`、`workflow_status`。
3. 实现 `router(state) -> RouteDecision`，明确区分新请求和活跃工作流续办。
4. 在 `app/agents/registry.py` 注册 `AgentSpec`。根图会自动添加 `<name>_agent` 和 Executor 路由。
5. 需要跨轮私有状态时以 `checkpointer=True` 编译子图；需要用户确认时使用 LangGraph `interrupt`。
6. 至少测试成功、缺少输入、普通异常、interrupt 恢复、跨轮续办和 Coordinator 最终综合。

普通问答和通用工具不需要创建领域 Agent，由 Coordinator 的通用处理路径直接处理；registry 只注册真正拥有独立工作流的领域 Agent。

### 当前边界

- 当前唯一注册到根图的领域 Agent 是 `travel_agent`。
- 领域选择目前由可测试的 `RouteDecision` 路由器完成，不是由 LLM 自由生成领域 Agent Tool Call。
- Executor 已支持最多 3 轮领域 handoff 和多个 `AgentResult` 的累积综合；当前 Travel 流程通常每轮只调用一个领域 Agent。
- 单轮主动拆解任务并并行或串行组合多个领域 Agent 尚未实现。

## 数据库

项目使用 **PostgreSQL 16 + pgvector 0.8**。默认可共用同一个实例，也支持通过
`DATABASE_URL` 和 `POSTGRES_URL` 分离业务历史与 LangGraph checkpoint；删除用户和重置会话时
会分别清理两个存储。

### 启动方式

通过 Docker Compose 启动（本机不需要单独安装 PostgreSQL）：

```bash
cd my-agent

# 首次启动：拉取 pgvector 镜像并启动
docker compose up -d

# 常用管理命令
docker compose ps                  # 查看状态
docker compose logs -f postgres    # 看日志
docker compose down                # 停止（保留数据）
docker compose down -v             # 停止并清除所有数据（慎用）

# 进 psql 手动操作
docker compose exec postgres psql -U myagent -d myagent
```

### 环境变量

`.env` 中配置：

```ini
CHECKPOINTER_TYPE=postgres
POSTGRES_URL=postgresql://myagent:myagent@localhost:5432/myagent
```

| 变量 | 默认 | 说明 |
|---|---|---|
| `CHECKPOINTER_TYPE` | `memory` | `memory`（进程内，重启丢失）或 `postgres`（持久化） |
| `POSTGRES_URL` | — | PostgreSQL 连接串，仅 `CHECKPOINTER_TYPE=postgres` 时需要 |
| `CONVERSATION_LOCK_TIMEOUT_SECONDS` | `30` | 同一进程内等待相同 thread 的超时秒数；必须大于 0 |

> 想临时切回内存模式，改 `.env` 为 `CHECKPOINTER_TYPE=memory` 重启即可，表结构不受影响。

### 容器配置（docker-compose.yml）

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16    # pgvector 官方镜像，已集成 pgvector 扩展
    container_name: myagent-pg
    environment:
      POSTGRES_USER: myagent
      POSTGRES_PASSWORD: myagent
      POSTGRES_DB: myagent
    ports:
      - "5432:5432"
    volumes:
      - myagent-pg-data:/var/lib/postgresql/data

volumes:
  myagent-pg-data:                    # Docker 托管的持久化数据卷
```

### 当前表结构

数据库里会涉及两类表：LangGraph checkpoint 表由应用在首次使用 Postgres checkpointer 时自动迁移；长期记忆验证表由脚本初始化。

| 表 | 用途 | 创建方式 |
|---|---|---|
| `checkpoints` | LangGraph 会话状态快照（完整 messages 历史 + 节点版本） | `AsyncPostgresSaver.setup()` 自动迁移 |
| `checkpoint_blobs` | checkpoint 二进制数据 | 自动迁移 |
| `checkpoint_writes` | checkpoint 写入记录（工具调用等） | 自动迁移 |
| `checkpoint_migrations` | 迁移版本追踪 | 自动迁移 |
| `app_users` | 用户与权限管理（用户名、角色、状态、密码哈希、兼容 API Key 哈希） | API 启动时自动初始化 |
| `chat_sessions` | 业务聊天会话（按 `user_id + thread_id` 唯一） | API 启动时自动初始化 |
| `chat_messages` | 永久聊天消息（用户消息、助手回复、工具调用） | API 启动时自动初始化 |
| `memory_entries` | 长期记忆验证表（含 `vector(1536)` 列，pgvector 语义检索） | `scripts/test_memory_pgvector.py` 自动初始化 |

`checkpoints` 每次对话自动写入，负责 LangGraph 上下文恢复；API `/chat` 会把真实 checkpoint id 命名为 `user:{user_id}:thread:{thread_id}`，避免不同用户复用同一个 `thread_id` 时串上下文。

`chat_sessions` 和 `chat_messages` 是业务聊天历史表，负责永久保存和分页查询。`POST /chat` 成功后会写入当前用户的会话、用户消息、助手回复和工具调用信息；若历史补写失败，接口仍返回本次回复并标记 `history_saved=false`。

`memory_entries` 是长期记忆 / RAG 的验证表，暂未接入聊天流程。它包含 `user_id` + `content` + `embedding`（pgvector 向量列），支持余弦距离做语义检索，**所有查询必须加 `WHERE user_id = ...`** 避免串用户。

`app_users` 在 API 启动时创建。用户通过 `POST /auth/login` 使用用户名密码登录，后续接口使用 `Authorization: Bearer <token>`；数据库只保存密码哈希。兼容旧版 API Key 鉴权，新增用户或重置 Key 时，明文 Key 只会在响应中返回一次。删除用户会级联删除业务聊天历史，并清理该用户命名空间下的 LangGraph checkpoint。

业务表和 checkpoint 表可显式初始化；清空命令只删除聊天会话与 checkpoint，保留用户、
角色、鉴权信息和长期记忆：

```bash
# 幂等初始化/迁移
python scripts/init_database.py

# 明确确认后重置会话与 checkpoint
# 执行前请先停止所有会写入这些数据库的 API 实例
python scripts/init_database.py \
  --reset-conversations \
  --confirm-reset RESET-CONVERSATIONS
```

业务历史通过 `DATABASE_URL` 清理，checkpoint 通过 `POSTGRES_URL` 独立清理，因此支持分库部署。
重置默认仅允许本机数据库；任一目标为非本机时还必须显式传入 `--allow-remote`。应用启动只执行
幂等建表和迁移，不会自动清空数据。

### 验证脚本

`scripts/test_memory_pgvector.py` 会自动创建 `vector` 扩展、`memory_entries` 表和索引，并验证 pgvector 存储、相似度排序、用户隔离是否正常：

```bash
python scripts/test_memory_pgvector.py
```

## 技术栈

| 层 | 技术 |
|---|---|
| LLM | DeepSeek / OpenAI 兼容协议 |
| Agent 编排 | LangGraph 0.2+ |
| 工具定义 | LangChain Tool 协议 |
| 领域 Agent 协议 | 内部 `AgentCall` / `AgentResult` + Agent Executor |
| API | FastAPI + Uvicorn |
| UI | Streamlit |
| 会话持久化 | LangGraph Checkpoint（Memory / AsyncPostgresSaver + psycopg_pool） |
| 长期记忆 | PostgreSQL pgvector 0.8（向量 1536 维 + IVFFlat 索引） |
| 配置 | python-dotenv + pydantic |
| HTTP | httpx |
| 数据库容器 | pgvector/pgvector:pg16（Docker Compose） |

## 项目状态

- [x] 模块化包结构
- [x] 工具注册机制
- [x] LangGraph Coordinator + ToolNode + 领域 Agent
- [x] FastAPI 层（/chat, /health）
- [x] Streamlit 聊天界面
- [x] Memory / Postgres Checkpointer 工厂（AsyncPostgresSaver + psycopg_pool）
- [x] Service 层复用 CLI / API / UI
- [x] 工具按领域分组
- [x] Coordinator → 领域 Agent → Coordinator 编排循环
- [x] Agent Executor 调用校验、结果归一化和失败转换
- [x] Coordinator 结构化结果综合与降级输出
- [x] Travel Agent 私有 checkpoint 与 interrupt 恢复
- [x] Docker Compose + pgvector 数据库
- [x] memory_entries 表结构 + pgvector 验证脚本
- [x] 自动化测试（当前 116 项）
- [ ] 增加更多领域 Agent，并支持单轮组合调用
- [ ] 长期记忆提取 + embedding 模块
- [ ] 外部 LLM、Tavily、Open-Meteo 和 PostgreSQL 的在线集成测试
