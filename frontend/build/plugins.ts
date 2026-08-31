import vue from "@vitejs/plugin-vue";
import { viteBuildInfo } from "./info";
import svgLoader from "vite-svg-loader";
import Icons from "unplugin-icons/vite";
import type { PluginOption } from "vite";
import vueJsx from "@vitejs/plugin-vue-jsx";
import tailwindcss from "@tailwindcss/vite";
import { configCompressPlugin } from "./compress";
// import { vitePluginFakeServer } from "vite-plugin-fake-server";

export function getPluginsList(
  VITE_COMPRESSION: ViteCompression
): PluginOption[] {
  return [
    tailwindcss(),
    vue(),
    // jsx、tsx语法支持
    vueJsx(),
    viteBuildInfo(),
    // vitePluginFakeServer({
    //   logger: false,
    //   include: "mock",
    //   infixName: false,
    //   enableProd: true
    // }),
    // ?component 内联 svg：禁用 cleanupIds 的 id 最小化——它按文件把 id
    // 独立改成 a/b/c，多张内联进同一页面后 id 冲突，url(#id) 文档级取首个
    // 匹配，导致渐变/滤镜互相串用（插画变形、变色）。保留源文件语义 id。
    svgLoader({
      svgoConfig: {
        plugins: [
          {
            name: "preset-default",
            params: {
              overrides: {
                cleanupIds: false
              }
            }
          }
        ]
      }
    }),
    Icons({
      compiler: "vue3",
      scale: 1
    }),
    configCompressPlugin(VITE_COMPRESSION)
  ];
}
