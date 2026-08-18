import type { Component } from "vue";
import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

type InterviewStatisticsType = {
  success: boolean;
  data: {
    inProgress: number; // 进行中‑访谈数量
    weekFinish: number; // 本周完成‑访谈数量
    assistDiscovery: number; // 辅助发现‑问题数量
    interviewCoverage: number; // 访谈覆盖‑访谈数量
  };
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
  goal: string;
  created_at: string;
  started_at: string;
  ended_at: string;
  icon: Component;
};

export type BaseInfoType = {
  title: string;
  project: string;
  interviewee: string;
  start_time: string;
  duration: string;
  end_time: string;
};

/** 获取访谈统计 */
export const getInterviewStatistics = () => {
  return http.request<InterviewStatisticsType>("get", "/interview-statistics");
};

/** 获取访谈列表 */
export const getInterviewList = () => {
  return http.request<InterviewListType>("get", "/interview-list");
};

/** 获取访谈列表 */
export const getInterviewsApi = () => {
  return http.request<InterviewListType>(
    "get",
    baseUrlApi("/api/v1/interviews")
  );
};
