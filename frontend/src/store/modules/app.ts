import { defineStore } from "pinia";
import { type appType, store, deviceDetection } from "../utils";

// 在 store 初始化阶段就根据 UA 决定 device 与 sidebar 初值，
// 避免 layout 侧 ResizeObserver 首帧异步回调覆盖同步设值
const isMobileUA = deviceDetection();

export const useAppStore = defineStore("xz-app", {
  state: (): appType => ({
    sidebar: {
      opened: !isMobileUA,
      withoutAnimation: false,
      isClickCollapse: false
    },
    // 当前系统固定使用 vertical 布局
    layout: "vertical",
    device: isMobileUA ? "mobile" : "desktop",
    // 浏览器窗口的可视区域大小
    viewportSize: {
      width: document.documentElement.clientWidth,
      height: document.documentElement.clientHeight
    }
  }),
  getters: {
    getSidebarStatus(state) {
      return state.sidebar.opened;
    },
    getDevice(state) {
      return state.device;
    },
    getViewportWidth(state) {
      return state.viewportSize.width;
    },
    getViewportHeight(state) {
      return state.viewportSize.height;
    }
  },
  actions: {
    TOGGLE_SIDEBAR(opened?: boolean, resize?: string) {
      if (opened && resize) {
        this.sidebar.withoutAnimation = true;
        this.sidebar.opened = true;
      } else if (!opened && resize) {
        this.sidebar.withoutAnimation = true;
        this.sidebar.opened = false;
      } else if (!opened && !resize) {
        this.sidebar.withoutAnimation = false;
        this.sidebar.opened = !this.sidebar.opened;
        this.sidebar.isClickCollapse = !this.sidebar.opened;
      }
    },
    async toggleSideBar(opened?: boolean, resize?: string) {
      await this.TOGGLE_SIDEBAR(opened, resize);
    },
    toggleDevice(device: string) {
      this.device = device;
    },
    setViewportSize(size) {
      this.viewportSize = size;
    }
  }
});

export function useAppStoreHook() {
  return useAppStore(store);
}
