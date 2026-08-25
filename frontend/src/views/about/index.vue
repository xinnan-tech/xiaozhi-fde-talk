<script setup lang="ts">
import { computed, onBeforeMount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import packageInfo from "../../../package.json";
import { getBackendVersion } from "@/api/version";

defineOptions({ name: "About" });

const { t } = useI18n();
const version = packageInfo.version;
// 后端版本号：未拉到（请求中 / 失败 / 未登录）时为 null —— about 页降级为
// 只显示前端版本，不向公网探测者暴露后端版本号。
const backendVersion = ref<string | null>(null);
// 仅当后端版本号拿到且与前端不同 → 显示两行；否则（一行 / 一致 / 仅前端）→ 单行
const hasBothVersions = computed(
  () => backendVersion.value !== null && backendVersion.value !== version,
);
const year = new Date().getFullYear();
const productName = t("about.product_name");
const productSummary = t("about.summary");
const maintainer = "xinnan-tech";
const license = "Apache License 2.0";
const repository = "https://github.com/xinnan-tech/xiaozhi-fde-talk";

const versionIcon = useRenderIcon("tabler:info-circle-filled");
const licenseIcon = useRenderIcon("tabler:clipboard-text");
const maintainerIcon = useRenderIcon("tabler:user");
const copyrightIcon = useRenderIcon("tabler:lock");
const repoIcon = useRenderIcon("tabler:link");
const docIcon = useRenderIcon("tabler:file-text");

onBeforeMount(async () => {
  try {
    const res = await getBackendVersion();
    backendVersion.value = res.version;
  } catch {
    // 401（未登录）/ 网络错：保持 null —— 模板降级为单行
  }
});
</script>

<template>
  <div class="about">
    <header class="about-header">
      <div class="header-left">
        <h1 class="header-title">{{ productName }}</h1>
        <p class="header-subtitle">{{ productSummary }}</p>
      </div>
    </header>

    <div class="status-bar">
      <div class="status-card">
        <div
          class="status-icon-box"
          :style="{ background: 'rgba(16, 185, 129, 0.15)' }"
        >
          <component
            :is="versionIcon"
            class="status-icon"
            :style="{ color: '#0f9d63' }"
          />
        </div>
        <div class="status-info">
          <template v-if="hasBothVersions">
            <div class="status-title">{{ t("about.version_frontend") }}</div>
            <div class="status-value">v{{ version }}</div>
            <div class="status-title status-title-secondary">
              {{ t("about.version_backend") }}
            </div>
            <div class="status-value">v{{ backendVersion }}</div>
          </template>
          <template v-else>
            <div class="status-title">{{ t("about.version") }}</div>
            <div class="status-value">v{{ version }}</div>
          </template>
        </div>
      </div>

      <div class="status-card">
        <div
          class="status-icon-box"
          :style="{ background: 'rgba(74, 144, 226, 0.15)' }"
        >
          <component
            :is="licenseIcon"
            class="status-icon"
            :style="{ color: '#409eff' }"
          />
        </div>
        <div class="status-info">
          <div class="status-title">{{ t("about.license") }}</div>
          <div class="status-value">{{ license }}</div>
        </div>
      </div>

      <div class="status-card">
        <div
          class="status-icon-box"
          :style="{ background: 'rgba(114, 46, 209, 0.15)' }"
        >
          <component
            :is="maintainerIcon"
            class="status-icon"
            :style="{ color: '#722ed1' }"
          />
        </div>
        <div class="status-info">
          <div class="status-title">{{ t("about.maintainer") }}</div>
          <div class="status-value">{{ maintainer }}</div>
        </div>
      </div>
    </div>

    <article class="info-card glass-card">
      <div class="card-title-row">
        <h2 class="card-title">{{ t("about.copyright") }}</h2>
      </div>

      <div class="card-body">
        <div class="card-column">
          <div class="column-row">
            <component :is="copyrightIcon" class="row-icon" />
            <span class="row-label">{{ t("about.rights") }}</span>
          </div>
          <div class="column-row">
            <span class="row-value">©{{ year }} {{ maintainer }}</span>
          </div>
        </div>

        <div class="card-column">
          <div class="column-row">
            <component :is="repoIcon" class="row-icon" />
            <span class="row-label">{{ t("about.repository") }}</span>
          </div>
          <div class="column-row">
            <a
              class="row-value repo-link"
              :href="repository"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ repository }}
            </a>
          </div>
        </div>

        <div class="card-column">
          <div class="column-row">
            <component :is="docIcon" class="row-icon" />
            <span class="row-label">{{ t("about.license_detail") }}</span>
          </div>
          <div class="column-row">
            <span class="row-value">{{ t("about.license_full") }}</span>
          </div>
        </div>
      </div>
    </article>
  </div>
