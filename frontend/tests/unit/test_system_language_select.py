"""issue #65：配置管理页语种字段改下拉。

admin 不再手填语言代码；真相之源在
backend/app/core/config_store.py:ENUM_KEYS，前端 SELECT_FIELD_OPTIONS 必
须与之对齐。本测试锁住三点契约：
1. SELECT_FIELD_OPTIONS 含三个目标 key
2. funasr_server.language 选项集合 == 后端 ENUM_KEYS
3. 模板按 selectVariant 分支：radio 渲染 ASR.type，dropdown 渲染语种
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_VUE = ROOT / "src" / "views" / "system" / "index.vue"
LOCALES_ZH = ROOT / "src" / "locales" / "zh-CN.json"
LOCALES_EN = ROOT / "src" / "locales" / "en-US.json"
LOCALES_VI = ROOT / "src" / "locales" / "vi-VN.json"
LOCALES_TW = ROOT / "src" / "locales" / "zh-TW.json"


def _script_block(text: str) -> str:
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def _template_block(text: str) -> str:
    start = text.index("<template")
    end = text.index("</template>", start)
    return text[start:end]


def _all_locale_keys(locale_path: Path) -> set[str]:
    return set(json.loads(locale_path.read_text(encoding="utf-8")).keys())


def test_select_field_options_has_three_target_keys():
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    for key in (
        "asr.funasr_server.language",
        "asr.doubao_stream.language",
        "llm.output_language"
    ):
        assert f'"{key}"' in script, f"缺 SELECT_FIELD_OPTIONS[\"{key}\"]"


def test_funasr_language_values_match_backend_enum_keys():
    """funasr 选项集合必须 == backend ENUM_KEYS，否则 set 时被 400 挡回。"""
    backend_enum = {"zh", "yue", "en"}
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    funasr_section_start = script.index('"asr.funasr_server.language"')
    funasr_section_end = script.index('"asr.doubao_stream.language"')
    funasr_block = script[funasr_section_start:funasr_section_end]
    found_values = {
        line.split('"')[1]
        for line in funasr_block.splitlines()
        if line.strip().startswith("{ value:")
    }
    assert found_values == backend_enum, (
        f"funasr 选项漂移：前端 {found_values} ≠ 后端 {backend_enum}。"
        f"改 ENUM_KEYS 必须同步 SELECT_FIELD_OPTIONS"
    )


def test_doubao_language_options_at_least_three():
    """doubao 至少 3 个常用 locale；admin 切其他 locale 时回退到 el-input。"""
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    start = script.index('"asr.doubao_stream.language"')
    end = script.index('"llm.output_language"')
    block = script[start:end]
    found_values = {
        line.split('"')[1]
        for line in block.splitlines()
        if line.strip().startswith("{ value:")
    }
    assert len(found_values) >= 3, f"doubao 选项至少 3 个，实际 {len(found_values)}"
    # 关键兜底：zh-CN / en-US 必在
    assert "zh-CN" in found_values and "en-US" in found_values


def test_template_has_el_select_branch_for_dropdown():
    """模板新增 el-select 分支处理 selectVariant='dropdown'。"""
    template = _template_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    assert "<el-select" in template, "缺 el-select 渲染分支"
    assert "<el-option" in template, "缺 el-option 子组件"
    assert "t(opt.labelKey)" in template, "el-option label 未走 i18n 翻译"


def test_template_radio_branch_intact_for_asr_type():
    """ASR.type 的 radio 渲染分支没被改成 dropdown。"""
    template = _template_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    assert "<el-radio-group" in template
    assert "<el-radio-button" in template
    # radio 分支条件必须是 selectVariant === 'radio'（Vue 模板用单引号）
    assert "field.selectVariant === 'radio'" in template, (
        "radio 分支条件应是 selectVariant 而非 key sentinel，"
        "否则后续加新 select 形态会被误判"
    )


def test_asr_field_options_resolved_at_render_time():
    """ASR 字段 options 在 buildConfigGroups 时不烤入；渲染时按当前 type 实时查。

    不同 type 共享 fieldKey（funasr_server / doubao_stream 都有 language 但
    选项不同），build 时烤入 dedup 后切 type 会沿用第一个遍历到的 type 的
    选项，导致 doubao_stream.language 下拉仍是 {zh, yue, en}，admin 选 "en"
    保存被 400 拒绝；stored "zh-CN" 因选项不匹配只能当 raw text 显示。
    """
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    assert "const selectOptionsFor" in script, (
        "缺 selectOptionsFor 渲染时查表函数"
    )


def test_template_select_uses_selectOptionsFor_fallback():
    """模板 el-option v-for 走 field.options ?? selectOptionsFor 兜底链。

    ASR 字段 options 不烤入，必须有兜底；非 ASR 字段（llm.output_language）
    options 烤入，chain 走 field.options 一支。
    """
    template = _template_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    assert "field.options ?? selectOptionsFor" in template, (
        "el-option v-for 必须走 field.options ?? selectOptionsFor 兜底链，"
        "否则 ASR 字段渲染时仍用 buildConfigGroups 时烤死的第一个 type 的选项"
    )


def test_i18n_keys_for_new_locales_present():
    """新增的 7 个语种 i18n key 必填，否则 el-select 显示 raw key。

    i18n parity CI 要求所有 locale（zh-CN / zh-TW / en-US / vi-VN）齐平——
    缺一个就 build 失败。修改 SELECT_FIELD_OPTIONS 加新 locale 也必须同步。
    """
    for locale_path in (LOCALES_ZH, LOCALES_EN, LOCALES_VI, LOCALES_TW):
        keys = _all_locale_keys(locale_path)
        for opt_key in (
            "config.opt.ja_jp",
            "config.opt.ko_kr",
            "config.opt.es_mx",
            "config.opt.fr_fr",
            "config.opt.de_de",
            "config.opt.ru_ru",
            "config.opt.pt_br",
        ):
            assert opt_key in keys, f"{locale_path.name} 缺 {opt_key}"