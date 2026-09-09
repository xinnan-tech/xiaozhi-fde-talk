import { test, expect } from "@playwright/test"

// HttpOnly cookie 模型——前后端都用 HttpOnly cookie 持有
// access_token / refresh_token，浏览器自动管（不可被 JS 读、跨 F5 持久）。
// F5 / 关页面再开页面，cookie 仍在 → 前端 main.ts bootstrap 调 /auth/me 重建
// Pinia → 用户仍是登录态。这条 spec 锁住核心契约：「F5 不会丢登录」。
//
// XSS 缓解：从同源 JS（任意路径）拿不到 accessToken（HttpOnly 拒 JS 读），
// 也不进 localStorage / js-cookie（前端 JS 堆不存任何 token）。
test("登录后 F5 刷新页面 → cookie 持久 → 仍是登录态（HttpOnly 模型核心契约）", async ({
  page,
  context
}) => {
  test.setTimeout(30_000)

  await page.goto("/")
  // 初始登录态（global-setup 已 UI 登录并写入 HttpOnly cookie 到 storageState）
  await expect(page.locator(".user-avatar.online")).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await page.waitForLoadState("domcontentloaded")

  // 关键断言 1：F5 后仍是登录态——HttpOnly cookie 持久，bootstrap 调
  // /auth/me 重建 Pinia user 字段，avatar 重新挂 .online。
  await expect(page.locator(".user-avatar.online")).toBeVisible({ timeout: 15_000 })

  // 关键断言 2：HttpOnly cookie 仍在 Playwright cookie jar 里（F5 不丢）。
  const cookies = await context.cookies()
  const cookieMap = Object.fromEntries(cookies.map(c => [c.name, c]))
  expect(cookieMap["authorized-token"]).toBeDefined()
  expect(cookieMap["refresh-token"]).toBeDefined()

  // 关键断言 3：document.cookie 看不到 HttpOnly 项（XSS 防御契约）。
  const docCookie = await page.evaluate(() => document.cookie)
  expect(docCookie).not.toContain("authorized-token")
  expect(docCookie).not.toContain("refresh-token")

  // 关键断言 4：localStorage 不含 accessToken / refreshToken 明文。
  const userInfo = await page.evaluate(() => localStorage.getItem("user-info"))
  if (userInfo) {
    expect(userInfo).not.toMatch(/accessToken|refreshToken/)
  }
})