</template>

<style lang="scss" scoped>
.about {
  box-sizing: border-box;
  max-width: 100%;
  padding: 30px 16px 6px 16px;

  /* 以内容区实际宽度作为自适应基准，自动兼容侧边栏展开/折叠 */
  container-type: inline-size;
  overflow-x: hidden;

  .about-header {
    display: flex;
    flex-wrap: wrap;
    gap: 28px;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px 20px;
    background: transparent;
  }

  .header-left {
    display: flex;
    flex-shrink: 0;
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

  /* 顶部状态条：与 home 页 status-bar 完全一致 */
  .status-bar {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }

  @container (width < 950px) {
    .status-bar {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  @container (width < 640px) {
    .status-bar {
      grid-template-columns: 1fr;
    }
  }

  .status-card {
    display: flex;
    gap: 20px;
    align-items: center;
    padding: 16px;
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 16px;
    box-shadow: 0 4px 20px rgb(0 0 0 / 8%);
    backdrop-filter: blur(4px);
  }

  .status-icon-box {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border-radius: 10px;
    box-shadow: 0 2px 8px rgb(0 0 0 / 10%);
  }

  .status-icon {
    width: 22px;
    height: 22px;
  }

  .status-info {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .status-title {
    font-size: 13px;
    color: #666;
  }

  /* 两行布局下，第一行与值紧贴、第二行拉开间距，避免两段版本堆在一起 */
  .status-title-secondary {
    margin-top: 4px;
  }

  .status-value {
    min-width: 0;
    overflow: hidden;
    font-size: 16px;
    font-weight: 600;
    color: #1a1a1a;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* 版权 / 仓库 / 协议 详情卡：与 home 的 glass-card 同款 */
  .glass-card {
    margin-top: 20px;
    width: 100%;
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
    padding-bottom: 16px;
    margin-bottom: 12px;
    border-bottom: 1px solid rgb(226 232 240 / 80%);
  }

  .card-title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: #1a1a1a;
  }

  .card-body {
    box-sizing: border-box;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0;
    padding: 4px 0;
  }

  @container (width < 950px) {
    .card-body {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      row-gap: 16px;
    }
  }

  @container (width < 640px) {
    .card-body {
      grid-template-columns: 1fr;
      row-gap: 16px;
    }
  }

  .card-column {
    position: relative;
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
    padding: 0 12px;
  }

  .card-column:first-child {
    padding-left: 0;
  }

  .card-column:last-child {
    padding-right: 0;
  }

  .card-column:not(:last-child)::after {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: 1px;
    content: "";
    background: rgb(0 0 0 / 10%);
  }

  @container (width < 950px) {
    .card-column:not(:last-child)::after {
      content: none;
    }
  }

  .column-row {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 13px;
  }

  .row-icon {
    flex-shrink: 0;
    width: 14px;
    height: 14px;
    color: #94a3b8;
  }

  .row-label {
    flex-shrink: 0;
    color: #999;
    white-space: nowrap;
  }

  .row-value {
    min-width: 0;
    overflow: hidden;
    font-weight: 500;
    color: #333;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .repo-link {
    color: #409eff;
    text-decoration: none;
    transition: color 0.2s;
  }

  .repo-link:hover {
    color: #1d7adb;
    text-decoration: underline;
  }
}
</style>