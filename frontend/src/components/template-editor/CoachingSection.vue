<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import Sortable from "sortablejs";

defineOptions({ name: "TemplateEditorCoaching" });
const { t } = useI18n();

type Item = { id: string; text: string; priority: number | null; desc: string };
const coaching = defineModel<{ playbook: string; must_ask: Item[] }>({
  required: true
});

const listEl = ref<HTMLElement>();
let sortable: Sortable | null = null;

onMounted(async () => {
  await nextTick();
  if (!listEl.value) return;
  sortable = Sortable.create(listEl.value, {
    handle: ".drag-handle",
    animation: 150,
    onEnd: ({ oldIndex, newIndex, item, from }) => {
      if (
        oldIndex === undefined ||
        newIndex === undefined ||
        oldIndex === newIndex
      ) {
        return;
      }
      // 先还原 Sortable 的 DOM 搬动，让 Vue 全权管理顺序
      // （:key="i" 的 keyed diff 对同序 key 只原地 patch 不搬节点，
      //   不还原 DOM 会造成视图与数据脱钩）
      from.removeChild(item);
      if (from.children[oldIndex])
        from.insertBefore(item, from.children[oldIndex]);
      else from.appendChild(item);
      const list = coaching.value.must_ask;
      const [moved] = list.splice(oldIndex, 1);
      list.splice(newIndex, 0, moved);
    }
  });
});
onBeforeUnmount(() => sortable?.destroy());

const addItem = () => {
  coaching.value.must_ask.push({ id: "", text: "", priority: null, desc: "" });
};
const removeItem = (i: number) => coaching.value.must_ask.splice(i, 1);
const move = (i: number, delta: -1 | 1) => {
  const j = i + delta;
  const list = coaching.value.must_ask;
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
};
</script>

<template>
  <label class="field-row field-row-wide">
    <span class="field-label">{{ t("system.template.playbook") }}</span>
    <el-input v-model="coaching.playbook" type="textarea" :rows="3" />
  </label>

  <div class="field-table-head">
    <span>{{ t("system.template.must_ask") }}</span>
    <el-button size="small" data-action="add-item" @click="addItem">
      {{ t("system.template.add_item") }}
    </el-button>
  </div>
  <div ref="listEl" class="must-ask-list">
    <div v-for="(m, i) in coaching.must_ask" :key="i" class="must-ask-item">
      <span class="drag-handle">⠿</span>
      <el-input
        v-model="m.id"
        :placeholder="t('system.template.item_id')"
        size="small"
        style="width: 130px"
      />
      <el-input
        v-model="m.text"
        :placeholder="t('system.template.item_text')"
        size="small"
      />
      <el-input-number
        v-model="m.priority"
        :min="1"
        size="small"
        style="width: 100px"
      />
      <el-input
        v-model="m.desc"
        :placeholder="t('system.template.item_desc')"
        size="small"
      />
      <span class="row-ops">
        <el-button text size="small" :disabled="i === 0" @click="move(i, -1)">
          ↑
        </el-button>
        <el-button
          text
          size="small"
          :disabled="i === coaching.must_ask.length - 1"
          @click="move(i, 1)"
        >
          ↓
        </el-button>
        <el-button text type="danger" size="small" @click="removeItem(i)"
          >✕</el-button
        >
      </span>
    </div>
  </div>
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

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
</style>
