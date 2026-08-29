import { describe, expect, it, vi, beforeEach } from "vitest";
import { usePermissionStoreHook } from "@/store/modules/permission";
import { useUserStoreHook } from "@/store/modules/user";

// 源码的 usePermissionStoreHook() 拿的是单例 pinia 上的实例。
// 测试也用 Hook 走同一个实例；用 $reset() 隔离 state。
function makeRoute(
  name: string,
  meta: Record<string, any> = {},
  children: any[] = []
) {
  return { name, path: `/${name}`, meta, children };
}

describe("stores/PermissionStore — state init", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
  });

  it("默认 registrationAllowed=false / wholeMenus=[] / cachePageList=[]", () => {
    const store = usePermissionStoreHook();
    expect(store.registrationAllowed).toBe(false);
    expect(store.wholeMenus).toEqual([]);
    expect(store.cachePageList).toEqual([]);
  });
});

describe("stores/PermissionStore — handleWholeMenus + role filter", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("user 角色下：admin-only 路由被过滤", () => {
    const perm = usePermissionStoreHook();
    const routes = [
      makeRoute("TestHomeU", { title: "Home", showLink: true, rank: 1 }),
      makeRoute("TestAdminU", {
        title: "Admin",
        showLink: true,
        rank: 2,
        roles: ["admin"]
      })
    ];
    perm.handleWholeMenus(routes);

    const names = perm.wholeMenus.map((m: any) => m.name);
    expect(names).toContain("TestHomeU");
    expect(names).not.toContain("TestAdminU");
  });

  it("admin 角色下：admin-only 路由可见", () => {
    const user = useUserStoreHook();
    user.SET_ROLE("admin");

    const perm = usePermissionStoreHook();
    const routes = [
      makeRoute("TestHomeA", { title: "Home", showLink: true, rank: 1 }),
      makeRoute("TestAdminA", {
        title: "Admin",
        showLink: true,
        rank: 2,
        roles: ["admin"]
      })
    ];
    perm.handleWholeMenus(routes);

    const names = perm.wholeMenus.map((m: any) => m.name);
    expect(names).toContain("TestHomeA");
    expect(names).toContain("TestAdminA");
  });
});

describe("stores/PermissionStore — requiresRegistrationAllowed filter", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("registrationAllowed=false → 注册专属路由被过滤", () => {
    const user = useUserStoreHook();
    user.SET_ROLE("admin");

    const perm = usePermissionStoreHook();
    const routes = [
      makeRoute("HomeG", { title: "Home", showLink: true, rank: 1 }),
      makeRoute("UserAdminG", {
        title: "UserAdmin",
        showLink: true,
        rank: 2,
        requiresRegistrationAllowed: true
      })
    ];

    perm.handleWholeMenus(routes);
    const names = perm.wholeMenus.map((m: any) => m.name);
    expect(names).toContain("HomeG");
    expect(names).not.toContain("UserAdminG");
  });

  it("setRegistrationAllowed(true) 后再 handleWholeMenus：注册专属路由出现", () => {
    // 源码 setRegistrationAllowed 内部 handleWholeMenus([]) 会丢外部 routes，
    // 真实用法：setRegistrationAllowed(true) 后再 handleWholeMenus(routes)。
    const user = useUserStoreHook();
    user.SET_ROLE("admin");

    const perm = usePermissionStoreHook();
    perm.setRegistrationAllowed(true);
    expect(perm.registrationAllowed).toBe(true);

    const routes = [
      makeRoute("HomeH", { title: "Home", showLink: true, rank: 1 }),
      makeRoute("UserAdminH", {
        title: "UserAdmin",
        showLink: true,
        rank: 2,
        requiresRegistrationAllowed: true
      })
    ];
    perm.handleWholeMenus(routes);

    const names = perm.wholeMenus.map((m: any) => m.name);
    expect(names).toContain("HomeH");
    expect(names).toContain("UserAdminH");
  });
});

describe("stores/PermissionStore — setRegistrationAllowed early return", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
  });

  it("从 false → false：不调 handleWholeMenus（early return）", () => {
    const perm = usePermissionStoreHook();
    expect(perm.registrationAllowed).toBe(false);
    const spy = vi.spyOn(perm, "handleWholeMenus");
    perm.setRegistrationAllowed(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("从 false → true：调 handleWholeMenus", () => {
    const perm = usePermissionStoreHook();
    expect(perm.registrationAllowed).toBe(false);
    const spy = vi.spyOn(perm, "handleWholeMenus");
    perm.setRegistrationAllowed(true);
    expect(spy).toHaveBeenCalled();
    expect(perm.registrationAllowed).toBe(true);
  });
});

describe("stores/PermissionStore — cacheOperate", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
  });

  it("add 添加到 cachePageList", () => {
    const perm = usePermissionStoreHook();
    perm.cacheOperate({ mode: "add", name: "Foo" });
    expect(perm.cachePageList).toContain("Foo");
  });

  it("add 重复添加：cachePageList.includes 守住，不重复", () => {
    const perm = usePermissionStoreHook();
    perm.cacheOperate({ mode: "add", name: "X" });
    perm.cacheOperate({ mode: "add", name: "X" });
    expect(perm.cachePageList.filter(n => n === "X").length).toBe(1);
  });

  it("delete 从 cachePageList 移除", () => {
    const perm = usePermissionStoreHook();
    perm.cacheOperate({ mode: "add", name: "Foo" });
    perm.cacheOperate({ mode: "delete", name: "Foo" });
    expect(perm.cachePageList).not.toContain("Foo");
  });

  it("refresh 等价 delete（强制重缓存）", () => {
    const perm = usePermissionStoreHook();
    perm.cacheOperate({ mode: "add", name: "Foo" });
    perm.cacheOperate({ mode: "refresh", name: "Foo" });
    expect(perm.cachePageList).not.toContain("Foo");
  });
});

describe("stores/PermissionStore — clearAllCachePage", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
  });

  it("清空 wholeMenus 和 cachePageList", () => {
    const perm = usePermissionStoreHook();
    perm.wholeMenus = [{ name: "x" }] as any;
    perm.cacheOperate({ mode: "add", name: "Foo" });

    perm.clearAllCachePage();
    expect(perm.wholeMenus).toEqual([]);
    expect(perm.cachePageList).toEqual([]);
  });
});

describe("stores/PermissionStore — getter currentRole", () => {
  beforeEach(() => {
    usePermissionStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("从 useUserStoreHook().role 读", () => {
    const user = useUserStoreHook();
    user.SET_ROLE("admin");
    const perm = usePermissionStoreHook();
    expect(perm.currentRole).toBe("admin");

    user.SET_ROLE("user");
    expect(perm.currentRole).toBe("user");
  });
});
