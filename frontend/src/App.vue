<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import zhTw from "element-plus/es/locale/lang/zh-tw";
import en from "element-plus/es/locale/lang/en";
import { useI18n } from "vue-i18n";
import { addPathMatch } from "@/router/utils";
import { usePermissionStoreHook } from "@/store/modules/permission";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { useInterviewStoreHook } from "@/store/modules/interview";
import { ReDialog } from "@/components/ReDialog";
import CreateInterviewDialog from "@/components/interview/CreateInterviewDialog.vue";
import LoginDialog from "@/components/auth/LoginDialog.vue";
import { saveInterviewApi, type CreateInterviewForm } from "@/api/interview";

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
const { createInterviewVisible, loginVisible } = storeToRefs(dialogStore);
const creatingInterview = ref(false);

const handleCreateInterview = async (form: CreateInterviewForm) => {
  if (creatingInterview.value) return;

  creatingInterview.value = true;
  try {
    await saveInterviewApi(form);
    dialogStore.closeCreateInterview();
    ElMessage.success(t("app.interview_create_success"));
    interviewStore.markInterviewCreated();
  } catch (error: any) {
    const detail = error?.response?.data?.detail;
    ElMessage.error(
      typeof detail === "string" ? detail : t("app.interview_create_failed")
    );
  } finally {
    creatingInterview.value = false;
  }
};

const initRoutes = () => {
  usePermissionStoreHook().handleWholeMenus([]);
  addPathMatch();
};

onMounted(initRoutes);
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

