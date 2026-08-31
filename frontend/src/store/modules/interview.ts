import { defineStore } from "pinia";
import { store } from "../utils";

export const useInterviewStore = defineStore("intv-interview", {
  state: () => ({
    interviewCreated: 0,
    // pause / resume / end 成功后通知首页拉新
    interviewStatusChanged: 0
    // ↑ 递增计数器当事件信号的临时方案（与 interviewCreated 同款 hack），
    //   后续应统一改为 dirty: boolean 或正经 action 广播。
  }),
  actions: {
    markInterviewCreated() {
      this.interviewCreated += 1;
    },
    markInterviewStatusChanged() {
      this.interviewStatusChanged += 1;
    }
  }
});

export function useInterviewStoreHook() {
  return useInterviewStore(store);
}
