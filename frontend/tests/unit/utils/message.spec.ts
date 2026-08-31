import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// vi.mock 工厂会被 hoist 到模块顶部，普通 const/let 还没初始化。
// vi.hoisted 让这部分定义也同步 hoist，让 mock 工厂能拿到。
const { elMessageFn } = vi.hoisted(() => {
  const fn = vi.fn().mockReturnValue("handler-id");
  // closeAll 是 ElMessage 的静态方法，挂到函数上即可模拟。
  fn.closeAll = vi.fn();
  return { elMessageFn: fn };
});

vi.mock("element-plus", () => ({
  ElMessage: elMessageFn
}));

// 必须在 mock 之后再 import，否则模块顶层会拿到真的 ElMessage。
import { message, closeAllMessage } from "@/utils/message";

describe("utils/message — message()", () => {
  beforeEach(() => {
    elMessageFn.mockClear();
  });
  afterEach(() => {
    elMessageFn.mockClear();
  });

  it("无 params：调用 ElMessage，customClass='pure-message'", () => {
    const handler = message("hi");
    expect(handler).toBe("handler-id");
    expect(elMessageFn).toHaveBeenCalledWith({
      message: "hi",
      customClass: "pure-message"
    });
  });

  it("type=warning：传递 type；customClass='pure-message'（默认 antd 替换）", () => {
    message("warn", { type: "warning" });
    expect(elMessageFn).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "warn",
        type: "warning",
        customClass: "pure-message"
      })
    );
  });

  it("customClass='el'：customClass 传空串", () => {
    message("ok", { customClass: "el" });
    expect(elMessageFn).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "ok",
        customClass: ""
      })
    );
  });

  it("dangerouslyUseHTMLString=true：原样传递", () => {
    message("html", { dangerouslyUseHTMLString: true });
    expect(elMessageFn).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "html",
        dangerouslyUseHTMLString: true
      })
    );
  });

  it("默认 duration=2000（覆盖 element-plus 的 3000）", () => {
    // 注意：源码里 duration 只在 params 存在时才参与拼装 options 对象；
    // 调 message("dur") 不传 params 时 ElMessage 收到的只有 {message, customClass}。
    // 这里传空对象让 params 分支生效，验证默认 duration=2000。
    message("dur", {});
    expect(elMessageFn).toHaveBeenCalledWith(
      expect.objectContaining({ duration: 2000 })
    );
  });

  it("显式 duration 覆盖默认值", () => {
    message("dur", { duration: 5000 });
    expect(elMessageFn).toHaveBeenCalledWith(
      expect.objectContaining({ duration: 5000 })
    );
  });

  it("onClose 非函数时封一层 → 调 onClose 直接被丢弃", () => {
    message("o", { onClose: "not a fn" as any });
    const call = elMessageFn.mock.calls[0][0];
    expect(() => call.onClose()).not.toThrow();
  });

  it("onClose 是函数时会被原样调用", () => {
    const cb = vi.fn();
    message("o", { onClose: cb });
    const call = elMessageFn.mock.calls[0][0];
    call.onClose();
    expect(cb).toHaveBeenCalled();
  });
});

describe("utils/message — closeAllMessage()", () => {
  it("调用 ElMessage.closeAll()", () => {
    (elMessageFn.closeAll as ReturnType<typeof vi.fn>).mockClear();
    closeAllMessage();
    expect(elMessageFn.closeAll).toHaveBeenCalledTimes(1);
  });
});