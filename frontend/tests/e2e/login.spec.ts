import { test, expect } from "@playwright/test"

const ADMIN_USER = "admin"
const ADMIN_PWD = "longenough1234"

// login.spec.ts 必须从「空 storageState」起步，才能验证
// 「未登录 → 触发登录框 → 提交 → 落 home」整条链路。
// chromium project 默认 use.storageState 已含登录态；这里 opt-out。
test.use({ storageState: { cookies: [], origins: [] } })

test.describe("login flow", () => {
  test("admin login closes dialog and lands on authenticated home", async ({ page }) => {
    // home 视图未登录时不会自动开 login dialog（brief 的假设有误）；
    // 实际触发点是 .user-avatar 点击。这里手动点开 dialog，再走同款流程。
    await page.goto("/")
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })
    await dialog.locator("input").nth(0).fill(ADMIN_USER)
    await dialog.locator("input").nth(1).fill(ADMIN_PWD)
    await dialog.locator(".login-btn").click()
    await dialog.waitFor({ state: "hidden", timeout: 15_000 })

    expect(await dialog.isVisible().catch(() => false)).toBe(false)
    const url = page.url()
    expect(url).toMatch(/4173\/(home)?(\?|$|#|\/)/)
    // 登录成功的直接证据：success message「Signed in successfully / 登录成功」
    //（home 视图不在 body 渲染用户名，只用头像 + online class，无法用 toContainText 抓）
    await expect(page.locator(".el-message--success")).toContainText(
      /登录成功|Signed in|success/i,
      { timeout: 5_000 }
    )
  })

  test("wrong password keeps dialog open with error", async ({ page }) => {
    await page.goto("/")
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })
    await dialog.locator("input").nth(0).fill("admin")
    await dialog.locator("input").nth(1).fill("definitely-wrong-password")
    await dialog.locator(".login-btn").click()
    // dialog 仍在（登录失败不会关闭）
    await expect(dialog).toBeVisible({ timeout: 5_000 })
    // Element Plus error message：前端 locale 默认 zh-CN 是「登录失败，请稍后再试」，
    // en-US 是 "Sign-in failed. Please try again later."——两条 regex 都覆盖
    await expect(page.locator(".el-message")).toContainText(
      /登录失败|登录|Sign-in failed|failed|失败|invalid|error/i,
      { timeout: 5_000 }
    )
  })
})