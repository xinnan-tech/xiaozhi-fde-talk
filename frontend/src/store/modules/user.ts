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
import { getToken, setToken, removeToken } from "@/utils/auth";

export const useUserStore = defineStore("pure-user", {
  state: (): userType => ({
    accessToken: getToken()?.accessToken ?? "",
    refreshToken: getToken()?.refreshToken ?? "",
    username: getToken()?.username ?? "",
    userId: getToken()?.userId ?? "",
    role: getToken()?.role ?? "user"
  }),
  actions: {
    SET_ACCESS_TOKEN(accessToken: string) {
      this.accessToken = accessToken;
    },
    /** 用 refresh token 换到新 access 后回填；refresh 自身不变。 */
    SET_REFRESH_TOKEN(refreshToken: string) {
      this.refreshToken = refreshToken;
    },
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
      if (result?.access_token) {
        this.SET_ACCESS_TOKEN(result.access_token);
        this.SET_REFRESH_TOKEN(result.refresh_token ?? "");
        this.SET_USERNAME(data.username);
        this.SET_USER_ID(result.user.id);
        this.SET_ROLE(result.user.role);
        setToken({
          accessToken: result.access_token,
          refreshToken: result.refresh_token,
          username: data.username,
          userId: result.user.id,
          role: result.user.role
        });
      }
      return result;
    },

    async registerByUsername(data: RegisterRequest): Promise<LoginResult> {
      const result = await registerApi(data);
      if (result?.access_token) {
        this.SET_ACCESS_TOKEN(result.access_token);
        this.SET_REFRESH_TOKEN(result.refresh_token ?? "");
        this.SET_USERNAME(result.user.username);
        this.SET_USER_ID(result.user.id);
        this.SET_ROLE(result.user.role);
        setToken({
          accessToken: result.access_token,
          refreshToken: result.refresh_token,
          username: result.user.username,
          userId: result.user.id,
          role: result.user.role
        });
      }
      return result;
    },

    /** 主动登出：先 enqueue 后端撤销（fire-and-forget），同时立刻清本地状态并跳转。
     *
     * 注意：撤销请求是 fire-and-forget，不 await。原因：
     * 1. 后端撤销（写 jti 黑名单）失败不应阻塞用户登出体验——本地 token 反正已废弃；
     * 2. 如果 await，PureHttp 默认 60s 超时期间用户卡在原路由、菜单仍为登录态；
     * 3. 关页面后 refresh_token 没被清，下次开页面用户仍是登录态——「登出没生效」。
     *
     * catch 至少 console.warn 上报，避免后端撤销失败（429 / 5xx）被静默吃掉，
     * 留下 refresh token 在剩余 TTL（默认 30 天）内仍可换 access 的口子。
     *
     * openrz P1.2：console.warn 不传整个 AxiosError。e.config.data.refresh_token
     * 与 e.config.headers.Authorization 会随对象展开落进浏览器 console 与日志
     * 聚合器（Sentry/Datadog 等），refresh/access token 直接被持久化。改为只
     * 打 status / message，避免泄露 token。
     */
    logOut() {
      const refreshToken = this.refreshToken;
      if (refreshToken) {
        logoutApi({ refresh_token: refreshToken }).catch(e => {
          // eslint-disable-next-line no-console
          console.warn(
            "[user.logOut] revoke failed:",
            e?.response?.status ?? e?.message ?? "unknown"
          );
        });
      }
      this.accessToken = "";
      this.refreshToken = "";
      this.username = "";
      this.userId = "";
      this.role = "user";
      removeToken();
      router.push("/home");
    }
  }
});

export function useUserStoreHook() {
  return useUserStore(store);
}
