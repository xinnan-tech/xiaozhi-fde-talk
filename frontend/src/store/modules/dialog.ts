import { defineStore } from "pinia";
import { store } from "../utils";
import { useUserStoreHook } from "./user";
import { ElMessage } from "element-plus";

export const useDialogStore = defineStore("intv-dialog", {
  state: () => ({
    createInterviewVisible: false,
    loginVisible: false
  }),
  actions: {
    openCreateInterview() {
      if (!useUserStoreHook().accessToken) {
        ElMessage({
          message: "请先登录",
          type: "warning"
        });
        this.openLogin();
        return;
      }

      this.createInterviewVisible = true;
    },
    closeCreateInterview() {
      this.createInterviewVisible = false;
    },
    openLogin() {
      this.loginVisible = true;
    },
    closeLogin() {
      this.loginVisible = false;
    }
  }
});

export function useDialogStoreHook() {
  return useDialogStore(store);
}
