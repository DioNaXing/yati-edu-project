# 🏗️ 亚体教务系统 v1.0

> 体培机构智能教务管理系统 — 替代小麦助教，年省 ¥10,000+

[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-brightgreen)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 🎯 一句话

用 AI + 微信小程序，让体培机构教务管理成本降低 85%，家长体验提升 10 倍。

## 🧩 核心功能

| 模块 | 功能 | 状态 |
|------|------|------|
| 🧑‍🎓 学员管理 | 档案、课时、续费预警 | ✅ |
| 👨‍🏫 教练管理 | 排课、绩效、负载检测 | ✅ |
| 📅 智能排课 | AI 驱动排课优化 | ✅ |
| 💰 财务看板 | 收入预测、盈亏分析 | ✅ |
| 📊 AI 教务管家 | 日报、异常检测、17 Skills | ✅ |
| 🏪 AI 店长 | 周报、趋势分析、9 Skills | ✅ |
| 📱 微信小程序 | 家长约课、消课、充值 | 🔄 |
| 🔔 企业微信推送 | 课时提醒、续费通知 | ✅ |

## 🚀 30 秒启动

```bash
# 1. 装依赖
pip install -r backend/requirements.txt

# 2. 初始化数据库
python backend/yati_edu_core.py --init

# 3. 启动！
uvicorn backend.yati_edu_core:app --host 0.0.0.0 --port 8000 --reload
```

浏览器打开 `http://localhost:8000/docs` → 自动生成 Swagger API 文档。

## 🐳 Docker 部署

```bash
# 一键启动（后端 + Nginx + SSL）
docker compose up -d

# 含 One API AI 网关
docker compose --profile full up -d
```

## ☁️ 腾讯云部署

见 [docs/腾讯云部署指南.md](docs/腾讯云部署指南.md)

## 📂 项目结构

```
yati-edu-project/
├── backend/           # FastAPI 后端
│   ├── yati_edu_core.py       # 核心服务（1,762 行）
│   ├── ai_skill_executor.py  # AI Skills 引擎
│   ├── wecom_pusher.py       # 企业微信推送
│   ├── requirements.txt
│   └── .env.example
├── frontend/          # 前端（微信小程序 / Web）
├── deploy/            # 部署配置
│   ├── Dockerfile
│   ├── nginx.conf
│   └── ssl/           # SSL 证书目录
├── docs/              # 文档
├── docker-compose.yml
└── README.md
```

## 💰 商业模式

- **SaaS 订阅**：¥299-599/月/机构（竞品小麦助教 ¥800-1000/月）
- **私有部署**：¥9,800 一次性 + ¥2,000/年维护
- **加盟授权**：¥5,000/年/品牌使用费

目标：3 年 800 万营业额，覆盖 50+ 体培机构。

## 🔗 关联项目

- [体培AI系统建设总控台](docs/总控台.md)
- [小麦助教迁移方案](docs/小麦助教迁移方案.md)
- [AI教务管家能力矩阵](docs/AI教务管家.md)
- [AI店长能力矩阵](docs/AI店长.md)

## 📄 License

MIT — 你可以自由使用、修改、商用。
