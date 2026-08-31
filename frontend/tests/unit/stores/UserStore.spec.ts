import { describe, expect, it, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import * as userApi from "@/api/user";
import { useUserStore } from "@/store/modules/user";

// logOut() 调 router.push("/home")，mock 路由避免被真 router 实例影响
vi.mock("@/router", () => ({
  router: { push: vi.fn() },
  resetRouter: vi.fn(),
  constantMenus: []
}));

// 注意：actions 内部把状态写进 store 实例，store 实例绑在调用者提供的 pinia 上。
// 这里 useUserStore() 不带参 → 用 setActivePinia 注入的 active pinia。
// 这跟源码的 useUserStoreHook() (走单例 pinia) 不同：测试用 active 隔离干净。
// logOut() 内部读的是 source 里硬编码的单例 pinia → 我们的用例不读跨 store，跳过这个差异。

describe("stores/UserStore — SET_* actions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("SET_ACCESS_TOKEN writes state.accessToken", () => {
    const store = useUserStore();
    store.SET_ACCESS_TOKEN("tok-123");
    expect(store.accessToken).toBe("tok-123");
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
});

describe("stores/UserStore — loginByUsername", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("按 result.access_token 写入 state", async () => {
    vi.spyOn(userApi, "loginApi").mockReset().mockResolvedValue({
      access_token: "tok-1",
      refresh_token: "rt-1",
      token_type: "bearer",
      user: { id: "u-1", username: "alice", role: "admin" }
    });
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.accessToken).toBe("tok-1");
    expect(store.refreshToken).toBe("rt-1");
    expect(store.username).toBe("alice");
    expect(store.userId).toBe("u-1");
    expect(store.role).toBe("admin");
  });

  it("login: result.access_token 缺失时 state 保持空", async () => {
    vi.spyOn(userApi, "loginApi").mockReset().mockResolvedValue({
      access_token: "",
      refresh_token: "rt-x",
      token_type: "bearer",
      user: { id: "u-1", username: "alice", role: "admin" }
    } as any);
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.accessToken).toBe("");
    expect(store.refreshToken).toBe("");
    expect(store.username).toBe("");
    expect(store.userId).toBe("");
    expect(store.role).toBe("user");
  });
});

describe("stores/UserStore — registerByUsername", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("注册成功：写 result.user.username（不是 data.username）到 state", async () => {
    vi.spyOn(userApi, "registerApi").mockReset().mockResolvedValue({
      access_token: "tok-r",
      refresh_token: "rt-r",
      token_type: "bearer",
      user: { id: "u-9", username: "canonical-name", role: "user" }
    });
    const store = useUserStore();
    await store.registerByUsername({
      username: "raw-input",
      password: "pw",
      confirm_password: "pw"
    });
    expect(store.accessToken).toBe("tok-r");
    expect(store.refreshToken).toBe("rt-r");
    expect(store.username).toBe("canonical-name");
    expect(store.userId).toBe("u-9");
    expect(store.role).toBe("user");
  });

  it("register: result.access_token 缺失时 state 保持空", async () => {
    vi.spyOn(userApi, "registerApi").mockReset().mockResolvedValue({
      access_token: "",
      refresh_token: "rt-r",
      token_type: "bearer",
      user: { id: "u-9", username: "canonical-name", role: "user" }
    } as any);
    const store = useUserStore();
    await store.registerByUsername({
      username: "raw-input",
      password: "pw",
      confirm_password: "pw"
    });
    expect(store.accessToken).toBe("");
    expect(store.refreshToken).toBe("");
    expect(store.username).toBe("");
    expect(store.userId).toBe("");
  });
});

