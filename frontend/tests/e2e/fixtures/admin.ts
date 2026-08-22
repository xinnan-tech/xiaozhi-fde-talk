import type { Page } from "@playwright/test"

const ADMIN_USER = "admin"
const ADMIN_PWD = "longenough1234" // 与 backend/tests/conftest.py::_TEST_ADMIN_PASSWORD 保持一致

export async function loginAsAdmin(page: Page) {
  await page.goto("/login")
  await page.getByLabel(/用户名|name|user/i).first().fill(ADMIN_USER)
  await page.getByLabel(/密码|password|pwd/i).first().fill(ADMIN_PWD)
  await page.getByRole("button", { name: /登录|login|sign in/i }).click()
  await page.waitForURL(/\/(home|dashboard|$)/, { timeout: 15_000 })
}
