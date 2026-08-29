import { describe, it, expect } from "vitest";
import propTypes from "@/utils/propTypes";

describe("utils/propTypes — basic validators (inherited from createTypes)", () => {
  // 注意：vue-types v6 的 BaseVueTypes 静态 getter 直接返回 validator 对象，
  // 不是工厂函数（不能再加 () 调用）。所以这里访问 propTypes.bool 而不是
  // propTypes.bool()。
  it("bool / string / number / integer / object / func 静态 getter 存在", () => {
    expect("bool" in propTypes).toBe(true);
    expect("string" in propTypes).toBe(true);
    expect("number" in propTypes).toBe(true);
    expect("integer" in propTypes).toBe(true);
    expect("object" in propTypes).toBe(true);
    expect("func" in propTypes).toBe(true);
  });

  it("bool 返回带 _vueTypes_name='boolean'、type=Boolean 的 validator", () => {
    // vue-types 内部 bool() 写的是 _vueTypes_name='boolean'，与 getter 名 'bool' 不同；
    // 这里锁定真实名字，避免误以为 getter 名 = 类型名。
    const v = propTypes.bool;
    expect(v).toBeDefined();
    expect(v._vueTypes_name).toBe("boolean");
    expect(v.type).toBe(Boolean);
  });

  it("string 返回带 _vueTypes_name='string'、type=String 的 validator", () => {
    const v = propTypes.string;
    expect(v._vueTypes_name).toBe("string");
    expect(v.type).toBe(String);
  });

  it("number 返回带 _vueTypes_name='number'、type=Number 的 validator", () => {
    const v = propTypes.number;
    expect(v._vueTypes_name).toBe("number");
    expect(v.type).toBe(Number);
  });

  it("integer 返回带 _vueTypes_name='integer'、type=Number 的 validator", () => {
    const v = propTypes.integer;
    expect(v._vueTypes_name).toBe("integer");
    expect(v.type).toBe(Number);
  });

  it("object 返回带 _vueTypes_name='object'、type=Object 的 validator", () => {
    const v = propTypes.object;
    expect(v._vueTypes_name).toBe("object");
    expect(v.type).toBe(Object);
  });

  it("func 返回带 _vueTypes_name='function'、type=Function 的 validator", () => {
    const v = propTypes.func;
    expect(v._vueTypes_name).toBe("function");
    expect(v.type).toBe(Function);
  });

  it("每个 validator 暴露 def / isRequired / validate", () => {
    const v = propTypes.bool;
    expect(typeof v.def).toBe("function");
    expect(typeof v.validate).toBe("function");
    expect(v.isRequired).toBeDefined();
  });
});

describe("utils/propTypes — style (toValidableType)", () => {
  it("style 返回 validable validator，_vueTypes_name='style'", () => {
    const v = propTypes.style;
    expect(v).toBeDefined();
    expect(v._vueTypes_name).toBe("style");
  });

  it("style.type 是 [String, Object] 数组（validable 形态）", () => {
    const v = propTypes.style;
    expect(Array.isArray(v.type)).toBe(true);
    expect(v.type).toContain(String);
    expect(v.type).toContain(Object);
  });

  it("style 暴露 .validate 方法", () => {
    expect(typeof propTypes.style.validate).toBe("function");
  });
});

describe("utils/propTypes — VNodeChild (toValidableType)", () => {
  it("VNodeChild 返回 validable validator", () => {
    const v = propTypes.VNodeChild;
    expect(v).toBeDefined();
    expect(v._vueTypes_name).toBe("VNodeChild");
    expect(v.type).toBeUndefined();
  });

  it("VNodeChild 暴露 .validate 方法", () => {
    expect(typeof propTypes.VNodeChild.validate).toBe("function");
  });
});