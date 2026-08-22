import { getPluginsList } from "./build/plugins";
import { include, exclude } from "./build/optimize";
import { type UserConfigExport, type ConfigEnv, loadEnv } from "vite";
import VueI18nPlugin from "@intlify/unplugin-vue-i18n/vite";
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
    // E2E 用的 preview 服务（playwright webServer 拉 pnpm preview）
    // 不带 proxy 会让浏览器 /api /ws 落 vite preview 静态服务器 404；
    // 这里把 E2E 后端地址写死 127.0.0.1:8001（per Global Constraint 端口 8001 E2E 专用）
    preview: {
      port: 4173,
      host: "0.0.0.0",
      strictPort: true,
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8001",
          changeOrigin: true
        },
        "/ws": {
          target: "http://127.0.0.1:8001",
          changeOrigin: true,
          ws: true
        }
      }
    },
    plugins: [
      VueI18nPlugin({
        include: pathResolve("./src/locales/**", import.meta.url)
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
            if (id.includes("element-plus") || id.includes("@element-plus")) {
              return "element-plus"
            }
            if (
              id.match(/[\\/]vue[\\/]/) ||
              id.match(/[\\/]vue-router[\\/]/) ||
              id.match(/[\\/]pinia[\\/]/)
            ) {
              return "vue-vendor"
            }
            if (id.includes("echarts")) return "echarts"
            if (id.includes("dayjs")) return "dayjs"
            if (id.includes("@vueuse")) return "vueuse"
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
            return "vendor"
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
