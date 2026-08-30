<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

/** AI 生成模式面板：受控（brief 由父级持有，切模式不丢）；生成动作与
 *  loading/错误处理都在父级（edit.vue）——本组件只管输入与示例。 */
defineProps<{
  modelValue: string;
  loading: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  generate: [];
}>();

const { t } = useI18n();

const examples = computed(() =>
  [1, 2, 3].map(n => t(`system.template.ai_example_${n}`))
);

const onInput = (value: string) => emit("update:modelValue", value);
</script>

<template>
  <div class="ai-gen" data-testid="ai-section">
    <h3 class="ai-title">{{ t("system.template.ai_title") }}</h3>
    <p class="ai-hint">{{ t("system.template.ai_hint") }}</p>
    <el-input
      :model-value="modelValue"
      type="textarea"
      :rows="5"
      maxlength="2000"
      show-word-limit
      resize="none"
      :placeholder="t('system.template.ai_placeholder')"
      data-testid="ai-brief"
      @update:model-value="onInput"
    />
    <div class="ai-examples">
      <span class="ai-examples-label">
        {{ t("system.template.ai_examples") }}
      </span>
      <div class="ai-example-chips">
        <button
          v-for="ex in examples"
          :key="ex"
          type="button"
          class="ai-example-chip"
          @click="onInput(ex)"
        >
          {{ ex }}
        </button>
      </div>
    </div>
    <div class="ai-actions">
      <el-button
        type="primary"
        size="large"
        :loading="loading"
        :disabled="!modelValue.trim()"
        data-testid="ai-generate"
        @click="emit('generate')"
      >
        {{
          loading
            ? t("system.template.ai_generate") + "…"
            : t("system.template.ai_generate")
        }}
      </el-button>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.ai-gen {
  display: grid;
  gap: 14px;
  justify-items: start;
  max-width: 640px;
  padding: 12px 4px;
}

.ai-title {
  margin: 0;
  color: #1a1a1a;
  font-size: 18px;
  font-weight: 600;
}

.ai-hint {
  margin: 0;
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
}

.ai-gen :deep(.el-textarea__inner) {
  font-size: 14px;
  line-height: 1.7;
}

.ai-examples {
  display: grid;
  gap: 6px;
  width: 100%;

  &-label {
    color: #98a2b3;
    font-size: 12px;
  }
}

.ai-example-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ai-example-chip {
  padding: 5px 12px;
  color: #3988ee;
  font-size: 13px;
  background: rgb(57 136 238 / 8%);
  border: 1px solid rgb(57 136 238 / 25%);
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s;

  &:hover {
    background: rgb(57 136 238 / 16%);
  }
}

.ai-actions {
  padding-top: 4px;
}
</style>
