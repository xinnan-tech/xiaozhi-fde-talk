export const baseUrlApi = (url: string): string => {
  // 永远走 origin-relative；host 路由交给 vite proxy（dev）/ 反代（生产）
  // / E2E 阶段的 vite preview 接管。bundle 里不夹任何后端 host，避免跨网段 / 跨域失败
  const base = import.meta.env.VITE_API_URL ?? ""
  return `${base}${url}`
}
