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

    /** 主动登出：先撤销 refresh token（best-effort），再清本地状态并跳转。 */
    async logOut() {
      const refreshToken = this.refreshToken;
      if (refreshToken) {
        try {
          await logoutApi({ refresh_token: refreshToken });
        } catch {
          // 后端撤销失败不应阻塞前端清状态——本地 token 反正已废弃。
        }
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
