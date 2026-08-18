<script setup lang="ts">
import { reactive, ref } from "vue";
import { type FormInstance, type FormRules } from "element-plus";
import { message } from "@/utils/message";
import { useUserStoreHook } from "@/store/modules/user";
import User from "~icons/ep/user";
import Lock from "~icons/ep/lock";

defineOptions({ name: "LoginDialog" });

interface RuleForm {
  username: string;
  password: string;
}

defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const loginRules = reactive<FormRules<RuleForm>>({
  username: [
    {
      required: true,
      message: "请输入用户名",
      trigger: "blur"
    }
  ],
  password: [
    {
      required: true,
      message: "请输入密码",
      trigger: "blur"
    }
  ]
});
const ruleFormRef = ref<FormInstance>();
const ruleForm = reactive<RuleForm>({
  username: "admin",
  password: "Abcd1234."
});
const passwordRef = ref<HTMLInputElement>();
const loading = ref(false);

const clickLogin = async (formEl: FormInstance | undefined) => {
  if (!formEl || loading.value) return;
  const valid = await formEl.validate().catch(() => false);
  if (!valid) return;

  loading.value = true;
  try {
    const result = await useUserStoreHook().loginByUsername({
      username: ruleForm.username,
      password: ruleForm.password
    });
    if (!result?.access_token) {
      message("登录失败，请检查用户名和密码", { type: "error" });
      return;
    }
    message("登录成功", { type: "success" });
    emit("update:modelValue", false);
  } catch {
    message("登录失败，请稍后重试", {
      type: "error"
    });
  } finally {
    loading.value = false;
  }
};

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === "Enter") {
    event.preventDefault();
    void clickLogin(ruleFormRef.value);
    passwordRef.value?.blur();
  }
};
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
            &#x6B22;&#x8FCE;&#x767B;&#x5F55;
          </div>
          <div class="text-[14px] text-[#666]">
            &#x767B;&#x5F55;&#x4E4B;&#x540E;&#x5373;&#x53EF;&#x4F7F;&#x7528;&#x8BBF;&#x8C08;&#x5DE5;&#x4F5C;&#x53F0;
          </div>
        </div>
        <img
          src="@/assets/images/login-chat-icon.png"
          class="w-36"
          alt="Login icon"
        />
      </div>
      <el-form ref="ruleFormRef" :model="ruleForm" :rules="loginRules">
        <el-form-item prop="username">
          <el-input
            v-model="ruleForm.username"
            class="login-input"
            placeholder="&#x8BF7;&#x8F93;&#x5165;&#x7528;&#x6237;&#x540D;"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            ref="passwordRef"
            v-model="ruleForm.password"
            class="login-input"
            type="password"
            placeholder="&#x8BF7;&#x8F93;&#x5165;&#x5BC6;&#x7801;"
            show-password
            :prefix-icon="Lock"
            @keydown="onKeydown"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            class="w-full login-btn"
            :loading="loading"
            @click="clickLogin(ruleFormRef)"
            >&#x767B;&#x5F55;</el-button
          >
        </el-form-item>
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
