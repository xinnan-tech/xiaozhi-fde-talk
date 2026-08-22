import type { Page } from "@playwright/test"

const ADMIN_USER = "admin"
const ADMIN_PWD = "longenough1234" // 与 backend/tests/conftest.py::_TEST_ADMIN_PASSWORD 保持一致

// 登录流：浏览器到 `/` → 路由守卫送 /home → home 视图不会自动 openLogin，
// 需点 .user-avatar（views/home/index.vue:323）触发 dialogStore.openLogin() →
// <LoginDialog> el-dialog 弹窗（class="login-dialog"）→ 填 username + password
// → 点登录按钮。后端 POST /api/v1/auth/login 200 后 dialog 关闭、token 入 store。
// selector 用结构化定位（不依赖 i18n 文案 / placeholder 文本）：
//   .login-dialog > input:nth(0) = 用户名；.login-dialog > input:nth(1) = 密码；.login-btn = 提交
export async function loginAsAdmin(page: Page) {
  await page.goto("/")
  await page.locator(".user-avatar").click()
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