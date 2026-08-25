import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

/** 后端 /api/v1/version 响应：仅 app 版本号（不暴露协议/模板/python/依赖版本）。 */
export interface BackendVersion {
  version: string;
}

/**
 * 拉取后端 app 版本号。
 *
 * 鉴权：依赖后端 get_current_user —— 未登录（401）或网络失败时直接抛错，
 * 调用方在 about 页降级为仅显示前端版本（设计：版本号不外泄给公网）。
 */
export const getBackendVersion = (): Promise<BackendVersion> =>
  http.request<BackendVersion>("get", baseUrlApi("/api/v1/version"));