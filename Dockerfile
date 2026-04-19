# 基于 Python 3.12-slim 镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 配置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    OLLAMA_HOST=http://host.docker.internal:11434

# 复制项目代码（需要完整项目树才能 pip install）
COPY . /app

# 安装基础运行依赖
RUN pip install --no-cache-dir .

# 暴露 FastAPI 或服务的潜在端口
EXPOSE 8000

# 默认启动命令（待用 FastAPI 包裹后修改）
CMD ["python", "-m", "mase"]
