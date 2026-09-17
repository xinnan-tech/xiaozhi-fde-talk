import { test, expect } from "@playwright/test"
import { ADMIN_USER, ADMIN_PWD } from "./fixtures/auth"

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
    // 错误文案候选：后端 I18nError 在 zh-CN 是「用户名或密码错误」，
    // en-US 是 "Username or password is incorrect"；旧的兜底 i18n
    // 是「登录失败，请稍后重试」/ "Sign-in failed. Please try again later."。
    // 必须用具体短语 + getByText：home 未登录访问会先弹 "Please sign in first"
    // / "请先登录"（http.auth.not_authenticated），跟"登录"沾边且还在 fade，
    // 只匹配 .el-message 会撞 strict mode 并可能误判。
    await expect(
      page.getByText(/登录失败|用户名或密码|Sign-in failed|Username or password|Login failed/i)
    ).toBeVisible({ timeout: 5_000 })
  })
})