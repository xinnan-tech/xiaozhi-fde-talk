<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import MarkdownIt from "markdown-it";

defineOptions({ name: "TemplateEditorReport" });
const { t } = useI18n();

const report = defineModel<{ doc: string }>({ required: true });
const props = defineProps<{ fieldKeys: string[] }>();

const md = new MarkdownIt({ html: false, breaks: true });
const preview = computed(() => md.render(report.value.doc || ""));
const variables = computed(() =>
  props.fieldKeys.filter(Boolean).map(k => `{{session.${k}}}`)
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
    <span class="field-label">{{ t("system.template.insert_var") }}：</span>
    <el-tag
      v-for="v in variables"
      :key="v"
      size="small"
      class="var-chip"
      @click="insertVar(v)"
      >{{ v }}</el-tag
    >
  </div>
  <div class="report-split">
    <el-input
      ref="editorRef"
      v-model="report.doc"
      type="textarea"
      :rows="16"
      :placeholder="t('system.template.report_doc')"
      class="report-editor"
    />
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div class="report-preview" v-html="preview" />
  </div>
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

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

    // v-html 渲染 markdown-it 产物（html:false 关闭 HTML 直通，见脚本内 md 配置）
    :deep(h1) {
      font-size: 18px;
    }

    :deep(h2) {
      font-size: 16px;
    }
  }
}

@media (max-width: 760px) {
  .report-split {
    grid-template-columns: 1fr;
  }
}
</style>
