FROM python:3.11-slim

LABEL maintainer="ESFNPD"
LABEL description="Exercise System for Network Planning Designers"

WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PORT=3030

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用文件
COPY app.py .
COPY exam.html .
COPY essay.html .
COPY kb.html .
COPY questions/ ./questions/
COPY scripts/ ./scripts/

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 3030

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3030/ || exit 1

# 启动命令
CMD ["python", "app.py"]
