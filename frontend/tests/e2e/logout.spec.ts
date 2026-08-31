import { test, expect } from "@playwright/test"

// 已登录 → hover 头像外层 BaseSelect 容器 .user-avatar-dropdown
// （home/index.vue:339，BaseSelect 把 @mouseenter 绑在最外层 .base-select 上，
// hover 内层 .user-avatar 不会冒泡触发）→ 菜单 BaseSelect 渲染 role="option"
// 列表（home/index.vue:69 userOperationOptions 含 change_password / logout）→
// 点 label 为「退出」/「Sign out」的 option → handleAvatarSelectChange('logout')
// → userStore.logOut() + ElMessage.success（无中间 ElMessageBox 确认）
// → removeToken() 清 localStorage[user-info] 与 cookie[authorized-token]
// → 再 hover avatar 触发 login-dialog（home 视图不自动弹登录框，见 redirect.spec.ts）
//
// 默认 chromium project 带 storageState（global-setup 写入）
test("已登录用户点登出后 token 清掉、再点 avatar 弹登录框", async ({ page }) => {
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

  // localStorage[user-info] 已清（storageLocal.removeItem(userKey)）
  const userInfo = await page.evaluate(() => localStorage.getItem("user-info"))
  expect(userInfo).toBeNull()

  // cookie[authorized-token] 已清（auth.ts:40 Cookies.remove(TokenKey)）
  const tokenCookie = await page.evaluate(() =>
    document.cookie
      .split(";")
      .map(s => s.trim())
      .find(s => s.startsWith("authorized-token="))
  )
  expect(tokenCookie === undefined || tokenCookie === "authorized-token=").toBe(true)

  // 再点 avatar（未登录态）触发 dialogStore.openLogin() → .login-dialog 弹出
  await page.locator(".user-avatar").click()
  await expect(page.locator(".login-dialog")).toBeVisible({ timeout: 10_000 })
})
