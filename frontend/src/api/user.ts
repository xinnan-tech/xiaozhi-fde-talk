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

export type LoginResult = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: UserInfo;
};

/** 登录 */
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

/** 用 refresh token 换新 access token（不签新 refresh，避免长期泄露放大）。 */
export type RefreshRequest = { refresh_token: string };
export type RefreshResult = { access_token: string; token_type: string };
export const refreshApi = (data: RefreshRequest) =>
  http.request<RefreshResult>("post", baseUrlApi("/api/v1/auth/refresh"), {
    data
  });

/** 撤销 refresh token（前端 logOut 时主动调，后端把 jti 加进撤销表）。 */
export type LogoutRequest = { refresh_token: string };
export const logoutApi = (data: LogoutRequest) =>
  http.request<{ ok: boolean }>("post", baseUrlApi("/api/v1/auth/logout"), {
    data
  });

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
