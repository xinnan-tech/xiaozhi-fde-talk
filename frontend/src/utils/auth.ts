import { ref } from "vue";
import { meApi } from "@/api/user";
import { useUserStoreHook } from "@/store/modules/user";
import { storageLocal } from "@pureadmin/utils";

/**
 * HttpOnly cookie 模型下前端会话工具。前端 JS 不持任何 token——
 *
 *   - access_token / refresh_token 全部由浏览器以 HttpOnly cookie 形式持有，
 *     document.cookie 看不到 HttpOnly 项，JS 物理不可读。
 *   - axios 走 withCredentials:true，浏览器在同源请求自动附 cookie；跨域要
 *     后端 CORS allow_credentials=True + 显式 origin 白名单（已配）。
 *   - WS 握手升级时浏览器自动带（同源路径），后端优先读 cookie + 兼容
 *     bearer.<token> subprotocol 兜底（脚本 / chaos 客户端）。
 *   - 401 静默续 access：调 POST /auth/refresh，refresh cookie 自动附，无 body。
 *   - F5 / 关页面后 cookie 仍在；main.ts 启动 + 路由守卫首跳前各调一次
 *     bootstrapSession() 重建 Pinia 用户字段（username / role / userId）。
 *
 * 本文件只剩「会话生命周期」API：bootstrapSession / isBootstrapped /
 * setBootstrapped / clearSession / hasPerms。setToken / getToken / removeToken
 * / formatToken / 旧 localStorage 全部移除——cookie 由浏览器管，前端没必要
 * 再持任何 token。
 */

/** 旧版一次性清理：从 #212 之前的版本升级上来的用户，localStorage 里残留
 *  的 user-info（含 accessToken / refreshToken 明文）必须立即删掉，避免
 *  XSS 一次拿到执行权就把 token 偷走。F5 / 启动会调一次，幂等。 */
function migrateStaleStorage(): void {
  storageLocal().removeItem("user-info");
}

/** 当前会话是否已登录。乐观判断——只表示 bootstrapSession() 已成功调过
 *  /auth/me。真实态以后端为准；axios 401 拦截器会在 cookie 失效时清空
 *  Pinia + 跳登录。
 *
 * 必须是 ref 不是 plain let：home 视图的 ``isLoggedIn = computed(() =>
 * isBootstrapped() && ...)`` 要靠 .value 访问追踪响应式依赖。改回 let
 * 会让 computed 算过一次 false 后不再追，登录后 ``.user-avatar.online``
 * 永远不出现——见 e2e 场景 A / D-1 / incognito-login 三处同时翻车。*/
const bootstrapped = ref(false);
export function isBootstrapped(): boolean {
  return bootstrapped.value;
}

export function setBootstrapped(v: boolean): void {
  bootstrapped.value = v;
}

/** 从 cookie 重建当前用户信息。调 /auth/me（cookie 自动附）；失败抛异常，
 *  由调用方走「未登录」分支。成功则把 user 字段写进 Pinia store 并标记
 *  已 bootstrap，避免后续路由切换重复调。
 *
 * 必须在 main.ts 启动 + Router 守卫里各调一次：main.ts 启动时建立首屏态，
 * 守卫负责 F5 后首跳。 */
export async function bootstrapSession(): Promise<boolean> {
  migrateStaleStorage();
  try {
    const me = await meApi();
    const store = useUserStoreHook();
    store.SET_USERNAME(me.username);
    store.SET_USER_ID(me.id);
    store.SET_ROLE(me.role);
    setBootstrapped(true);
    return true;
  } catch {
    setBootstrapped(false);
    return false;
  }
}

/** 清 Pinia + 重置 bootstrap 标志。logout / 401 过期路径复用。
 *  HttpOnly cookie 由后端通过 Set-Cookie Max-Age=0 清除，前端不动 cookie。 */
export function clearSession(): void {
  setBootstrapped(false);
  const store = useUserStoreHook();
  store.SET_USERNAME("");
  store.SET_USER_ID("");
  store.SET_ROLE("user");
}

/** UI 权限判据：当前是否已登录。语义上等同 isBootstrapped()——保留命名
 *  是因为 directives/perms 和 RePerms 组件按「按钮 / 区块」粒度控权，
 *  鉴权点不必区分具体 role。 */
export const hasPerms = (_value: string | Array<string>): boolean =>
  isBootstrapped();