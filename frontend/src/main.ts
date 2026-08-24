import App from "./App.vue";
import router from "./router";
import { setupStore } from "@/store";
import { getPlatformConfig } from "./config";
import { MotionPlugin } from "@vueuse/motion";
import { createApp, type Directive } from "vue";
import { injectResponsiveStorage } from "@/utils/responsive";
import { i18n } from "@/i18n";
import "element-plus/dist/index.css";

// 引入重置样式
import "./style/reset.scss";
// 导入公共样式
import "./style/index.scss";
// 一定要在main.ts中导入tailwind.css，防止vite每次hmr都会请求src/style/index.scss整体css文件导致热更新慢的问题
import "./style/tailwind.css";
// 导入字体图标
import "./assets/iconfont/iconfont.css";

const app = createApp(App);
app.use(i18n);

// 自定义指令
import * as directives from "@/directives";
Object.keys(directives).forEach(key => {
  app.directive(key, (directives as { [key: string]: Directive })[key]);
});

// 全局注册 @iconify/vue 图标库
import { IconifyIconOffline, FontIcon } from "./components/ReIcon";
// 不再注册 IconifyIconOnline：内网访问不到 api.iconify.design / unisvg，
// 任何 useRenderIcon("prefix:name") 都交给离线 storage 处理；
// 白名单由 scripts/build-offline-icons.py 生成到 offlineIconBundle.generated.ts。
app.component("IconifyIconOffline", IconifyIconOffline);
app.component("FontIcon", FontIcon);

// 全局注册按钮级别权限组件
import { Auth } from "@/components/ReAuth";
import { Perms } from "@/components/RePerms";
app.component("Auth", Auth);
app.component("Perms", Perms);

// 全局注册vue-tippy
import "tippy.js/dist/tippy.css";
import "tippy.js/themes/light.css";
import VueTippy from "vue-tippy";
import Vue3Signature from "vue3-signature";
app.use(VueTippy);

getPlatformConfig(app).then(async config => {
  setupStore(app);
  app.use(router);
  await router.isReady();
  injectResponsiveStorage(app, config);
  app.use(MotionPlugin).use(Vue3Signature);
  app.mount("#app");
});
