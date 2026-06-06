# 运行镜像使用 Python 3.12-slim，和 pyproject 的运行时版本保持一致。
FROM python:3.12-slim

# 所有路径都以 /app 为根，便于 FastAPI、CLI 和 package import 使用同一相对位置。
WORKDIR /app

# 容器默认面向本地 Ollama：host.docker.internal 让容器能访问宿主机 11434。
# PYTHONPATH=/app 兼容根目录 shim 和源码树直接运行。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    OLLAMA_HOST=http://host.docker.internal:11434

# 复制完整项目树：安装包、集成层、前端产物和兼容 shim 都在构建上下文内。
COPY . /app

# 只安装运行依赖；开发/测试依赖由本机或 CI 的 dev extra 管理。
RUN pip install --no-cache-dir .

# 预留 HTTP 服务端口。OpenAI 兼容平台默认端口是 8765，可通过运行参数映射。
EXPOSE 8000

# 默认执行包入口，适合快速 smoke；生产 HTTP 平台可改用 integrations.openai_compat.server。
CMD ["python", "-m", "mase"]
