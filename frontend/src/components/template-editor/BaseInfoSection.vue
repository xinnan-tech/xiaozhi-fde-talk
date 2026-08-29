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
    <label class="field-row">
      <span class="field-label">{{ t("system.template.field_id") }}</span>
      <el-input v-model="tpl.id" :disabled="idLocked" class="field-input" />
    </label>
    <label v-if="idLocked" class="field-row">
      <span class="field-label" />
      <span class="id-hint">{{ t("system.template.id_immutable") }}</span>
    </label>
    <label class="field-row">
      <span class="field-label">{{ t("system.template.field_name") }}</span>
      <el-input v-model="tpl.name" class="field-input" />
    </label>
    <label class="field-row">
      <span class="field-label">{{ t("system.template.field_icon_url") }}</span>
      <el-input
        v-model="tpl.icon_url"
        class="field-input"
        placeholder="https://..."
      />
    </label>
    <label class="field-row">
      <span class="field-label">{{ t("system.template.field_icon_alt") }}</span>
      <el-input v-model="tpl.icon_alt" class="field-input" placeholder="📋" />
    </label>
  </div>
</template>

<style lang="scss" scoped>
@use "./sections.scss" as *;

.id-hint {
  color: #98a2b3;
  font-size: 12px;
}
</style>
