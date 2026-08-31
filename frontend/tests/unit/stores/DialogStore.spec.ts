import { describe, expect, it, beforeEach } from "vitest";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { useUserStoreHook } from "@/store/modules/user";

// 源码 dialog.ts 用 useDialogStoreHook() / useUserStoreHook()（单例 pinia）。
// 测试也走单例，避免 active pinia 改动不到 source 的读路径。

describe("stores/DialogStore — state init", () => {
  beforeEach(() => {
    useDialogStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("默认 createInterviewVisible=false, loginVisible=false", () => {
    const dlg = useDialogStoreHook();
    expect(dlg.createInterviewVisible).toBe(false);
    expect(dlg.loginVisible).toBe(false);
  });
});

describe("stores/DialogStore — openCreateInterview 路由分支", () => {
  beforeEach(() => {
    useDialogStoreHook().$reset();
    useUserStoreHook().$reset();
  });

  it("无 accessToken 时：跳到 openLogin()，不打开 createInterview", () => {
    const user = useUserStoreHook();
    user.accessToken = "";

    const dlg = useDialogStoreHook();
    dlg.openCreateInterview();

    expect(dlg.loginVisible).toBe(true);
    expect(dlg.createInterviewVisible).toBe(false);
  });

  it("有 accessToken 时：打开 createInterview，loginVisible 不变", () => {
    const user = useUserStoreHook();
    user.SET_ACCESS_TOKEN("tok");

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
