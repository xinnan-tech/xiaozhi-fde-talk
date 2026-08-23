<script setup lang="ts">
import { useDebounceFn } from "@vueuse/core";
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useUserStoreHook } from "@/store/modules/user";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { useInterviewStoreHook } from "@/store/modules/interview";
import ReSegmented from "@/components/ReSegmented";
import ChangePasswordDialog from "@/components/auth/ChangePasswordDialog.vue";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import { isSupportedLocale, setLocale, type SupportedLocale } from "@/i18n";
import {
  type InterviewItem,
  type InterviewListType,
  getStatisticsApi,
  getInterviewsApi
} from "@/api/interview";

defineOptions({
  name: "Home"
});

const router = useRouter();
const { locale, t } = useI18n();
const userStore = useUserStoreHook();
const dialogStore = useDialogStoreHook();
const interviewStore = useInterviewStoreHook();
const { interviewCreated } = storeToRefs(interviewStore);

const searchIcon = useRenderIcon("tabler:search");
const clearIcon = useRenderIcon("tabler:x");
const plusIcon = useRenderIcon("tabler:plus");
const chatbotIcon = useRenderIcon("tabler:message-chatbot-filled");
const checkIcon = useRenderIcon("tabler:circle-check-filled");
const bellIcon = useRenderIcon("majesticons:bell");
const folderIcon = useRenderIcon("tabler:folder-open-filled");
const clockIcon = useRenderIcon("tabler:clock");
const checkboxIcon = useRenderIcon("tabler:checkbox");
const messageIcon = useRenderIcon("tabler:message");
const businessmanIcon = useRenderIcon("flat-color-icons:businessman");
const noteIcon = useRenderIcon("majesticons:note-text");
const languageIcon = useRenderIcon("flowbite:language-outline");
const keyIcon = useRenderIcon("tabler:key");
const logoutIcon = useRenderIcon("tabler:logout");

const localeOptions: Array<{ value: SupportedLocale; label: string }> = [
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁體中文" },
  { value: "en-US", label: "English" },
  { value: "vi-VN", label: "Tiếng Việt" }
];

const statisticsLoading = ref(false);
const listLoading = ref(false);
const searchKeyword = ref("");
const debouncedSearchKeyword = ref("");
const tabValue = ref(0);
const tabOptions = computed(() => [
  { label: t("home.tab.all"), value: "all" },
  { label: t("home.tab.created"), value: "created" },
  { label: t("home.tab.in_progress"), value: "in_progress" },
  { label: t("home.tab.suspended"), value: "suspended" },
  { label: t("home.tab.ended"), value: "ended" }
]);
const interviewStatusLabels: Record<string, string> = {
  created: "home.status.created",
  in_progress: "home.status.in_progress",
  suspended: "home.status.suspended",
  ended: "home.status.ended"
};
const statusList = ref([
  {
    key: "in_progress",
    titleKey: "home.stats.in_progress",
    count: 0,
    unitKey: "home.stats.interview_unit",
    color: "#409eff",
    bgColor: "rgba(74, 144, 226, 0.15)",
    icon: chatbotIcon
  },
  {
    key: "week_finish",
    titleKey: "home.stats.week_finish",
    count: 0,
    unitKey: "home.stats.interview_unit",
    color: "#52c41a",
    bgColor: "rgba(82, 196, 26, 0.15)",
    icon: checkIcon
  },
  {
    key: "assist_discovery",
    titleKey: "home.stats.assist_discovery",
    count: 0,
    unitKey: "home.stats.question_unit",
    color: "#faad14",
    bgColor: "rgba(250, 173, 20, 0.15)",
    icon: bellIcon
  },
  {
    key: "interview_coverage",
    titleKey: "home.stats.interview_coverage",
    count: 0,
    unitKey: "home.stats.interview_unit",
    color: "#722ed1",
    bgColor: "rgba(114, 46, 209, 0.15)",
    icon: folderIcon
  }
]);
const interviewList = ref<InterviewItem[]>([]);

