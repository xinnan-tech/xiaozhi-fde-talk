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
});
