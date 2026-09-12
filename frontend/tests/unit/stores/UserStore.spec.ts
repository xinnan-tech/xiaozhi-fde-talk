import { describe, expect, it, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import {
  useUserStore,
  bootstrapSession,
  isBootstrapped
} from "@/store/modules/user";
import { setBootstrapped } from "@/utils/auth";

// logOut() 调 router.push("/home")，mock 路由避免被真 router 实例影响
vi.mock("@/router", () => ({
  router: { push: vi.fn() },
  resetRouter: vi.fn(),
  constantMenus: []
}));

// 把所有 api/user mock 句柄用 vi.hoisted 提到 factory 之上，避免
// "Cannot access before initialization"。注意 store.ts 的 logoutApi / loginApi
// 等调用都从 @/api/user 拉取，本工厂覆盖后 store 走的就是 mock。
const mocks = vi.hoisted(() => ({
  loginApi: vi.fn(),
  registerApi: vi.fn(),
  logoutApi: vi.fn(),
  meApi: vi.fn()
}));
vi.mock("@/api/user", () => ({
  loginApi: mocks.loginApi,
  registerApi: mocks.registerApi,
  logoutApi: mocks.logoutApi,
  meApi: mocks.meApi,
  registrationStatusApi: vi.fn(),
  refreshApi: vi.fn(),
  changePasswordApi: vi.fn()
}));

describe("stores/UserStore — SET_* actions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setBootstrapped(false);
    mocks.logoutApi.mockReset();
  });

  it("SET_USERNAME writes state.username", () => {
    const store = useUserStore();
    store.SET_USERNAME("bob");
    expect(store.username).toBe("bob");
  });

  it("SET_USER_ID writes state.userId", () => {
    const store = useUserStore();
    store.SET_USER_ID("u-42");
    expect(store.userId).toBe("u-42");
  });

  it("SET_ROLE writes state.role", () => {
    const store = useUserStore();
    store.SET_ROLE("admin");
    expect(store.role).toBe("admin");
  });

  it("store 不再持有 accessToken / refreshToken 字段（HttpOnly 模型）", () => {
    const store = useUserStore();
    expect((store as unknown as Record<string, unknown>).accessToken).toBeUndefined();
    expect((store as unknown as Record<string, unknown>).refreshToken).toBeUndefined();
  });
});

describe("stores/UserStore — loginByUsername（HttpOnly）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setBootstrapped(false);
    mocks.loginApi.mockReset();
    mocks.logoutApi.mockReset();
  });

  it("按 result.user 写 state，不读 access_token", async () => {
    mocks.loginApi.mockResolvedValue({
      access_token: "tok-1",
      refresh_token: "rt-1",
      user: { id: "u-1", username: "alice", role: "admin" }
    });
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.username).toBe("alice");
    expect(store.userId).toBe("u-1");
    expect(store.role).toBe("admin");
    expect((store as unknown as Record<string, unknown>).accessToken).toBeUndefined();
  });

  it("login: result.user 缺失时 state 保持空 + bootstrap 标志不变", async () => {
    mocks.loginApi.mockResolvedValue({
      access_token: "",
      refresh_token: "rt-x",
      user: undefined
    } as any);
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.username).toBe("");
    expect(store.userId).toBe("");
    expect(store.role).toBe("user");
    expect(isBootstrapped()).toBe(false);
  });
});

describe("stores/UserStore — registerByUsername（HttpOnly）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setBootstrapped(false);
    mocks.registerApi.mockReset();
    mocks.logoutApi.mockReset();
  });

  it("注册成功：写 result.user.username + bootstrap 标志置 true", async () => {
    mocks.registerApi.mockResolvedValue({
      access_token: "tok-r",
      refresh_token: "rt-r",
      user: { id: "u-9", username: "canonical-name", role: "user" }
    });
    const store = useUserStore();
    await store.registerByUsername({
      username: "raw-input",
      password: "pw",
      confirm_password: "pw"
    });
    expect(store.username).toBe("canonical-name");
    expect(store.userId).toBe("u-9");
    expect(store.role).toBe("user");
    expect(isBootstrapped()).toBe(true);
  });

  it("register: result.user 缺失时 state 保持空", async () => {
    mocks.registerApi.mockResolvedValue({
      access_token: "",
      refresh_token: "rt-r",
      user: undefined
    } as any);
    const store = useUserStore();
    await store.registerByUsername({
      username: "raw-input",
      password: "pw",
      confirm_password: "pw"
    });
    expect(store.username).toBe("");
    expect(store.userId).toBe("");
  });
});

