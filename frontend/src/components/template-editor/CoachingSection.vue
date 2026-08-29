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

/** 高级项（问题标识）默认收起：小白只需要关心问什么 */
const showAdvanced = ref(false);

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

/** 新增问题：标识自动生成（q1、q2…避让已有），顺序由列表位置决定 */
const addItem = () => {
  const used = new Set(coaching.value.must_ask.map(m => m.id).filter(Boolean));
  let n = coaching.value.must_ask.length + 1;
  while (used.has(`q${n}`)) n += 1;
  coaching.value.must_ask.push({
    id: `q${n}`,
    text: "",
    priority: null,
    desc: ""
  });
};
const removeItem = (i: number) => coaching.value.must_ask.splice(i, 1);
</script>

<template>
  <label class="field-row field-row-wide">
    <span class="field-label">{{ t("system.template.playbook") }}</span>
    <el-input v-model="coaching.playbook" type="textarea" :rows="3" />
  </label>

  <div class="field-table-head">
    <span>
      {{ t("system.template.must_ask") }}
      <span class="required-star">*</span>
    </span>
    <span class="head-side">
      <label class="advanced-toggle">
        <el-switch v-model="showAdvanced" size="small" />
        <span>{{ t("system.template.advanced") }}</span>
      </label>
      <el-button size="small" data-action="add-item" @click="addItem">
        {{ t("system.template.add_item") }}
      </el-button>
    </span>
  </div>
  <p class="list-hint">{{ t("system.template.must_ask_hint") }}</p>

  <div ref="listEl" class="must-ask-list">
    <div v-for="(m, i) in coaching.must_ask" :key="i" class="must-ask-item">
      <div class="item-main">
        <span
          class="drag-handle"
          :title="t('system.template.drag_hint')"
          :aria-label="t('system.template.drag_hint')"
          role="button"
          tabindex="0"
        >
          ⠿
        </span>
        <span class="item-index">{{ i + 1 }}</span>
        <el-input
          v-model="m.text"
          :placeholder="t('system.template.item_text')"
          size="small"
          class="item-text"
        />
        <el-button
          text
          type="danger"
          size="small"
          class="item-remove"
          @click="removeItem(i)"
        >
          ✕
        </el-button>
      </div>
      <div class="item-sub">
        <el-input
          v-model="m.desc"
          :placeholder="t('system.template.item_desc')"
          size="small"
        />
      </div>
      <div v-if="showAdvanced" class="item-advanced">
        <span class="advanced-label">
          {{ t("system.template.item_id") }}
        </span>
        <el-input v-model="m.id" size="small" class="advanced-input" />
        <span class="advanced-hint">
          {{ t("system.template.item_id_hint") }}
        </span>
      </div>
    </div>
  </div>
  <p v-if="coaching.must_ask.length === 0" class="list-empty">
    {{ t("system.template.must_ask_empty") }}
  </p>
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

.head-side {
  display: flex;
  gap: 12px;
  align-items: center;
}

.advanced-toggle {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  color: #667085;
  font-size: 12px;
  font-weight: 400;
  cursor: pointer;
}

.list-hint {
  margin: -2px 0 10px;
  color: #8a94a6;
  font-size: 12px;
}

.list-empty {
  margin: 4px 0 0;
  color: #98a2b3;
  font-size: 13px;
  text-align: center;
}

.must-ask {
  &-list {
    display: grid;
    gap: 8px;
  }

  &-item {
    padding: 8px 10px;
    background: rgb(255 255 255 / 60%);
    border: 1px solid #e9eef5;
    border-radius: 10px;
    transition:
      border-color 0.2s,
      box-shadow 0.2s;

    &:hover {
      border-color: #b6d4f5;
      box-shadow: 0 1px 4px rgb(57 136 238 / 10%);
    }

    .drag-handle {
      flex: 0 0 auto;
      color: #98a2b3;
      cursor: grab;
      user-select: none;
    }

    .item-index {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      color: #667085;
      font-size: 12px;
      background: #f2f6fc;
      border-radius: 50%;
    }

    .item-text {
      flex: 1;
    }

    .item-remove {
      flex: 0 0 auto;
    }
  }
}

.item-main {
  display: flex;
  gap: 8px;
  align-items: center;
}

.item-sub {
  padding-left: 36px;
  margin-top: 6px;
}

.item-advanced {
  display: flex;
  gap: 8px;
  align-items: center;
  padding-left: 36px;
  margin-top: 6px;

  .advanced-label {
    flex: 0 0 auto;
    color: #667085;
    font-size: 12px;
  }

  .advanced-input {
    flex: 0 0 180px;
  }

  .advanced-hint {
    color: #98a2b3;
    font-size: 12px;
  }
}
</style>