/** 是否已登录 */
const isLoggedIn = computed(() => Boolean(userStore.accessToken));

const filteredInterviewList = computed(() => {
  const keyword = debouncedSearchKeyword.value.trim().toLowerCase();
  const selectedStatus = tabOptions.value[tabValue.value].value;

  return interviewList.value.filter(item => {
    const matchTab = selectedStatus === "all" || item.status === selectedStatus;

    if (!matchTab) {
      return false;
    }

    if (!keyword) {
      return true;
    }

    return item.base_info?.title?.toLowerCase().includes(keyword);
  });
});

const updateSearchKeyword = useDebounceFn((keyword: string) => {
  debouncedSearchKeyword.value = keyword;
}, 300);

const handleSearchInput = (event: Event) => {
  searchKeyword.value = (event.target as HTMLInputElement).value;
  updateSearchKeyword(searchKeyword.value);
};

const clearSearch = () => {
  updateSearchKeyword.cancel();
  searchKeyword.value = "";
  debouncedSearchKeyword.value = "";
};

const handleLocaleChange = async (value: string | number | object) => {
  const nextLocale = String(value);
  if (!isSupportedLocale(nextLocale) || locale.value === nextLocale) return;

  setLocale(nextLocale);
  if (isLoggedIn.value) await getInterviewList();
};

const openCreateDialog = () => {
  dialogStore.openCreateInterview();
};

const openInterviewPage = (item: (typeof interviewList.value)[number]) => {
  router.push({
    path:
      item.status !== "ended" ? `/interview/${item.id}` : `/report/${item.id}`
  });
};

/** 格式化最近时间 */
const formatRecentTime = (value: string | null) => {
  if (!value) return "--";

  // 未携带时区后缀的 UTC ISO 字符串
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const timestamp = new Date(hasTimezone ? value : `${value}Z`).getTime();
  if (Number.isNaN(timestamp)) return "--";

  const diff = Math.max(0, Date.now() - timestamp);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diff < minute) return t("home.time.just_now");
  if (diff < hour) {
    return t("home.time.minutes_ago", { count: Math.floor(diff / minute) });
  }
  if (diff < day) {
    return t("home.time.hours_ago", { count: Math.floor(diff / hour) });
  }
  if (diff < 30 * day) {
    return t("home.time.days_ago", { count: Math.floor(diff / day) });
  }

  return new Intl.DateTimeFormat(locale.value, {
    year: "numeric",
    month: "numeric",
    day: "numeric"
  }).format(timestamp);
};

const clickUserAvatar = () => {
  if (!isLoggedIn.value) {
    dialogStore.openLogin();
  }
};

// 头像菜单（登录后）：改密 + 登出
const changePwdVisible = ref(false);

const handleAvatarCommand = (command: string) => {
  if (command === "change_password") {
    changePwdVisible.value = true;
  } else if (command === "logout") {
    logOut();
    ElMessage.success(t("home.logout_success"));
  }
};

const logOut = () => {
  userStore.logOut();
  statusList.value.forEach(item => {
    item.count = 0;
  });
  interviewList.value = [];
};

/** 获取访谈统计 */
const getStatistics = async () => {
  statisticsLoading.value = true;
  try {
    const statistics = await getStatisticsApi();
    if (!statistics) return;
    statusList.value.forEach(item => {
      if (statistics[item.key]) {
        item.count = statistics[item.key];
      }
    });
  } catch {
    statusList.value.forEach(item => {
      item.count = 0;
    });
  } finally {
    statisticsLoading.value = false;
  }
};

/** 获取访谈列表 */
const getInterviewList = async () => {
  listLoading.value = true;
  try {
    const res: InterviewListType = await getInterviewsApi();
    interviewList.value = res.items.map(item => ({
      ...item,
      icon: noteIcon
    }));
  } catch {
    interviewList.value = [];
  } finally {
    listLoading.value = false;
  }
};

