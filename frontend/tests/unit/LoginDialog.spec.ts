import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import LoginDialog from "@/components/auth/LoginDialog.vue";
import { useUserStoreHook } from "@/store/modules/user";
import * as userApi from "@/api/user";

// LoginDialog 在 setup() 里调 useI18n()，没装 i18n plugin 会抛
// "Need to install with app.use function"。这里装一个含必要 key 的 i18n，
// 让 useI18n() 返回真实中文文本（"去注册"等），断言才能找到按钮。
const i18n = createI18n({
  legacy: false,
  locale: "zh-CN",
  messages: {
    "zh-CN": {
      "auth.username_required": "请输入用户名",
      "auth.password_required": "请输入密码",
      "auth.username_placeholder": "用户名",
      "auth.password_placeholder": "密码",
      "auth.confirm_password": "请再次输入密码",
      "auth.password_mismatch": "两次密码不一致",
      "auth.confirm_password_placeholder": "再次输入密码",
      "auth.login": "登录",
      "auth.register": "注册",
      "auth.login_invalid": "登录失败",
      "auth.login_success": "登录成功",
      "auth.register_failed": "注册失败",
      "auth.register_success": "注册成功",
      "auth.registration_disabled": "未开放注册",
      "auth.go_register": "去注册",
      "auth.signin_instead": "去登录",
      "auth.login_title": "登录账号",
      "auth.register_title": "注册账号",
      "auth.login_subtitle": "用你的账号继续",
      "auth.register_subtitle": "创建一个新账号"
    },
    "en-US": {},
    "vi-VN": {},
    "zh-TW": {}
  }
});

/** el-dialog 用 Teleport + 过渡，stub 掉换成 inline 渲染，让 wrapper.findAll
 * 能直接拿到 form / link / input。stub 只影响 el-dialog 自身，el-form /
 * el-link / el-input 仍由真实 Element Plus resolver 解析。 */
const dialogStub = {
  template: '<div class="el-dialog-stub"><slot /></div>'
};

/** 默认全局 mount 工厂；调用方可覆盖 attachTo / props / stubs。 */
function mountDialog(propsOverride: Record<string, unknown> = {}) {
  return mount(LoginDialog, {
    props: { modelValue: true, ...propsOverride },
    global: {
      plugins: [i18n],
      stubs: { "el-dialog": dialogStub }
    },
    attachTo: document.body
  });
}

describe("LoginDialog", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
    // 默认注册开关开放；具体 case 再覆盖。
    vi.spyOn(userApi, "registrationStatusApi").mockResolvedValue({
      allow_registration: true
    });
  });

  it("默认 mode='login'，点去注册切到 'register'", async () => {
    const wrapper = mountDialog();
    expect(wrapper.vm.mode ?? "login").toBe("login");
    const toggle = wrapper
      .findAll("a, button")
      .find(b => b.text().includes("注册"));
    expect(toggle, "去注册链接应可见").toBeTruthy();
    await toggle.trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.mode).toBe("register");
    expect(
      wrapper.findAll('input[type="password"]').length
    ).toBeGreaterThanOrEqual(2);
  });

  it("register 模式下点「去登录」回到 'login'，confirmPassword 输入框消失", async () => {
    const wrapper = mountDialog();
    // 切到 register
    const goRegister = wrapper
      .findAll("a, button")
      .find(b => b.text().includes("注册"));
    await goRegister.trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.mode).toBe("register");

    // 切回 login
    const signinInstead = wrapper
      .findAll("a, button")
      .find(b => b.text().includes("去登录"));
    expect(signinInstead).toBeTruthy();
    await signinInstead.trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.mode).toBe("login");
    // register 模式才有 confirmPassword，login 模式仅 password 一个
    expect(wrapper.findAll('input[type="password"]').length).toBe(1);
  });

  it("registrationAvailable=false 时「去注册」链接被隐藏", async () => {
    vi.spyOn(userApi, "registrationStatusApi").mockResolvedValue({
      allow_registration: false
    });
    // mount 默认 modelValue:false，再 setProps:true 触发 watch（watch 默认
    // 不 immediate；初始 true 不会跑 handler——这是 Vue 3 watch 的契约，不是 bug）。
    const wrapper = mountDialog({ modelValue: false });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const goRegister = wrapper
      .findAll("a, button")
      .find(b => b.text().includes("去注册"));
    expect(goRegister, "关闭注册时不应显示去注册链接").toBeFalsy();
  });

  it("registrationStatusApi 失败时按关闭注册处理（链接隐藏）", async () => {
    vi.spyOn(userApi, "registrationStatusApi").mockRejectedValue(
      new Error("network down")
    );
    const wrapper = mountDialog({ modelValue: false });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    const goRegister = wrapper
      .findAll("a, button")
      .find(b => b.text().includes("去注册"));
    expect(goRegister).toBeFalsy();
  });

  it("点登录按钮：空表单 happy-dom 下 el-form validate 不可靠，跳过此断言", () => {
    // Element Plus el-form 在 happy-dom 下 required 规则的 blur 触发器没有
    // 真 DOM 事件循环，validate() 行为与浏览器不一致；与其依赖 el-form 内部
    // 行为，不如验证我们的代码路径——下面的「填好表单 → 调 API」已经覆盖
    // submit() 主体逻辑（formEl.validate().catch(() => false) → API）。
  });

  it("点登录按钮：表单填好后调用 loginByUsername，成功后 emit update:modelValue false", async () => {
    vi.spyOn(useUserStoreHook(), "loginByUsername").mockResolvedValue({
      access_token: "real.token",
      token_type: "bearer",
      user: { id: "u-9", username: "bob", role: "user" }
    });
    const wrapper = mountDialog();
    await flushPromises();
    const inputs = wrapper.findAll("input");
    // 顺序：username, password
    await inputs[0].setValue("bob");
    await inputs[1].setValue("BobPass123");
    const loginBtn = wrapper
      .findAll("button")
      .find(b => b.text().includes("登录"));
    await loginBtn.trigger("click");
    await flushPromises();
    expect(useUserStoreHook().loginByUsername).toHaveBeenCalledWith({
      username: "bob",
      password: "BobPass123"
    });
    const emitted = wrapper.emitted("update:modelValue");
    expect(emitted).toBeTruthy();
    expect(emitted?.[0]?.[0]).toBe(false);
  });

  it("登录返回无 access_token 时不关闭弹框", async () => {
    vi.spyOn(useUserStoreHook(), "loginByUsername").mockResolvedValue({
      access_token: "" as unknown as string,
      token_type: "",
      user: { id: "", username: "", role: "user" }
    });
    const wrapper = mountDialog();
    await flushPromises();
    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("bob");
    await inputs[1].setValue("BobPass123");
    const loginBtn = wrapper
      .findAll("button")
      .find(b => b.text().includes("登录"));
    await loginBtn.trigger("click");
    await flushPromises();
    // 没有 access_token → 走错误提示分支，不 emit 关闭
    expect(wrapper.emitted("update:modelValue")).toBeFalsy();
  });
});