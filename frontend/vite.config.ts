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
          target: process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true
        },
        "/ws": {
          target: process.env.E2E_BACKEND_URL || "http://127.0.0.1:8000",
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
      ...getPluginsList(VITE_COMPRESSION),
      // 生产构建剥除 console.* 调试调用：避免调试日志 / 报错信息泄露到用户控制台
      // （Vue 路由 / 麦克风错误堆栈可能含本地路径、内部组件名等侦察信号）。
      // 仅 build 模式生效（dev 仍保留 console）。整段 console.X(...) 用自平衡
      // 括号定位右边界，整段替换为 `void 0` —— 保留合法 expression 形态，让
      // `return console.error(...)`、`if (x) console.log(...)` 之类嵌入调用
      // 语法结构不破。后续 `;` / `\n` 不动，避免吞到下一条语句开头（曾因此踩坑：
      // strip 掉 `\n` 后 `return const` 解析失败）。
      {
        name: "strip-console",
        apply: "build",
        transform(code, id) {
          if (id.includes("node_modules")) return null;
          if (!/console\.(log|debug|info|warn|error)\s*\(/.test(code))
            return null;
          const out: string[] = [];
          const re = /console\.(log|debug|info|warn|error)\s*\(/g;
          let last = 0;
          let m: RegExpExecArray | null;
          while ((m = re.exec(code)) !== null) {
            out.push(code.slice(last, m.index));
            // 从开括号向后扫描，自平衡括号 / 单引号 / 双引号 / 反引号模板串
            // / 行注释 / 块注释，遇到匹配的右括号停下。
            let depth = 1;
            let i = m.index + m[0].length;
            const src = code;
            while (i < src.length && depth > 0) {
              const c = src[i];
              if (c === "'" || c === '"' || c === "`") {
                // 跳过字符串字面量（不解析转义——保持简单且够用）
                const quote = c;
                i++;
                while (i < src.length && src[i] !== quote) {
                  if (src[i] === "\\") i++;
                  i++;
                }
                i++;
                continue;
              }
              if (c === "/" && src[i + 1] === "/") {
                // 行注释
                while (i < src.length && src[i] !== "\n") i++;
                continue;
              }
              if (c === "/" && src[i + 1] === "*") {
                i += 2;
                while (
                  i < src.length &&
                  !(src[i] === "*" && src[i + 1] === "/")
                )
                  i++;
                i += 2;
                continue;
              }
              if (c === "(") depth++;
              else if (c === ")") depth--;
              i++;
            }
            // 整段 console.X(...) 替换为 void 0（合法 expression），不动尾部。
            out.push("void 0");
            last = i;
            re.lastIndex = i;
          }
          out.push(code.slice(last));
          const stripped = out.join("");
          if (stripped === code) return null;
          return { code: stripped, map: null };
        }
      }
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
          return deps.filter(dep => whitelist.some(w => dep.includes(w)));
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
            if (!id.includes("node_modules")) return;
            // 不再硬塞 element-plus：让 unplugin 按组件自动拆，节省首屏 chunk
            if (
              id.match(/[\\/]vue[\\/]/) ||
              id.match(/[\\/]vue-router[\\/]/) ||
              id.match(/[\\/]pinia[\\/]/)
            ) {
              return "vue-vendor";
            }
            if (id.includes("echarts")) return "echarts";
            if (id.includes("dayjs")) return "dayjs";
            // vueuse 跟 vue 运行时强耦合，独立 chunk 会触发跨 chunk TDZ（"Cannot access 'zt' before initialization"）
            // 跟 vue-vendor 合并避免循环依赖被 chunk 边界切断
            if (id.includes("@vueuse")) return "vue-vendor";
            if (id.includes("axios")) return "axios";
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
              return "utils-vendor";
            }
            // element-plus 子模块按组件拆 chunk（unplugin 已做精确路径 import）
            const m = id.match(
              /[\\/]element-plus[\\/]es[\\/]components[\\/]([^\\/]+)/
            );
            if (m) return `element-plus-${m[1]}`;
            // CodeMirror（模板编辑器 JSON 模式）：独立 chunk。编辑器路由本身懒加载，
            // 但 manualChunks 兜底优先于动态导入拆分——不单拆会被合进 vue-vendor
            // （首屏 modulepreload 白名单），所有页面首屏都要为它多下载。
            if (id.includes("codemirror") || id.includes("@lezer")) {
              return "codemirror";
            }
            // 兜底合并到 vue-vendor：element-plus 按需引入后，vendor 跟 vue-vendor
            // 之间出现循环依赖（chunk 边界切断执行顺序 → TDZ "Cannot access X before initialization"）。
            // 合并成一个 chunk 消除边界；首屏只多等一次 vue-vendor 下载，但 B3 已 modulepreload 它，无明显延迟。
            return "vue-vendor";
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
