"""测试桩 LLM：返回确定性有效响应，无需真实 API key。

激活条件：`llm.type=stub`。仅供 e2e / 离线单测使用，生产配置默认是
"openai"——任何把 llm.type 设为 "stub" 的行为都必须由测试自己发起。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.adapters.llm.base import LLMProvider

# 与 templates/pm.json must_ask 同形：6 条种子项全 todo。覆盖循环
# (state.ignored_ids / skipped_ids → IGNORED / SKIPPED) 能按 id 命中。
_COACHING_ITEMS: list[dict[str, str]] = [
    {"id": "objective", "text": "对方真正想达成什么（动机/目标）",
     "status": "todo", "reason": ""},
    {"id": "pain", "text": "痛点 / 未满足需求", "status": "todo", "reason": ""},
    {"id": "current_solution", "text": "现在怎么解决 / 有没有用竞品或替代",
     "status": "todo", "reason": ""},
    {"id": "constraints", "text": "预算 / 时间线 / 其他约束",
     "status": "todo", "reason": ""},
    {"id": "decision", "text": "决策人是谁 / 谁拍板",
     "status": "todo", "reason": ""},
    {"id": "success", "text": "怎么衡量做成没做成（可量化指标）",
     "status": "todo", "reason": ""},
]

# 报告桩：满足 test_report_generation_and_export 断言
# （≥3 个 `##+ ` 标题、无悬空标签、>600 字符、无未填占位符）。
_REPORT_MD: str = """# E2E测试 需求调研报告

> 受访者：测试对象　开始：2026-08-22 10:00　结束：2026-08-22 11:00

## 背景与目的
本次访谈围绕 E2E测试 项目的目标展开。受访者阐述了在当前业务流程中遇到的挑战，以及对新工具的期望。本次访谈的核心目标是验证方案可行性并梳理后续执行路径，确定下一阶段的关键里程碑。

## 受访者与场景
- 客户 / 行业：科技公司 / SaaS
- 现状：使用 Excel + 邮件管理访谈记录，无统一平台
- 关键诉求：希望能在 3 个月内落地新工具

## 需求与痛点
- 痛点 1：访谈记录散落难以回顾，影响知识沉淀
- 痛点 2：跨团队协作时信息不对称
- 痛点 3：转写与摘要依赖人工，耗时易遗漏
- 未满足需求：缺少自动化的转写与要点提炼能力
- 未满足需求：缺少跨团队共享访谈结论的统一视图

## 机会与建议
- 机会点：高优引入 AI 摘要 + 清单推荐能力
- 机会点：与现有 CRM 系统打通，减少手工搬运
- 待验证假设：受访者愿意付费使用高级版
- 待验证假设：跨团队对统一访谈模板的接受度
- 待补充调研项：对比 3 家供应商的报价与功能
- 待补充调研项：数据合规与跨境传输要求

## 下一步
- 待办：组织一次内部 demo 演示
- 待办：与 IT 部门对接 SSO 接入
- 待办：整理访谈模板与清单 v1 版本
- 待核实点：确认数据合规与隐私要求

## 建议后续动作
- 确认调研结论并归档到知识库
- 录入用户画像 / 痛点库
- 分享给产品与研发团队评审
"""


class StubLLMProvider(LLMProvider):
    """测试桩：不联网、不耗 token；chat_text / chat_json 都返确定性响应。"""

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        model: str = "stub",
        llm_timeout_s: float = 45.0,
    ) -> None:
        # 保留构造签名与 OpenAILLMProvider 对齐；stub 模式下这些参数无意义。
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._llm_timeout_s = llm_timeout_s

    @property
    def configured(self) -> bool:
        return True

    async def chat_json(
        self,
        system: str,
        user: str,
        retries: int = 2,
        output_schema: Optional[type] = None,
    ) -> dict[str, Any]:
        return {"items": [dict(it) for it in _COACHING_ITEMS]}

    async def chat_text(
        self,
        system: str,
        user: str,
        retries: int = 2,
        json_mode: bool = False,
    ) -> str:
        if json_mode:
            return json.dumps(
                {"items": [dict(it) for it in _COACHING_ITEMS]},
                ensure_ascii=False,
            )
        return _REPORT_MD

    async def aclose(self) -> None:
        return None
