import Cookies from "js-cookie";
import { useUserStoreHook } from "@/store/modules/user";
import { storageLocal } from "@pureadmin/utils";

/**
 * JWT 存储安全说明
 * ------------------------
 * 当前 token 同时写入 `storageLocal`（localStorage 代理）与 `js-cookie`：
 * 后端 /auth/login 与 /auth/register 当前以 JSON 返回 Bearer token，前端无
 * httpOnly cookie 可用，只能在 JS 域可读的位置落盘。
 *
 * 风险：任意 XSS（含 LLM 输出中的 <img onerror>、依赖链供应链等）都能读走
 * accessToken → 攻击者拿到完整会话。`frontend/src/views/report/index.vue`
 * 是已知 XSS 入口，其 markdown-it 已硬化为 `html:false`（详见该文件同
 * 段注释 + 本仓库 "fix(report): 关闭 markdown-it html 直通…" 提交）。
 *
 * 计划迁移：后端 /auth/login 与 /auth/register 响应头追加
 * `Set-Cookie: authorized-token=...; HttpOnly; SameSite=Lax; Secure`，
 * 前端移除 localStorage / js-cookie 落盘并改读 `withCredentials` 请求。
 * 同时后端需引入 CSRF token（双提交 cookie 或 synchronizer token pattern）
 * 应对跨站请求伪造。跟踪 issue 单独建。
 */

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
