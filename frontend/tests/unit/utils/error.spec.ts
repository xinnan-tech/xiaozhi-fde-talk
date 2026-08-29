import { describe, it, expect } from "vitest";
import { extractBackendError, extractDetailText } from "@/utils/error";

describe("utils/error — extractBackendError", () => {
  it("e 为 null → 返回 fallback", () => {
    expect(extractBackendError(null, "F")).toBe("F");
  });

  it("e 为 undefined → 返回 fallback", () => {
    expect(extractBackendError(undefined, "F")).toBe("F");
  });

  it("response.data.detail 为字符串 → 原样返回", () => {
    const e = { response: { data: { detail: "服务繁忙" } } };
    expect(extractBackendError(e, "F")).toBe("服务繁忙");
  });

  it("pydantic 422 单条 → field: msg 拼接", () => {
    const e = {
      response: {
        data: {
          detail: [{ loc: ["body", "username"], msg: "required", type: "value_error" }]
        }
      }
    };
    expect(extractBackendError(e, "F")).toBe("username: required");
  });

  it("pydantic 422 多条 → 用 ； 拼接", () => {
    const e = {
      response: {
        data: {
          detail: [
            { loc: ["body", "username"], msg: "required", type: "value_error" },
            { loc: ["body", "password"], msg: "too short", type: "value_error" }
          ]
        }
      }
    };
    expect(extractBackendError(e, "F")).toBe("username: required；password: too short");
  });

  it("缺 detail → 返回 fallback", () => {
    const e = { response: { data: {} } };
    expect(extractBackendError(e, "F")).toBe("F");
  });

  it("detail 为 null → 返回 fallback", () => {
    const e = { response: { data: { detail: null } } };
    expect(extractBackendError(e, "F")).toBe("F");
  });

  it("detail 是数组但单条 msg 缺失 → 跳过该项；全跳则用 fallback", () => {
    const e = {
      response: {
        data: {
          detail: [{ loc: ["body", "x"], type: "value_error" }]
        }
      }
    };
    expect(extractBackendError(e, "F")).toBe("F");
  });

  it("loc 只有一个元素 → 不带 field 前缀", () => {
    const e = {
      response: {
        data: { detail: [{ loc: ["x"], msg: "boom" }] }
      }
    };
    expect(extractBackendError(e, "F")).toBe("boom");
  });

  it("空 detail 数组 → 返回 fallback", () => {
    const e = { response: { data: { detail: [] } } };
    expect(extractBackendError(e, "F")).toBe("F");
  });
});

describe("utils/error — extractDetailText", () => {
  it("字符串 detail → 原样返回", () => {
    expect(extractDetailText("err")).toBe("err");
  });

  it("空白字符串 → 返回空串（由调用方兜底）", () => {
    expect(extractDetailText("   ")).toBe("");
  });

  it("null / undefined → 返回空串", () => {
    expect(extractDetailText(null)).toBe("");
    expect(extractDetailText(undefined)).toBe("");
  });

  it("pydantic 单条 → field: msg", () => {
    expect(
      extractDetailText([{ loc: ["body", "username"], msg: "required" }])
    ).toBe("username: required");
  });

  it("pydantic 多条 → 用 ； 拼接", () => {
    expect(
      extractDetailText([
        { loc: ["body", "username"], msg: "required" },
        { loc: ["body", "password"], msg: "too short" }
      ])
    ).toBe("username: required；password: too short");
  });

  it("单条 msg 缺失 → 跳过；全跳返回空串", () => {
    expect(extractDetailText([{ loc: ["body", "x"], type: "value_error" }])).toBe("");
  });

  it("空数组 → 返回空串", () => {
    expect(extractDetailText([])).toBe("");
  });

  it("非字符串 / 非数组 detail → 返回空串", () => {
    expect(extractDetailText(42)).toBe("");
    expect(extractDetailText({})).toBe("");
  });
});