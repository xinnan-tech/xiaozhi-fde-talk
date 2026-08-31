import { describe, expect, it, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useInterviewStore } from "@/store/modules/interview";

describe("stores/InterviewStore — state init", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("默认 interviewCreated=0", () => {
    const store = useInterviewStore();
    expect(store.interviewCreated).toBe(0);
  });

  it("默认 interviewStatusChanged=0（pause / resume / end 触发用）", () => {
    const store = useInterviewStore();
    expect(store.interviewStatusChanged).toBe(0);
  });
});

describe("stores/InterviewStore — markInterviewCreated", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("调一次：1", () => {
    const store = useInterviewStore();
    store.markInterviewCreated();
    expect(store.interviewCreated).toBe(1);
  });

  it("调三次：3", () => {
    const store = useInterviewStore();
    store.markInterviewCreated();
    store.markInterviewCreated();
    store.markInterviewCreated();
    expect(store.interviewCreated).toBe(3);
  });
});

describe("stores/InterviewStore — markInterviewStatusChanged", () => {
  // 回归 #91：pause / resume / end 后访谈页通知首页刷新；之前 store 没这字段，
  // pause 后首页列表仍是 in_progress，直到下次手动刷新才更新。
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("调一次：1", () => {
    const store = useInterviewStore();
    store.markInterviewStatusChanged();
    expect(store.interviewStatusChanged).toBe(1);
  });

  it("连续 pause / resume / end 三次：3", () => {
    const store = useInterviewStore();
    store.markInterviewStatusChanged();
    store.markInterviewStatusChanged();
    store.markInterviewStatusChanged();
    expect(store.interviewStatusChanged).toBe(3);
  });

  it("与 interviewCreated 互相独立——pause 不该污染 create 计数", () => {
    const store = useInterviewStore();
    store.markInterviewCreated();
    store.markInterviewStatusChanged();
    expect(store.interviewCreated).toBe(1);
    expect(store.interviewStatusChanged).toBe(1);
  });
});
