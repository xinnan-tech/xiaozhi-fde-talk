<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

defineOptions({ name: "TemplateEditorReport" });
const { t } = useI18n();

const report = defineModel<{ doc: string }>({ required: true });
const props = defineProps<{ fieldOptions: { key: string; label: string }[] }>();

const variables = computed(() =>
  props.fieldOptions.map(f => ({
    var: `{{session.${f.key}}}`,
    label: f.label
  }))
);

// el-input 组件 ref 拿到的是 expose 代理（名单外 key 返回 undefined，
// 没有 querySelector）；其 expose 名单恰好含原生 textarea 元素，直接取。
const editorRef = ref<{ textarea?: HTMLTextAreaElement }>();

const insertVar = (v: string) => {
  const el = editorRef.value?.textarea;
  if (!el) {
    report.value.doc += v;
    return;
  }
  const { selectionStart: s, selectionEnd: e, value } = el;
  report.value.doc = value.slice(0, s) + v + value.slice(e);
  requestAnimationFrame(() => {
    el.focus();
    el.selectionStart = el.selectionEnd = s + v.length;
  });
};
</script>

<template>
  <div class="var-chips">
    <span class="var-chips-label">{{ t("system.template.insert_var") }}</span>
    <el-tag
      v-for="v in variables"
      :key="v.var"
      size="small"
      class="var-chip"
      @click="insertVar(v.var)"
      >{{ v.label }}&nbsp;<code>{{ v.var }}</code></el-tag
    >
  </div>
  <p class="doc-hint">{{ t("system.template.doc_hint") }}</p>
  <el-input
    ref="editorRef"
    v-model="report.doc"
    type="textarea"
    :autosize="{ minRows: 14 }"
    :placeholder="t('system.template.report_doc')"
    class="report-editor"
  />
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

.var-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;

  &-label {
    color: #667085;
    font-size: 12px;
  }

  .var-chip {
    cursor: pointer;

    code {
      color: #5b8ac7;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }

    &:hover {
      opacity: 0.8;
    }
  }
}

.doc-hint {
  margin: 0 0 8px;
  color: #8a94a6;
  font-size: 12px;
}

// Markdown 骨架：等宽字体 + 稍松行高，标题行(#/##)一眼可辨
.report-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.7;
}
</style>
