import { defineStore } from "pinia";
import { store } from "../utils";

export const useInterviewStore = defineStore("intv-interview", {
  state: () => ({
    interviewCreated: 0
  }),
  actions: {
    markInterviewCreated() {
      this.interviewCreated += 1;
    }
  }
});

export function useInterviewStoreHook() {
  return useInterviewStore(store);
}
