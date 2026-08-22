<script setup lang="ts">
import { getTopMenu } from "@/router/utils";
import { useNav } from "@/layout/hooks/useNav";
import { useI18n } from "vue-i18n";

defineProps({
  collapse: Boolean
});

const { title, getLogo } = useNav();
const { t } = useI18n();
</script>

<template>
  <div class="sidebar-logo-container" :class="{ collapses: collapse }">
    <transition name="sidebarLogoFade">
      <router-link
        v-if="collapse"
        key="collapse"
        :title="title"
        class="sidebar-logo-link"
        :to="getTopMenu()?.path ?? '/'"
      >
        <img :src="getLogo()" alt="logo" />
      </router-link>
      <router-link
        v-else
        key="expand"
        :title="title"
        class="sidebar-logo-link"
        :to="getTopMenu()?.path ?? '/'"
      >
        <img :src="getLogo()" alt="logo" />
        <span class="sidebar-title">{{ t("sidebar.logo.title") }}</span>
      </router-link>
    </transition>
  </div>
</template>

<style lang="scss" scoped>
.sidebar-logo-container {
  position: relative;
  width: 100%;
  height: 64px;
  overflow: hidden;

  .sidebar-logo-link {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    width: 100%;
    height: 100%;
    padding: 0 18px 0 20px;
    box-sizing: border-box;
    gap: 6px;

    img {
      display: inline-block;
      width: 40px;
      height: 40px;
      flex: 0 0 auto;
    }

    .sidebar-title {
      display: inline-block;
      min-width: 0;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 19px;
      font-weight: 600;
      line-height: 1.2;
      color: var(--pure-theme-sub-menu-active-text);
      white-space: nowrap;
    }
  }

  &.collapses {
    .sidebar-logo-link {
      justify-content: center;
      padding: 0;
      gap: 0;
    }

    img {
      width: 36px;
      height: 36px;
    }
  }
}
</style>
