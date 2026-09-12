import { defineStore } from "pinia";
import { type userType, store, router } from "../utils";
import {
  type LoginRequest,
  type LoginResult,
  type RegisterRequest,
  loginApi,
  registerApi,
  logoutApi
} from "@/api/user";
import {
  bootstrapSession,
  isBootstrapped,
  setBootstrapped
} from "@/utils/auth";

export const useUserStore = defineStore("pure-user", {
  /** 状态只剩 user 元数据——accessToken / refreshToken 由 HttpOnly cookie 持有，
   * JS 不可读也不应在 Pinia 留副本。F5 / 关页面后调 bootstrapSession()
   * 从 /auth/me 重建 user 字段。 */
  state: (): userType => ({
    username: "",
    userId: "",
    role: "user"
  }),
  actions: {
    SET_USERNAME(username: string) {
      this.username = username;
    },
    SET_USER_ID(userId: string) {
      this.userId = userId;
    },
    SET_ROLE(role: "admin" | "user") {
      this.role = role;
    },

    async loginByUsername(data: LoginRequest): Promise<LoginResult> {
      const result = await loginApi(data);
      if (result?.user) {
        this.SET_USERNAME(data.username);
        this.SET_USER_ID(result.user.id);
        this.SET_ROLE(result.user.role);
        setBootstrapped(true);
      }
      return result;
    },

    async registerByUsername(data: RegisterRequest): Promise<LoginResult> {
      const result = await registerApi(data);
      if (result?.user) {
        this.SET_USERNAME(result.user.username);
        this.SET_USER_ID(result.user.id);
        this.SET_ROLE(result.user.role);
        setBootstrapped(true);
      }
      return result;
    },

    /** 主动登出：调后端撤销 refresh jti + 清 HttpOnly cookie + 清 Pinia + 跳转。
     *
     * 不 await 撤销的原因（见 README：fire-and-forget 设计）：
     *  - 后端撤销失败不应阻塞用户体验；本地 cookie 反正已清；
     *  - await 期间 PureHttp 60s 超时卡住路由；
     *  - 不立刻清 cookie → 关页面后 refresh 还在，30 天 TTL 内可换 access。
     *
     * console.warn 只打 status / message，避免传整个 AxiosError 时
     * e.config.headers.Authorization 落进日志聚合器泄露 token
     * （openrz P1.2）。
     *
     * 直接用 ``this`` 写 Pinia 字段（不是 clearSession() 通过 useUserStoreHook
     * 写单例 pinia）——Vue/Pinia 的 ``this`` 指向当前活跃 pinia 实例本身，
     * 兼容测试里 setActivePinia 的隔离；clearSession() 里的 useUserStoreHook
     * 只动单例 pinia，会漏改活跃实例。
     */
    logOut() {
      logoutApi()
        .catch(e => {
          // eslint-disable-next-line no-console
          console.warn(
            "[user.logOut] revoke failed:",
            e?.response?.status ?? e?.message ?? "unknown"
          );
        });
      this.username = "";
      this.userId = "";
      this.role = "user";
      setBootstrapped(false);
      router.push("/home");
    }
  }
});

export function useUserStoreHook() {
  return useUserStore(store);
}

/** 暴露给 main.ts / Router 守卫复用：F5 后从 /auth/me 重建会话。 */
export { bootstrapSession, isBootstrapped };