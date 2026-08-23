<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { FormInstance, FormRules } from "element-plus/es/components/form";
import { useI18n } from "vue-i18n";
import { message } from "@/utils/message";
import { extractBackendError } from "@/utils/error";
import { useUserStoreHook } from "@/store/modules/user";
import { registrationStatusApi } from "@/api/user";
import User from "~icons/ep/user";
import Lock from "~icons/ep/lock";

defineOptions({ name: "LoginDialog" });

interface RuleForm {
  username: string;
  password: string;
  confirmPassword: string;
}

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();

const { t } = useI18n();
const mode = ref<"login" | "register">("login");
const registrationAvailable = ref<boolean | null>(null);

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      ruleForm.username = "";
      ruleForm.password = "";
      ruleForm.confirmPassword = "";
      mode.value = "login";
      try {
        const r = await registrationStatusApi();
        registrationAvailable.value = r.allow_registration;
      } catch {
        registrationAvailable.value = false; // 失败降级禁用
      }
    }
  }
);

const loginRules = computed<FormRules<RuleForm>>(() => ({
  username: [{ required: true, message: t("auth.username_required"), trigger: "blur" }],
  password: [{ required: true, message: t("auth.password_required"), trigger: "blur" }],
  confirmPassword:
    mode.value === "register"
      ? [
          { required: true, message: t("auth.confirm_password"), trigger: "blur" },
          {
            validator: (_, v, cb) =>
              v === ruleForm.password ? cb() : cb(new Error(t("auth.password_mismatch"))),
            trigger: "blur"
          }
        ]
      : []
}));

const ruleFormRef = ref<FormInstance>();
const ruleForm = reactive<RuleForm>({ username: "", password: "", confirmPassword: "" });
const loading = ref(false);

async function submit(formEl: FormInstance | undefined) {
  if (!formEl || loading.value) return;
  const valid = await formEl.validate().catch(() => false);
  if (!valid) return;
  loading.value = true;
  try {
    const store = useUserStoreHook();
    if (mode.value === "login") {
      const r = await store.loginByUsername({ username: ruleForm.username, password: ruleForm.password });
      if (!r?.access_token) {
        message(t("auth.login_invalid"), { type: "error" });
        return;
      }
      message(t("auth.login_success"), { type: "success" });
    } else {
      const r = await store.registerByUsername({
        username: ruleForm.username,
        password: ruleForm.password,
        confirm_password: ruleForm.confirmPassword
      });
      if (!r?.access_token) {
        message(t("auth.register_failed"), { type: "error" });
        return;
      }
      message(t("auth.register_success"), { type: "success" });
    }
    emit("update:modelValue", false);
  } catch (e: unknown) {
    // 后端 detail 三种形态（I18nError / pydantic 422 / HTTPException）见
    // @/utils/error.ts；统一交给 extractBackendError 解析，取不到再走 i18n 兜底。
    // 这里 login / register 都读 detail，避免「用户名或密码错误」被泛化为
    // 「登录失败，请稍后重试」。
    message(
      extractBackendError(
        e,
        mode.value === "login" ? t("auth.login_failed") : t("auth.register_failed")
      ),
      { type: "error" }
    );
  } finally {
    loading.value = false;
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter") {
    event.preventDefault();
    void submit(ruleFormRef.value);
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="550px"
    align-center
    destroy-on-close
    class="login-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div>
      <div class="flex justify-between -translate-y-7">
        <div class="flex flex-col justify-center">
          <div class="mb-2 text-[28px] font-semibold text-[#1a1a1a]">
            {{ mode === "login" ? t("auth.login_title") : t("auth.register_title") }}
          </div>
          <div class="text-[14px] text-[#666]">
            {{ mode === "login" ? t("auth.login_subtitle") : t("auth.register_subtitle") }}
          </div>
        </div>
        <img src="@/assets/images/login-chat-icon.png" class="w-36" alt="Login icon" />
      </div>
      <el-form ref="ruleFormRef" :model="ruleForm" :rules="loginRules">
        <el-form-item prop="username">
          <el-input v-model="ruleForm.username" class="login-input" :placeholder="$t('auth.username_placeholder')" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input ref="passwordRef" v-model="ruleForm.password" class="login-input" type="password" :placeholder="$t('auth.password_placeholder')" show-password :prefix-icon="Lock" @keydown="onKeydown" />
        </el-form-item>
        <el-form-item v-if="mode === 'register'" prop="confirmPassword">
          <el-input v-model="ruleForm.confirmPassword" class="login-input" type="password" :placeholder="$t('auth.confirm_password_placeholder')" show-password :prefix-icon="Lock" @keydown="onKeydown" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="w-full login-btn" :loading="loading" @click="submit(ruleFormRef)">
            {{ mode === "login" ? t("auth.login") : t("auth.register") }}
          </el-button>
        </el-form-item>
        <div class="text-center text-sm text-[#666]">
          <template v-if="mode === 'login'">
            <!--
              注册入口：注册关闭（registrationAvailable === false）时直接隐藏，
              避免「看到却点不动」的反向引导；其它状态显示「去注册」链接。
            -->
            <el-link
              v-if="registrationAvailable !== false"
              type="primary"
              @click="mode = 'register'"
            >{{ t("auth.go_register") }}</el-link>
          </template>
          <template v-else>
            <el-link type="primary" @click="mode = 'login'">{{ t("auth.signin_instead") }}</el-link>
          </template>
        </div>
      </el-form>
    </div>
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
    padding: 0 24px;
  }
  .el-form-item {
    margin-bottom: 20px;
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
