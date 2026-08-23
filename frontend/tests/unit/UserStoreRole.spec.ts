import { describe, expect, it, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import type { LoginResult } from "@/api/user";
import type { DataInfo } from "@/utils/auth";
import { useUserStore } from "@/store/modules/user";
import * as userApi from "@/api/user";

describe("LoginResult schema", () => {
  it("includes user.role", () => {
    const r: LoginResult = {
      access_token: "x",
      token_type: "bearer",
      user: { id: "u-1", username: "alice", role: "admin" },
    };
    expect(r.user.role).toBe("admin");
  });
});

describe("DataInfo schema", () => {
  it("includes userId and role", () => {
    const d: DataInfo = {
      accessToken: "x",
      username: "alice",
      userId: "u-1",
      role: "admin",
    };
    expect(d.role).toBe("admin");
    expect(d.userId).toBe("u-1");
  });
});

describe("useUserStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.spyOn(userApi, "loginApi").mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      user: { id: "u-1", username: "alice", role: "admin" },
    });
  });

  it("loginByUsername writes role to state", async () => {
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.role).toBe("admin");
    expect(store.userId).toBe("u-1");
  });
});
