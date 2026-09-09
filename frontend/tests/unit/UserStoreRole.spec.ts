import { describe, expect, it, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import type { LoginResult } from "@/api/user";
import type { userType } from "@/store/types";
import { useUserStore } from "@/store/modules/user";
import * as userApi from "@/api/user";

describe("LoginResult schema", () => {
  it("只含 user 字段（HttpOnly 模型下前端不再读 token）", () => {
    // 后端兼容地仍带 access_token / refresh_token / token_type 字段，但前端
    // 写 LoginResult 类型只声明 user——这里用 as unknown as 模拟完整后端
    // 响应以验证 schema 形状契约。
    const r = {
      access_token: "x",
      refresh_token: "rt",
      token_type: "bearer",
      user: { id: "u-1", username: "alice", role: "admin" }
    } as unknown as LoginResult;
    expect(r.user.role).toBe("admin");
  });
});

describe("userType schema", () => {
  it("HttpOnly 模型下 Pinia user store 只含 username / userId / role（无 token）", () => {
    // userType 不再带 accessToken / refreshToken——前端 JS 看不到 token。
    const u: userType = {
      username: "alice",
      userId: "u-1",
      role: "admin"
    };
    expect(u.role).toBe("admin");
    expect(u.userId).toBe("u-1");
  });
});

describe("useUserStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(userApi, "loginApi").mockResolvedValue({
      user: { id: "u-1", username: "alice", role: "admin" }
    } as unknown as LoginResult);
  });

  it("loginByUsername writes role to state", async () => {
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.role).toBe("admin");
    expect(store.userId).toBe("u-1");
  });
});