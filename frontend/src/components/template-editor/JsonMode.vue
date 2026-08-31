<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { basicSetup } from "codemirror";
import { EditorView } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { json } from "@codemirror/lang-json";

defineOptions({ name: "TemplateEditorJson" });

const props = defineProps<{ code: string }>();
const emit = defineEmits<{ "update:code": [value: string] }>();

// CodeMirror 自建 DOM 树挂在 host 内（host 是原生 div，非组件 ref）。
// v-if 切走时本组件随之卸载 → onBeforeUnmount destroy；
// 切回时重新 onMounted，以挂载时刻的 props.code 重建文档，
// 编辑器内容与 jsonCode 状态始终同源。
const host = ref<HTMLElement>();
let view: EditorView | null = null;

onMounted(() => {
  if (!host.value) return;
  view = new EditorView({
    state: EditorState.create({
      doc: props.code,
      extensions: [
        basicSetup,
        json(),
        EditorView.lineWrapping,
        EditorView.updateListener.of(u => {
          if (u.docChanged) emit("update:code", u.state.doc.toString());
        })
      ]
    }),
    parent: host.value
  });
});

onBeforeUnmount(() => {
  view?.destroy();
  view = null;
});

// 外部整体替换（如从表单模式切入）时同步编辑器内容；
// current === next 时跳过，避免「输入 → emit → 回写」的回声循环
watch(
  () => props.code,
  next => {
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== next) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: next }
      });
    }
  }
);

/** 错误面板点击跳行：滚到目标行并高亮一拍（basicSetup 的 highlightActiveLine） */
const focusLine = (line: number) => {
  if (!view) return;
  const info = view.state.doc.line(Math.min(line, view.state.doc.lines));
  view.dispatch({
    selection: { anchor: info.from },
    effects: EditorView.scrollIntoView(info.from, { y: "center" })
  });
  view.focus();
};
defineExpose({ focusLine });
</script>

<template>
  <div ref="host" class="json-editor" data-testid="json-editor" />
</template>

<style lang="scss" scoped>
.json-editor {
  min-height: 480px;
  overflow: hidden;
  font-size: 13px;
  border: 1px solid #dfe5ee;
  border-radius: 8px;

  :deep(.cm-editor) {
    height: 520px;

    .cm-scroller {
      font-family: var(--font-family-code, monospace);
    }
  }
}
</style>
