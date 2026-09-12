import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useUserStore, isBootstrapped } from "@/store/modules/user";
import { setBootstrapped } from "@/utils/auth";
import * as userApi from "@/api/user";

/**
 * XSS 抗性回归：模拟「恶意脚本拿到执行权」的最坏情形——它能调任意 JS API。
 * 验证以下不变量：
 *  - JS 堆（Pinia store）里找不到任何 JWT
 *  - window.localStorage 里找不到任何 JWT
 *  - document.cookie 不含 HttpOnly 项（cookie 名 + value 都没有）
 *
 * 核心安全声明：access_token / refresh_token 只存在于 HttpOnly cookie——
 * 这是浏览器层强制隔离，JS 物理不可读；本测试只是把这条防线「合约化」
 * 钉死，防止有人未来无意中改回 localStorage。
 */

const apiMocks = vi.hoisted(() => ({
  loginApi: vi.fn(),
  logoutApi: vi.fn()
}));
vi.mock("@/api/user", () => ({
  loginApi: apiMocks.loginApi,
  registerApi: vi.fn(),
  logoutApi: apiMocks.logoutApi,
  meApi: vi.fn(),
  refreshApi: vi.fn(),
  changePasswordApi: vi.fn(),
  registrationStatusApi: vi.fn()
}));
vi.mock("@/router", () => ({
  router: { push: vi.fn() },
  resetRouter: vi.fn(),
  constantMenus: []
}));

// JWT 形状字符串：3 段 base64url 拼接 + 含 sub / exp claim 提升可信度
const JWT_LIKE =
  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1LTEiLCJleHAiOjE5MDAwMDAwMDB9.signature";

function collectAllWindowTokens(): string[] {
  // 把 JS 全部可见的字符串都搜一遍——这是攻击者会跑的 payload
  const haystacks: string[] = [];
  haystacks.push(window.localStorage.getItem("user-info") ?? "");
  haystacks.push(window.localStorage.getItem("authorized-token") ?? "");
  for (let i = 0; i < window.localStorage.length; i++) {
    const k = window.localStorage.key(i);
    if (k) haystacks.push(window.localStorage.getItem(k) ?? "");
  }
  haystacks.push(document.cookie);
  return haystacks.filter(Boolean);
}

describe("XSS resistance — loginByUsername 后 JS 不可见任何 token", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setBootstrapped(false);
    apiMocks.loginApi.mockReset();
    apiMocks.logoutApi.mockReset();
    window.localStorage.clear();
    document.cookie.split(";").forEach(c => {
      const name = c.split("=")[0]?.trim();
      if (name) {
        document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
      }
    });
  });
  afterEach(() => {
    setBootstrapped(false);
  });

  it("loginByUsername 后：Pinia store 字段无 accessToken / refreshToken", async () => {
    // 即便后端响应 body 仍带 token（兼容路径），前端不应该把 token 写进任何状态
    apiMocks.loginApi.mockResolvedValue({
      access_token: JWT_LIKE,
      refresh_token: JWT_LIKE,
      user: { id: "u-1", username: "alice", role: "admin" }
    });
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });

    const stateRecord = store.$state as Record<string, unknown>;
    expect(stateRecord.accessToken).toBeUndefined();
    expect(stateRecord.refreshToken).toBeUndefined();

    // 即便深搜 state（防御未来有人加额外字段），也不该找到 JWT 形状字符串
    const flat = JSON.stringify(stateRecord);
    expect(flat).not.toContain(JWT_LIKE);
  });

  it("loginByUsername 后：window.localStorage 任何 key 都不含 token", async () => {
    apiMocks.loginApi.mockResolvedValue({
      access_token: JWT_LIKE,
      refresh_token: JWT_LIKE,
      user: { id: "u-1", username: "alice", role: "user" }
    });
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });

    const allTokens = collectAllWindowTokens();
    for (const hay of allTokens) {
      expect(hay, "localStorage item 不应含 JWT").not.toContain(JWT_LIKE);
    }
  });

  it("loginByUsername 后：document.cookie 不含 authorized-token / refresh-token", async () => {
    // 模拟 HttpOnly cookie 不被 document.cookie 暴露：
    // 我们手工 setItem 一个非 HttpOnly 的同名 cookie，document.cookie 应该看到；
    // 但生产路径是 HttpOnly——断言不存在普通 cookie 即可。
    apiMocks.loginApi.mockResolvedValue({
      user: { id: "u-1", username: "alice", role: "user" }
    });
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });

    // document.cookie 永远不显示 HttpOnly 项；同理也不应出现 token 名。
    expect(document.cookie).not.toContain("authorized-token");
    expect(document.cookie).not.toContain("refresh-token");
  });

  it("logOut 后：Pinia store 立即清空，token 不可从状态恢复", async () => {
    apiMocks.loginApi.mockResolvedValue({
      user: { id: "u-1", username: "alice", role: "admin" }
    });
    apiMocks.logoutApi.mockResolvedValue({ ok: true });
    const store = useUserStore();
    await store.loginByUsername({ username: "alice", password: "x" });
    expect(store.username).toBe("alice");

    store.logOut();

    expect(store.username).toBe("");
    expect(store.userId).toBe("");
    expect(store.role).toBe("user");
    expect(isBootstrapped()).toBe(false);

    // logOut 不应把 token 写到任何 localStorage 路径
    const allTokens = collectAllWindowTokens();
    for (const hay of allTokens) {
      expect(hay).not.toContain(JWT_LIKE);
    }
  });
});