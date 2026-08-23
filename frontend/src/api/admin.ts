import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

export type AdminUserInfo = {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at: string;
};

export const listUsersApi = () =>
  http.request<AdminUserInfo[]>("get", baseUrlApi("/api/v1/admin/users"));

export type ResetPasswordRequest = { new_password: string };
export const resetPasswordApi = (userId: string, data: ResetPasswordRequest) =>
  http.request<{ ok: boolean }>(
    "post",
    baseUrlApi(`/api/v1/admin/users/${userId}/password`),
    { data }
  );
