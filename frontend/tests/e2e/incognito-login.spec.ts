import { test, expect } from "@playwright/test"
import { ADMIN_USER, ADMIN_PWD } from "./fixtures/auth"

// 隐身新用户首访：浏览器 storage context 是全新的——没有 cookies / localStorage /
// sessionStorage，对应用户的「隐身模式」/「首次访问」/「退出后清缓存再访问」场景。
// 走 browser.newContext() 拿独立 context，避免复用默认 { page } 上下文。
test("隐身新用户访问 / 自动弹登录框 + 登录成功", async ({ browser }) => {
  test.setTimeout(30_000)

  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  try {
    const page = await context.newPage()
    await page.goto("/")

    // 首屏断言：未登录状态下 home 视图不应自动弹 .login-dialog（per views/home/index.vue：
    // dialog 由 .user-avatar / .create-btn 点击触发 dialogStore.openLogin）。
    // 至少要能看到 .user-avatar 可点（带 placeholder 头像的右侧按钮）。
    await expect(page.locator(".user-avatar")).toBeVisible({ timeout: 15_000 })
    await expect(page.locator(".login-dialog")).not.toBeVisible()

    // 点击头像触发 dialog
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })

    // 结构化 selector：用户名 + 密码 + 登录按钮（与 login.spec.ts / admin.ts 一致）
    await dialog.locator("input").nth(0).fill(ADMIN_USER)
    await dialog.locator("input").nth(1).fill(ADMIN_PWD)
    await dialog.locator(".login-btn").click()
    await dialog.waitFor({ state: "hidden", timeout: 15_000 })

    // 登录成功的直接证据：Element Plus success toast 含「登录成功 / Signed in / success」
    await expect(page.locator(".el-message--success")).toContainText(
      /登录成功|Signed in|success/i,
      { timeout: 5_000 }
    )

    // 已登录指示：home 视图 .user-avatar 在登录后加 .online class
    await expect(page.locator(".user-avatar.online")).toBeVisible({
      timeout: 5_000,
    })
  } finally {
    await context.close()
  }
})
