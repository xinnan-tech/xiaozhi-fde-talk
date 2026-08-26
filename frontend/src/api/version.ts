import { http } from "@/utils/http";
import { baseUrlApi } from "./utils";

/** 后端 /api/v1/version 响应：仅 app 版本号（不暴露协议/模板/python/依赖版本）。 */
export interface BackendVersion {
  version: string;
}

/**
 * 拉取后端 app 版本号。
 *
 * 鉴权：后端用 get_current_user_optional，匿名返 200 + {"version": ""}，
 * 已登录返真实版本号。调用方在 about 页把空串等同 null —— 降级为仅显示
 * 前端版本（设计：版本号不外泄给公网探测者）。
 */
export const getBackendVersion = (): Promise<BackendVersion> =>
  http.request<BackendVersion>("get", baseUrlApi("/api/v1/version"));