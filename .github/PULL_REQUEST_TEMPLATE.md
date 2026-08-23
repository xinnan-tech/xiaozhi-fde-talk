## 改动说明

简明扼要写 1-3 句话。

## 关联 issue

- Fixes #（如有）
- Refs #（相关 issue）

## 改动类型

- [ ] bug fix
- [ ] 新功能
- [ ] 重构（无功能变更）
- [ ] 文档 / 注释
- [ ] 性能优化
- [ ] 测试

## 检查清单

- [ ] 已有 / 新增单测覆盖变更（`pytest backend/tests/unit`）
- [ ] 前端如改动，跑过 `pnpm typecheck` 与 `pnpm lint`
- [ ] commit message 遵循仓库约定（中文 ≤50 码点，无 `@` 协作 trailer，无 P0 / review 等叙事主语）
- [ ] 没有引入叙事型注释（"上一轮"、"P0-#N" 等）
- [ ] 若改环境变量 / 部署 / 数据库结构：同步更新 `backend/.env.example`、README 与 Alembic 迁移
- [ ] 文档（如 `docs/websocket-protocol.md`）已同步

## 测试方法

描述本地复现 / 验证步骤，或贴关键日志片段。

## 风险与影响

- 向后兼容（兼容老客户端 / 老配置？）
- 部署侧变更（环境变量、镜像构建、迁移）
- 协议 / 接口变更