/**
 * 从任意 axios 错误里提取后端响应里的可读文本，供 UI 直接展示。
 *
 * 后端 detail 三种形态：
 * - 后端 `I18nError` → 已本地化字符串 detail
 * - pydantic 422 → `[{loc:[body,field], msg, type}]` 列表，按 `field: msg` 拼接
 * - FastAPI `HTTPException` → 字符串 detail（可能英文）
 *
 * 取不到时回退到调用方传入的 i18n 兜底文案，避免再次落入「登录失败，请稍后重试」
 * 这种把后端具体原因模糊化的兜底。
 *
 * 用法：
 *   } catch (e: unknown) {
 *     message(extractBackendError(e, t("auth.login_failed")), { type: "error" });
 *   }
 *
 * 注意：401 由 `@/utils/http/index.ts` 的响应拦截器按 `response.data.code` 是否存在
 * 区分业务 401 与 JWT 过期；本函数只负责文案提取，不处理登出/重登流程。
 */
export function extractBackendError(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } } | null)
    ?.response?.data?.detail;
  return extractDetailText(detail) || fallback;
}

/**
 * 仅把后端 `detail` 字段展开成字符串，拼接方式见 `extractBackendError` 文档。
 * 取不到（结构不符 / 数组为空 / 全部 msg 缺失）时返回空串，由调用方自行决定兜底。
 */
export function extractDetailText(detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail
      .map((d: { msg?: string; loc?: unknown[] }) => {
        const msg = typeof d?.msg === "string" ? d.msg.trim() : "";
        if (!msg) return "";
        const field =
          Array.isArray(d?.loc) && d.loc.length > 1
            ? String(d.loc[d.loc.length - 1])
            : "";
        return field ? `${field}: ${msg}` : msg;
      })
      .filter((s): s is string => s.length > 0);
    if (parts.length > 0) return parts.join("；");
  }
  return "";
}