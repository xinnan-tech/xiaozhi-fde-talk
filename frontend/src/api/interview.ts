import type { Component } from "vue";
import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

export type InterviewStatisticsType = {
  in_progress: number; // 进行中‑访谈数量
  week_finish: number; // 本周完成‑访谈数量
  assist_discovery: number; // 辅助发现‑问题数量
  interview_coverage: number; // 访谈覆盖‑访谈数量
};

export type InterviewListType = {
  items: InterviewItem[];
};

export type InterviewItem = {
  id: string;
  template_id: string;
  template_version: string;
  status: string;
  base_info: BaseInfoType;
  title: string;
  interviewee: string;
  type: string;
  recent_time: string | null;
  pending_count: number;
  covered_count: number;
  asked_count: number;
  goal: string;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  icon: Component;
};

type BaseInfoType = {
  title: string;
  project: string;
  interviewee: string;
  start_time: string;
  duration: string;
  end_time: string;
};

export type TemplateItem = {
  id: string;
  name: string;
  icon_url: string;
  icon_alt: string;
  version: string;
};

export type TemplateListType = {
  items: TemplateItem[];
};

export type CreateInterviewForm = {
  base_info: BaseInfoType;
  goal: string;
  template_id: string;
};

/** 获取访谈统计 */
export const getStatisticsApi = () => {
  return http.request<InterviewStatisticsType>(
    "get",
    baseUrlApi("/api/v1/interviews/statistics")
  );
};

/** 获取访谈列表 */
export const getInterviewsApi = () => {
  return http.request<InterviewListType>(
    "get",
    baseUrlApi("/api/v1/interviews")
  );
};

/** 获取访谈模板列表 */
export const getInterviewsTemplatesApi = () => {
  return http.request<TemplateListType>("get", baseUrlApi("/api/v1/templates"));
};

/** 创建访谈 */
export const saveInterviewApi = (data: CreateInterviewForm) => {
  return http.request<unknown>("post", baseUrlApi("/api/v1/interviews"), {
    data
  });
};

export type InterviewDetailItem = {
  id: string;
  text: string;
  status: "new" | "todo" | "done" | "skipped" | "ignored";
  reason: string;
  priority: number;
  desc: string;
};

export type InterviewDetailType = {
  id: string;
  template_id: string;
  template_version: string;
  status:
    | "created"
    | "setting_up"
    | "in_progress"
    | "suspended"
    | "ended"
    | "extracting"
    | "done";
  base_info: BaseInfoType;
  goal: string;
  first_batch_generated: boolean;
  consumed_seq: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  items: InterviewDetailItem[];
  skipped_ids: string[];
  ignored_ids: string[];
  coverage: Record<string, unknown>;
  transcript: unknown[];
};

/** 获取访谈详情 */
export const getInterviewDetailApi = (id: string) => {
  return http.request<InterviewDetailType>(
    "get",
    baseUrlApi(`/api/v1/interviews/${id}`)
  );
};

/** 忽略访谈问题 */
export const ignoreInterviewItemApi = (sessionId: string, itemId: string) => {
  return http.request<unknown>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/items/${itemId}/ignore`)
  );
};

/** 取消忽略访谈问题 */
export const unignoreInterviewItemApi = (sessionId: string, itemId: string) => {
  return http.request<unknown>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/items/${itemId}/unignore`)
  );
};

/** 结束访谈 */
export const endInterviewApi = (sessionId: string) => {
  return http.request<unknown>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/end`)
  );
};
