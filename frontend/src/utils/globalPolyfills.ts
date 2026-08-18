// 如果项目出现 `global is not defined` 报错，通常是某个依赖不兼容当前运行环境。
// 解决办法就是将该文件引入 src/main.ts 即可 import "@/utils/globalPolyfills";
if (typeof (window as any).global === "undefined") {
  (window as any).global = window;
}

export {};
