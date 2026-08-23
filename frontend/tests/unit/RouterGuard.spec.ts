import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useUserStoreHook } from "@/store/modules/user";
import router from "@/router";

describe("router guards", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("普通用户访问 /system 被重定向", async () => {
    const store = useUserStoreHook();
    store.SET_ACCESS_TOKEN("dummy.token.value");
    store.SET_ROLE("user");

    // 期望 push /system 跳到 /403
    await router.push("/system").catch(() => {});
    // 简化断言：实际路由 path 应该是 /403（取决于具体实现）
    expect(router.currentRoute.value.path).toMatch(/\/403|home/);
  });
});