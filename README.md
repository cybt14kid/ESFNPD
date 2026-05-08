# ESFNPD - Exercise System for Network Planning Designers

一款面向 **软考高级网络规划设计师** 的在线刷题系统，支持选择题和案例分析题，配有详细解析。

![Docker](https://img.shields.io/badge/Docker-ready-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## 功能特性

- **基础选择题**：446 道配解析
- **案例分析题**：36 道配解析
- **错题本**：自动记录错题
- **统计面板**：实时掌握学习进度
- **拓扑图支持**：网络工程拓扑图可视化
- **Docker 部署**：一键启动

## 快速开始

### Docker Compose（推荐）

```bash
# 克隆仓库
git clone https://github.com/YOUR_USERNAME/esfnpe.git
cd esfnpe

# 启动服务
docker-compose up -d

# 访问
open http://localhost:3030
```

### Docker 手动运行

```bash
docker build -t esfnpe .
docker run -d -p 3030:3030 --name esfnpe esfnpe
```

### 本地运行

```bash
pip install -r requirements.txt
python app.py
# 访问 http://localhost:3030
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/questions/random?count=10` | GET | 随机抽题 |
| `/api/questions/submit` | POST | 提交答案 |
| `/api/wrong` | GET | 获取错题本 |
| `/api/stats/overview` | GET | 学习统计 |

## 题库结构

```
questions/
├── basic-questions.json   # 基础选择题（446道）
├── case-questions.json   # 案例分析题（36道）
├── sent-index.json        # 题目索引
├── topology/              # 拓扑图（9张）
└── essays/                # 论文素材
```

## 技术栈

- **后端**：Flask + SQLite
- **前端**：原生 HTML/CSS/JS
- **容器**：Docker

## 开源协议

MIT License - 详见 [LICENSE](LICENSE) 文件。

## 贡献

欢迎提交 Issue 和 Pull Request！
