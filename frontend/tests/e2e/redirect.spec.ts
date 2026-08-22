import { test, expect } from "@playwright/test"
import { loginAsAdmin } from "./fixtures/admin"

test.describe("route guards", () => {
  test("unauthenticated visit to non-/home protected route is redirected to /home", async ({
    page,
    context,
  }) => {
    // 清掉任何残留 token / cookie
    await context.clearCookies()
    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })
    // /interviews 不在 whiteList ["/home","/system","/system/config"]，守卫会送 /home
    await page.goto("/interviews")
    await expect(page).toHaveURL(/\/home/, { timeout: 10_000 })
    // home 视图未登录时不会自动 openLogin（弹窗只在点 .user-avatar / .create-btn 时弹出）
    await expect(page.locator(".login-dialog")).not.toBeVisible()
  })

  test("authenticated visit to /home stays on /home", async ({ page }) => {
    // loginAsAdmin 已封装：goto → 点 .user-avatar → 填表 → 登录 → dialog 隐藏
    await loginAsAdmin(page)
    // 登录后再访问 /home 应稳定
    await page.goto("/home")
    await expect(page).toHaveURL(/\/home/, { timeout: 10_000 })
    // 登录态指示器：home 视图 .user-avatar 在已登录时带 .online class（views/home/index.vue:324）
    await expect(page.locator(".user-avatar.online")).toBeVisible({
      timeout: 5_000,
    })
  })
})
