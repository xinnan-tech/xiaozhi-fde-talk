<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { extractBackendError } from "@/utils/error";
import { getInterviewTemplateDetailApi } from "@/api/interview";
import {
  createAdminTemplateApi,
  updateAdminTemplateApi,
  type TemplateDoc
} from "@/api/admin";
import BaseInfoSection from "@/components/template-editor/BaseInfoSection.vue";
import SessionSection from "@/components/template-editor/SessionSection.vue";
import CoachingSection from "@/components/template-editor/CoachingSection.vue";
import ReportSection from "@/components/template-editor/ReportSection.vue";
import JsonMode from "@/components/template-editor/JsonMode.vue";
import {
  parseJsonSafe,
  validateTemplateStructure,
  type StructError
} from "@/utils/templateValidation";

defineOptions({ name: "SystemTemplateEdit" });

const route = useRoute();
const router = useRouter();
const { t } = useI18n();

const isNew = computed(() => route.name === "SystemTemplateNew");
const copyFrom = computed(() => (route.query.copyFrom as string) || "");
const templateId = computed(() => (route.params.id as string) || "");

const blank = (): TemplateDoc => ({
  id: "",
  version: "1",
  icon_url: "",
  icon_alt: "📋",
  name: "",
  session: {
    name: "",
    goal: "",
    base_fields: [],
    setup: { intro: "", extract_to: [], required: [] }
  },
  coaching: { playbook: "", must_ask: [] },
  report: { doc: "" },
  safety: []
});

const tpl = reactive<TemplateDoc>(blank());
const mode = ref<"form" | "json">("form");
const saving = ref(false);
const jsonCode = ref(""); // JSON 模式的文本（Task 11 使用）

const fieldKeys = computed(() => tpl.session.base_fields.map(f => f.key));

const applyDoc = (doc: TemplateDoc) => {
  Object.assign(tpl, blank(), JSON.parse(JSON.stringify(doc)));
};

// ---- JSON 模式（CodeMirror + 校验 + 模式切换闸门） ----

const jsonEditor = ref<InstanceType<typeof JsonMode>>();
const structErrors = ref<StructError[]>([]);
const syntaxError = ref<{
  line: number;
  column: number;
  message: string;
} | null>(null);

const jsonErrors = computed(() => {
  const list: string[] = [];
  if (syntaxError.value) {
    const { line, column, message } = syntaxError.value;
    list.push(`第 ${line} 行 第 ${column} 列：${message}`);
  }
  for (const e of structErrors.value) list.push(`${e.path}：${e.message}`);
  return list;
});

/** 进 JSON 模式：表单数据无损序列化 */
const enterJsonMode = () => {
  jsonCode.value = JSON.stringify(tpl, null, 2);
  syntaxError.value = null;
  structErrors.value = [];
};

/** 离开 JSON 模式的闸门：解析 + 校验全过才放行（= 渲染回表单） */
const applyJsonToForm = (): boolean => {
  const { data, error } = parseJsonSafe(jsonCode.value);
  if (error) {
    syntaxError.value = error;
    structErrors.value = [];
    return false;
  }
  syntaxError.value = null;
  const errs = validateTemplateStructure(data);
  structErrors.value = errs;
  if (errs.length) return false;
  applyDoc(data as TemplateDoc);
  return true;
};

const onModeChange = (next: "form" | "json") => {
  if (next === mode.value) return;
  if (next === "json") {
    enterJsonMode();
    mode.value = "json";
    return;
  }
  // json → form：闸门，通过才切换
  if (applyJsonToForm()) {
    mode.value = "form";
  } else {
    ElMessage.warning(t("system.template.json_apply_blocked"));
    // mode 保持 json：阻止切换
  }
};

/** JSON 内容变化时即时校验，粘贴即反馈（单一入口，不走 v-model） */
const onJsonInput = (value: string) => {
  jsonCode.value = value;
  const { data, error } = parseJsonSafe(value);
  syntaxError.value = error ?? null;
  structErrors.value = error ? [] : validateTemplateStructure(data);
};

