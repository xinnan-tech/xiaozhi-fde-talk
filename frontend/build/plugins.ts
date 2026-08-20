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
    svgLoader(),
    Icons({
      compiler: "vue3",
      scale: 1
    }),
    configCompressPlugin(VITE_COMPRESSION)
  ];
}
