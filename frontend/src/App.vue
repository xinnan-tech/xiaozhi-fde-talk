<script setup lang="ts">
import { onMounted } from "vue";
import { storeToRefs } from "pinia";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import { ElConfigProvider, ElMessage } from "element-plus";
import { addPathMatch } from "@/router/utils";
import { usePermissionStoreHook } from "@/store/modules/permission";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { ReDialog } from "@/components/ReDialog";
import CreateInterviewDialog from "@/components/interview/CreateInterviewDialog.vue";
import LoginDialog from "@/components/auth/LoginDialog.vue";

export type CreateInterviewForm = {
  interviewee: string;
  interviewTime: string;
  duration: string;
  goal: string;
};

const currentLocale = zhCn;
const dialogStore = useDialogStoreHook();
const { createInterviewVisible, loginVisible } = storeToRefs(dialogStore);

const handleCreateInterview = (form: CreateInterviewForm) => {
  dialogStore.closeCreateInterview();
  ElMessage.success(`已创建 ${form.goal}`);
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
      @submit="handleCreateInterview"
    />
    <LoginDialog v-model="loginVisible" />
    <ReDialog />
  </el-config-provider>
</template>
