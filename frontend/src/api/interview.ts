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

// base_info 是自由字典：键由所选模板的 base_fields 决定（后端 Session.base_info）。
// 具名键是历史/运行时固定键（end_time 由开始时间+时长算出），仅供旧代码取值方便
type BaseInfoType = {
  [key: string]: string | undefined;
  title?: string;
  project?: string;
  interviewee?: string;
  start_time?: string;
  duration?: string;
  end_time?: string;
};

export type TemplateItem = {
  id: string;
  name: string;
  icon_url: string;
  icon_alt: string;
  version: string;
};

export type TemplateBaseField = {
  key: string;
  label: string;
  type?: string;
  required?: boolean;
  default?: string;
  placeholder?: string;
};

export type InterviewTemplateDetail = TemplateItem & {
  session?: {
    base_fields?: TemplateBaseField[];
    // 访谈名称/访谈目标是固定伪字段，默认值挂在 session 上（空串=无）
    title_default?: string;
    goal_default?: string;
  };
};

export type TemplateListType = {
  items: TemplateItem[];
};

export type CreateInterviewForm = {
  base_info: BaseInfoType;
  goal: string;
  template_id: string;
};

// POST /api/v1/interviews 响应：完整 session 摘要的 id + status 子集。
// status 复用 InterviewDetailType["status"] 避免单点真值漂移。
export type CreatedInterview = Pick<InterviewDetailType, "id" | "status">;

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

/** 获取模板详情，用于提取接口的字段定义 */
export const getInterviewTemplateDetailApi = (templateId: string) => {
  return http.request<InterviewTemplateDetail>(
    "get",
    baseUrlApi(`/api/v1/templates/${templateId}`)
  );
};

export type ExtractInterviewRequest = {
  transcript: string;
  template_id: string;
  fields: string[];
  field_labels: Record<string, string>;
  field_types: Record<string, string>;
  current_values: Record<string, string>;
};

export type ExtractInterviewResponse = {
  values: Record<string, string>;
};

/** 从粘贴文本中提取访谈表单字段 */
export const extractInterviewFieldsApi = (
  data: ExtractInterviewRequest,
  signal?: AbortSignal
) => {
  return http.request<ExtractInterviewResponse>(
    "post",
    baseUrlApi("/api/v1/interviews/extract"),
    { data, signal }
  );
};

export type OcrInterviewRequest = {
  image_base64: string;
};

export type OcrInterviewResponse = {
  text: string;
};

/** 拍照识别：后端视觉模型提取图片文字 */
export const ocrInterviewImageApi = (data: OcrInterviewRequest) => {
  return http.request<OcrInterviewResponse>(
    "post",
    baseUrlApi("/api/v1/interviews/ocr"),
    { data }
  );
};

/** 创建访谈 */
export const saveInterviewApi = (data: CreateInterviewForm) => {
  return http.request<CreatedInterview>(
    "post",
    baseUrlApi("/api/v1/interviews"),
    { data }
  );
};

export type TranscriptItem = {
  corrected_text: string;
  end_ms: number;
  final: true;
  seg_id: string;
  speaker: string;
  start_ms: number;
  text: string;
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
  // 模板字段定义（快照优先）：运行页按它渲染 base_info 的 label/控件
  template_fields?: TemplateBaseField[];
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
  transcript: TranscriptItem[];
};

export type InterviewReportType = {
  status: "ready" | string;
  content_md: string;
};

/** 获取访谈详情 */
export const getInterviewDetailApi = (id: string) => {
  return http.request<InterviewDetailType>(
    "get",
    baseUrlApi(`/api/v1/interviews/${id}`)
  );
};

export type FirstBatchResponse = {
  generated: boolean;
  items: InterviewDetailItem[];
};

/** 触发/获取首批评量（幂等：已生成/已开聊/已结束则直接返回当前清单）。 */
export const firstBatchInterviewApi = (sessionId: string) => {
  return http.request<FirstBatchResponse>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/first-batch`)
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

/** 暂停访谈 */
export const suspendInterviewApi = (sessionId: string) => {
  return http.request<unknown>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/suspend`)
  );
};

/** 继续访谈 */
export const resumeInterviewApi = (sessionId: string) => {
  return http.request<unknown>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/resume`)
  );
};

/** 获取访谈报告 */
export const getInterviewReportApi = (
  sessionId: string,
  options?: { force?: boolean }
) => {
  // force=true 时拼 ?force=true 给后端跳过缓存强制重生（issue #82「重新生成报告」按钮）。
  // options 缺省 / force=undefined 时不发 query，与历史行为一致。
  return http.request<InterviewReportType>(
    "get",
    baseUrlApi(`/api/v1/interviews/${sessionId}/report`),
    { params: { force: options?.force } }
  );
};

/** 导出访谈报告 */
export const exportInterviewReportApi = (sessionId: string, format = "md") => {
  return http.request<Blob>(
    "post",
    baseUrlApi(`/api/v1/interviews/${sessionId}/export`),
    {
      params: { format },
      responseType: "blob"
    }
  );
};

/** 删除访谈 */
export const deleteInterviewApi = (sessionId: string) => {
  return http.request<unknown>(
    "delete",
    baseUrlApi(`/api/v1/interviews/${sessionId}`)
  );
};
