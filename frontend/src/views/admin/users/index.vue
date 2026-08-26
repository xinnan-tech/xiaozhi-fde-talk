<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { message } from "@/utils/message";
import { extractBackendError } from "@/utils/error";
import {
  listUsersApi,
  resetPasswordApi,
  type AdminUserInfo
} from "@/api/admin";
import { registrationStatusApi } from "@/api/user";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({ name: "AdminUsers" });

const { t } = useI18n();

const searchIcon = useRenderIcon("tabler:search");
const clearIcon = useRenderIcon("tabler:x");
const refreshIcon = useRenderIcon("ep:refresh");

const loading = ref(false);
const users = ref<AdminUserInfo[]>([]);
const registrationAllowed = ref(false);
const resetDialogVisible = ref(false);
const resetTarget = ref<AdminUserInfo | null>(null);
const resetForm = reactive({ new_password: "", confirm: "" });
const resetting = ref(false);

const searchKeyword = ref("");

const filteredUsers = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase();
  if (!keyword) return users.value;
  return users.value.filter(
    user =>
      user.username.toLowerCase().includes(keyword) ||
      user.role.toLowerCase().includes(keyword)
  );
});

const formatDateTime = (value: string | null) => {
  if (!value) return "--";
  // 后端返回 UTC 时间（带 +00:00），转为本地时间后展示
  const date = new Date(value);
  return date.toLocaleString();
};

const roleLabel = (role: AdminUserInfo["role"]) =>
  role === "admin" ? t("users.role.admin") : t("users.role.user");

const roleTagType = (role: AdminUserInfo["role"]) =>
  role === "admin" ? "danger" : "info";

const handleSearchInput = (event: Event) => {
  searchKeyword.value = (event.target as HTMLInputElement).value;
};

const clearSearch = () => {
  searchKeyword.value = "";
};

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

function openReset(user: AdminUserInfo) {
  resetTarget.value = user;
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
  } catch (e: unknown) {
    // 后端 I18nError 已返回精确文案（用户不存在 / 新密码不合规等），
    // 交给 helper 解析；取不到再走 i18n 兜底。
    message(extractBackendError(e, t("users.reset_password_failed")), {
      type: "error"
    });
  } finally {
    resetting.value = false;
  }
}
</script>

