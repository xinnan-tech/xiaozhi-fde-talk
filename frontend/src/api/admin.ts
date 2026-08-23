import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

export type AdminUserInfo = {
  id: string;
  username: string;
  role: "admin" | "user";
  created_at: string;
  password_changed_at: string | null;
};

export const listUsersApi = () =>
  http.request<AdminUserInfo[]>("get", baseUrlApi("/api/v1/admin/users"));

export const resetPasswordApi = (user_id: string, new_password: string) =>
  http.request<{ ok: boolean }>(
    "post",
    baseUrlApi(`/api/v1/admin/users/${user_id}/password`),
    { data: { new_password } }
  );
