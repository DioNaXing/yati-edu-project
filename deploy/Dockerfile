# 亚体教务系统 v1.0 — Docker 镜像
# 构建: docker build -t yati-edu:latest .
# 💰 变现点：Docker 镜像可推送至阿里云/腾讯云容器镜像服务
# 📦 打包节点：一个镜像 = 完整教务系统

FROM python:3.11-slim

LABEL maintainer="亚体教务系统"
LABEL description="体培机构智能教务管理系统"

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY backend/requirements.txt .

# 安装 Python 依赖（国内用清华源加速）
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制应用代码
COPY backend/ ./backend/
COPY deploy/ ./deploy/

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 启动服务
CMD ["uvicorn", "backend.yati_edu_core:app", "--host", "0.0.0.0", "--port", "8000"]