const jumpToLine = (line: number) => jsonEditor.value?.focusLine(line);

/** 错误面板点击：语法错误固定为第一条，点击跳到出错行 */
const onJsonErrorClick = (index: number) => {
  if (syntaxError.value && index === 0) jumpToLine(syntaxError.value.line);
};

onMounted(async () => {
  if (isNew.value) {
    if (copyFrom.value) {
      // 复制：加载源模板 → 换 id、名称加「副本」
      // （接口返回类型只声明了列表用字段，后端实际返回完整模板 JSON，
      //   与 TemplateDoc 结构一致——简报已核实，此处显式断言收窄类型）
      const src = (await getInterviewTemplateDetailApi(
        copyFrom.value
      )) as TemplateDoc;
      applyDoc({
        ...src,
        id: "",
        name: `${src.name}（${t("system.template.copy_suffix")}）`,
        version: "1"
      });
    }
    return; // 空白
  }
  const doc = (await getInterviewTemplateDetailApi(
    templateId.value
  )) as TemplateDoc;
  applyDoc(doc);
});

const save = async () => {
  if (saving.value) return;
  // JSON 模式下直接点保存：先过同一道解析+结构闸门（通过则并入表单数据），
  // 失败不保存——否则 JSON 改动会被旧表单数据悄悄覆盖
  if (mode.value === "json" && !applyJsonToForm()) {
    ElMessage.warning(t("system.template.json_apply_blocked"));
    return;
  }
  saving.value = true;
  try {
    const payload = JSON.parse(JSON.stringify(tpl));
    const saved = isNew.value
      ? await createAdminTemplateApi(payload)
      : await updateAdminTemplateApi(payload.id, payload);
    // 新建成功后切到编辑形态（id 锁定），避免重复 POST
    if (isNew.value) {
      router.replace(`/system/templates/edit/${saved.id}`);
    }
    applyDoc(saved);
    ElMessage.success(t("system.template.save_success"));
  } catch (e) {
    ElMessage.error(extractBackendError(e, t("system.template.save_failed")));
  } finally {
    saving.value = false;
  }
};

const cancel = () => router.push("/system/config");
</script>

