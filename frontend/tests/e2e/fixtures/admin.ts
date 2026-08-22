import type { Page } from "@playwright/test"

const ADMIN_USER = "admin"
const ADMIN_PWD = "longenough1234" // 与 backend/tests/conftest.py::_TEST_ADMIN_PASSWORD 保持一致

// 登录流：浏览器到 `/` → 路由守卫送 /home → /home 视图检测无 token 自动 openLogin()
// → <LoginDialog> el-dialog 弹窗（class="login-dialog"）→ 填 username + password → 点登录按钮
// selector 用结构化定位（不依赖 i18n 文案 / placeholder 文本）：
//   .login-dialog > input:nth(0) = 用户名；.login-dialog > input:nth(1) = 密码；.login-btn = 提交
export async function loginAsAdmin(page: Page) {
  await page.goto("/")
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