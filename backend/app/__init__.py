"""访谈助手后端服务（uvicorn 启动）。

分层结构（依赖方向：transport → services → domain；core 被所有层依赖）：
    core/          横切：配置、日志、异常、安全、策略、常量
    domain/        纯领域模型（pydantic，零副作用）
    services/      应用服务/用例 + 协议无关 SessionRuntime
    adapters/      外部集成接缝（ASR/LLM 端口与实现）
    persistence/   持久化基础设施（DB engine + ORM + Repository）
    transport/     传输层（HTTP / WebSocket 薄适配器）
"""
__version__ = "0.0.0"
