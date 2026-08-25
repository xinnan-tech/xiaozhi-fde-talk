import { chromium, request as playwrightRequest, type FullConfig } from "@playwright/test"
import { ADMIN_USER, ADMIN_PWD } from "./fixtures/auth"

// 与 playwright.config.ts webServer[0].port=8001 对齐：frontend vite preview 把 /api 反代到 8001
const E2E_API = "http://127.0.0.1:8001"

export default async function globalSetup(config: FullConfig) {
  // 先在 fresh DB 上注册首用户（按 auth/register 契约：count==0 → role=admin）。
  // 不再走旧版 bootstrap 的 seed admin：d0084ff / 6c926b9 已删 seed + 简化 bootstrap，
  // 但 global-setup 没同步——这里补回。注册失败（如用户已存在）吞掉，让后续 UI 登录失败再报。
  const apiCtx = await playwrightRequest.newContext({ baseURL: E2E_API })
  let adminToken: string | undefined
  try {
    const regResp = await apiCtx.post("/api/v1/auth/register", {
      data: {
        username: ADMIN_USER,
        password: ADMIN_PWD,
        confirm_password: ADMIN_PWD,
      },
    })
    if (regResp.status() === 200) {
      const regData = (await regResp.json()) as { access_token?: string }
      adminToken = regData.access_token
    }
  } finally {
    await apiCtx.dispose()
  }

  // 首用户已注册后，config_store 默认 auth.allow_registration="false"。
  // registration 场景 A（zero-user 注册）/ 场景 D-1/D-2（注册 bob）依赖该开关为 true；
  // 场景 C 显式 PUT 关掉，不依赖初值，但初值 false 也无害。全局打开让后续 spec 顺序无关。
  if (adminToken) {
    const flagCtx = await playwrightRequest.newContext({ baseURL: E2E_API })
    try {
      await flagCtx.put("/api/v1/admin/config/auth", {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { allow_registration: "true" },
      })
    } finally {
      await flagCtx.dispose()
    }
  }

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