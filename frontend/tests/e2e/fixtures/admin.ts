import type { Page } from "@playwright/test"
import { ADMIN_USER, ADMIN_PWD } from "./auth"

export { ADMIN_USER, ADMIN_PWD }

// 登录流：浏览器到 `/` → 路由守卫送 /home → home 视图不会自动 openLogin，
// 需点 .user-avatar（views/home/index.vue:323）触发 dialogStore.openLogin() →
// <LoginDialog> el-dialog 弹窗（class="login-dialog"）→ 填 username + password
// → 点登录按钮。后端 POST /api/v1/auth/login 200 后 dialog 关闭、token 入 store。
// selector 用结构化定位（不依赖 i18n 文案 / placeholder 文本）：
//   .login-dialog > input:nth(0) = 用户名；.login-dialog > input:nth(1) = 密码；.login-btn = 提交
//
// chromium project use.storageState 默认带登录态（globalSetup 一次写入），
// 已登录时 .user-avatar 带 .online class；幂等跳过避免无效点击触发登出确认弹窗
export async function loginAsAdmin(page: Page) {
  await page.goto("/")
  // 先等 home 视图挂载完 + userStore 恢复完，避免 .online 类的 race：
  // 否则 avatar 已挂上 .online 但 click 触发的是登出 confirm 而不是 login dialog
  const avatar = page.locator(".user-avatar")
  await avatar.waitFor({ state: "visible", timeout: 15_000 })
  if (await page.locator(".user-avatar.online").isVisible().catch(() => false)) {
    return
  }
  await avatar.click()
  const dialog = page.locator(".login-dialog")
  await dialog.waitFor({ state: "visible", timeout: 15_000 })
  await dialog.locator("input").nth(0).fill(ADMIN_USER)
  await dialog.locator("input").nth(1).fill(ADMIN_PWD)
  await dialog.locator(".login-btn").click()
  await dialog.waitFor({ state: "hidden", timeout: 15_000 })
}

// 直接断言 LoginDialog 当前是否可见（spec 失败用例要用）
export async function isLoginDialogVisible(page: Page): Promise<boolean> {
  return page.locator(".login-dialog").isVisible().catch(() => false)
}