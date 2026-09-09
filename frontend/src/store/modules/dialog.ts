import { defineStore } from "pinia";
import { store } from "../utils";
import { isBootstrapped } from "@/utils/auth";

export const useDialogStore = defineStore("intv-dialog", {
  state: () => ({
    createInterviewVisible: false,
    loginVisible: false
  }),
  actions: {
    openCreateInterview() {
      // HttpOnly cookie 由浏览器管，前端 JS 看不出是否「持 token」。
      // 用 isBootstrapped() 作判据——F5 后 /auth/me 调通即为登录态，未调通即
      // 未登录。前端没必要再读 userStore.accessToken（字段已删）。
      if (!isBootstrapped()) {
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
