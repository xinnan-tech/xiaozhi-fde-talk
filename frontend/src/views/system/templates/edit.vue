<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ElMessage, ElMessageBox } from "element-plus";
import { extractBackendError } from "@/utils/error";
import { getInterviewTemplateDetailApi } from "@/api/interview";
import {
  createAdminTemplateApi,
  updateAdminTemplateApi,
  generateAdminTemplateApi,
  type TemplateDoc
} from "@/api/admin";
import AiGenerateSection from "@/components/template-editor/AiGenerateSection.vue";
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
    setup: { intro: "", extract_to: [], required: [] },
    title_default: "",
    goal_default: ""
  },
  coaching: { playbook: "", must_ask: [] },
  report: { doc: "" },
  safety: []
});

const tpl = reactive<TemplateDoc>(blank());
/** 最后一次服务端（或本地初始化）落定的模板快照——JSON 字符串做浅比较。
 * 任意字段改动后 stringify 不同 → dirty=true，cancel 弹确认 */
const lastSavedJson = ref(JSON.stringify(blank()));
const dirty = computed(() => JSON.stringify(tpl) !== lastSavedJson.value);

const markSaved = (doc: TemplateDoc) => {
  lastSavedJson.value = JSON.stringify(doc);
};

/** 三模式：AI 生成 / 表单 / JSON。AI 模式只对「空白新建」开放——
 *  复制与编辑场景已有内容可调，直接落表单 */
type Mode = "ai" | "form" | "json";
const showAiMode = computed(() => isNew.value && !copyFrom.value);
const mode = ref<Mode>(showAiMode.value ? "ai" : "form");
const saving = ref(false);
const jsonCode = ref(""); // JSON 模式的文本（Task 11 使用）

// ---- AI 生成模式 ----

const aiBrief = ref("");
const generating = ref(false);

const generate = async () => {
  if (generating.value) return;
  const brief = aiBrief.value.trim();
  if (!brief) return;
  generating.value = true;
  try {
    const doc = await generateAdminTemplateApi(brief);
    // 生成结果覆盖当前表单（ai_hint 已提示），成功即切表单模式微调
    applyDoc(doc);
    mode.value = "form";
    ElMessage.success(t("system.template.ai_success"));
  } catch (e) {
    // HTTP 错误（LLM 未配置 / 超时 / 输出不合规）由拦截器统一 toast，
    // 这里只兜底无响应异常，避免重复弹窗
    if (!(e as { response?: unknown })?.response) {
      ElMessage.error(extractBackendError(e, t("system.template.ai_failed")));
    }
  } finally {
    generating.value = false;
  }
};

const fieldOptions = computed(() =>
  tpl.session.base_fields
    .filter(f => f.key)
    .map(f => ({ key: f.key, label: f.label || f.key }))
);

const applyDoc = (doc: TemplateDoc) => {
  Object.assign(tpl, blank(), JSON.parse(JSON.stringify(doc)));
  markSaved(tpl);
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

const onModeChange = (next: Mode) => {
  if (next === mode.value) return;
  if (next === "json") {
    // → JSON：表单数据无损序列化
    enterJsonMode();
    mode.value = "json";
    return;
  }
  // json → form/ai：闸门，解析+结构校验通过才放行
  if (mode.value === "json" && !applyJsonToForm()) {
    ElMessage.warning(t("system.template.json_apply_blocked"));
    return; // mode 保持 json：阻止切换
  }
  // ai ↔ form：自由切换（brief 在父级持有，回来不丢）
  mode.value = next;
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
    const payload = JSON.parse(JSON.stringify(tpl)) as TemplateDoc;
    // 必问清单的「优先级」= 列表顺序（与引擎首评后的 i+1 重排一致），
    // 编辑器里不再暴露数字输入，保存时按行序回写；
    // 历史数据里漏填的问题标识在此自动补齐（q1、q2…避让已有）
    const usedIds = new Set<string>();
    payload.coaching?.must_ask?.forEach(m => {
      if (m.id) usedIds.add(m.id);
    });
    payload.coaching?.must_ask?.forEach((m, i) => {
      m.priority = i + 1;
      if (!m.id) {
        let n = i + 1;
        while (usedIds.has(`q${n}`)) n += 1;
        m.id = `q${n}`;
        usedIds.add(m.id);
      }
    });
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
    // HTTP 错误（含 4xx/5xx）已由 axios 拦截器统一 toast，
    // 这里只兜底无响应的异常（断网等），避免同一错误弹两次
    if (!(e as { response?: unknown })?.response) {
      ElMessage.error(extractBackendError(e, t("system.template.save_failed")));
    }
  } finally {
    saving.value = false;
  }
};

const cancel = async () => {
  if (!dirty.value) {
    router.push("/system/config");
    return;
  }
  try {
    await ElMessageBox.confirm(
      t("system.template.cancel_confirm"),
      t("system.template.cancel_confirm_title"),
      {
        confirmButtonText: t("system.template.cancel_confirm_ok"),
        cancelButtonText: t("system.template.cancel"),
        type: "warning"
      }
    );
    router.push("/system/config");
  } catch {
    // 用户点取消——留在编辑器
  }
};
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
        <!-- 受控模式：mode 只经 onModeChange 变更（json 离开有闸门） -->
        <el-radio-group
          :model-value="mode"
          size="small"
          @update:model-value="onModeChange($event as Mode)"
        >
          <el-radio-button v-if="showAiMode" value="ai" data-testid="mode-ai">
            {{ t("system.template.mode_ai") }}
          </el-radio-button>
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
          :disabled="mode === 'ai'"
          data-testid="tpl-save"
          @click="save"
        >
          {{ t("system.template.save") }}
        </el-button>
      </div>
    </header>

    <!-- AI 生成模式：一句话 → LLM 生成整份模板 → 自动切表单微调 -->
    <div v-if="mode === 'ai'" class="tpl-editor-body">
      <section class="tpl-section">
        <h2>{{ t("system.template.mode_ai") }}</h2>
        <AiGenerateSection
          v-model="aiBrief"
          :loading="generating"
          @generate="generate"
        />
      </section>
    </div>

    <!-- 表单模式：四分区；JSON 模式走下方 v-else 分支 -->
    <div v-else-if="mode === 'form'" class="tpl-editor-body">
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
        <ReportSection v-model="tpl.report" :field-options="fieldOptions" />
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
</style>
