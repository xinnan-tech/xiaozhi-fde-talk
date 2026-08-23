<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import packageInfo from "../../../package.json";

defineOptions({ name: "About" });

const { t } = useI18n();
const version = packageInfo.version;
const year = new Date().getFullYear();
const license = packageInfo.license;
const repository = packageInfo.repository?.url ?? packageInfo.homepage;

const dependencies = Object.entries(packageInfo.dependencies ?? {})
  .map(([name, version]) => ({ name, version }))
  .sort((a, b) => a.name.localeCompare(b.name));

const productIcon = useRenderIcon("tabler:info-circle-filled");
const versionIcon = useRenderIcon("tabler:tag");
const authorIcon = useRenderIcon("tabler:user-circle");
const licenseIcon = useRenderIcon("tabler:license");
const repoIcon = useRenderIcon("tabler:brand-github");
const stackIcon = useRenderIcon("tabler:stack-2");
const heartIcon = useRenderIcon("tabler:heart");
</script>

<template>
  <div class="about-page">
    <header class="about-header">
      <div class="header-left">
        <h1 class="header-title">{{ t("about.title") }}</h1>
        <p class="header-subtitle">{{ t("about.subtitle") }}</p>
      </div>
    </header>

    <section class="about-grid">
      <article class="info-card glass-card">
        <div class="card-title-row">
          <component :is="productIcon" class="card-icon" />
          <h2>{{ t("about.section_product") }}</h2>
          <span class="version-badge">
            <component :is="versionIcon" class="badge-icon" />
            v{{ version }}
          </span>
        </div>

        <p class="info-description">{{ t("about.description") }}</p>

        <div class="meta-list">
          <div class="meta-row">
            <span class="meta-label">
              <component :is="productIcon" class="meta-icon" />
              {{ t("about.product") }}
            </span>
            <span class="meta-value">{{ t("about.product_name") }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">
              <component :is="authorIcon" class="meta-icon" />
              {{ t("about.field_author") }}
            </span>
            <span class="meta-value">{{ t("about.product_name") }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">
              <component :is="licenseIcon" class="meta-icon" />
              {{ t("about.field_license") }}
            </span>
            <span class="meta-value">{{ license }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">
              <component :is="repoIcon" class="meta-icon" />
              {{ t("about.field_repo") }}
            </span>
            <a
              class="meta-value repo-link"
              :href="repository"
              target="_blank"
              rel="noopener"
            >
              {{ repository }}
            </a>
          </div>
          <div class="meta-row">
            <span class="meta-label">
              <component :is="heartIcon" class="meta-icon" />
              {{ t("about.copyright") }}
            </span>
            <span class="meta-value">
              ©{{ year }} {{ t("about.product_name") }}
            </span>
          </div>
        </div>
      </article>

      <article class="stack-card glass-card">
        <div class="card-title-row">
          <component :is="stackIcon" class="card-icon" />
          <h2>{{ t("about.section_stack") }}</h2>
          <span class="card-count">{{ dependencies.length }}</span>
        </div>
        <p class="stack-hint">{{ t("about.stack_hint") }}</p>
        <div class="deps-list">
          <div v-for="dep in dependencies" :key="dep.name" class="dep-row">
            <span class="dep-name">{{ dep.name }}</span>
            <span class="dep-version">{{ dep.version }}</span>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<style lang="scss" scoped>
.about-page {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 30px 8px 18px 16px;
}

.about-page {
  .about-header {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-end;
    justify-content: space-between;
    padding: 8px 16px 20px;
  }

  .header-left {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .header-title {
    margin: 0;
    font-size: 28px;
    font-weight: 600;
    color: #1a1a1a;
  }

  .header-subtitle {
    margin: 0;
    font-size: 14px;
    color: #666;
  }

  .about-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
    gap: 16px;
    padding: 0 8px 0 16px;
  }

  @container (width < 1100px) {
    .about-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .glass-card {
    background: rgb(255 255 255 / 68%);
    border: 1px solid rgb(255 255 255 / 72%);
    border-radius: 16px;
    box-shadow: 0 0 10px rgb(31 47 86 / 10%);
    backdrop-filter: blur(10px);
  }

  .info-card,
  .stack-card {
    display: flex;
    flex-direction: column;
    padding: 20px 22px 22px;
  }

  .card-title-row {
    display: flex;
    gap: 8px;
    align-items: center;
    color: #3988ee;

    h2 {
      margin: 0;
      font-size: 17px;
      font-weight: 600;
      color: #1a1a1a;
    }
  }

  .card-icon {
    width: 18px;
    height: 18px;
    color: #3988ee;
  }

  .card-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 26px;
    height: 20px;
    padding: 0 8px;
    font-size: 11px;
    font-weight: 700;
    color: #3988ee;
    background: rgb(74 144 226 / 12%);
    border-radius: 10px;
  }

  .version-badge {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    margin-left: auto;
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

  .info-description {
    margin: 14px 0 18px;
    font-size: 14px;
    line-height: 1.75;
    color: #475569;
  }

  .meta-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 0 0;
    border-top: 1px solid rgb(226 232 240 / 90%);
  }

  .meta-row {
    display: grid;
    grid-template-columns: 132px minmax(0, 1fr);
    gap: 12px;
    align-items: center;
    min-height: 38px;
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

  .repo-link {
    overflow: hidden;
    text-overflow: ellipsis;
    color: #3988ee;
    text-decoration: none;
    transition: color 0.2s ease;

    &:hover {
      color: #1f4ed8;
      text-decoration: underline;
    }
  }

  .stack-hint {
    margin: 12px 0 14px;
    font-size: 13px;
    line-height: 1.6;
    color: #64748b;
  }

  .deps-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px 18px;
  }

  @container (width < 700px) {
    .deps-list {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  .dep-row {
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
    min-height: 32px;
    padding: 4px 12px;
    font-size: 12px;
    background: rgb(241 245 249 / 70%);
    border: 1px solid rgb(226 232 240 / 70%);
    border-radius: 8px;
    transition:
      border-color 0.2s ease,
      background-color 0.2s ease;
  }

  .dep-row:hover {
    border-color: rgb(74 144 226 / 35%);
    background: rgb(239 246 255 / 80%);
  }

  .dep-name {
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
    color: #334155;
    white-space: nowrap;
  }

  .dep-version {
    flex-shrink: 0;
    font-family:
      ui-monospace,
      SFMono-Regular,
      Menlo,
      Monaco,
      Consolas,
      "Liberation Mono",
      "Courier New",
      monospace;
    font-size: 11px;
    color: #64748b;
  }
}
</style>