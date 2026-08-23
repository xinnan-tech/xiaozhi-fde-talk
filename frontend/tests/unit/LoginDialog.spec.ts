import { mount } from "@vue/test-utils";
import { describe, it, expect, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import LoginDialog from "@/components/auth/LoginDialog.vue";

describe("LoginDialog", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("默认 mode='login'，点去注册切到 'register'", async () => {
    const wrapper = mount(LoginDialog, { props: { modelValue: true } });
    expect(wrapper.vm.mode ?? "login").toBe("login");
    // 简化：找"去注册"链接点击
    const toggle = wrapper.findAll("a, button").find(b => b.text().includes("注册"));
    if (toggle) await toggle.trigger("click");
    // 断言 confirmPassword 输入框出现
    expect(wrapper.findAll('input[type="password"]').length).toBeGreaterThanOrEqual(2);
  });
});
