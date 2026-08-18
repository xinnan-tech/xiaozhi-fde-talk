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
