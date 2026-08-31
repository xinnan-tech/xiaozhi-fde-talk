import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import Cookies from "js-cookie";

// storageLocal() 在测试环境 isClient() === false → 走不到 window.localStorage。
// 在测试里我们模拟一个同形的 storage：基于一个简单的内部 map，提供
// getItem / setItem / removeItem 三方法，行为与真实接口一致（getItem 不存在
// 时返回 null，跟 @pureadmin/utils 的 storageLocal 一致）。
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

// useUserStoreHook 是 Pinia store 上的钩子，setToken 内部要调它的 SET_* 写动作。
// 这里 stub 成一个 no-op 对象，让 setToken 不依赖 Pinia 实例。
vi.mock("@/store/modules/user", () => ({
  useUserStoreHook: () => ({
    SET_ACCESS_TOKEN: vi.fn(),
    SET_USERNAME: vi.fn(),
    SET_USER_ID: vi.fn(),
    SET_ROLE: vi.fn(),
    accessToken: ""
  })
}));

import { setToken, getToken, removeToken, formatToken, userKey, TokenKey } from "@/utils/auth";

function clearAll() {
  memStore.clear();
  // js-cookie 没有提供 clearAll，但 remove 已知键即可
  Cookies.remove(TokenKey);
  // 也清一下 happy-dom 自己的 localStorage，避免跨 spec 串扰
  window.localStorage.clear();
}

describe("utils/auth — setToken / getToken / removeToken", () => {
  beforeEach(() => clearAll());
  afterEach(() => clearAll());

  it("setToken 写入内存 + Cookie", () => {
    setToken({
      accessToken: "tok-1",
      username: "alice",
      userId: "u-1",
      role: "admin"
    });
    expect(memStore.get(userKey)).toEqual({
      accessToken: "tok-1",
      username: "alice",
      userId: "u-1",
      role: "admin"
    });
    expect(Cookies.get(TokenKey)).toBe(
      JSON.stringify({
        accessToken: "tok-1",
        username: "alice",
        userId: "u-1",
        role: "admin"
      })
    );
  });

  it("setToken 后 getToken 返回完整 DataInfo", () => {
    setToken({
      accessToken: "tok-2",
      username: "bob",
      userId: "u-2",
      role: "user"
    });
    expect(getToken()).toEqual({
      accessToken: "tok-2",
      username: "bob",
      userId: "u-2",
      role: "user"
    });
  });

  it("getToken：localStorage 旧 token 缺 role → removeToken + 返回 null", () => {
    memStore.set(userKey, { accessToken: "old", username: "x" });
    expect(getToken()).toBeNull();
    expect(memStore.has(userKey)).toBe(false);
  });

  it("getToken：localStorage 旧 token 缺 userId → removeToken + 返回 null", () => {
    memStore.set(userKey, {
      accessToken: "old",
      username: "x",
      role: "user"
    });
    expect(getToken()).toBeNull();
    expect(memStore.has(userKey)).toBe(false);
  });

  it("getToken：localStorage 为空但 cookie 仍存在 → 清 cookie + 返回 null", () => {
    Cookies.set(TokenKey, "stale-cookie-value");
    expect(getToken()).toBeNull();
    expect(Cookies.get(TokenKey)).toBeUndefined();
  });

  it("getToken：完全空 → 返回 null", () => {
    expect(getToken()).toBeNull();
  });

  it("removeToken 清空内存 + Cookie", () => {
    setToken({
      accessToken: "tok-3",
      username: "carol",
      userId: "u-3",
      role: "user"
    });
    expect(memStore.has(userKey)).toBe(true);
    expect(Cookies.get(TokenKey)).toBeTruthy();
    removeToken();
    expect(memStore.has(userKey)).toBe(false);
    expect(Cookies.get(TokenKey)).toBeUndefined();
  });

  it("setToken 写 Cookie 时挂 Secure + SameSite=Strict（缓解 XSS 一次性偷 refresh）", () => {
    // document.cookie 不暴露 Secure / SameSite 这些属性（它们只在 Set-Cookie 头里），
    // 所以直接 spyOn Cookies.set 抓 options 参数来断言。
    const spy = vi.spyOn(Cookies, "set");
    try {
      setToken({
        accessToken: "tok-sec",
        refreshToken: "rt-sec",
        username: "alice",
        userId: "u-1",
        role: "user"
      });
      expect(spy).toHaveBeenCalledWith(
        TokenKey,
        expect.any(String),
        expect.objectContaining({
          secure: true,
          sameSite: "Strict"
        })
      );
    } finally {
      spy.mockRestore();
    }
  });

  it("setToken：role / userId 缺省时存原值（undefined，不强行给默认值）", () => {
    // 源码：storageLocal().setItem(userKey, { accessToken, username, userId, role })，
    // 没有 userId/role 时直接是 undefined；默认 "" / "user" 只作用于 store 的 SET_USER_ID / SET_ROLE，
    // 不写到存储介质里。这样 getToken 下次还能命中「缺 role/userId → 强制重登」的升级兼容分支。
    setToken({ accessToken: "tok-4", username: "dave" });
    const stored = memStore.get(userKey);
    expect(stored.userId).toBeUndefined();
    expect(stored.role).toBeUndefined();
    expect(stored.refreshToken).toBeUndefined();
  });

  it("setToken 写入 refreshToken + getToken 完整 round-trip", () => {
    // 401 静默续 access 的前提：refreshToken 跟 accessToken 一起落盘，重启浏览器后还能取到。
    setToken({
      accessToken: "at-1",
      refreshToken: "rt-1",
      username: "alice",
      userId: "u-1",
      role: "user"
    });
    const got = getToken();
    expect(got?.accessToken).toBe("at-1");
    expect(got?.refreshToken).toBe("rt-1");
    expect(got?.userId).toBe("u-1");
    expect(got?.role).toBe("user");
  });
});

describe("utils/auth — formatToken", () => {
  it('formatToken("x") → "Bearer x"', () => {
    expect(formatToken("abc")).toBe("Bearer abc");
  });

  it("formatToken(空串) → 'Bearer '", () => {
    expect(formatToken("")).toBe("Bearer ");
  });
});