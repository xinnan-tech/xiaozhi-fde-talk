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

/** 旧版一次性清理：迁移前版本残留的 localStorage user-info（含 accessToken
 *  / refreshToken 明文）必须立即删掉，避免 XSS 一次拿到执行权就把 token 偷走。
 *  F5 / 启动会调一次，幂等。 */
function migrateStaleStorage(): void {
  storageLocal().removeItem("user-info");
}

/** 当前会话是否已登录。乐观判断——只表示 bootstrapSession() 已成功调过
 *  /auth/me。真实态以后端为准；axios 401 拦截器会在 cookie 失效时清空
 *  Pinia + 跳登录。
 *
 * 必须是 ref（不是 plain let）：home 视图 ``isLoggedIn = computed(() =>
 *  isBootstrapped() && ...)`` 靠 .value 访问让 Vue 追踪响应式依赖。*/
const bootstrapped = ref(false);

export function isBootstrapped(): boolean {
  return bootstrapped.value;
}

export function setBootstrapped(v: boolean): void {
  bootstrapped.value = v;
}

/** bootstrap 结果分类——告诉调用方为什么失败，路由守卫据此决定是否清 session。
 *
 *  - ``authenticated``：cookie 有效 + /auth/me 返 user；Pinia 已写入。
 *  - ``unauthenticated``：cookie 缺失 / 过期 / /auth/me 401；应清 session。
 *  - ``transient_error``：后端 5xx / 网络错；保留 Pinia 当前态，避免后端
 *    短暂抽风时被误判未登录踢出。F5 后下一次 bootstrap 会再尝试。 */
export type BootstrapResult =
  "authenticated" | "unauthenticated" | "transient_error";

/** 从 cookie 重建当前用户信息。调 /auth/me（cookie 自动附）。
 *
 * 失败分两类：
 *  - 401 / cookie 缺失：bootstrapResult = "unauthenticated"，应清 session。
 *  - 5xx / 网络错：bootstrapResult = "transient_error"，保留 Pinia 当前态。
 *
 * 必须在 main.ts 启动 + Router 守卫里各调一次：main.ts 启动时建立首屏态，
 *  守卫负责 F5 后首跳。 */
export async function bootstrapSession(): Promise<BootstrapResult> {
  migrateStaleStorage();
  try {
    const me = await meApi();
    const store = useUserStoreHook();
    store.SET_USERNAME(me.username);
    store.SET_USER_ID(me.id);
    store.SET_ROLE(me.role);
    setBootstrapped(true);
    return "authenticated";
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response
      ?.status;
    if (
      status === 401 ||
      (status === undefined &&
        (err as { message?: string })?.message?.includes("401"))
    ) {
      // 401：cookie 真过期或被吊销，清 session。
      // 兜底分：network error 时 status 也是 undefined，但 message 含 401 字符串。
      setBootstrapped(false);
      return "unauthenticated";
    }
    // 5xx / 网络错 / 其他：保留 Pinia 当前态，仅记 warn。
    console.warn(
      "[bootstrapSession] transient error, keeping session:",
      status ?? (err as Error)?.message
    );
    return "transient_error";
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
