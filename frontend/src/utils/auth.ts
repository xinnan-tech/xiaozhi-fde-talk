import Cookies from "js-cookie";
import { useUserStoreHook } from "@/store/modules/user";
import { storageLocal } from "@pureadmin/utils";

/**
 * JWT 存储安全说明
 * ------------------------
 * accessToken 走 `storageLocal`（localStorage 代理），refreshToken 只走
 * `js-cookie`（Secure + SameSite=Strict）。两个介质的风险：
 *
 * - localStorage：任意同源 JS 都可读，XSS 一次即拿到 accessToken（短期 TTL）。
 * - cookie：Secure 强制 https；SameSite=Strict 阻止跨站请求附带 cookie，
 *   但 cookie 本身仍 JS 可读（同源 XSS 仍可拿到 refreshToken）。
 *
 * 风险：任意 XSS（含 LLM 输出中的 <img onerror>、依赖链供应链等）都能读走
 * token。`frontend/src/views/report/index.vue` 是已知 XSS 入口，其
 * markdown-it 已硬化为 `html:false`（详见该文件同段注释 + 本仓库
 * "fix(report): 关闭 markdown-it html 直通…" 提交）。
 *
 * refreshToken 不再写 localStorage（openrz P1.1）：localStorage 始终 JS 可读，
 * 且无 Secure/SameSite 这种网络层缓解。删一处明文向量（30 天 TTL）。cookie
 * 仍临时承担 refreshToken 存储，401 静默续 access 由 getToken() 拼回。
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
  /** refresh token：用于 401 时静默换 access，留空表示旧版登录（无静默续期）。 */
  refreshToken?: string;
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
  if (userInfo?.accessToken) {
    // refreshToken 不进 localStorage（openrz P1.1），仅 cookie 持有。
    // 从 cookie 拼回，让 401 静默续 access 还能取到 refresh token。
    if (!userInfo.refreshToken) {
      const cookieRaw = Cookies.get(TokenKey);
      if (cookieRaw) {
        try {
          const parsed = JSON.parse(cookieRaw) as Partial<DataInfo>;
          if (typeof parsed.refreshToken === "string") {
            userInfo.refreshToken = parsed.refreshToken;
          }
        } catch {
          // cookie 不是合法 JSON（极少见，例如旧版登录留的脏值）→ 忽略，
          // userInfo.refreshToken 保持 undefined，401 走清会话路径。
        }
      }
    }
    return userInfo;
  }

  // 清理没有对应本地用户信息的旧 cookie，避免被误判为登录状态。
  Cookies.remove(TokenKey);
  return null;
}

/**
 * @description 设置访问令牌和用户名
 */
export function setToken(data: DataInfo) {
  const { accessToken, refreshToken, username, userId, role } = data;
  const tokenInfo = JSON.stringify({
    accessToken,
    refreshToken,
    username,
    userId,
    role
  });

  // 临时缓解 XSS 一次即拿到 refresh token（30 天 TTL）的问题。
  // 长期方案见文件顶部 TODO：后端下 httpOnly cookie + CSRF。
  // Secure 强制 https；SameSite=Strict 阻止跨站请求附带 cookie。
  Cookies.set(TokenKey, tokenInfo, {
    secure: true,
    sameSite: "Strict"
  });
  const store = useUserStoreHook();
  store.SET_ACCESS_TOKEN(accessToken);
  store.SET_USERNAME(username);
  store.SET_USER_ID(userId ?? "");
  store.SET_ROLE(role ?? "user");
  // openrz P1.1：refreshToken 不写 localStorage。明文 JS 可读 + 无网络层
  // 缓解，是 XSS 偷 30 天 TTL token 的最佳载体。refreshToken 仅 cookie 持有，
  // 由 getToken() 在读路径拼回。
  storageLocal().setItem(userKey, {
    accessToken,
    username,
    userId,
    role
  } as DataInfo);
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
