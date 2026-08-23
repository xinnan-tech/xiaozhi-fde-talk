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