<template>
  <div class="tpl-editor" data-testid="tpl-editor">
    <header class="tpl-editor-header">
      <h1>
        {{
          isNew
            ? t("system.template.editor_title_new")
            : t("system.template.editor_title_edit")
        }}
      </h1>
      <div class="mode-switch">
        <!-- 受控模式：mode 只经 onModeChange 变更（json → form 有闸门） -->
        <el-radio-group
          :model-value="mode"
          size="small"
          @update:model-value="onModeChange($event as 'form' | 'json')"
        >
          <el-radio-button value="form" data-testid="mode-form">
            {{ t("system.template.mode_form") }}
          </el-radio-button>
          <el-radio-button value="json" data-testid="mode-json">
            {{ t("system.template.mode_json") }}
          </el-radio-button>
        </el-radio-group>
      </div>
      <div class="header-actions">
        <el-button @click="cancel">{{ t("system.template.cancel") }}</el-button>
        <el-button
          type="primary"
          :loading="saving"
          data-testid="tpl-save"
          @click="save"
        >
          {{ t("system.template.save") }}
        </el-button>
      </div>
    </header>

    <!-- 表单模式：四分区；JSON 模式走下方 v-else 分支 -->
    <div v-if="mode === 'form'" class="tpl-editor-body">
      <section class="tpl-section">
        <h2>{{ t("system.template.section_base") }}</h2>
        <BaseInfoSection v-model="tpl" :id-locked="!isNew" />
      </section>
      <section class="tpl-section">
        <h2>{{ t("system.template.section_session") }}</h2>
        <SessionSection v-model="tpl.session" />
      </section>
      <section class="tpl-section">
        <h2>{{ t("system.template.section_coaching") }}</h2>
        <CoachingSection v-model="tpl.coaching" />
      </section>
      <section class="tpl-section">
        <h2>{{ t("system.template.section_report") }}</h2>
        <ReportSection v-model="tpl.report" :field-keys="fieldKeys" />
      </section>
    </div>

    <!-- JSON 模式：CodeMirror + 错误面板 -->
    <div v-else class="tpl-editor-body">
      <section class="tpl-section">
        <h2>{{ t("system.template.mode_json") }}</h2>
        <JsonMode
          ref="jsonEditor"
          :code="jsonCode"
          @update:code="onJsonInput"
        />
        <div
          v-if="jsonErrors.length"
          class="json-error-panel"
          data-testid="json-errors"
        >
          <h3>{{ t("system.template.json_errors") }}</h3>
          <button
            v-for="(msg, i) in jsonErrors"
            :key="i"
            class="json-error-item"
            type="button"
            @click="onJsonErrorClick(i)"
          >
            {{ msg }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.tpl-editor {
  box-sizing: border-box;
  height: 100%;
  padding: 24px 16px;
  overflow: auto;

  &-header {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px 16px;

    h1 {
      margin: 0;
      color: #1a1a1a;
      font-size: 22px;
      font-weight: 600;
    }
  }

  &-body {
    display: grid;
    gap: 16px;
    max-width: 980px;
    margin: 0 auto;
  }
}

.tpl-section {
  padding: 16px 20px;
  background: rgb(255 255 255 / 65%);
  border: 1px solid rgb(255 255 255 / 75%);
  border-radius: 16px;
  box-shadow: 0 0 10px rgb(0 0 0 / 8%);

  h2 {
    margin: 0 0 12px;
    color: #3988ee;
    font-size: 16px;
    font-weight: 600;
  }
}

.json-error-panel {
  margin-top: 12px;
  padding: 12px 16px;
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 8px;

  h3 {
    margin: 0 0 8px;
    color: #c45656;
    font-size: 14px;
  }

  .json-error-item {
    display: block;
    padding: 2px 0;
    color: #c45656;
    font-size: 13px;
    text-align: left;
    background: transparent;
    border: 0;
    cursor: pointer;
  }
}

// 以下公共类（.section-grid/.field-row/.field-label/.field-table* 等）同时
// 存在于各 Section 组件的 scoped 样式（template-editor/sections.scss）——
// scoped 样式不穿透子组件，两处各持一份，类名与取值保持一致。
.section-grid {
  display: grid;
  gap: 8px;
}

.field-row {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 10px;
  align-items: center;

  &-wide {
    grid-template-columns: 120px minmax(0, 1fr);
    align-items: flex-start;
  }
}

.field-label {
  color: #667085;
  font-size: 12px;
}

.field-table {
  margin-top: 12px;

  &-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 12px 0 8px;
    color: #344054;
    font-size: 13px;
    font-weight: 600;
  }
}

.fields {
  width: 100%;

  td {
    padding: 4px 6px 4px 0;
  }

  .drag-handle {
    width: 20px;
    color: #98a2b3;
    cursor: grab;
    text-align: center;
  }

  .row-ops {
    white-space: nowrap;
    text-align: right;
  }
}

.must-ask {
  &-list {
    display: grid;
    gap: 8px;
  }

  &-item {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    padding: 8px;
    background: rgb(255 255 255 / 48%);
    border: 1px solid #e9eef5;
    border-radius: 8px;

    .drag-handle {
      color: #98a2b3;
      cursor: grab;
    }
  }
}

.var-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 8px;

  .var-chip {
    cursor: pointer;
  }
}

.report {
  &-split {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  &-preview {
    min-height: 320px;
    padding: 12px 16px;
    overflow: auto;
    background: #fff;
    border: 1px solid #e9eef5;
    border-radius: 8px;

    :deep(h1) {
      font-size: 18px;
    }

    :deep(h2) {
      font-size: 16px;
    }
  }
}

.id-hint {
  color: #98a2b3;
  font-size: 12px;
}

@media (max-width: 760px) {
  .report-split {
    grid-template-columns: 1fr;
  }
}
</style>
