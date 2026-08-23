# 贡献指南

感谢你愿意为「小智方糖」添砖加瓦。本仓库托管 FastAPI 后端 + Vue 3 前端 + Docker
部署编排，目标是做一个面向 FDE / 产品经理 / 售前 / 咨询师的开源 AI 访谈搭档。

## 开发环境

| 工具 | 版本 |
| --- | --- |
| Conda（后端 Python） | Python 3.12 |
| Node.js（前端） | >= 20.19 或 >= 22.13 |
| pnpm（前端包管理） | >= 9 |
| Docker（FunASR） | 任意 24+ 版本 |

后端：

```bash
conda create -n xiaozhi-fde-talk python=3.12 -y
conda activate xiaozhi-fde-talk
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
cp .env.example .env
python main.py
```

前端：

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:8848
pnpm build        # 输出 dist/，由后端 SERVE_FRONTEND=true 托管
```

## 分支与提交

- 主分支是 `main`；新功能从 `main` 拉 feature 分支（如 `feature/coach-recompute`），
  修复拉 fix 分支（如 `fix/ws-takeover-race`）。
- 中文 commit subject，≤ 50 个码点；正文可选但简明。
- 一个 commit 只做一件事（不要混 style 与 substance）。commit 内禁止出现
  `@anthropic` 之类的协作 trailer。
- 提交前 `git status` 复核——本仓与同事共享，避免误带他人未提交的工作。

## PR 检查清单

- [ ] 单测 / e2e 全绿（`pytest backend/tests/unit` + `pnpm test:e2e`）
- [ ] Lint 干净（`pnpm lint`，后端无独立 lint，遵循 ruff/black 风格）
- [ ] 没有叙事型注释（如「上一轮」「review #N」「P0-X」）
- [ ] commit message 不带 `@`，且遵循中文 ≤50 码点
- [ ] 若新增 / 修改环境变量，同步更新 `backend/.env.example` 与 README

## 代码风格

- 后端：函数中文 docstring 允许；命名 snake_case；类 PascalCase；模块先 `from __future__ import annotations`。
- 前端：Vue 3 + TS；组件 PascalCase；组合式 API；i18n 走 `vue-i18n`，
  不允许在模板里硬编码用户可见字符串。
- 注释应自解释：写「为什么」而不是「做了什么」，不要把 review 讨论过程搬进源码。
- 共享配置变更（环境变量、KV 配置项、Alembic 迁移）需在 PR 描述里单独列出，
  便于运维侧跟进。

## 设计文档

内部设计与 RFC 走内部文档通道（按需申请），不在本仓长期维护。如果你有重大架构
变更提案，请先开 issue 讨论。

## 行为准则

请阅读并遵守 `CODE_OF_CONDUCT.md`。任何问题邮件 `security@xinnan-tech.com`。