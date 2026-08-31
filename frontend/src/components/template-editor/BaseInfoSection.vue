<script setup lang="ts">
import { useI18n } from "vue-i18n";

defineOptions({ name: "TemplateEditorBaseInfo" });
const { t } = useI18n();
const tpl = defineModel<{
  id: string;
  name: string;
  icon_url: string;
  icon_alt: string;
}>({
  required: true
});
defineProps<{ idLocked: boolean }>();
</script>

<template>
  <div class="section-grid">
    <!-- 模板 ID + 名称同行显示：
         section-grid 是双列布局，但 ID 和 名称都是短文本，没必要各占一行浪费空间 -->
    <div class="base-info-row">
      <label class="field-row">
        <span class="field-label">
          {{ t("system.template.field_id") }}
          <span v-if="!idLocked" class="required-star">*</span>
        </span>
        <el-input v-model="tpl.id" :disabled="idLocked" class="field-input" />
      </label>
      <label class="field-row">
        <span class="field-label">
          {{ t("system.template.field_name") }}
          <span class="required-star">*</span>
        </span>
        <el-input v-model="tpl.name" class="field-input" />
      </label>
    </div>
    <label v-if="idLocked" class="field-row field-row-wide">
      <span class="field-label" />
      <span class="id-hint">{{ t("system.template.id_immutable") }}</span>
    </label>
    <!-- icon_url / icon_alt 不再开放编辑：字段保留在数据里随模板原样保存 -->
  </div>
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

.base-info-row {
  // 跨满 section-grid 的两列，把 ID 和 名称塞进同一行
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.id-hint {
  color: #98a2b3;
  font-size: 12px;
}
</style>
