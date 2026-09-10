import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useUserStoreHook } from "@/store/modules/user";
import router from "@/router";
import { setBootstrapped } from "@/utils/auth";

// /auth/me 走 http.request，mock 避免 axios 打到 localhost。
// vi.mock factory 会被 hoisted，引用顶层 const 会"Cannot access before init"。
// 用 vi.hoisted 把句柄提到 factory 之上。
const { meApiMock } = vi.hoisted(() => ({ meApiMock: vi.fn() }));
vi.mock("@/api/user", async () => {
  const actual = await vi.importActual<typeof import("@/api/user")>("@/api/user");
  return { ...actual, meApi: meApiMock };
});

type SessionShape = {
  username: string;
  userId: string;
  role: "admin" | "user";
};

/** HttpOnly 模型下「登录态」由 isBootstrapped() + Pinia user
 *  字段组成。守卫不再读 localStorage / cookie。直接调 Pinia actions 注入
 *  + setBootstrapped(true) 模拟已登录会话。 */
function seedLogin(session: SessionShape) {
  const store = useUserStoreHook();
  store.SET_USERNAME(session.username);
  store.SET_USER_ID(session.userId);
  store.SET_ROLE(session.role);
  setBootstrapped(true);
}

function clearLogin() {
  const store = useUserStoreHook();
  store.SET_USERNAME("");
  store.SET_USER_ID("");
  store.SET_ROLE("user");
  setBootstrapped(false);
  window.localStorage.clear();
}

describe("router guards (HttpOnly cookie 模型)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    clearLogin();
    // 默认 guest：无 cookie → /auth/me 返 401 → bootstrapSession 返回
    // "unauthenticated" → 守卫走未登录分支跳 /home。
    // 单测可单独覆盖 meApiMock 验证其他分支（transient_error 等）。
    meApiMock.mockReset();
    meApiMock.mockRejectedValue({
      response: { status: 401 },
      message: "Request failed with status code 401"
    });
  });

  afterEach(() => {
    clearLogin();
  });

  it("普通用户访问 /system 被重定向到 /error/403", async () => {
    seedLogin({
      username: "alice",
      userId: "u-1",
      role: "user"
    });

    await router.push("/system").catch(() => {});
    expect(router.currentRoute.value.path).toMatch(/\/error\/403/);
  });

  it("admin 访问 /system 不会被角色守卫拦截", async () => {
    seedLogin({
      username: "root",
      userId: "u-0",
      role: "admin"
    });

    await router.push("/system").catch(() => {});
    expect(router.currentRoute.value.path).not.toMatch(/\/error\/403/);
  });

  it("admin 访问 /admin/users 不会被角色守卫拦截", async () => {
    seedLogin({
      username: "root",
      userId: "u-0",
      role: "admin"
    });

    await router.push("/admin/users").catch(() => {});
    expect(router.currentRoute.value.path).not.toMatch(/\/error\/403/);
  });

  it("guest 访问 /system（不在白名单）被重定向到 /home", async () => {
    // 未登录 → isBootstrapped() false → 走白名单分支 → /system 不在白名单 → /home
    await router.push("/system").catch(() => {});
    expect(router.currentRoute.value.path).toBe("/home");
  });

  it("guest 访问 /report/:id 同样被踢回 /home", async () => {
    await router.push("/report/abc123").catch(() => {});
    expect(router.currentRoute.value.path).toBe("/home");
  });

  it("guest 访问 /home 放行（白名单根）", async () => {
    await router.push("/home").catch(() => {});
    expect(router.currentRoute.value.path).toBe("/home");
  });

  it("guest 访问 /about 放行（白名单）", async () => {
    await router.push("/about").catch(() => {});
    expect(router.currentRoute.value.path).toBe("/about");
  });

  it("isBootstrapped=true 但 role 字段缺失 → 走角色守卫 → /error/403", async () => {
    // 守卫两层校验：isBootstrapped=false → 未登录 → /home；isBootstrapped=true
    // 但 role 不匹配 → 角色守卫 → /error/403。这两条分支独立，不能混淆。
    setBootstrapped(true);
    await router.push("/system").catch(() => {});
    expect(router.currentRoute.value.path).toMatch(/\/error\/403/);
  });
});