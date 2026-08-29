import { describe, expect, it, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useAppStore } from "@/store/modules/app";

// 用 unwrapped useAppStore() 让 setActivePinia(createPinia()) 生效

describe("stores/AppStore — state init", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("默认 sidebar.opened=true", () => {
    const store = useAppStore();
    expect(store.sidebar.opened).toBe(true);
    expect(store.sidebar.withoutAnimation).toBe(false);
    expect(store.sidebar.isClickCollapse).toBe(false);
  });

  it("device 是 'desktop' 或 'mobile'", () => {
    const store = useAppStore();
    expect(["desktop", "mobile"]).toContain(store.device);
  });
});

describe("stores/AppStore — toggleSideBar", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("(true, 'resize') → opened=true, withoutAnimation=true", async () => {
    const store = useAppStore();
    store.sidebar.opened = false;
    await store.toggleSideBar(true, "resize");
    expect(store.sidebar.opened).toBe(true);
    expect(store.sidebar.withoutAnimation).toBe(true);
  });

  it("(false, 'resize') → opened=false, withoutAnimation=true", async () => {
    const store = useAppStore();
    store.sidebar.opened = true;
    await store.toggleSideBar(false, "resize");
    expect(store.sidebar.opened).toBe(false);
    expect(store.sidebar.withoutAnimation).toBe(true);
  });

  it("(undefined, undefined) 切换 opened→!opened；withoutAnimation=false", async () => {
    // 源码：
    //   this.sidebar.opened = !this.sidebar.opened;
    //   this.sidebar.isClickCollapse = !this.sidebar.opened;
    // 切换后 opened=false → isClickCollapse = !false = true
    const store = useAppStore();
    store.sidebar.opened = true;

    await store.toggleSideBar(undefined, undefined);
    expect(store.sidebar.opened).toBe(false);
    expect(store.sidebar.withoutAnimation).toBe(false);
    expect(store.sidebar.isClickCollapse).toBe(true);

    await store.toggleSideBar(undefined, undefined);
    expect(store.sidebar.opened).toBe(true);
    expect(store.sidebar.withoutAnimation).toBe(false);
    expect(store.sidebar.isClickCollapse).toBe(false);
  });
});

describe("stores/AppStore — toggleDevice / setViewportSize", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("toggleDevice('mobile')", () => {
    const store = useAppStore();
    store.toggleDevice("mobile");
    expect(store.device).toBe("mobile");
  });

  it("toggleDevice('desktop')", () => {
    const store = useAppStore();
    store.toggleDevice("mobile");
    store.toggleDevice("desktop");
    expect(store.device).toBe("desktop");
  });

  it("setViewportSize({ width, height })", () => {
    const store = useAppStore();
    store.setViewportSize({ width: 800, height: 600 });
    expect(store.viewportSize).toEqual({ width: 800, height: 600 });
  });
});

describe("stores/AppStore — getters", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("getSidebarStatus / getDevice / getViewportWidth / getViewportHeight", () => {
    const store = useAppStore();
    store.sidebar.opened = false;
    store.toggleDevice("mobile");
    store.setViewportSize({ width: 1024, height: 768 });

    expect(store.getSidebarStatus).toBe(false);
    expect(store.getDevice).toBe("mobile");
    expect(store.getViewportWidth).toBe(1024);
    expect(store.getViewportHeight).toBe(768);
  });
});
