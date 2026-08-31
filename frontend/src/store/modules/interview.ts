import { defineStore } from "pinia";
import { store } from "../utils";

export const useInterviewStore = defineStore("intv-interview", {
  state: () => ({
    interviewCreated: 0,
    // 访谈状态变更（pause / resume / end / delete 等）：让首页 watcher 调
    // getInterviewList + getStatistics 刷新——之前的实现只对「新建」触发刷新，
    // pause 后回首页列表仍是 in_progress，#91 复现的就是这条路径。
    interviewStatusChanged: 0
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
