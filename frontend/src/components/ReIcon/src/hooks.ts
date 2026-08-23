import type { iconType } from "./types";
import { h, defineComponent, type Component, markRaw } from "vue";
import { FontIcon, IconifyIconOffline } from "../index";

/**
 * 支持 `iconfont`、自定义 `svg` 以及 `iconify` 中所有的图标
 * @param icon 必传 图标
 * @param attrs 可选 iconType 属性
 * @returns Component
 */
export function useRenderIcon(icon: any, attrs?: iconType): Component {
  // iconfont
  const ifReg = /^IF-/;
  // typeof icon === "function" 属于SVG
  if (ifReg.test(icon)) {
    // iconfont
    const name = icon.split(ifReg)[1];
    const iconName = name.slice(
      0,
      name.indexOf(" ") == -1 ? name.length : name.indexOf(" ")
    );
    const iconType = name.slice(name.indexOf(" ") + 1, name.length);
    return markRaw(
      defineComponent({
        name: "FontIcon",
        render() {
          return h(FontIcon, {
            icon: iconName,
            iconType,
            ...attrs
          });
        }
      })
    );
  } else if (typeof icon === "function" || typeof icon?.render === "function") {
    // svg
    return attrs ? h(icon, { ...attrs }) : markRaw(icon);
  } else if (typeof icon === "object") {
    return markRaw(
      defineComponent({
        name: "OfflineIcon",
        render() {
          return h(IconifyIconOffline, {
            icon: icon,
            ...attrs
          });
        }
      })
    );
  } else {
    // 字符串图标统一走离线通道（@iconify/vue/dist/offline）。
    // 之前按 "包含冒号即在线" 路由会让内网用户拿不到头像 / 侧边栏图标，
    // 因为前端访问不了 api.iconify.design，unisvg 镜像又时好时坏。
    // 现在统一落到 @iconify/vue/dist/offline 的 storage 里——白名单走
    // scripts/build-offline-icons.py 预生成 offlineIconBundle.generated.ts
    // 给 storage 注册；找不到就返回 null，不再尝试网络。
    return markRaw(
      defineComponent({
        name: "Icon",
        render() {
          if (!icon) return;
          return h(IconifyIconOffline, {
            icon,
            ...attrs
          });
        }
      })
    );
  }
}
