import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

/** 配置项的值类型。后端可能返回字符串、数字、布尔值或 null。 */
export type SystemConfigValue = string | number | boolean | null;

/** 一个配置分组，例如 llm、asr、coach。 */
export type SystemConfigSection = Record<string, SystemConfigValue>;

/** 系统配置 */
export interface SystemConfig {
  llm?: SystemConfigSection & {
    type?: string;
    base_url?: string;
    api_key?: string | null;
    model?: string;
  };
  asr?: SystemConfigSection & {
    type?: string;
    sample_rate?: string | number;
    ws_url?: string;
    ws_verify_ssl?: string | boolean;
    api_key?: string | null;
  };
  coach?: SystemConfigSection & {
    pause_s?: string | number;
    max_pending_segments?: string | number;
    min_interval_s?: string | number;
    llm_timeout_s?: string | number;
  };
  auth?: SystemConfigSection & {
    jwt_expire_minutes?: string | number;
    allow_registration?: boolean;
  };
  session?: SystemConfigSection & {
    grace_period_s?: string | number;
    idle_timeout_s?: string | number;
    idle_check_interval_s?: string | number;
    liveness_window_s?: string | number;
    max_concurrent?: string | number;
  };

  /** 允许后端新增未知配置分组。 */
  [section: string]: SystemConfigSection | undefined;
}

/** ASR 诊断结果 */
export interface AsrDiagnosticsResult {
  ok: boolean;
  code: string;
  message: string;
  latency_ms: number;
  detail: {
    utterances: string[];
    sample: string;
  };
}

/** LLM 诊断结果 */
export interface LlmDiagnosticsResult {
  ok: boolean;
  code: string;
  message: string;
  latency_ms: number;
  detail: {
    model: string;
    reply: string;
  };
}

/** OCR 诊断结果 */
export interface OcrDiagnosticsResult {
  ok: boolean;
  code: string;
  message: string;
  latency_ms: number;
  detail: {
    model: string;
    reply: string;
  };
}

/** 系统诊断结果 */
export interface SystemDiagnostics {
  ok: boolean;
  asr: AsrDiagnosticsResult;
  llm: LlmDiagnosticsResult;
  ocr: OcrDiagnosticsResult;
}

/** 系统配置 */
export const systemConfigApi = () => {
  return http.request<SystemConfig>("get", baseUrlApi("/api/v1/admin/config"));
};

/** 运行全部自检 */
export const systemDiagnosticsApi = () => {
  return http.request<SystemDiagnostics>(
    "post",
    baseUrlApi("/api/v1/diagnostics")
  );
};

/** 运行 ASR 自检 */
export const systemAsrDiagnosticsApi = () => {
  return http.request<AsrDiagnosticsResult>(
    "post",
    baseUrlApi("/api/v1/diagnostics/asr")
  );
};

/** 运行 LLM 自检 */
export const systemLlmDiagnosticsApi = () => {
  return http.request<LlmDiagnosticsResult>(
    "post",
    baseUrlApi("/api/v1/diagnostics/llm")
  );
};

/** 运行 OCR 自检 */
export const systemOcrDiagnosticsApi = () => {
  return http.request<OcrDiagnosticsResult>(
    "post",
    baseUrlApi("/api/v1/diagnostics/ocr")
  );
};

/** 保存系统配置 */
export const systemConfigSaveApi = <T>(configName: string, config: T) => {
  return http.request<T>(
    "put",
    baseUrlApi(`/api/v1/admin/config/${configName}`),
    {
      data: config
    }
  );
};
