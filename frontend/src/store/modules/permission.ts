import { defineStore } from "pinia";
import type { RouteRecordName } from "vue-router";
import {
  type cacheType,
  store,
  ascending,
  filterTree,
  constantMenus,
  formatFlatteningRoutes
} from "../utils";
import { useUserStoreHook } from "./user";

/** 递归按 meta.roles + meta.requiresRegistrationAllowed 过滤菜单。
 *  - meta.roles 未设或空数组 → 所有已登录用户可见
 *  - meta.roles 命中用户当前角色 → 可见
 *  - meta.requiresRegistrationAllowed=true → 仅当 store.registrationAllowed=true 时可见
 */
function filterMenuByUserRole(
  menus: any[],
  role: string,
  registrationAllowed: boolean
): any[] {
  return menus
    .filter((item: any) => {
      const requiredRoles = item.meta?.roles as string[] | undefined;
      if (requiredRoles && requiredRoles.length > 0) {
        if (!requiredRoles.includes(role)) return false;
      }
      if (
        item.meta?.requiresRegistrationAllowed === true &&
        !registrationAllowed
      ) {
        return false;
      }
      return true;
    })
    .map((item: any) => {
      if (item.children) {
        item.children = filterMenuByUserRole(
          item.children,
          role,
          registrationAllowed
        );
      }
      return item;
    });
}

export const usePermissionStore = defineStore("pure-permission", {
  state: () => ({
    // 静态路由生成的菜单
    constantMenus,
    // 整体路由生成的菜单（静态、动态）
    wholeMenus: [] as any[],
    // 整体路由（一维数组格式）
    flatteningRoutes: [] as any[],
    // 缓存页面keepAlive
    cachePageList: [] as RouteRecordName[],
    // allow_registration 当前值：从 /api/v1/auth/registration-status 拉取，
    // 用于过滤「用户管理」菜单——管理员开启注册时才显示。
    registrationAllowed: false
  }),
  getters: {
    currentRole(): string {
      return useUserStoreHook().role ?? "user";
    }
  },
  actions: {
    /** 组装整体路由生成的菜单 */
    handleWholeMenus(routes: any[]) {
      const all = ascending(this.constantMenus.concat(routes));
      this.wholeMenus = filterMenuByUserRole(
        filterTree(all),
        this.currentRole,
        this.registrationAllowed
      );
      this.flatteningRoutes = formatFlatteningRoutes(
        this.constantMenus.concat(routes) as any
      );
    },
    /** 重新触发菜单过滤（用户角色或注册开关变化时调用） */
    applyMenuFilter() {
      this.handleWholeMenus([]);
    },
    /** 写入 allow_registration 当前值并刷新菜单。 */
    setRegistrationAllowed(allowed: boolean) {
      if (this.registrationAllowed === allowed) return;
      this.registrationAllowed = allowed;
      this.handleWholeMenus([]);
    },
    /** 清理页面缓存 */
    clearCache() {
      this.cachePageList = [];
    },
    cacheOperate({ mode, name }: cacheType) {
      const delIndex = this.cachePageList.findIndex(v => v === name);
      switch (mode) {
        case "refresh":
          this.cachePageList = this.cachePageList.filter(v => v !== name);
          break;
        case "add":
          if (!this.cachePageList.includes(name)) {
            this.cachePageList.push(name);
          }
          break;
        case "delete":
          delIndex !== -1 && this.cachePageList.splice(delIndex, 1);
          break;
      }
    },
    /** 清空缓存页面 */
    clearAllCachePage() {
      this.wholeMenus = [];
      this.cachePageList = [];
    }
  }
});

export function usePermissionStoreHook() {
  return usePermissionStore(store);
}
