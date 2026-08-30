<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import type { FormInstance, FormRules } from "element-plus/es/components/form";
import { useI18n } from "vue-i18n";
import { message } from "@/utils/message";
import { useUserStoreHook } from "@/store/modules/user";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { changePasswordApi } from "@/api/user";
import Lock from "~icons/ep/lock";

defineOptions({ name: "ChangePasswordDialog" });

interface ChangePwdForm {
  old_password: string;
  new_password: string;
  confirm_new_password: string;
}

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();

const { t } = useI18n();
const userStore = useUserStoreHook();
const dialogStore = useDialogStoreHook();

const formRef = ref<FormInstance>();
const form = reactive<ChangePwdForm>({
  old_password: "",
  new_password: "",
  confirm_new_password: ""
});
const loading = ref(false);

const rules = computed<FormRules<ChangePwdForm>>(() => ({
  old_password: [
    {
      required: true,
      message: t("auth.change_password_old_placeholder"),
      trigger: "blur"
    }
  ],
  new_password: [
    {
      required: true,
      message: t("auth.change_password_new_placeholder"),
      trigger: "blur"
    },
    {
      min: 8,
      message: t("auth.change_password_new_placeholder"),
      trigger: "blur"
    }
  ],
  confirm_new_password: [
    {
      required: true,
      message: t("auth.change_password_confirm_placeholder"),
      trigger: "blur"
    },
    {
      validator: (_, v, cb) =>
        v === form.new_password
          ? cb()
          : cb(new Error(t("auth.change_password_mismatch"))),
      trigger: "blur"
    }
  ]
}));

function reset() {
  form.old_password = "";
  form.new_password = "";
  form.confirm_new_password = "";
}

async function submit(formEl: FormInstance | undefined) {
  if (!formEl || loading.value) return;
  const valid = await formEl.validate().catch(() => false);
  if (!valid) return;
  loading.value = true;
  try {
    await changePasswordApi({
      old_password: form.old_password,
      new_password: form.new_password
    });
    message(t("auth.change_password_success"), { type: "success" });
    // 改密会 bump password_changed_at，吊销旧 token 的 pwd_ver；当前会话立刻失效。
    // 直接登出并唤起登录 dialog，避免「看似成功但下一跳 401」的不一致体验。
    userStore.logOut();
    emit("update:modelValue", false);
    dialogStore.openLogin();
    reset();
  } catch (e: unknown) {
    // 后端 4xx/5xx 错误已由 http 响应拦截器统一 toast（带 grouping 去重），
    // 这里再 message() 会形成两条 toast（issue #62 同源反馈）。
    // 仅当网络错误（无 response）时给兜底——拦截器只处理有 response 的情况。
    const hasResponse = (e as { response?: unknown })?.response !== undefined;
    if (!hasResponse) {
      message(t("auth.change_password_failed"), { type: "error" });
    }
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="450px"
    align-center
    append-to-body
    destroy-on-close
    class="login-dialog"
    :title="t('auth.change_password_title')"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item prop="old_password">
        <el-input
          v-model="form.old_password"
          class="login-input"
          type="password"
          show-password
          :placeholder="t('auth.change_password_old_placeholder')"
          :prefix-icon="Lock"
        />
      </el-form-item>
      <el-form-item prop="new_password">
        <el-input
          v-model="form.new_password"
          class="login-input"
          type="password"
          show-password
          :placeholder="t('auth.change_password_new_placeholder')"
          :prefix-icon="Lock"
        />
      </el-form-item>
      <el-form-item prop="confirm_new_password">
        <el-input
          v-model="form.confirm_new_password"
          class="login-input"
          type="password"
          show-password
          :placeholder="t('auth.change_password_confirm_placeholder')"
          :prefix-icon="Lock"
          @keydown.enter="submit(formRef)"
        />
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          class="w-full login-btn"
          :loading="loading"
          @click="submit(formRef)"
        >
          {{ t("auth.change_password") }}
        </el-button>
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<style lang="scss">
.login-dialog {
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 90%);
  border-radius: 16px !important;
  background: linear-gradient(to top right, #fff 0%, #e2ecfc 85%) !important;
  box-shadow: 0 22px 70px rgb(31 41 55 / 24%) !important;

  .el-dialog__header {
    padding: 14px 24px 16px;
    margin-right: 0;
  }
  .el-dialog__body {
    padding: 0 24px 16px;
  }
  .el-form-item {
    margin-bottom: 18px;
  }
  .login-input .el-input__wrapper {
    width: 100%;
    height: 40px;
    padding: 1px 16px;
    border-radius: 8px;
    box-shadow: 0 1px 4px rgb(0 0 0 / 8%);
  }
  .login-input .el-input__wrapper.is-focus {
    box-shadow: 0 2px 8px rgb(74 144 226 / 20%);
  }
  .login-btn {
    height: 40px;
    border-radius: 8px;
  }
}
</style>
