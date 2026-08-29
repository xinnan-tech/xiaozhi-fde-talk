"""模板种子：DB 空表时由 loader.warm() 幂等种入。

内容 = 原 backend/templates/pm.json（文件删除后此处是唯一种源，勿手改格式；
修改模板请走 admin 模板管理界面）。
"""
from __future__ import annotations

SEED_TEMPLATES: list[dict] = [
    {
        "id": "pm-research",
        "version": "1",
        "icon_url": "",
        "icon_alt": "📋",
        "name": "产品经理",
        "session": {
            "name": "用户/需求访谈",
            "goal": "本次访谈想搞清楚什么（用户在设置页填，喂给辅导首算）",
            "base_fields": [
                {"key": "project", "label": "项目/对象"},
                {"key": "interviewee", "label": "受访者"},
                {"key": "start_time", "label": "开始时间", "type": "datetime"},
                {"key": "duration", "label": "访谈时长", "type": "duration"},
            ],
            "setup": {
                "intro": "请用一两句话说说这次访谈：项目/对象、大致需求、达成目标、大概几点到几点。",
                "extract_to": ["project", "interviewee", "goal", "start_time", "end_time"],
                "required": ["project", "goal"],
            },
        },
        "coaching": {
            "playbook": "你在辅助一位产品经理做需求/用户访谈。目标已给出；据此 + must_ask 实时提醒还该问什么、追问什么。",
            "must_ask": [
                {"id": "objective", "text": "对方真正想达成什么（动机/目标）", "priority": 1},
                {"id": "pain", "text": "痛点 / 未满足需求", "priority": 2},
                {"id": "current_solution", "text": "现在怎么解决 / 有没有用竞品或替代", "priority": 3},
                {"id": "constraints", "text": "预算 / 时间线 / 其他约束", "priority": 4},
                {"id": "decision", "text": "决策人是谁 / 谁拍板", "priority": 5},
                {"id": "success", "text": "怎么衡量做成没做成（可量化指标）", "priority": 6},
            ],
        },
        "report": {
            "doc": "# {{session.project}} 需求调研报告\n> 受访者：{{session.interviewee}}　开始：{{session.start_time}}　结束：{{session.end_time}}\n\n## 背景与目的\n{{ 项目背景、为什么做、目标——一段话 }}\n\n## 受访者与场景\n- 客户 / 行业：{{ 客户与行业标签 }}\n- 现状：{{ 受访者现状与使用场景 }}\n\n## 需求与痛点\n- 痛点：{{ 痛点列表 }}\n- 未满足需求：{{ 未满足的需求 }}\n\n## 机会与建议\n- 机会点 / 优先级建议：{{ … }}\n- 待验证假设 / 待补充调研项：{{ … }}\n\n## 下一步\n- 待办与待核实点：{{ … }}\n\n## 建议后续动作\n- 确认调研结论\n- 录入用户画像 / 痛点库\n- 分享给团队\n",
        },
        "safety": [],
    },
]
