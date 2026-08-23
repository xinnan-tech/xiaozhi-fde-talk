# 更新日志

本项目的所有重要变更都记录在此文件。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-08-23

### 新增
- 自助用户体系：首个注册用户成为超级管理员，后续可注册 / 重置密码 / 改密自动吊销旧 token
- `/admin/users` 用户管理页（列用户 + 重置密码）
- `/auth/change-password` 自助改密入口
- WebSocket 实时访谈通道（音频转写 + 辅导）
- 结构化报告生成（Markdown / HTML / Word 导出）
- 多语种界面（zh-CN / en-US / zh-TW / vi-VN）
- Docker Compose 一键部署（FunASR + 主应用）

### 安全
- 报告页 v-html 走 markdown-it html:false 防 stored XSS
- `/auth/register` 接入限流，首用户注册走 SQLite BEGIN IMMEDIATE 防双 admin 竞态
- 4 个 Pydantic 请求 DTO 加 extra=forbid 防字段注入
- 5 个其他请求 DTO 加 extra=forbid 防 LLM prompt 注入
- 密码哈希 bcrypt ≥ 4.2.1 全版本锁
- prod 模式关 `/docs` `/redoc` `/openapi.json` 防 API 字典泄露
- refresh token 骨架 + /auth/logout

### 修复
- 旧硬编码管理员启动密码清理（首用户注册路径取代）
- JWT secret 不再从环境变量读取，由 DB 自动生成
- SQLite 数据库文件 .gitignore 强化
- 测试不再依赖环境变量 `APP_ADMIN_PASSWORD`

### 文档
- CONTRIBUTING / SECURITY / CODE_OF_CONDUCT / issue 模板 / PR 模板
- README 补架构 / 配置 / 部署 / 截图章节
- Docker deployment 章节
- WebSocket 协议文档补 4 个 server 帧契约