import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

export type LoginRequest = {
  /** 用户名 */
  username: string;
  /** 密码 */
  password: string;
};

export type LoginResult = {
  /** 访问令牌 */
  access_token: string;
  /** 访问令牌类型 */
  token_type: string;
};

/** 登录 */
export const loginApi = (data: LoginRequest) => {
  return http.request<LoginResult>("post", baseUrlApi("/api/v1/auth/login"), {
    data
  });
};
