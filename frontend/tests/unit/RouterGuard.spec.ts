import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useUserStoreHook } from "@/store/modules/user";
import router from "@/router";

const userKey = "user-info";

type TokenShape = {
  accessToken: string;
  username: string;
  userId: string;
  role: "admin" | "user";
};

/** getToken()（src/router/index.ts:128 调用）从 localStorage 读；
 * 不能只 SET_ACCESS_TOKEN——那样只动 Pinia state，guard 仍然判未登录。
 * setToken 走 storageLocal()，但 storageLocal 在 vitest+happy-dom 下
 * isClient()=false 走内存空 storage，绕开它直接写 localStorage。 */
function setTokenInStorage(token: TokenShape) {
  window.localStorage.setItem(userKey, JSON.stringify(token));
}

function clearToken() {
  window.localStorage.removeItem(userKey);
}

describe("router guards", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    clearToken();
  });

  afterEach(() => {
    clearToken();
  });

  it("普通用户访问 /system 被重定向到 /error/403", async () => {
    setTokenInStorage({
      accessToken: "dummy.token.value",
      username: "alice",
      userId: "u-1",
      role: "user"
    });
    useUserStoreHook().SET_ROLE("user");

    await router.push("/system").catch(() => {});
    expect(router.currentRoute.value.path).toMatch(/\/error\/403/);
  });

  it("admin 访问 /system 不会被角色守卫拦截", async () => {
    setTokenInStorage({
      accessToken: "admin.token.value",
      username: "root",
      userId: "u-0",
      role: "admin"
    });
    useUserStoreHook().SET_ROLE("admin");

    await router.push("/system").catch(() => {});
    // /system 重定向到 /system/config；二者都标 roles:["admin"]，guard 放行后
    // 落点要么是 /system/config（redirect 命中）要么是 /system（声明本身）。
    expect(router.currentRoute.value.path).not.toMatch(/\/error\/403/);
  });

  it("admin 访问 /admin/users 不会被角色守卫拦截", async () => {
    setTokenInStorage({
      accessToken: "admin.token.value",
      username: "root",
      userId: "u-0",
      role: "admin"
    });
    useUserStoreHook().SET_ROLE("admin");

    await router.push("/admin/users").catch(() => {});
    expect(router.currentRoute.value.path).not.toMatch(/\/error\/403/);
  });

  it("guest 访问 /system（不在白名单）被重定向到 /home", async () => {
    // 未登录 → getToken() 返回 null → 走白名单分支 → /system 不在白名单 → /home
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

  it("旧 token 缺 role 字段 → getToken 视作未登录 → 被踢回 /home", async () => {
    // 模拟「升级前留下的旧 token」：只有 accessToken+username，缺 role/userId
    window.localStorage.setItem(
      userKey,
      JSON.stringify({
        accessToken: "legacy.token",
        username: "alice"
      })
    );
    await router.push("/system").catch(() => {});
    expect(router.currentRoute.value.path).toBe("/home");
    // 同时旧 token 已被 removeToken() 清掉
    expect(window.localStorage.getItem(userKey)).toBeNull();
  });
});