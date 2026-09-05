"""单元测试：skill 注册表 / 执行器 / 报告渲染。

不依赖外部服务（内置 skill 纯函数）。
"""
from __future__ import annotations

from app.services.reports.skill_renderer import render_skills
from app.services.skill.executor import SkillResult, invoke_skill
from app.services.skill.registry import SkillArtifact, list_public_skills


def test_skill_registry_list():
    ids = [s["id"] for s in list_public_skills()]
    assert "echo" in ids and "text-card" in ids and "markdown-table" in ids


async def test_skill_executor_success():
    result = await invoke_skill("echo", {"title": "联调", "content": "skill 已执行"})
    assert result.ok and result.artifact is not None
    assert "skill 已执行" in result.artifact.content


async def test_skill_executor_unknown():
    result = await invoke_skill("missing-skill", {})
    assert not result.ok and "unknown skill" in result.error


async def test_skill_renderer_replace_marker():
    md = '前文\n\n{{skill: echo, inputs: {"title": "补充", "content": "hello"}}}\n\n后文'
    rendered = await render_skills(md)
    assert "{{skill:" not in rendered and "### 补充" in rendered and "hello" in rendered


async def test_skill_renderer_bad_inputs_fallback():
    rendered = await render_skills("{{skill: echo, inputs: [1, 2]}}")
    assert "JSON object" in rendered


async def test_skill_renderer_includes_artifact_warnings(monkeypatch):
    """技能产物中的 warnings 应出现在最终报告 Markdown 中。"""
    artifact = SkillArtifact(
        mime="text/markdown",
        content="### T\n\n| a |\n| --- |\n| x |",
        meta={"warnings": ["row 0: trailing 1 cell dropped"]},
    )

    async def fake_invoke(*_args, **_kwargs):
        return SkillResult(ok=True, artifact=artifact)

    monkeypatch.setattr(
        "app.services.reports.skill_renderer.invoke_skill", fake_invoke
    )
    rendered = await render_skills("{{skill: markdown-table, inputs: {}}}")
    assert "> Note: row 0: trailing 1 cell dropped" in rendered
