import { defineStore } from "pinia";
import { type userType, store, router } from "../utils";
import { type LoginRequest, type LoginResult, loginApi } from "@/api/user";
import { getToken, setToken, removeToken } from "@/utils/auth";

export const useUserStore = defineStore("pure-user", {
  state: (): userType => ({
    // 访问令牌
    accessToken: getToken()?.accessToken ?? "",
    // 用户名
    username: getToken()?.username ?? ""
  }),
  actions: {
    /** 存储访问令牌 */
    SET_ACCESS_TOKEN(accessToken: string) {
      this.accessToken = accessToken;
    },
    /** 存储用户名 */
    SET_USERNAME(username: string) {
      this.username = username;
    },
    /** 登入 */
    async loginByUsername(data: LoginRequest): Promise<LoginResult> {
      const result = await loginApi(data);
      if (result?.access_token) {
        this.SET_ACCESS_TOKEN(result.access_token);
        this.SET_USERNAME(data.username);
        setToken({
          accessToken: result.access_token,
          username: data.username
        });
      }
      return result;
    },
    /** 前端登出（不调用接口） */
    logOut() {
      this.accessToken = "";
      this.username = "";
      removeToken();
      router.push("/home");
    }
  }
});

export function useUserStoreHook() {
  return useUserStore(store);
}
