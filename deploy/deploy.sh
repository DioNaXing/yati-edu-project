#!/bin/bash
# 亚体教务系统 — 腾讯云一键部署脚本
# 用法: bash deploy.sh <服务器IP> <root密码>
# 部署指南: docs/腾讯云部署指南.md

set -e

SERVER_IP="${1:?请提供服务器 IP}"
SERVER_PASS="${2:?请提供 root 密码}"
PROJECT_DIR="/root/yati-edu-project"

echo "🚀 开始部署亚体教务系统到 $SERVER_IP"

# ---- Step 1: 安装依赖 ----
echo "📦 Step 1/5: 安装 Docker..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@$SERVER_IP "
  command -v docker &>/dev/null || curl -fsSL https://get.docker.com | bash
  systemctl enable docker --now
  echo 'Docker OK: ' \$(docker --version)
"

# ---- Step 2: 上传代码 ----
echo "📤 Step 2/5: 上传代码..."
sshpass -p "$SERVER_PASS" ssh root@$SERVER_IP "mkdir -p $PROJECT_DIR"
sshpass -p "$SERVER_PASS" rsync -avz --exclude '.git' --exclude 'data/' \
  ~/yati-edu-project/ root@$SERVER_IP:$PROJECT_DIR/

# ---- Step 3: 配置环境变量 ----
echo "⚙️  Step 3/5: 配置环境变量..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
sshpass -p "$SERVER_PASS" ssh root@$SERVER_IP "
  cd $PROJECT_DIR
  cp backend/.env.example backend/.env
  sed -i 's|change-me-please|'$SECRET_KEY'|' backend/.env
  sed -i 's|your-one-api-token|sk-placeholder|' backend/.env
  echo '环境变量已配置'
"

# ---- Step 4: 启动服务 ----
echo "🐳 Step 4/5: 启动 Docker 服务..."
sshpass -p "$SERVER_PASS" ssh root@$SERVER_IP "
  cd $PROJECT_DIR
  docker compose up -d --build
  sleep 3
  docker compose ps
"

# ---- Step 5: 验证 ----
echo "✅ Step 5/5: 验证服务..."
sshpass -p "$SERVER_PASS" ssh root@$SERVER_IP "
  curl -s http://localhost:8000/health
"

echo ""
echo "🎉 部署完成！"
echo "API 地址: http://$SERVER_IP:8000"
echo "API 文档: http://$SERVER_IP:8000/docs"
echo ""
echo "下一步: 配置域名 + SSL 证书（参考 docs/腾讯云部署指南.md）"
