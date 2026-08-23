import Cookies from "js-cookie";
import { useUserStoreHook } from "@/store/modules/user";
import { storageLocal } from "@pureadmin/utils";

export interface DataInfo {
  /** token */
  accessToken: string;
  /** 用户名 */
  username: string;
  userId?: string;
  role?: "admin" | "user";
}

export const userKey = "user-info";
export const TokenKey = "authorized-token";

/** 获取`token` */
export function getToken(): DataInfo | null {
  const userInfo = storageLocal().getItem<DataInfo>(userKey);
  // 升级兼容：旧 token 无 role/userId 字段会让路由守卫误判 admin 为 user
  // → 立即清掉强制重登。Fix 7
  if (
    userInfo?.accessToken &&
    (userInfo.role === undefined || userInfo.userId === undefined)
  ) {
    removeToken();
    return null;
  }
  if (userInfo?.accessToken) return userInfo;

  // 清理没有对应本地用户信息的旧 cookie，避免被误判为登录状态。
  Cookies.remove(TokenKey);
  return null;
}

/**
 * @description 设置访问令牌和用户名
 */
export function setToken(data: DataInfo) {
  const { accessToken, username, userId, role } = data;
  const tokenInfo = JSON.stringify({ accessToken, username, userId, role });

  Cookies.set(TokenKey, tokenInfo);
  const store = useUserStoreHook();
  store.SET_ACCESS_TOKEN(accessToken);
  store.SET_USERNAME(username);
  store.SET_USER_ID(userId ?? "");
  store.SET_ROLE(role ?? "user");
  storageLocal().setItem(userKey, { accessToken, username, userId, role });
}

/** 删除`token`以及key值为`user-info`的localStorage信息 */
export function removeToken() {
  Cookies.remove(TokenKey);
  storageLocal().removeItem(userKey);
}

/** 格式化token（jwt格式） */
export const formatToken = (token: string): string => {
  return "Bearer " + token;
};

/** 当前登录用户是否可操作 */
export const hasPerms = (value: string | Array<string>): boolean => {
  return Boolean(value && useUserStoreHook().accessToken);
};