<template>
  <div class="admin-users-page">
    <header class="admin-users-header">
      <div class="header-left">
        <h1 class="header-title">{{ t("users.list_title") }}</h1>
        <p class="header-subtitle">{{ t("users.subtitle") }}</p>
      </div>
      <div class="header-right">
        <div class="search-box">
          <input
            :value="searchKeyword"
            type="text"
            class="search-input"
            :placeholder="t('users.search_placeholder')"
            autocomplete="off"
            @input="handleSearchInput"
          />
          <button
            v-if="searchKeyword"
            type="button"
            class="clear-search-btn"
            :aria-label="t('home.clear_search')"
            :title="t('home.clear_search')"
            @click="clearSearch"
          >
            <component :is="clearIcon" />
          </button>
          <component :is="searchIcon" class="search-icon" />
        </div>
        <el-button
          class="refresh-btn"
          plain
          :icon="refreshIcon"
          :loading="loading"
          @click="reload"
        >
          {{ t("system.reload") }}
        </el-button>
      </div>
    </header>

    <div class="table-card glass-card">
      <el-table
        v-loading="loading"
        :data="filteredUsers"
        stripe
        :empty-text="t('users.empty_state')"
        class="users-table"
        row-class-name="users-table-row"
      >
        <el-table-column
          type="index"
          :label="t('users.col_index')"
          width="72"
          align="center"
        />
        <el-table-column
          prop="username"
          :label="t('users.col_username')"
          min-width="160"
        >
          <template #default="{ row }">
            <div class="user-cell">
              <span class="user-avatar">{{ row.username.charAt(0).toUpperCase() }}</span>
              <span class="user-name">{{ row.username }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          :label="t('users.col_role')"
          width="140"
          align="center"
        >
          <template #default="{ row }">
            <el-tag
              :type="roleTagType(row.role)"
              size="small"
              effect="light"
              round
            >
              {{ roleLabel(row.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column
          prop="created_at"
          :label="t('users.col_created_at')"
          width="200"
          align="center"
        >
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column
          prop="password_changed_at"
          :label="t('users.col_password_changed_at')"
          width="200"
          align="center"
        >
          <template #default="{ row }">
            <span v-if="row.password_changed_at" class="datetime-value">
              {{ formatDateTime(row.password_changed_at) }}
            </span>
            <span v-else class="muted-text">{{ t("users.never_changed") }}</span>
          </template>
        </el-table-column>
        <el-table-column
          :label="t('users.col_actions')"
          width="160"
          align="center"
          fixed="right"
        >
          <template #default="{ row }">
            <el-tooltip
              :disabled="registrationAllowed"
              :content="t('users.registration_closed_hint')"
              placement="top"
            >
              <el-button
                class="row-action"
                type="primary"
                text
                bg
                size="small"
                :disabled="!registrationAllowed"
                @click="openReset(row as AdminUserInfo)"
              >
                {{ t("users.reset_password") }}
              </el-button>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="resetDialogVisible"
      :title="t('users.reset_password_title')"
      width="480px"
      align-center
      class="reset-dialog"
    >
      <p v-if="resetTarget" class="dialog-subtitle">
        {{ t("users.dialog_subtitle", { username: resetTarget.username }) }}
      </p>
      <el-form label-position="top">
        <el-form-item :label="t('users.new_password')">
          <el-input
            v-model="resetForm.new_password"
            type="password"
            show-password
            :placeholder="t('users.new_password_placeholder')"
          />
        </el-form-item>
        <el-form-item :label="t('users.confirm_new_password')">
          <el-input
            v-model="resetForm.confirm"
            type="password"
            show-password
            :placeholder="t('users.confirm_password_placeholder')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDialogVisible = false">
          {{ t("users.cancel_button") }}
        </el-button>
        <el-button
          type="primary"
          :loading="resetting"
          @click="submitReset"
        >
          {{ t("users.confirm_button") }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.admin-users-page {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 30px 8px 18px 16px;
}

.admin-users-page {
  .admin-users-header {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-end;
    justify-content: space-between;
    padding: 8px 16px 20px;
  }

  .header-left {
    display: flex;
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
    width: 220px;
    max-width: 100%;
    height: 36px;
    padding: 0 64px 0 14px;
    font-size: 14px;
    color: #334155;
    outline: none;
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 75%);
    border-radius: 8px;
    box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
    transition: box-shadow 0.2s, border-color 0.2s;
  }

  .search-input:focus {
    background: #fff;
    border-color: rgb(74 144 226 / 60%);
    box-shadow: 0 4px 12px rgb(74 144 226 / 18%);
  }

  .search-input::placeholder {
    color: #94a3b8;
  }

  .search-icon {
    position: absolute;
    right: 12px;
    width: 16px;
    height: 16px;
    color: #94a3b8;
    pointer-events: none;
  }

  .clear-search-btn {
    position: absolute;
    right: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    color: #94a3b8;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: 4px;
  }

  .clear-search-btn:hover {
    color: #475569;
    background: rgb(0 0 0 / 6%);
  }

  .clear-search-btn :deep(svg) {
    width: 14px;
    height: 14px;
  }

  .refresh-btn {
    height: 36px;
    border-radius: 8px;
  }

  .glass-card {
    background: rgb(255 255 255 / 68%);
    border: 1px solid rgb(255 255 255 / 72%);
    border-radius: 16px;
    box-shadow: 0 0 10px rgb(31 47 86 / 10%);
    backdrop-filter: blur(10px);
  }

  .table-card {
    padding: 6px 8px 8px;
    margin: 0 8px 0 16px;
  }

  .users-table {
    width: 100%;
    font-size: 13px;

    :deep(.el-table__header-wrapper th) {
      height: 48px;
      font-size: 13px;
      font-weight: 600;
      color: #334155;
      background: rgb(241 245 249 / 60%) !important;
      border-bottom: 1px solid rgb(226 232 240 / 80%);
    }

    :deep(.el-table__header-wrapper th .cell) {
      letter-spacing: 0.02em;
    }

    :deep(.el-table__row td) {
      height: 56px;
      padding: 0;
      background: transparent !important;
      border-bottom: 1px solid rgb(226 232 240 / 70%);
    }

    :deep(.el-table__row) {
      transition: background-color 0.18s ease;
    }

    :deep(.el-table__row:hover > td) {
      background: rgb(239 246 255 / 55%) !important;
    }

    :deep(.el-table__empty-block) {
      min-height: 220px;
    }

    :deep(.el-table__empty-text) {
      color: #94a3b8;
      font-size: 13px;
    }
  }

  .user-cell {
    display: inline-flex;
    gap: 10px;
    align-items: center;
  }

  .user-avatar {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    font-size: 13px;
    font-weight: 700;
    color: #fff;
    background: linear-gradient(135deg, #409eff, #1f4ed8);
    border-radius: 999px;
    box-shadow: 0 4px 10px rgb(64 158 255 / 22%);
  }

  .user-name {
    font-size: 13px;
    font-weight: 600;
    color: #1a1a1a;
  }

  .datetime-value {
    font-size: 12px;
    color: #475569;
  }

  .muted-text {
    font-size: 12px;
    color: #94a3b8;
    font-style: italic;
  }

  .row-action.el-button {
    height: 28px;
    padding: 0 12px;
    font-size: 12px;
    font-weight: 600;
    border-radius: 999px;
    background: rgb(74 144 226 / 10%);
  }

  .row-action.el-button:hover {
    background: rgb(74 144 226 / 18%);
  }
}

.reset-dialog {
  .dialog-subtitle {
    margin: -4px 0 14px;
    font-size: 13px;
    color: #64748b;
  }

  :deep(.el-form-item__label) {
    font-weight: 500;
    color: #334155;
  }
}
</style>