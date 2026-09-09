import { describe, expect, it, beforeEach } from "vitest";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { useUserStoreHook } from "@/store/modules/user";
import { setBootstrapped } from "@/utils/auth";

// 源码 dialog.ts 用 useDialogStoreHook() / useUserStoreHook()（单例 pinia）。
// 测试也走单例，避免 active pinia 改动不到 source 的读路径。
// isBootstrapped() 是模块级状态，beforeEach 复位。

describe("stores/DialogStore — state init", () => {
  beforeEach(() => {
    useDialogStoreHook().$reset();
    useUserStoreHook().$reset();
    setBootstrapped(false);
  });

  it("默认 createInterviewVisible=false, loginVisible=false", () => {
    const dlg = useDialogStoreHook();
    expect(dlg.createInterviewVisible).toBe(false);
    expect(dlg.loginVisible).toBe(false);
  });
});

describe("stores/DialogStore — openCreateInterview 路由分支（HttpOnly）", () => {
  beforeEach(() => {
    useDialogStoreHook().$reset();
    useUserStoreHook().$reset();
    setBootstrapped(false);
  });

  it("isBootstrapped=false 时：跳到 openLogin()，不打开 createInterview", () => {
    setBootstrapped(false);
    const dlg = useDialogStoreHook();
    dlg.openCreateInterview();

    expect(dlg.loginVisible).toBe(true);
    expect(dlg.createInterviewVisible).toBe(false);
  });

  it("isBootstrapped=true 时：打开 createInterview，loginVisible 不变", () => {
    setBootstrapped(true);
    const dlg = useDialogStoreHook();
    dlg.openCreateInterview();

    expect(dlg.createInterviewVisible).toBe(true);
    expect(dlg.loginVisible).toBe(false);
  });
});

describe("stores/DialogStore — closeCreateInterview", () => {
  beforeEach(() => {
    useDialogStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("把 createInterviewVisible 关掉", () => {
    const dlg = useDialogStoreHook();
    dlg.createInterviewVisible = true;
    dlg.closeCreateInterview();
    expect(dlg.createInterviewVisible).toBe(false);
  });
});

describe("stores/DialogStore — openLogin / closeLogin", () => {
  beforeEach(() => {
    useDialogStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("openLogin 把 loginVisible=true", () => {
    const dlg = useDialogStoreHook();
    dlg.openLogin();
    expect(dlg.loginVisible).toBe(true);
  });

  it("closeLogin 把 loginVisible=false", () => {
    const dlg = useDialogStoreHook();
    dlg.loginVisible = true;
    dlg.closeLogin();
    expect(dlg.loginVisible).toBe(false);
  });
});