describe("stores/UserStore — logOut", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("清空 state 并调 router.push('/home')", async () => {
    const routerMod = await import("@/router");
    const store = useUserStore();
    store.SET_ACCESS_TOKEN("tok");
    store.SET_USERNAME("alice");
    store.SET_USER_ID("u-1");
    store.SET_ROLE("admin");

    store.logOut();

    expect(store.accessToken).toBe("");
    expect(store.username).toBe("");
    expect(store.userId).toBe("");
    expect(store.role).toBe("user");
    expect(routerMod.router.push as any).toHaveBeenCalledWith("/home");
  });

  it("logOut 同步清状态：调用后立刻可读空 state（不等 logoutApi）", async () => {
    // P1.3: logOut 改成同步 fire-and-forget。原因是：
    // - await logoutApi 在 60s 超时内页面卡在原路由；
    // - 关页面后 refresh_token 没被清，下次开页面用户仍是登录态——「登出没生效」。
    // 这里用 vi.mock 把 logoutApi 全替换掉，避免 axios 在 happy-dom 下打到
    // http://localhost:3000（dev server），打出 ECONNREFUSED 噪音。
    const logoutApiMock = vi.fn().mockResolvedValue({ ok: true });
    vi.doMock("@/api/user", async () => {
      const actual = await vi.importActual<typeof import("@/api/user")>(
        "@/api/user"
      );
      return { ...actual, logoutApi: logoutApiMock };
    });
    try {
      const routerMod = await import("@/router");
      // 清掉之前 import 的 store 模块（拿到新的 mocked logoutApi 绑定）。
      vi.resetModules();
      const { useUserStore: useStoreFresh } = await import(
        "@/store/modules/user"
      );
      const store = useStoreFresh();
      store.SET_ACCESS_TOKEN("tok");
      store.SET_REFRESH_TOKEN("rt-1");
      store.SET_USERNAME("alice");
      store.SET_USER_ID("u-1");
      store.SET_ROLE("user");

      store.logOut();

      // 调完立即可读：状态、router、removeToken 都不能等 logoutApi。
      expect(store.accessToken).toBe("");
      expect(store.refreshToken).toBe("");
      expect(store.username).toBe("");
      expect(store.userId).toBe("");
      expect(store.role).toBe("user");
      expect(routerMod.router.push as any).toHaveBeenCalledWith("/home");
      expect(logoutApiMock).toHaveBeenCalledWith({ refresh_token: "rt-1" });
    } finally {
      vi.doUnmock("@/api/user");
      vi.resetModules();
    }
  });

  it("logOut：refreshToken 存在时 fire-and-forget 调 logoutApi（不等结果）", async () => {
    // 验证 logoutApi 被 fire-and-forget 调用（不 await logOut）。
    vi.spyOn(userApi, "logoutApi").mockReset().mockResolvedValue({
      ok: true
    } as any);
    const store = useUserStore();
    store.SET_ACCESS_TOKEN("tok");
    store.SET_REFRESH_TOKEN("rt-1");

    store.logOut();

    // logoutApi 应已被发起（同步路径），但 logOut 自身已返回。
    expect(userApi.logoutApi).toHaveBeenCalledWith({ refresh_token: "rt-1" });
    // 等一个 microtask 让 promise 链把状态清掉（虽然同步路径已清），
    // 主要是确认 fire-and-forget 不抛错。
    await Promise.resolve();
    expect(store.accessToken).toBe("");
    expect(store.refreshToken).toBe("");
  });

  it("logOut：logoutApi reject 时本地状态仍被清空（fire-and-forget + console.warn）", async () => {
    // P1.4: 后端撤销失败不应阻塞前端清状态，且要上报方便追踪。
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(userApi, "logoutApi").mockReset().mockRejectedValue(
      new Error("boom")
    );
    const store = useUserStore();
    store.SET_ACCESS_TOKEN("tok");
    store.SET_REFRESH_TOKEN("rt-1");

    store.logOut();

    // 同步路径：状态立即清空、不等 logoutApi 的 reject。
    expect(store.accessToken).toBe("");
    expect(store.refreshToken).toBe("");

    // 等 reject 的 .catch 跑完，warn 应被打到 console。
    await new Promise(r => setTimeout(r, 0));
    expect(warnSpy).toHaveBeenCalled();
    expect(String(warnSpy.mock.calls[0]?.[0] ?? "")).toContain(
      "revoke refresh token failed"
    );

    warnSpy.mockRestore();
  });
});
