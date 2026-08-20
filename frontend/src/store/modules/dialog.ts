import { defineStore } from "pinia";
import { store } from "../utils";
import { useUserStoreHook } from "./user";

export const useDialogStore = defineStore("intv-dialog", {
  state: () => ({
    createInterviewVisible: false,
    loginVisible: false
  }),
  actions: {
    openCreateInterview() {
      if (!useUserStoreHook().accessToken) {
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
