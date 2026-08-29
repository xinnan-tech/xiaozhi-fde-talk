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

/** 模板完整结构（与后端 domain.template.Template JSON 对齐） */
export type TemplateDoc = {
  id: string;
  version: string;
  icon_url: string;
  icon_alt: string;
  name: string;
  session: {
    name: string;
    goal: string;
    base_fields: {
      key: string;
      label: string;
      type: string;
      required: boolean;
    }[];
    setup: { intro: string; extract_to: string[]; required: string[] };
  };
  coaching: {
    playbook: string;
    must_ask: {
      id: string;
      text: string;
      priority: number | null;
      desc: string;
    }[];
  };
  report: { doc: string };
  safety: unknown[];
};

export type AdminTemplateSummary = {
  id: string;
  name: string;
  icon_url: string;
  icon_alt: string;
  version: string;
  updated_at: string | null;
  referenced: boolean;
};

export const listAdminTemplatesApi = () =>
  http.request<AdminTemplateSummary[]>(
    "get",
    baseUrlApi("/api/v1/admin/templates")
  );

export const createAdminTemplateApi = (tpl: TemplateDoc) =>
  http.request<TemplateDoc>("post", baseUrlApi("/api/v1/admin/templates"), {
    data: tpl
  });

export const updateAdminTemplateApi = (id: string, tpl: TemplateDoc) =>
  http.request<TemplateDoc>(
    "put",
    baseUrlApi(`/api/v1/admin/templates/${id}`),
    { data: tpl }
  );

export const deleteAdminTemplateApi = (id: string) =>
  http.request<{ ok: boolean }>(
    "delete",
    baseUrlApi(`/api/v1/admin/templates/${id}`)
  );

/** AI 一句话生成模板：只生成不落库，结果直接进编辑器（长文生成，耗时可达分钟级） */
export const generateAdminTemplateApi = (brief: string) =>
  http.request<TemplateDoc>(
    "post",
    baseUrlApi("/api/v1/admin/templates/generate"),
    // 4000 token 输出的生成远超普通请求，单独放宽（默认 60s）
    { data: { brief }, timeout: 180000 }
  );
