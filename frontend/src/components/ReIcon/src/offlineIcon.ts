// 这里存放本地图标，在 src/layout/index.vue 文件中加载，避免在首启动加载
import { getSvgInfo } from "@pureadmin/utils";
import { addIcon } from "@iconify/vue/dist/offline";

// 已经写死的几张菜单 icon，沿用 ~icons 加载的形式（unplugin-icons 会在构建期把 svg 内联）
// https://icon-sets.iconify.design/ep/?keyword=ep
import EpHomeFilled from "~icons/ep/home-filled?raw";

// https://icon-sets.iconify.design/ri/?keyword=ri
import RiSearchLine from "~icons/ri/search-line?raw";
import RiInformationLine from "~icons/ri/information-line?raw";

const icons = [
  // Element Plus Icon
  ["ep/home-filled", EpHomeFilled],
  // Remix Icon
  ["ri/search-line", RiSearchLine],
  ["ri/information-line", RiInformationLine]
];

// 本地菜单图标，后端在路由的 icon 中返回对应的图标字符串并且前端在此处使用 addIcon 添加即可渲染菜单图标
icons.forEach(([name, icon]) => {
  addIcon(name as string, getSvgInfo(icon as string));
});

// 自动生成的白名单：把所有 useRenderIcon("prefix:name") 形式的在线图标注册到离线 storage。
// 内网环境访问不到 api.iconify.design 时，只要这张表里登记过就能正常渲染。
// 文件由 scripts/build-offline-icons.py 重生成，不要手改。
import "./offlineIconBundle.generated";
