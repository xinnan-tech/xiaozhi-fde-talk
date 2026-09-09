import { test, expect } from "@playwright/test"

// 已登录 → hover 头像外层 BaseSelect 容器 .user-avatar-dropdown
// （home/index.vue，BaseSelect 把 @mouseenter 绑在最外层 .base-select 上，
// hover 内层 .user-avatar 不会冒泡触发）→ 菜单 BaseSelect 渲染 role="option"
// 列表 → 点 label 为「退出」/「Sign out」的 option → handleAvatarSelectChange('logout')
// → userStore.logOut() → POST /auth/logout（cookie 自动附）→ 后端撤销 jti +
// Set-Cookie Max-Age=0 清两个 cookie + 浏览器清 cookie + 前端清 Pinia。
//
// HttpOnly cookie 由浏览器管理，document.cookie 看不到
// HttpOnly 项（这是 XSS 防御契约）。登出后用 context.cookies() 直接查
// Playwright 持有的 cookie 列表应不包含 authorized-token / refresh-token。
//
// 默认 chromium project 带 storageState（global-setup 写入 HttpOnly cookie）
test("已登录用户点登出后 cookie 清掉、avatar 掉线、再点 avatar 弹登录框", async ({
  page,
  context
}) => {
  test.setTimeout(30_000)

  await page.goto("/")
  // 已登录指示：.user-avatar.online
  await expect(page.locator(".user-avatar.online")).toBeVisible({ timeout: 15_000 })

  // hover 头像外层 BaseSelect 容器（mouseenter 才冒泡到外层监听器）
  await page.locator(".user-avatar-dropdown").hover()
  const menu = page.locator(".base-select-menu.is-open")
  await menu.waitFor({ state: "visible", timeout: 10_000 })

  // BaseSelect 菜单里 role="option" 的按钮，按 label 匹配「退出」/「Sign out」
  await menu.getByRole("option", { name: /^退出$|^Sign out$/ }).click()

  // 登出后：avatar 不再带 .online
  await expect(page.locator(".user-avatar.online")).toHaveCount(0, { timeout: 10_000 })

  // HttpOnly cookie 由浏览器管，logout API 返 Set-Cookie Max-Age=0 后
  // Playwright 持有的 cookie 列表里这两个应被移除。
  const cookiesAfter = await context.cookies()
  const cookieMap = Object.fromEntries(cookiesAfter.map(c => [c.name, c]))
  expect(cookieMap["authorized-token"]).toBeUndefined()
  expect(cookieMap["refresh-token"]).toBeUndefined()

  // 再点 avatar（未登录态）触发 dialogStore.openLogin() → .login-dialog 弹出
  await page.locator(".user-avatar").click()
  await expect(page.locator(".login-dialog")).toBeVisible({ timeout: 10_000 })
})