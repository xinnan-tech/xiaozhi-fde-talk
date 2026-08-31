import { test, expect } from "@playwright/test"
import { loginAsAdmin } from "./fixtures/admin"
import { fillCreateInterviewForm } from "./fixtures/create-interview"

// 连续创建 2 个不同标题的访谈 → home 列表都显示 → 点各自进对应详情
test("创建 2 个访谈、home 列表都显示、点击各自进对应详情", async ({ page }) => {
  test.setTimeout(60_000)

  await loginAsAdmin(page)

  const createBtn = page
    .getByRole("button", { name: /新建访谈|New interview/i })
    .first()
  const dialog = page.locator(".create-interview-dialog")
  const submitBtn = page
    .getByRole("button", { name: /创建访谈|create.*interview/i })
    .last()

  // 第一个访谈
  await createBtn.click()
  await dialog.waitFor({ state: "visible", timeout: 10_000 })
  const title1 = `e2e-multi-a-${Date.now()}`
  await fillCreateInterviewForm(page, title1)
  await submitBtn.click()
  await expect(dialog).not.toBeVisible({ timeout: 10_000 })
  // PR #135：创建成功后跳 /interview/:id，再点 home 顶部 .create-btn 必须先回 /home。
  // 用 .home-header 作锚点（仅 home 视图有，sidebar / interview 视图都不渲染），
  // 避免误中 sidebar 的 .create-btn（侧栏与 home 都有 .create-btn class）。
  await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })
  await page.goto("/#/home")
  await page.locator(".home-header").waitFor({ state: "visible", timeout: 10_000 })

  // 第二个访谈
  await createBtn.click()
  await dialog.waitFor({ state: "visible", timeout: 10_000 })
  const title2 = `e2e-multi-b-${Date.now()}`
  await fillCreateInterviewForm(page, title2)
  await submitBtn.click()
  await expect(dialog).not.toBeVisible({ timeout: 10_000 })
  await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })
  // 回 /home 检查 2 条访谈都在列表里（这是本测试的核心断言：home 列表显示 2 个）。
  await page.goto("/#/home")
  await page.locator(".home-header").waitFor({ state: "visible", timeout: 10_000 })
  await page.waitForLoadState("networkidle", { timeout: 10_000 })

  // 列表显示 2 个
  await expect(
    page.locator(".interview-card", { hasText: title1 })
  ).toBeVisible({ timeout: 10_000 })
  await expect(
    page.locator(".interview-card", { hasText: title2 })
  ).toBeVisible({ timeout: 10_000 })

  // 点 title1 进对应详情
  await page.locator(".interview-card", { hasText: title1 }).first().click()
  await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })
  await expect(page.locator("body")).toContainText(title1)
})
