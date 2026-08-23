<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import packageInfo from "../../../package.json";

defineOptions({ name: "About" });

const { t } = useI18n();
const version = packageInfo.version;
const year = new Date().getFullYear();
const productName = packageInfo.name;
const maintainer = "xinnan-tech";

const versionIcon = useRenderIcon("tabler:tag");
const authorIcon = useRenderIcon("tabler:user-circle");
const copyrightIcon = useRenderIcon("tabler:copyright");
</script>

<template>
  <div class="about-page">
    <header class="about-header">
      <h1 class="header-title">{{ t("about.title") }}</h1>
    </header>

    <article class="info-card glass-card">
      <div class="card-title-row">
        <h2 class="product-name">{{ productName }}</h2>
        <span class="version-badge">
          <component :is="versionIcon" class="badge-icon" />
          v{{ version }}
        </span>
      </div>

      <div class="meta-list">
        <div class="meta-row">
          <span class="meta-label">
            <component :is="authorIcon" class="meta-icon" />
            {{ t("about.maintainer") }}
          </span>
          <span class="meta-value">{{ maintainer }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">
            <component :is="copyrightIcon" class="meta-icon" />
            {{ t("about.copyright") }}
          </span>
          <span class="meta-value">©{{ year }} {{ maintainer }}</span>
        </div>
      </div>
    </article>
  </div>
</template>

<style lang="scss" scoped>
.about-page {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding: 38px 16px 18px;
}

.about-page {
  .about-header {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-end;
    justify-content: space-between;
    align-self: stretch;
    padding: 8px 16px 20px;
  }

  .header-title {
    margin: 0;
    font-size: 28px;
    font-weight: 600;
    color: #1a1a1a;
  }

  .glass-card {
    width: 100%;
    max-width: 640px;
    padding: 22px 26px 24px;
    background: rgb(255 255 255 / 68%);
    border: 1px solid rgb(255 255 255 / 72%);
    border-radius: 16px;
    box-shadow: 0 0 10px rgb(31 47 86 / 10%);
    backdrop-filter: blur(10px);
  }

  .card-title-row {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 18px;
    border-bottom: 1px solid rgb(226 232 240 / 80%);
  }

  .product-name {
    margin: 0;
    overflow: hidden;
    font-size: 20px;
    font-weight: 600;
    color: #1a1a1a;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .version-badge {
    display: inline-flex;
    flex-shrink: 0;
    gap: 5px;
    align-items: center;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
    color: #0f9d63;
    background: rgb(16 185 129 / 14%);
    border-radius: 999px;
  }

  .badge-icon {
    width: 13px;
    height: 13px;
  }

  .meta-list {
    display: flex;
    flex-direction: column;
    padding-top: 4px;
  }

  .meta-row {
    display: grid;
    grid-template-columns: 132px minmax(0, 1fr);
    gap: 12px;
    align-items: center;
    min-height: 44px;
    padding: 6px 0;
    border-bottom: 1px dashed rgb(226 232 240 / 72%);

    &:last-child {
      border-bottom: 0;
    }
  }

  .meta-label {
    display: inline-flex;
    gap: 7px;
    align-items: center;
    font-size: 13px;
    color: #64748b;
  }

  .meta-icon {
    width: 14px;
    height: 14px;
    color: #94a3b8;
  }

  .meta-value {
    overflow-wrap: anywhere;
    font-size: 13px;
    font-weight: 500;
    color: #334155;
  }
}
</style>