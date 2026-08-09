# My-Agent

基于 **LangGraph + FastAPI + Streamlit** 的多工具 Agent。

## 特性

- 🔧 **工具可插拔**：新增工具只需在 `app/tools/` 下创建文件 + `registry.py` 注册
- 🤖 **LangGraph 工作流**：单 Agent → 多 Agent Supervisor 平滑演进
- 💾 **会话持久化**：MemorySaver（开发）/ PostgresSaver（生产）可切换
- 🌐 **FastAPI 接口**：提供 `/chat` 和 `/health`
- 🖥️ **Streamlit UI**：提供本地可视化聊天界面
- 🔑 **环境变量管理**：.env 集中配置，支持 Pydantic 校验

## 目录结构

```
my-agent/
├── run.py                     # 统一入口（CLI / API）
├── streamlit_app.py           # Streamlit 聊天界面
├── requirements.txt           # 依赖（带版本下限）
├── .env                       # 环境变量（已 .gitignore）
│
└── app/
    ├── core/                  # 基础设施（不依赖上层）
    │   ├── config.py          # get_settings() 集中校验 .env
    │   ├── llm.py             # ChatOpenAI 单例
    │   └── checkpointer.py    # 工厂：MemorySaver / PostgresSaver
    │
    ├── services/              # 业务服务层，供 CLI / API / UI 复用
    │   └── chat_service.py    # chat() / health()
    │
    ├── tools/                 # 所有工具
    │   ├── registry.py        # 按领域组合 all_tools / tool_groups
    │   └── weather/
    │       ├── current.py     # get_weather（Open-Meteo）
    │       ├── typhoon.py     # get_typhoon（中央气象台）
    │       ├── codes.py       # Open-Meteo 天气码映射
    │       └── registry.py    # weather_tools
    │
    ├── graph/                 # LangGraph 层
    │   ├── state.py           # State TypedDict
    │   ├── prompts.py         # SYSTEM_PROMPT
    │   ├── nodes.py           # chatbot 节点 + Supervisor 扩展位
    │   ├── router.py          # 未来领域路由 / Supervisor 预留
    │   └── builder.py         # build_graph() 组装工作流
    │
    ├── api/                   # FastAPI 层
    │   ├── main.py            # FastAPI app 工厂
    │   ├── schemas.py         # 请求/响应模型
    │   └── routes.py          # handle_chat / handle_health
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
| `CHECKPOINTER_TYPE` | `memory` | `memory` 或 `postgres` |
| `POSTGRES_URL` | — | PostgreSQL 连接串 |
| `API_HOST` | `0.0.0.0` | API 监听地址 |
| `API_PORT` | `8000` | API 监听端口 |

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

### 4. HTTP 调用

```bash
# 健康检查
curl http://localhost:8000/health
# → {"status": "ok", "model": "deepseek-chat"}

# 对话
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "查下深圳今天天气"}'
# → {"reply": "...", "thread_id": "xxx", "tool_calls": [...]}

# 带 thread_id 保持会话
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "那明天呢？", "thread_id": "上一次返回的 thread_id"}'
```

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

## 架构演进

```
阶段 1（当前）：单 Agent + 多工具
  START → chatbot → (tools) → chatbot → END

阶段 2：Supervisor 多 Agent
  START → supervisor ┬─→ weather_agent → END
                     ├─→ typhoon_agent  → END
                     └─→ search_agent  → END

阶段 3：多 Agent + 共享状态 + 记忆
  各子 Agent 独立 graph，通过 Supervisor 协调，共用 checkpoint
```

演进时只改 `app/graph/builder.py` 和 `app/graph/nodes.py`，**外部接口（CLI / API）零改动**。

## 生产级部署

### PostgreSQL 会话持久化

```bash
pip install langgraph-checkpoint-postgres asyncpg

# .env
CHECKPOINTER_TYPE=postgres
POSTGRES_URL=postgresql://user:pass@host:5432/myagent
```

首次启动时 `PostgresSaver` 会自动建表。

### Docker（示例）

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "run.py", "api"]
```

## 技术栈

| 层 | 技术 |
|---|---|
| LLM | DeepSeek / OpenAI 兼容协议 |
| Agent 编排 | LangGraph 0.2+ |
| 工具定义 | LangChain Tool 协议 |
| API | FastAPI + Uvicorn |
| UI | Streamlit |
| 会话持久化 | LangGraph Checkpoint（Memory / Postgres） |
| 配置 | python-dotenv + pydantic |
| HTTP | httpx |

## 项目状态

- [x] 模块化包结构
- [x] 工具注册机制
- [x] LangGraph 单 Agent + ToolNode
- [x] FastAPI 层（/chat, /health）
- [x] Streamlit 聊天界面
- [x] Memory / Postgres Checkpointer 工厂
- [x] Service 层复用 CLI / API / UI
- [x] 工具按领域分组
- [x] Supervisor 扩展位预留
- [ ] Supervisor 多 Agent 实现（工具 > 15 或业务域差异大时）
- [ ] Docker / docker-compose
- [ ] 单元测试 + 集成测试
