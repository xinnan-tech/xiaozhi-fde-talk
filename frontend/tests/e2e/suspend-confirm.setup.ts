// 直接通过 UI 登录 admin（与 tests/e2e/global-setup.ts 一致），
// 浏览器到 `/` → 路由守卫送 /home → home 视图不自动 openLogin，
// 需点 .user-avatar 触发 dialogStore.openLogin → <LoginDialog> el-dialog
// 弹窗 → 填 username + password → 点登录按钮。后端 POST
//  /api/v1/auth/login 200 后 dialog 关闭、HttpOnly cookie（authorized-token
// + refresh-token）由浏览器自动管理。
//
// HttpOnly cookie 模型下 storageState 直接持久化两个 cookie。
// F5 / 进程退出再开仍持登录态，前端 bootstrapSession() 调 /auth/me 重建 Pinia。
//
// 当前用法：本文件已被 playwright.suspend.config.ts 改为复用
// tests/e2e/.auth/admin.json（由 global-setup.ts 生成），不再单独触发；
// 保留为参考实现，不再被任何 config 引用。
import { chromium, type FullConfig } from "@playwright/test"
import { writeFileSync, mkdirSync } from "node:fs"
import { dirname } from "node:path"

const E2E_BASE = "http://127.0.0.1:4174"
const STATE_PATH = "tests/e2e/.auth/suspend-admin.json"
const ADMIN_USER = "admin"
const ADMIN_PWD = "Admin1234"

mkdirSync(dirname(STATE_PATH), { recursive: true })

async function main() {
  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()

  await page.goto(E2E_BASE + "/")
  await page.locator(".user-avatar").click()
  const dialog = page.locator(".login-dialog")
  await dialog.waitFor({ state: "visible", timeout: 15_000 })
  await dialog.locator("input").nth(0).fill(ADMIN_USER)
  await dialog.locator("input").nth(1).fill(ADMIN_PWD)
  await dialog.locator(".login-btn").click()
  await dialog.waitFor({ state: "hidden", timeout: 15_000 })

  // storageState 含两个 HttpOnly cookie，由浏览器管理。
  await context.storageState({ path: STATE_PATH })
  await browser.close()
  console.log("wrote", STATE_PATH)
}

main().catch(e => {
  console.error(e)
  process.exit(1)
})