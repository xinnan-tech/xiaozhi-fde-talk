import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import Icons from "unplugin-icons/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import { alias } from "./build/utils";

export default defineConfig({
  plugins: [
    vue(),
    // ~icons/ep/user 一类虚拟模块在 LoginDialog 等组件里有引用；测试时不渲染
    // 真实图标，但要保证 import 能 resolve。
    Icons({ compiler: "vue3", scale: 1 }),
    // 跟 prod vite.config.ts 一致：按需注入 Element Plus 组件。
    // LoginDialog / 等用了 el-form / el-dialog / el-link，没这个 plugin 测试里
    // 会报 "Failed to resolve component: el-link" 等，导致断言找不到 DOM。
    Components({ resolvers: [ElementPlusResolver({ importStyle: false })] })
  ],
  resolve: { alias },
  // src/router/index.ts:59 调 getHistoryMode(import.meta.env.VITE_ROUTER_HISTORY)，
  // VITE_ROUTER_HISTORY 在生产 .env 里设为 "hash"；测试环境没 load .env，
  // 这里 define 一个常量兜底，避免跑测试时 .split(",") 拿到 undefined。
  define: {
    "import.meta.env.VITE_ROUTER_HISTORY": JSON.stringify("hash")
  },
  test: {
    environment: "happy-dom",
    globals: true,
    include: ["tests/unit/**/*.spec.ts"]
  }
});
