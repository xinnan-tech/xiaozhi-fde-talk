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
