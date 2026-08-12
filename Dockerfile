# ---------- 阶段 1: 装依赖 ----------
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- 阶段 2: 运行 ----------
FROM python:3.12-slim

WORKDIR /app

# 从 builder 拷贝 Python 依赖（已编译好的 wheel）
COPY --from=builder /install /usr/local

# 拷贝应用代码
COPY app/ ./app/
COPY run.py .

EXPOSE 8000

# 会话锁是进程内锁，必须保持单 worker。
# 需要多 worker/多实例时，应先接入带幂等保护的分布式会话队列。
CMD ["gunicorn", "app.api.main:app", \
     "--workers", "1", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
