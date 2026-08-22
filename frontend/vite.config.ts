import { getPluginsList } from "./build/plugins";
import { include, exclude } from "./build/optimize";
import { type UserConfigExport, type ConfigEnv, loadEnv } from "vite";
import VueI18nPlugin from "@intlify/unplugin-vue-i18n/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import AutoImport from "unplugin-auto-import/vite";
import {
  root,
  alias,
  wrapperEnv,
  pathResolve,
  __APP_INFO__
} from "./build/utils";

export default ({ mode }: ConfigEnv): UserConfigExport => {
  const env = loadEnv(mode, root);
  const {
    VITE_PORT,
    VITE_COMPRESSION,
    VITE_PUBLIC_PATH,
    VITE_API_URL,
    VITE_WS_BASE_URL
  } = wrapperEnv(env);

  return {
    base: VITE_PUBLIC_PATH,
    root,
    resolve: {
      alias
    },
    // 服务端渲染
    server: {
      // 端口号
      port: VITE_PORT,
      host: "0.0.0.0",
      // 本地跨域代理 https://cn.vitejs.dev/config/server-options.html#server-proxy
      proxy: {
        "/api": {
          // 这里填写后端地址
          target: VITE_API_URL,
          changeOrigin: true
        },
        "/ws": {
          target: VITE_WS_BASE_URL,
          changeOrigin: true,
          ws: true
        }
      },
      // 预热文件以提前转换和缓存结果，降低启动期间的初始页面加载时长并防止转换瀑布
      warmup: {
        clientFiles: ["./index.html", "./src/{views,components}/*"]
      }
    },
    // E2E + 手动预览：playwright webServer 跑 8001，本机手动测试可用 8000 主后端
    // 代理目标由环境变量 E2E_BACKEND_URL 切换：e2e 默认 127.0.0.1:8001，
    // 手动预览不传 → 走 127.0.0.1:8000（用户主程序，跟 8000 页面同源同数据）
    preview: {
      port: 4173,
      host: "0.0.0.0",
      strictPort: true,
      proxy: {
        "/api": {
          target:
            process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true
        },
        "/ws": {
          target:
            process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true,
          ws: true
        }
      }
    },
    plugins: [
      VueI18nPlugin({
        include: pathResolve("./src/locales/**", import.meta.url)
      }),
      Components({
        resolvers: [ElementPlusResolver({ importStyle: "css" })]
      }),
      AutoImport({
        resolvers: [ElementPlusResolver()]
      }),
      ...getPluginsList(VITE_COMPRESSION)
    ],
    // https://cn.vitejs.dev/config/dep-optimization-options.html#dep-optimization-options
    optimizeDeps: {
      include,
      exclude
    },
    build: {
      // https://cn.vitejs.dev/guide/build.html#browser-compatibility
      target: "es2015",
      sourcemap: false,
      // 消除打包大小超过500kb警告
      chunkSizeWarningLimit: 4000,
      // B3：限 modulepreload 到 6 chunk，避开 HTTP/1.1 单 origin 6 并发排队
      // 白名单：vue-vendor（合并 vue 运行时 + vueuse + 其他未分类 vendor）+ 5 个首屏最常用 element-plus 组件
      modulePreload: {
        polyfill: false,
        resolveDependencies: (_filename, deps) => {
          const whitelist = [
            "vue-vendor",
            "element-plus-message",
            "element-plus-form",
            "element-plus-input",
            "element-plus-dialog",
            "element-plus-button"
          ];
          return deps.filter((dep) =>
            whitelist.some((w) => dep.includes(w))
          );
        }
      },
      rollupOptions: {
        input: {
          index: pathResolve("./index.html", import.meta.url)
        },
        // 静态资源分类打包
        output: {
          chunkFileNames: "static/js/[name]-[hash].js",
          entryFileNames: "static/js/[name]-[hash].js",
          assetFileNames: "static/[ext]/[name]-[hash].[ext]",
          // 拆 vendor：主入口单点 > 1MB 会拉长首屏 JS parse 时间，
          // 把大体积依赖按类别拆到独立 chunk，配合浏览器长缓存复用。
          manualChunks(id) {
            if (!id.includes("node_modules")) return
            // 不再硬塞 element-plus：让 unplugin 按组件自动拆，节省首屏 chunk
            if (
              id.match(/[\\/]vue[\\/]/) ||
              id.match(/[\\/]vue-router[\\/]/) ||
              id.match(/[\\/]pinia[\\/]/)
            ) {
              return "vue-vendor"
            }
            if (id.includes("echarts")) return "echarts"
            if (id.includes("dayjs")) return "dayjs"
            // vueuse 跟 vue 运行时强耦合，独立 chunk 会触发跨 chunk TDZ（"Cannot access 'zt' before initialization"）
            // 跟 vue-vendor 合并避免循环依赖被 chunk 边界切断
            if (id.includes("@vueuse")) return "vue-vendor"
            if (id.includes("axios")) return "axios"
            if (
              id.includes("sortablejs") ||
              id.includes("tippy.js") ||
              id.includes("vue-tippy") ||
              id.includes("markdown-it") ||
              id.includes("localforage") ||
              id.includes("responsive-storage") ||
              id.includes("@pureadmin") ||
              id.includes("path-browserify") ||
              id.includes("animate.css") ||
              id.includes("vue-i18n") ||
              id.includes("@intlify")
            ) {
              return "utils-vendor"
            }
            // element-plus 子模块按组件拆 chunk（unplugin 已做精确路径 import）
            const m = id.match(/[\\/]element-plus[\\/]es[\\/]components[\\/]([^\\/]+)/);
            if (m) return `element-plus-${m[1]}`;
            // 兜底合并到 vue-vendor：element-plus 按需引入后，vendor 跟 vue-vendor
            // 之间出现循环依赖（chunk 边界切断执行顺序 → TDZ "Cannot access X before initialization"）。
            // 合并成一个 chunk 消除边界；首屏只多等一次 vue-vendor 下载，但 B3 已 modulepreload 它，无明显延迟。
            return "vue-vendor"
          }
        }
      }
    },
    define: {
      __INTLIFY_PROD_DEVTOOLS__: false,
      __APP_INFO__: JSON.stringify(__APP_INFO__)
    }
  };
};
