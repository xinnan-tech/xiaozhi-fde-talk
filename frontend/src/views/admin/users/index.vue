<script setup lang="ts">
import { ref, reactive, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { message, messageBox } from "@/utils/message";
import { listUsersApi, resetPasswordApi, type AdminUserInfo } from "@/api/admin";
import { registrationStatusApi } from "@/api/user";

defineOptions({ name: "AdminUsers" });

const { t } = useI18n();
const loading = ref(false);
const users = ref<AdminUserInfo[]>([]);
const registrationAllowed = ref(false);
const resetDialogVisible = ref(false);
const resetTarget = ref<AdminUserInfo | null>(null);
const resetForm = reactive({ new_password: "", confirm: "" });
const resetting = ref(false);

async function reload() {
  loading.value = true;
  try {
    users.value = await listUsersApi();
  } finally {
    loading.value = false;
  }
}

async function loadRegistrationFlag() {
  try {
    const r = await registrationStatusApi();
    registrationAllowed.value = r.allow_registration;
  } catch {
    registrationAllowed.value = false;
  }
}

onMounted(async () => {
  await Promise.all([reload(), loadRegistrationFlag()]);
});

function openReset(u: AdminUserInfo) {
  resetTarget.value = u;
  resetForm.new_password = "";
  resetForm.confirm = "";
  resetDialogVisible.value = true;
}

async function submitReset() {
  if (!resetTarget.value) return;
  if (resetForm.new_password !== resetForm.confirm) {
    message(t("auth.password_mismatch"), { type: "error" });
    return;
  }
  resetting.value = true;
  try {
    await resetPasswordApi(resetTarget.value.id, resetForm.new_password);
    message(t("users.reset_password_success"), { type: "success" });
    resetDialogVisible.value = false;
  } catch {
    message(t("users.reset_password_failed"), { type: "error" });
  } finally {
    resetting.value = false;
  }
}
</script>

<template>
  <div class="admin-users-page p-4">
    <el-card shadow="never">
      <template #header>
        <span class="text-base font-semibold">{{ t("users.list_title") }}</span>
      </template>
      <el-table v-loading="loading" :data="users" stripe>
        <el-table-column prop="username" :label="t('users.col_username')" />
        <el-table-column prop="role" :label="t('users.col_role')" width="120" />
        <el-table-column prop="created_at" :label="t('users.col_created_at')" width="200" />
        <el-table-column :label="t('users.col_actions')" width="180">
          <template #default="{ row }">
            <el-tooltip :disabled="registrationAllowed" :content="t('users.registration_closed_hint')" placement="top">
              <el-button size="small" :disabled="!registrationAllowed" @click="openReset(row)">
                {{ t("users.reset_password") }}
              </el-button>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="resetDialogVisible" :title="t('users.reset_password_title')" width="480px">
      <el-form>
        <el-form-item :label="t('users.new_password')">
          <el-input v-model="resetForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('users.confirm_new_password')">
          <el-input v-model="resetForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="submitReset">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-users-page {
  /* 卡片 / 输入 / 按钮 tokens 见 spec §6.2.b */
}
</style>
