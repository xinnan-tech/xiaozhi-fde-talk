import { chromium, type FullConfig } from "@playwright/test"
import { ADMIN_USER, ADMIN_PWD } from "./fixtures/auth"

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL as string
  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(baseURL + "/")
  await page.locator(".user-avatar").click()
  const dialog = page.locator(".login-dialog")
  await dialog.waitFor({ state: "visible", timeout: 15_000 })
  await dialog.locator("input").nth(0).fill(ADMIN_USER)
  await dialog.locator("input").nth(1).fill(ADMIN_PWD)
  await dialog.locator(".login-btn").click()
  await dialog.waitFor({ state: "hidden", timeout: 15_000 })
  await context.storageState({ path: "tests/e2e/.auth/admin.json" })
  await browser.close()
}