export const baseUrlApi = (url: string): string => {
  // spec §一：bundle 不嵌入任何后端 host。
  // 任何 `import.meta.env.VITE_*` 都会被 vite build 期内联到源码中，
  // 必须只允许运行时宿主（浏览器 / nginx）通过相对路径 + 反代解析 host。
  // 显式绝对地址（生产极少数场景）不再经此函数，直接传完整 URL。
  return url;
};
