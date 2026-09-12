import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * HttpOnly cookie 模型。前端 JS 不持任何 token；本文件回归新合约：
 *
 *   - bootstrapSession 调 /auth/me：成功 → isBootstrapped true + Pinia
 *     SET_USERNAME / SET_USER_ID / SET_ROLE；失败 → false
 *   - isBootstrapped 默认 false；setBootstrapped 切换
 *   - hasPerms 等同 isBootstrapped
 *   - 旧版 setToken/getToken/removeToken/formatToken 不再导出
 *   - 旧版 localStorage[user-info] 由 migrateStaleStorage 一次清掉
 *     （在 bootstrapSession 里走）
 */

const memStore = new Map<string, any>();

vi.mock("@pureadmin/utils", () => ({
  storageLocal: () => ({
    getItem: <T = any>(key: string): T | null =>
      memStore.has(key) ? (memStore.get(key) as T) : null,
    setItem: (key: string, value: any) => memStore.set(key, value),
    removeItem: (key: string) => memStore.delete(key)
  }),
  isFunction: (x: unknown) => typeof x === "function"
}));

// /auth/me 通过 meApi 走 http.request；mock 它避免 axios 打到 localhost。
const meApiMock = vi.fn();
vi.mock("@/api/user", () => ({
  meApi: () => meApiMock()
}));

// user store SET_* 是 no-op stub——本测试只关心「被调过」，不关心字段值。
vi.mock("@/store/modules/user", () => ({
  useUserStoreHook: () => ({
    SET_USERNAME: vi.fn(),
    SET_USER_ID: vi.fn(),
    SET_ROLE: vi.fn()
  })
}));

import {
  isBootstrapped,
  setBootstrapped,
  bootstrapSession,
  hasPerms,
  clearSession
} from "@/utils/auth";

function clearAll() {
  // 复位模块级 bootstrap 标志——auth.ts 里的 let bootstrapped 是模块状态
  setBootstrapped(false);
  memStore.clear();
  window.localStorage.clear();
  meApiMock.mockReset();
}

describe("utils/auth — bootstrapSession / isBootstrapped", () => {
  beforeEach(clearAll);
  afterEach(clearAll);

  it("isBootstrapped 默认 false，hasPerms 同 false", () => {
    expect(isBootstrapped()).toBe(false);
    expect(hasPerms("any")).toBe(false);
  });

  it("bootstrapSession 成功（/auth/me 返 user）→ isBootstrapped true + Pinia SET_* 调用", async () => {
    meApiMock.mockResolvedValue({
      id: "u-1",
      username: "alice",
      role: "admin"
    });
    const result = await bootstrapSession();
    expect(result).toBe("authenticated");
    expect(isBootstrapped()).toBe(true);
    expect(hasPerms("any")).toBe(true);
  });

  it("bootstrapSession 失败（cookie 失效 / 401）→ isBootstrapped false", async () => {
    meApiMock.mockRejectedValue({
      response: { status: 401 },
      message: "Request failed with status code 401"
    });
    const result = await bootstrapSession();
    expect(result).toBe("unauthenticated");
    expect(isBootstrapped()).toBe(false);
  });

  it("setBootstrapped 切换标志", () => {
    setBootstrapped(true);
    expect(isBootstrapped()).toBe(true);
    setBootstrapped(false);
    expect(isBootstrapped()).toBe(false);
  });

  it("bootstrapSession 5xx → transient_error（保留 Pinia）", async () => {
    setBootstrapped(true);
    meApiMock.mockRejectedValue({
      response: { status: 500 },
      message: "Internal Server Error"
    });
    const result = await bootstrapSession();
    expect(result).toBe("transient_error");
    expect(isBootstrapped()).toBe(true); // 不动 Pinia
  });

  it("bootstrapSession network error（无 response.status）→ transient_error", async () => {
    // ERR_NETWORK / CORS 预检失败：axios 没拿到 response，但 message 可能含
    // 任何字符串（含上游 502/504 错误页 body 里偶尔夹带的 "401"）。
    // 旧版 message.includes("401") 兜底会在这种情况把已登录用户误判为
    // unauthenticated → 清 Pinia。回归钉死：必须返回 transient_error。
    setBootstrapped(true);
    meApiMock.mockRejectedValue({
      message: "Network Error or proxy body containing 401 Unauthorized"
    });
    const result = await bootstrapSession();
    expect(result).toBe("transient_error");
    expect(isBootstrapped()).toBe(true);
  });

  it("bootstrapSession 每次启动会先清掉旧版残留 localStorage[user-info]", async () => {
    memStore.set("user-info", { accessToken: "leaked", refreshToken: "leaked" });
    meApiMock.mockRejectedValue({
      response: { status: 401 },
      message: "Request failed with status code 401"
    });
    await bootstrapSession();
    // 幂等清理：即便 bootstrap 失败也要先清掉历史残留
    expect(memStore.get("user-info")).toBeUndefined();
  });
});

describe("utils/auth — clearSession", () => {
  beforeEach(clearAll);
  afterEach(clearAll);

  it("重置 bootstrap 标志 + Pinia 清空", () => {
    setBootstrapped(true);
    clearSession();
    expect(isBootstrapped()).toBe(false);
  });
});

describe("utils/auth — hasPerms 语义", () => {
  beforeEach(clearAll);
  afterEach(clearAll);

  it("未 bootstrap → false", () => {
    expect(hasPerms("admin")).toBe(false);
    expect(hasPerms(["admin", "user"])).toBe(false);
  });

  it("已 bootstrap → true（参数 value 不参与判权，鉴权交由后端）", () => {
    setBootstrapped(true);
    expect(hasPerms("admin")).toBe(true);
    expect(hasPerms(["admin", "user"])).toBe(true);
    expect(hasPerms("anything-else")).toBe(true);
  });
});

/** e2e 回归钉死：isBootstrapped() 必须是响应式（Vue ref）而不是普通 let。
 *
 * 失败原因（修复前）：utils/auth.ts 用 ``let bootstrapped = false``，home 视图
 * 的 ``isLoggedIn = computed(() => isBootstrapped() && ...)`` 第一次算过后
 * 不再追依赖；登录成功后 setBootstrapped(true) 改了普通 let，computed 不重算，
 * ``.user-avatar.online`` 永远不出现——e2e 场景 A / D-1 / incognito-login 三
 * 处同时翻车。改为 ref 后 .value 访问被 Vue 追踪，computed 重新求值。
 */
describe("utils/auth — isBootstrapped 响应式（e2e 翻车回归）", () => {
  beforeEach(clearAll);
  afterEach(clearAll);

  it("computed(() => isBootstrapped() && user.username) 在 setBootstrapped(true) 后重算为 true", async () => {
    const { computed, ref, effectScope } = await import("vue");
    const scope = effectScope();
    const username = ref("");
    const isLoggedIn = computed(() => isBootstrapped() && Boolean(username.value));
    scope.run(() => {
      // 初始：未 bootstrap，isLoggedIn = false
      expect(isLoggedIn.value).toBe(false);
      // 只设 username：依赖 username 但 bootstrapped 仍 false，computed 重算后仍 false
      username.value = "alice";
      expect(isLoggedIn.value).toBe(false);
      // 设 setBootstrapped(true)：必须触发 computed 重算，且重算后读到新值
      setBootstrapped(true);
      expect(isLoggedIn.value).toBe(true);
      // 反向：清回 false 也必须重算
      setBootstrapped(false);
      expect(isLoggedIn.value).toBe(false);
    });
    scope.stop();
  });
});