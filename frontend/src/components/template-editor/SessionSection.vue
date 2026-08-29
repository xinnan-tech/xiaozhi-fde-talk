<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import Sortable from "sortablejs";

defineOptions({ name: "TemplateEditorSession" });
const { t } = useI18n();

type Field = { key: string; label: string; type: string; required: boolean };
const session = defineModel<{
  name: string;
  goal: string;
  base_fields: Field[];
  setup: { intro: string; extract_to: string[]; required: string[] };
}>({ required: true });

const tbody = ref<HTMLElement>();
let sortable: Sortable | null = null;

onMounted(async () => {
  await nextTick();
  if (!tbody.value) return;
  sortable = Sortable.create(tbody.value, {
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
      const list = session.value.base_fields;
      const [moved] = list.splice(oldIndex, 1);
      list.splice(newIndex, 0, moved);
    }
  });
});
onBeforeUnmount(() => sortable?.destroy());

const addField = () => {
  session.value.base_fields.push({
    key: "",
    label: "",
    type: "text",
    required: false
  });
};
const removeField = (i: number) => {
  const [removed] = session.value.base_fields.splice(i, 1);
  // 联动清理：被删字段从 setup.extract_to / setup.required 移除
  for (const attr of ["extract_to", "required"] as const) {
    session.value.setup[attr] = session.value.setup[attr].filter(
      k => k !== removed.key
    );
  }
};
const move = (i: number, delta: -1 | 1) => {
  const j = i + delta;
  const list = session.value.base_fields;
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
};

const FIELD_TYPES = ["text", "datetime", "duration"];
</script>

<template>
  <div class="section-grid">
    <label class="field-row">
      <span class="field-label">{{ t("system.template.session_name") }}</span>
      <el-input v-model="session.name" class="field-input" />
    </label>
    <label class="field-row">
      <span class="field-label">{{ t("system.template.session_goal") }}</span>
      <el-input v-model="session.goal" class="field-input" />
    </label>
  </div>

  <div class="field-table">
    <div class="field-table-head">
      <span>{{ t("system.template.fields") }}</span>
      <el-button size="small" data-action="add-field" @click="addField">
        {{ t("system.template.add_field") }}
      </el-button>
    </div>
    <table class="fields">
      <tbody ref="tbody">
        <tr v-for="(f, i) in session.base_fields" :key="i">
          <td class="drag-handle">⠿</td>
          <td>
            <el-input
              v-model="f.key"
              :placeholder="t('system.template.field_key')"
              size="small"
            />
          </td>
          <td>
            <el-input
              v-model="f.label"
              :placeholder="t('system.template.field_label')"
              size="small"
            />
          </td>
          <td>
            <el-select v-model="f.type" size="small" style="width: 110px">
              <el-option
                v-for="ty in FIELD_TYPES"
                :key="ty"
                :value="ty"
                :label="ty"
              />
            </el-select>
          </td>
          <td>
            <el-checkbox
              v-model="f.required"
              :aria-label="t('system.template.field_required')"
            />
          </td>
          <td class="row-ops">
            <el-button
              text
              size="small"
              :disabled="i === 0"
              @click="move(i, -1)"
            >
              ↑
            </el-button>
            <el-button
              text
              size="small"
              :disabled="i === session.base_fields.length - 1"
              @click="move(i, 1)"
            >
              ↓
            </el-button>
            <el-button text type="danger" size="small" @click="removeField(i)">
              ✕
            </el-button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="section-grid">
    <label class="field-row field-row-wide">
      <span class="field-label">{{ t("system.template.setup_intro") }}</span>
      <el-input v-model="session.setup.intro" type="textarea" :rows="2" />
    </label>
    <div class="field-row field-row-wide">
      <span class="field-label">{{ t("system.template.extract_to") }}</span>
      <el-checkbox-group v-model="session.setup.extract_to">
        <el-checkbox
          v-for="f in session.base_fields.filter(x => x.key)"
          :key="f.key"
          :value="f.key"
          >{{ f.key }}</el-checkbox
        >
      </el-checkbox-group>
    </div>
    <div class="field-row field-row-wide">
      <span class="field-label">{{
        t("system.template.required_fields")
      }}</span>
      <el-checkbox-group v-model="session.setup.required">
        <el-checkbox
          v-for="f in session.base_fields.filter(x => x.key)"
          :key="f.key"
          :value="f.key"
          >{{ f.key }}</el-checkbox
        >
        <el-checkbox value="goal">goal</el-checkbox>
      </el-checkbox-group>
    </div>
  </div>
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

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
</style>