describe("stores/UserStore — logOut", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setBootstrapped(true);
    mocks.logoutApi.mockReset();
  });

  it("清空 state + 调 router.push('/home') + fire-and-forget logoutApi（无 body）", async () => {
    const routerMod = await import("@/router");
    mocks.logoutApi.mockResolvedValue({ ok: true });

    const store = useUserStore();
    store.SET_USERNAME("alice");
    store.SET_USER_ID("u-1");
    store.SET_ROLE("admin");

    store.logOut();

    // 同步路径：状态立即清空，不等 logoutApi
    expect(store.username).toBe("");
    expect(store.userId).toBe("");
    expect(store.role).toBe("user");
    expect(routerMod.router.push as any).toHaveBeenCalledWith("/home");
    // HttpOnly 模型：logoutApi 不再带 refresh_token 参数
    expect(mocks.logoutApi).toHaveBeenCalledWith();
    expect(isBootstrapped()).toBe(false);
  });

  it("logOut：logoutApi reject 时本地状态仍被清空（fire-and-forget + console.warn）", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    mocks.logoutApi.mockRejectedValue(new Error("boom"));
    const store = useUserStore();
    store.SET_USERNAME("alice");

    store.logOut();

    expect(store.username).toBe("");
    await new Promise(r => setTimeout(r, 0));
    expect(warnSpy).toHaveBeenCalled();
    expect(String(warnSpy.mock.calls[0]?.[0] ?? "")).toContain("revoke failed");
    warnSpy.mockRestore();
  });

  it("logOut：console.warn 不泄漏 token（openrz P1.2）", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const sensitiveError: any = new Error("Request failed with status code 500");
    sensitiveError.isAxiosError = true;
    sensitiveError.config = {
      url: "/api/v1/auth/logout",
      method: "post",
      headers: { Authorization: "Bearer SECRET-at-leak" }
    };
    sensitiveError.response = {
      status: 500,
      statusText: "Internal Server Error",
      data: { detail: "boom" }
    };
    mocks.logoutApi.mockRejectedValue(sensitiveError);
    const store = useUserStore();
    store.SET_USERNAME("alice");
    store.logOut();
    await new Promise(r => setTimeout(r, 0));

    expect(warnSpy).toHaveBeenCalled();
    const allArgs = warnSpy.mock.calls
      .map(call =>
        call.map(a => (typeof a === "string" ? a : JSON.stringify(a))).join(" ")
      )
      .join("\n");
    expect(allArgs).not.toContain("SECRET-at-leak");
    expect(allArgs).not.toContain("Authorization");
    expect(allArgs).toContain("500");
    warnSpy.mockRestore();
  });
});

describe("stores/UserStore — bootstrapSession 暴露", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setBootstrapped(false);
    mocks.meApi.mockReset();
    mocks.logoutApi.mockReset();
  });

  it("bootstrapSession 调 /auth/me 成功 → isBootstrapped true", async () => {
    mocks.meApi.mockResolvedValue({
      id: "u-1",
      username: "alice",
      role: "admin"
    });
    const result = await bootstrapSession();
    expect(result).toBe("authenticated");
    expect(isBootstrapped()).toBe(true);
  });

  it("bootstrapSession 失败（meApi 抛）→ isBootstrapped false", async () => {
    mocks.meApi.mockRejectedValue({
      response: { status: 401 },
      message: "Request failed with status code 401"
    });
    const result = await bootstrapSession();
    expect(result).toBe("unauthenticated");
    expect(isBootstrapped()).toBe(false);
  });
});