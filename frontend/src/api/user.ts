import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

export type LoginRequest = {
  /** 用户名 */
  username: string;
  /** 密码 */
  password: string;
};

export type UserInfo = {
  id: string;
  username: string;
  role: "admin" | "user";
};

/** HttpOnly cookie 模型下，access_token / refresh_token 由浏览器
 *  以 cookie 持有。响应 body 里后端仍兼容返 token 字段（scripts / 测试用），
 *  前端不读、也不存——仅依赖 user 字段完成 UI 跳转。 */
export type LoginResult = {
  user: UserInfo;
};

/** 登录：cookie 自动由后端 Set-Cookie 下发。 */
export const loginApi = (data: LoginRequest) => {
  return http.request<LoginResult>("post", baseUrlApi("/api/v1/auth/login"), {
    data
  });
};

export type RegistrationStatus = { allow_registration: boolean };
export const registrationStatusApi = () =>
  http.request<RegistrationStatus>(
    "get",
    baseUrlApi("/api/v1/auth/registration-status")
  );

export type RegisterRequest = {
  username: string;
  password: string;
  confirm_password: string;
};
export const registerApi = (data: RegisterRequest) =>
  http.request<LoginResult>("post", baseUrlApi("/api/v1/auth/register"), {
    data
  });

/** 用 refresh token（cookie 自动附）换新 access（cookie 自动下发）。
 *
 * 响应拦截器用 _refreshRequest 标志识别本调用自身 401 不二次触发 refresh。
 */
export type RefreshResult = { access_token: string; token_type: string };
export const refreshApi = () =>
  http.request<RefreshResult>(
    "post",
    baseUrlApi("/api/v1/auth/refresh"),
    undefined,
    // 标记请求本身就是 refresh 调用，响应拦截器看到 401 不会二次触发
    // refresh-on-401，避免递归。http/index.ts 的拦截器读这个标志。
    { _refreshRequest: true }
  );

/** 撤销 refresh token（cookie 自动附）+ 清两个 HttpOnly cookie。 */
export const logoutApi = () =>
  http.request<{ ok: boolean }>("post", baseUrlApi("/api/v1/auth/logout"));

/** 自助改密：普通用户改自己密码（旧密码验证 + 写新密码）。 */
export type ChangePasswordRequest = {
  old_password: string;
  new_password: string;
};
export const changePasswordApi = (data: ChangePasswordRequest) =>
  http.request<{ ok: boolean }>(
    "post",
    baseUrlApi("/api/v1/auth/change-password"),
    { data }
  );

/** 当前用户信息（cookie 鉴权）。F5 后 main.ts / Router 守卫调一次填充 Pinia。 */
export const meApi = () =>
  http.request<UserInfo>("get", baseUrlApi("/api/v1/auth/me"));