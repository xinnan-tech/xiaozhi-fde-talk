import { test, expect } from "@playwright/test"

// 登录态来自 storageState（global-setup 写入 tests/e2e/.auth/admin.json）；
// F5 刷新应仍持 token：userStore 初始化时 getToken() 读 localStorage[user-info]，
// accessToken 不空 → .user-avatar.online
test("登录后 F5 刷新页面仍保持登录态", async ({ page }) => {
  test.setTimeout(30_000)

  await page.goto("/")
  await expect(page.locator(".user-avatar.online")).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await page.waitForLoadState("domcontentloaded")

  // 仍登录：avatar 带 .online；不弹登录框
  await expect(page.locator(".user-avatar.online")).toBeVisible({ timeout: 15_000 })
  await expect(page.locator(".login-dialog")).not.toBeVisible()
})
