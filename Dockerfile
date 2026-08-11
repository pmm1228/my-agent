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

# 生产启动：gunicorn 多 worker + uvicorn worker class
# 单机 2-4 worker 足够模拟，正式按 CPU 核数调
CMD ["gunicorn", "app.api.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
