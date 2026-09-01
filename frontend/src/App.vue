<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import zhTw from "element-plus/es/locale/lang/zh-tw";
import en from "element-plus/es/locale/lang/en";
import { useI18n } from "vue-i18n";
import { addPathMatch } from "@/router/utils";
import { usePermissionStoreHook } from "@/store/modules/permission";
import { useUserStoreHook } from "@/store/modules/user";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { useInterviewStoreHook } from "@/store/modules/interview";
import { ElMessage } from "element-plus";
import { ReDialog } from "@/components/ReDialog";
import CreateInterviewDialog from "@/components/interview/CreateInterviewDialog.vue";
import LoginDialog from "@/components/auth/LoginDialog.vue";
import { saveInterviewApi, type CreateInterviewForm } from "@/api/interview";
import { interviewRouteTarget } from "@/utils/interview";
import { registrationStatusApi } from "@/api/user";

const { locale, t } = useI18n();
const currentLocale = computed(() => {
  switch (locale.value) {
    case "zh-TW":
      return zhTw;
    case "en-US":
      return en;
    default:
      return zhCn;
  }
});
const dialogStore = useDialogStoreHook();
const interviewStore = useInterviewStoreHook();
const permissionStore = usePermissionStoreHook();
const userStore = useUserStoreHook();
const router = useRouter();
const { role: userRole } = storeToRefs(userStore);
const { createInterviewVisible, loginVisible } = storeToRefs(dialogStore);
const creatingInterview = ref(false);

const handleCreateInterview = async (form: CreateInterviewForm) => {
  if (creatingInterview.value) return;

  creatingInterview.value = true;
  try {
    // 后端 POST /api/v1/interviews 返完整 session 摘要（id + status）。
    // 走 utils/interview 的统一路由约定：status === "ended" 去报告页，
    // 否则去访谈页。新建访谈 status 不会 ended，但抽公共函数避免
    // 多入口用不同条件方向造成漂移。
    const created = await saveInterviewApi(form);
    if (!created?.id) {
      // 响应 schema 漂移 / wrapper 变更等导致 id 缺失：不当作成功，
      // 避免弹"创建成功"却停在原页（与本 PR 标题同一症状）。
      throw new Error(t("app.interview_create_failed"));
    }
    dialogStore.closeCreateInterview();
    ElMessage.success(t("app.interview_create_success"));
    interviewStore.markInterviewCreated();
    router
      .push({ path: interviewRouteTarget(created) })
      .catch(() => ElMessage.error(t("app.interview_create_failed")));
  } catch (error: any) {
    // 后端 4xx/5xx 已由 http 响应拦截器统一 toast；
    // 这里再 ElMessage.error 会形成两条 toast（#62 同源）。
    // 仅当网络错误（无 response）时给兜底——拦截器只处理有 response 的情况。
    const hasResponse = error?.response !== undefined;
    if (!hasResponse) {
      ElMessage.error(t("app.interview_create_failed"));
    }
  } finally {
    creatingInterview.value = false;
  }
};

const fetchRegistrationStatus = async () => {
  try {
    const r = await registrationStatusApi();
    permissionStore.setRegistrationAllowed(r.allow_registration);
  } catch {
    permissionStore.setRegistrationAllowed(false);
  }
};

const initRoutes = () => {
  permissionStore.handleWholeMenus([]);
  addPathMatch();
};

onMounted(() => {
  initRoutes();
  void fetchRegistrationStatus();
});

// 用户角色变化（登录 / 登出 / 注册）→ 重新过滤菜单。
// 监听 role 而非整个 userStore：role 之外字段（username / avatar）变化不需要重算。
//
// 注册场景同时重拉 registration-status：零用户时后端强制返 true 撑开注册入口，
// 首个用户注册后切到 cfg 真值（默认 false）。仅按 role 触发 filter 会让 admin
// 菜单闪现一次再被刷新校正。setRegistrationAllowed 早出兜底 role 维度过滤。
watch(
  () => userRole?.value,
  newRole => {
    if (newRole === undefined) return;
    void fetchRegistrationStatus().finally(() => {
      permissionStore.applyMenuFilter();
    });
  }
);

defineExpose({ fetchRegistrationStatus });
</script>

<template>
  <el-config-provider :locale="currentLocale">
    <router-view v-slot="{ Component, route }">
      <Transition
        v-if="route.path === '/interview'"
        name="fade-transform"
        mode="out-in"
        appear
      >
        <component :is="Component" :key="route.fullPath" />
      </Transition>

      <component :is="Component" v-else />
    </router-view>
    <CreateInterviewDialog
      v-model="createInterviewVisible"
      :submitting="creatingInterview"
      @submit="handleCreateInterview"
    />
    <LoginDialog v-model="loginVisible" />
    <ReDialog />
  </el-config-provider>
</template>