const refreshAfterCreate = async () => {
  if (!isLoggedIn.value) return;
  await Promise.all([getStatistics(), getInterviewList()]);
};

watch(interviewCreated, async created => {
  if (created > 0) await refreshAfterCreate();
});

watch(
  isLoggedIn,
  async (loggedIn: boolean) => {
    if (!loggedIn) {
      logOut();
      return;
    }
    await Promise.all([getStatistics(), getInterviewList()]);
  },
  { immediate: true }
);
</script>

<template>
  <div class="home">
    <header class="home-header">
      <div class="header-left">
        <h1 class="header-title">{{ $t("home.title") }}</h1>
        <p class="header-subtitle">{{ $t("home.subtitle") }}</p>
      </div>
      <div class="header-right">
        <div class="search-box">
          <input
            :value="searchKeyword"
            type="text"
            class="search-input"
            :placeholder="$t('home.search_placeholder')"
            autocomplete="off"
            @input="handleSearchInput"
          />
          <button
            v-if="searchKeyword"
            type="button"
            class="clear-search-btn"
            :aria-label="$t('home.clear_search')"
            :title="$t('home.clear_search')"
            @click="clearSearch"
          >
            <component :is="clearIcon" />
          </button>
          <component :is="searchIcon" class="search-icon" />
        </div>
        <el-button
          class="create-btn"
          type="primary"
          :icon="plusIcon"
          @click="openCreateDialog"
        >
          {{ $t("home.create_interview") }}
        </el-button>
        <div
          v-if="!isLoggedIn"
          class="user-avatar w-10 h-10 rounded-full flex items-center justify-center"
          @click="clickUserAvatar"
        >
          <component :is="businessmanIcon" class="w-8 h-8" />
        </div>
        <el-dropdown
          v-else
          trigger="click"
          placement="bottom-end"
          class="user-avatar-dropdown"
          @command="handleAvatarCommand"
        >
          <div
            class="user-avatar w-10 h-10 rounded-full flex items-center justify-center online"
          >
            <component :is="businessmanIcon" class="w-8 h-8" />
          </div>
          <template #dropdown>
            <el-dropdown-menu class="user-menu">
              <el-dropdown-item command="change_password" :icon="keyIcon">
                {{ t("auth.change_password") }}
              </el-dropdown-item>
              <el-dropdown-item command="logout" :icon="logoutIcon" divided>
                {{ t("home.logout") }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-dropdown
          class="locale-dropdown"
          trigger="hover"
          placement="bottom-end"
          @command="handleLocaleChange"
        >
          <button
            type="button"
            class="locale-trigger"
            :aria-label="$t('home.switch_language')"
            :title="$t('home.switch_language')"
          >
            <component :is="languageIcon" class="locale-icon" />
          </button>
          <template #dropdown>
            <el-dropdown-menu class="locale-menu">
              <el-dropdown-item
                v-for="item in localeOptions"
                :key="item.value"
                :command="item.value"
                :class="{ 'is-active': locale === item.value }"
              >
                <span>{{ item.label }}</span>
                <span v-if="locale === item.value" class="locale-check">✓</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="status-bar">
      <div v-for="item in statusList" :key="item.key" class="status-card">
        <div class="status-icon-box" :style="{ background: item.bgColor }">
          <component
            :is="item.icon"
            class="status-icon"
            :style="{ color: item.color }"
          />
        </div>
        <el-skeleton :loading="statisticsLoading" animated>
          <template #template>
            <div>
              <el-skeleton-item style="width: 40px; height: 20px" />
            </div>
            <div>
              <el-skeleton-item style="width: 60px; height: 20px" />
            </div>
          </template>
          <template #default>
            <div class="status-info">
              <div class="status-title">{{ $t(item.titleKey) }}</div>
              <div class="flex items-baseline">
                <div class="mr-1 text-[22px] text-[#1a1a1a] font-semibold">
                  {{ item.count }}
                </div>
                <div class="text-[12px] text-[#999]">
                  {{ $t(item.unitKey) }}
                </div>
              </div>
            </div>
          </template>
        </el-skeleton>
      </div>
    </div>

    <div class="tab-bar">
      <ReSegmented v-model="tabValue" :options="tabOptions" />
    </div>

    <div class="">
      <el-skeleton
        class="interview-list"
        :loading="listLoading"
        :count="2"
        animated
      >
        <template #template>
          <div
            class="interview-card"
            style="background-color: rgba(255, 255, 255, 0.6)"
          >
            <div class="flex gap-4 justify-between">
              <div class="flex-1">
                <el-skeleton-item
                  style="width: 44px; height: 44px; border-radius: 12px"
                />
                <el-skeleton-item
                  style="
                    margin: 6px 0 0 20px;
                    width: 60%;
                    height: 24px;
                    vertical-align: top;
                  "
                />
              </div>
              <el-skeleton-item
                style="
                  margin-top: 4px;
                  width: 50px;
                  height: 28px;
                  border-radius: 20px;
                  vertical-align: top;
                "
              />
            </div>
            <div class="card-body">
              <div>
                <div>
                  <el-skeleton-item style="width: 60px; height: 22px" />
                </div>
                <div>
                  <el-skeleton-item style="width: 40px; height: 22px" />
                </div>
              </div>
              <div>
                <div>
                  <el-skeleton-item style="width: 60px; height: 22px" />
                </div>
                <div>
                  <el-skeleton-item style="width: 40px; height: 22px" />
                </div>
              </div>
              <div>
                <div>
                  <el-skeleton-item style="width: 60px; height: 22px" />
                </div>
                <div>
                  <el-skeleton-item style="width: 40px; height: 22px" />
                </div>
              </div>
            </div>
            <div>
              <el-skeleton-item style="width: 100%; height: 28px" />
            </div>
          </div>
        </template>
        <template #default>
          <div class="interview-list">
            <div
              v-for="item in filteredInterviewList"
              :key="item.id"
              class="interview-card"
              role="button"
              tabindex="0"
              @click="openInterviewPage(item)"
            >
              <div class="card-header">
                <div class="card-icon-box">
                  <component :is="item.icon" class="card-icon" />
                </div>
                <h3 class="card-title">
                  {{ item.base_info?.title || "--" }}
                </h3>
                <div class="card-status" :class="`status-${item.status}`">
                  <span class="status-text">
                    {{ $t(interviewStatusLabels[item.status] ?? item.status) }}
                  </span>
                </div>
              </div>
              <div class="card-body">
                <div class="card-column">
                  <div class="column-row">
                    <span class="row-label">{{
                      $t("home.field.interviewee")
                    }}</span>
                  </div>
                  <div class="column-row">
                    <span class="row-value">{{
                      item.interviewee || "--"
                    }}</span>
                  </div>
                </div>
                <div class="card-column">
                  <div class="column-row">
                    <span class="row-label">{{ $t("home.field.type") }}</span>
                  </div>
                  <div class="column-row">
                    <span class="row-value">{{ item.type || "--" }}</span>
                  </div>
                </div>
                <div class="card-column">
                  <div class="column-row">
                    <span class="row-label">{{ $t("home.field.recent") }}</span>
                  </div>
                  <div class="column-row">
                    <span class="row-value">{{
                      formatRecentTime(item.recent_time)
                    }}</span>
                  </div>
                </div>
              </div>
              <div class="card-footer">
                <div class="footer-pill">
                  <div class="pill-column">
                    <component
                      :is="clockIcon"
                      class="pill-icon text-[#409eff]"
                    />
                    <span class="pill-text">{{
                      $t("home.metric.pending")
                    }}</span>
                    <span class="pill-count">{{ item.pending_count }}</span>
                  </div>
                  <div class="pill-column">
                    <component
                      :is="checkboxIcon"
                      class="pill-icon text-[#52c41a]"
                    />
                    <span class="pill-text">{{
                      $t("home.metric.covered")
                    }}</span>
                    <span class="pill-count">{{ item.covered_count }}</span>
                  </div>
                  <div class="pill-column">
                    <component
                      :is="messageIcon"
                      class="pill-icon text-[#409eff]"
                    />
                    <span class="pill-text">{{ $t("home.metric.asked") }}</span>
                    <span class="pill-count">{{ item.asked_count }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </el-skeleton>
    </div>

    <ChangePasswordDialog v-model="changePwdVisible" />
  </div>
</template>

<style lang="scss" scoped>
.home {
  box-sizing: border-box;
  max-width: 100%;
  padding: 30px 16px 6px 16px;

  /* 以内容区实际宽度作为自适应基准，自动兼容侧边栏展开/折叠 */
  container-type: inline-size;
  overflow-x: hidden;

  .home-header {
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

  .header-right {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }

  .search-box {
    position: relative;
    display: flex;
    align-items: center;
  }

  .search-input {
    box-sizing: border-box;
    width: 200px;
    max-width: 100%;
    height: 40px;
    padding: 0 64px 0 16px;
    font-size: 14px;
    outline: none;
    border: none;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
    transition: box-shadow 0.2s;
  }

  .search-input:focus {
    box-shadow: 0 4px 12px rgb(74 144 226 / 20%);
  }

  .search-input::placeholder {
    color: #999;
  }

  .search-icon {
    position: absolute;
    right: 12px;
    width: 18px;
    height: 18px;
    color: #999;
    pointer-events: none;
  }

  .clear-search-btn {
    position: absolute;
    right: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    color: #999;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 4px;
  }

  .clear-search-btn:hover {
    color: #666;
    background: rgb(0 0 0 / 6%);
  }

  .clear-search-btn :deep(svg) {
    width: 16px;
    height: 16px;
  }

  .create-btn {
    height: 40px;
    border-radius: 8px;
  }

  .status-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
  }

  .user-avatar {
    position: relative;
    border: 1px solid #fff;
    background-color: rgba(255, 255, 255, 0.6);
    // box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    cursor: pointer;

    &::after {
      content: "";
      position: absolute;
      right: -1px;
      bottom: -1px;
      border: 1px solid #fff;
      border-radius: 50%;
      width: 11px;
      height: 11px;
      background-color: #ccc;
    }

    &.online::after {
      background-color: #52c41a;
    }

    &:hover {
      box-shadow: 0 0 8px rgba(0, 0, 0, 0.08);
    }
  }

  /* 头像被 el-dropdown trigger 包裹后，点击区域需要直传；原 w-10 h-10 圆环保持。 */
  .user-avatar-dropdown {
    display: inline-flex;
  }

  :deep(.user-menu) {
    min-width: 152px;
    padding: 6px;
    border-radius: 8px;
  }

  :deep(.user-menu .el-dropdown-menu__item) {
    display: flex;
    align-items: center;
    gap: 8px;
    border-radius: 6px;
  }

  .locale-dropdown {
    display: inline-flex;
    align-items: center;
  }

  .locale-trigger {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    padding: 0;
    color: #666;
    background: transparent;
    border: 0;
    cursor: pointer;
    outline: none;
    transition:
      box-shadow 0.2s,
      color 0.2s,
      background-color 0.2s;

    &:hover,
    &:focus-visible {
      color: #409eff;
    }
  }

  .locale-icon {
    width: 22px;
    height: 22px;
  }

  :deep(.locale-menu) {
    min-width: 132px;
    padding: 6px;
    border-radius: 8px;
  }

  :deep(.locale-menu .el-dropdown-menu__item) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding-right: 12px;
    border-radius: 6px;
  }

  :deep(.locale-menu .el-dropdown-menu__item.is-active) {
    color: var(--el-color-primary);
    background-color: var(--el-color-primary-light-9);
  }

  .locale-check {
    font-size: 14px;
    font-weight: 600;
  }

  /* 与 .interview-list 使用同一套内容区断点，保持重排一致 */
  @container (width < 1250px) {
    .status-bar {
      grid-template-columns: repeat(4, 1fr);
    }
  }

  @container (width < 950px) {
    .status-bar {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  @container (width < 460px) {
    .status-card {
      .status-icon-box {
        display: none;
      }
    }
  }

  /* @container (width < 640px) {
  .status-bar {
    grid-template-columns: 1fr;
  }
} */

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
    gap: 1px;
  }

  .status-title {
    font-size: 13px;
    color: #666;
  }

  .tab-bar {
    padding: 20px 0;
  }

  .tab-bar :deep(.pure-segmented) {
    position: relative;
    padding: 4px;
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 22px;
    box-shadow: 0 4px 20px rgb(0 0 0 / 8%);
    backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
  }

  .tab-bar :deep(.pure-segmented-item) {
    border-radius: 18px;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .tab-bar :deep(.pure-segmented-item > div) {
    min-height: 34px;
    padding: 0 20px;
    font-size: 14px;
    font-weight: 500;
    line-height: 34px;
    color: rgb(31 35 41 / 60%);
    transition: color 0.25s;
  }

  .tab-bar :deep(.pure-segmented-item:hover) {
    background: rgb(255 255 255 / 35%);
    border-radius: 18px;
  }

  .tab-bar :deep(.pure-segmented-item:hover > div) {
    color: rgb(31 35 41 / 85%);
  }

  .tab-bar :deep(.pure-segmented-item-selected > div) {
    color: rgb(31 35 41 / 95%);
  }

  .tab-bar :deep(.pure-segmented-item-selected) {
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 18px;
    box-shadow:
      0 2px 6px rgb(31 35 41 / 8%),
      0 4px 12px rgb(31 35 41 / 6%);
    backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
  }

  .tab-bar :deep(.pure-segmented-group) {
    gap: 6px;
  }

  .interview-list {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }

  /* 以内容区实际宽度为准（自动适配侧边栏展开/折叠），而非视口宽度 */
  @container (width < 1250px) {
    .interview-list {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }

  @container (width < 950px) {
    .interview-list {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @container (width < 640px) {
    .interview-list {
      grid-template-columns: 1fr;
    }
  }

  .interview-card {
    box-sizing: border-box;
    min-width: 0;
    padding: 16px;
    background: transparent;
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 16px;
    box-shadow: 0 0 10px rgb(0 0 0 / 8%);
    backdrop-filter: blur(4px);
    backdrop-filter: blur(4px);
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    cursor: pointer;
    outline: none;
  }

  .interview-card:hover {
    border-color: rgb(255 255 255 / 90%);
    box-shadow: 0 0 16px rgb(0 0 0 / 12%);
    transform: translateY(-2px);
  }

  .interview-card:focus-visible {
    border-color: rgb(74 144 226 / 95%);
    box-shadow:
      0 8px 32px rgb(0 0 0 / 12%),
      0 0 0 3px rgb(74 144 226 / 18%);
  }

  .card-header {
    display: flex;
    gap: 10px;
    align-items: center;
    min-width: 0;
    margin-bottom: 12px;
  }

  .card-icon-box {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    background: linear-gradient(
      145deg,
      rgb(255 255 255 / 86%),
      rgb(231 240 255 / 58%)
    );
    border-radius: 12px;

    /* border: 1px solid rgba(255, 255, 255, 0.74); */
    box-shadow:
      0 20px 42px rgb(79 122 188 / 16%),
      inset 0 1px 0 rgb(255 255 255 / 50%);

    /* background: rgba(255, 255, 255, 0.7); */
    backdrop-filter: blur(8px);
    backdrop-filter: blur(8px);
  }

  .card-icon {
    width: 22px;
    height: 22px;
    color: #409eff;
  }

  .card-title {
    flex: 1;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 15px;
    font-weight: 600;
    color: #1a1a1a;
    white-space: nowrap;
  }

  .card-status {
    display: flex;
    gap: 6px;
    align-items: center;
    padding: 6px 12px;
    border-radius: 20px;
    box-shadow: 0 2px 8px rgb(31 35 41 / 6%);
    backdrop-filter: blur(8px);
    backdrop-filter: blur(8px);
  }

  .card-status.status-created {
    color: #722ed1;
    background: rgb(114 46 209 / 15%);
  }

  .card-status.status-in_progress {
    color: #409eff;
    background: rgb(74 144 226 / 15%);
  }

  .card-status.status-suspended {
    color: #d48806;
    background: rgb(250 173 20 / 15%);
  }

  .card-status.status-ended {
    color: #8c8c8c;
    background: rgb(140 140 140 / 15%);
  }

  .status-text {
    font-size: 12px;
    font-weight: 500;
  }

  .card-body {
    box-sizing: border-box;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0;
    padding: 12px 0;
    margin-bottom: 12px;
  }

  .card-column {
    position: relative;
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 6px;

    /* 允许列宽严格等分（1/3），不受内容 min-content 影响，
     从而让分隔线与下方 .pill-column 的分隔线对齐 */
    min-width: 0;
    padding: 0 12px;
  }

  .card-column:first-child {
    padding-left: 0;
  }

  .card-column:last-child {
    padding-right: 0;
  }

  /* 竖向分隔线：与 .pill-column 同样用伪元素绘制，保证两者同一渲染方式、
   像素级垂直对齐（避免 border 与 background 的亚像素对齐差异） */
  .card-column:not(:last-child)::after {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: 1px;
    content: "";
    background: rgb(0 0 0 / 10%);
  }

  .column-row {
    display: flex;
    align-items: center;
    font-size: 13px;
  }

  .row-label {
    flex-shrink: 0;
    width: auto;
    white-space: nowrap;
    color: #999;
  }

  .row-value {
    /* 列被强制等分后，窄宽度下用省略号收尾，避免文本压到分隔线上 */
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    color: #333;
    white-space: nowrap;
  }

  .card-footer {
    display: flex;
    padding: 6px 0;
  }

  .footer-pill {
    box-sizing: border-box;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
    background: rgb(255 255 255 / 70%);
    border-radius: 8px;
    box-shadow: 0 2px 8px rgb(31 35 41 / 6%);
  }

  .pill-column {
    position: relative;
    box-sizing: border-box;
    display: flex;
    flex: 1;
    flex-direction: row;
    gap: 4px;
    align-items: center;
    justify-content: center;

    /* 同 .card-column，保证三列严格等分，分隔线位置一致 */
    min-width: 0;
    padding: 8px 6px;
    overflow: hidden;
  }

  /* 竖向分隔线：用伪元素绘制，上下内缩，短于父元素高度 */
  .pill-column:not(:last-child)::after {
    position: absolute;
    top: 6px;
    right: 0;
    bottom: 6px;
    width: 1px;
    content: "";
    background: rgb(0 0 0 / 10%);
  }

  @container (width < 950px) {
    .pill-column {
      gap: 2px;
      padding: 6px 8px;
    }
  }

  /* @container (width < 640px) {
  .footer-pill {
    grid-template-columns: 1fr;
  }

  .pill-column:not(:last-child)::after {
    content: none;
  }

  .pill-column:not(:last-child) {
    border-bottom: 1px solid rgb(0 0 0 / 10%);
  }
} */

  .pill-icon {
    width: 14px;
    height: 14px;
  }

  .pill-text {
    font-size: 12px;
    color: #666;

    /* 窄宽度下禁止换行，保证「待访谈/已覆盖/已提问」单行完整展示 */
    white-space: nowrap;
  }

  .pill-count {
    font-size: 13px;
    font-weight: 600;
    color: #1a1a1a;
  }
}
</style>
