import { describe, expect, it, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useSettingStore } from "@/store/modules/settings";

describe("stores/SettingsStore — changeSetting action", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("改 title 生效", () => {
    const store = useSettingStore();
    store.changeSetting({ key: "title", value: "NewTitle" });
    expect(store.title).toBe("NewTitle");
  });

  it("改 hiddenSideBar=true 生效", () => {
    const store = useSettingStore();
    store.changeSetting({ key: "hiddenSideBar", value: true });
    expect(store.hiddenSideBar).toBe(true);
  });

  it("非 state key（notAStateKey）不会污染 state（Reflect.has 守护）", () => {
    const store = useSettingStore() as any;
    store.changeSetting({ key: "notAStateKey", value: "x" });
    expect(store.notAStateKey).toBeUndefined();
    // 原 state 没被改
    expect(store.title).not.toBe("x");
  });

  it("直接调 CHANGE_SETTING action 也工作", () => {
    const store = useSettingStore();
    store.CHANGE_SETTING({ key: "title", value: "ViaAction" });
    expect(store.title).toBe("ViaAction");
  });
});

describe("stores/SettingsStore — getters", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("getTitle / getHiddenSideBar 反映当前值", () => {
    const store = useSettingStore();
    store.changeSetting({ key: "title", value: "T1" });
    store.changeSetting({ key: "hiddenSideBar", value: true });

    expect(store.getTitle).toBe("T1");
    expect(store.getHiddenSideBar).toBe(true);
  });
});
