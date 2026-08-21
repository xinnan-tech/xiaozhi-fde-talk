<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useNav } from "@/layout/hooks/useNav";
import { useDialogStoreHook } from "@/store/modules/dialog";
import botPng from "@/assets/images/bot.png";
import botSmilePng from "@/assets/images/bot-smile.png";

const { isCollapse } = useNav();
const { t } = useI18n();
const dialogStore = useDialogStoreHook();

const botCardRef = ref();
const isHovered = ref(false);

const handleCreateInterview = () => {
  dialogStore.openCreateInterview();
};

const handleMouseEnter = () => {
  isHovered.value = true;
};

const handleMouseLeave = () => {
  isHovered.value = false;
};
</script>

<template>
  <div
    class="sidebar-bot-card"
    :class="{ collapses: isCollapse }"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
  >
    <img
      v-if="!isCollapse"
      class="bot-avatar"
      :src="isHovered ? botSmilePng : botPng"
      alt="bot"
    />
    <el-tooltip
      v-else
      :content="t('sidebar.assistant.create')"
      placement="right"
      effect="light"
    >
      <img
        class="bot-avatar-small"
        :src="isHovered ? botSmilePng : botPng"
        alt="bot"
        @click.stop="handleCreateInterview"
      />
    </el-tooltip>
    <div class="bot-card-content">
      <div v-if="!isCollapse" class="bot-info">
        <div class="bot-name">{{ t("sidebar.assistant.name") }}</div>
        <div class="bot-status">{{ t("sidebar.assistant.status") }}</div>
        <div class="bot-features">
          <div class="bot-feature-item">
            {{ t("sidebar.assistant.feature_id") }}
          </div>
          <div class="bot-feature-item">
            {{ t("sidebar.assistant.feature_quick_create") }}
          </div>
          <div class="bot-feature-item">
            {{ t("sidebar.assistant.feature_prompt") }}
          </div>
          <div class="bot-feature-item">
            {{ t("sidebar.assistant.feature_report") }}
          </div>
        </div>
        <el-button
          class="create-btn"
          type="primary"
          @click.stop="handleCreateInterview"
        >
          {{ t("sidebar.assistant.create") }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.sidebar-bot-card {
  position: absolute;
  bottom: 44px;
  left: 50%;
  z-index: 10;
  width: 78%;
  padding: 20px 12px 12px;
  cursor: pointer;
  background: rgb(255 255 255 / 80%);
  border-radius: 16px;
  box-shadow: 0 4px 12px rgb(0 0 0 / 10%);
  backdrop-filter: blur(10px);
  transform: translateX(-50%);
  transition: all var(--pure-transition-duration);

  .bot-avatar {
    position: absolute;
    top: -80px;
    left: 50%;
    width: 120px;
    height: 120px;
    transform: translateX(-50%);
  }

  &:hover {
    background: rgb(255 255 255 / 95%);
    box-shadow: 0 6px 16px rgb(0 0 0 / 15%);
    transform: translateX(-50%) translateY(-2px);
  }

  &.collapses {
    bottom: 44px;
    left: 50%;
    width: 40px;
    padding: 6px 8px;
    transform: translateX(-50%);

    &:hover {
      transform: translateX(-50%) translateY(-2px);
    }
  }

  .bot-avatar-small {
    width: 28px;
    height: 28px;
    border-radius: 50%;
  }

  .bot-card-content {
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: center;

    .collapses & {
      justify-content: center;
    }
  }

  .bot-info {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: auto;
    text-align: center;

    .bot-name {
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 15px;
      font-weight: 600;
      color: #666;
      white-space: nowrap;
    }

    .bot-status {
      margin-top: 4px;
      font-size: 12px;
      color: #999;
    }

    .bot-features {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      align-self: center;
      width: max-content;
      max-width: 100%;
      padding: 0;
      margin-top: 8px;
      font-size: 12px;

      .bot-feature-item {
        display: flex;
        align-items: flex-start;
        width: max-content;
        max-width: 100%;
        margin-bottom: 2px;
        color: #999;
        text-align: left;
        white-space: nowrap;

        &::before {
          margin-right: 4px;
          color: #409eff;
          content: "•";
          text-align: center;
        }
      }
    }

    .create-btn {
      margin-top: 6px;
      height: 32px;
      border-radius: 8px;
    }
  }
}
</style>
