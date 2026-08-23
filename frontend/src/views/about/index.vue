<script setup lang="ts">
import { useI18n } from "vue-i18n";
import packageInfo from "../../../package.json";

defineOptions({ name: "About" });

const { t } = useI18n();
const version = packageInfo.version;
const year = new Date().getFullYear();
</script>

<template>
  <div class="about-page">
    <el-card class="about-card" shadow="never">
      <template #header>
        <div class="about-header">
          <span class="about-title">{{ t("about.title") }}</span>
          <span class="about-version">v{{ version }}</span>
        </div>
      </template>

      <el-descriptions :column="1" border>
        <el-descriptions-item :label="t('about.product')">
          {{ t("about.product_name") }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('about.version')">
          v{{ version }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('about.copyright')">
          ©{{ year }} {{ t("about.product_name") }}
        </el-descriptions-item>
      </el-descriptions>

      <p class="about-desc">{{ t("about.description") }}</p>
    </el-card>
  </div>
</template>

<style lang="scss" scoped>
.about-page {
  display: flex;
  justify-content: center;
  padding: 24px;
}

.about-card {
  width: 100%;
  max-width: 640px;
}

.about-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.about-title {
  font-size: 16px;
  font-weight: 600;
}

.about-version {
  color: rgba(0, 0, 0, 0.45);
  font-size: 12px;
}

.about-desc {
  margin-top: 16px;
  color: rgba(0, 0, 0, 0.65);
  line-height: 1.6;
  font-size: 13px;
}
</style>