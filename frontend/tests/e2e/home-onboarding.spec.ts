import { test, expect } from "@playwright/test"
import { fillCreateInterviewForm } from "./fixtures/create-interview"

// 首页引导面板（views/home/index.vue + components/home/HomeOnboarding.vue）：
// 显示条件 = !listLoading && interviewList 为空。未登录时列表恒为空 → 面板可见；
// 列表非空（无论过滤后是否为空）→ 面板隐藏；仅筛选无结果时显示 .filtered-empty。
// 同一轮 e2e 里其它 spec 可能已给 admin 造过访谈，因此已登录段用
// 「面板可见 ⟺ 无访谈卡片」的不变式断言，再自造一条访谈验证隐藏分支。
test.describe("home onboarding panel", () => {
  test("未登录显示引导面板；有访谈或仅筛选无结果时不显示", async ({
    page,
    browser
  }) => {
    test.setTimeout(90_000)

    // 1) 未登录（全新 storage context）：面板可见、四步齐全
    // fresh context 无 localStorage，getInitialLocale 走 detectBrowserLocale →
    // navigator.language；CI headless chromium 默认 en-US，会渲染英文态「Start
    // Your First Professional Interview」，断言 zh-CN 文案会失败。沿用
    // i18n.spec.ts:11-18 的模式：goto 后钉 xz_locale=zh-CN 再 reload。
    const fresh = await browser.newContext({
      storageState: { cookies: [], origins: [] }
    })
    try {
      const guest = await fresh.newPage()
      await guest.goto("/")
      await guest.evaluate(() => localStorage.setItem("xz_locale", "zh-CN"))
      await guest.reload()
      await guest.waitForLoadState("domcontentloaded")
      const guestPanel = guest.locator(".home-onboarding")
      await expect(guestPanel).toBeVisible({ timeout: 15_000 })
      await expect(guestPanel.locator(".step-card")).toHaveCount(4)
      await expect(guestPanel).toContainText("开始您的第一场专业访谈")
    } finally {
      await fresh.close()
    }

    // 2) 已登录（默认 storageState admin）：等列表加载完成，断言不变式
    await page.goto("/")
    const panel = page.locator(".home-onboarding")
    await expect(
      panel.or(page.locator(".interview-card").first())
    ).toBeVisible({ timeout: 15_000 })
    const hasInterview = (await page.locator(".interview-card").count()) > 0
    if (hasInterview) {
      await expect(panel).not.toBeVisible()
    } else {
      await expect(panel).toBeVisible()
    }

    // 3) 自造一条访谈 → 卡片出现、面板隐藏（流程与 create-interview.spec.ts 一致）
    await page
      .getByRole("button", { name: /新建访谈|New interview/i })
      .first()
      .click()
    const dialog = page.locator(".create-interview-dialog")
    await dialog.waitFor({ state: "visible", timeout: 10_000 })

    // fixture 首字段自带 waitFor visible（即对话框就绪信号）
    await fillCreateInterviewForm(page, `e2e-onboarding-${Date.now()}`, "2026-08-28 16:00:00")
    await page
      .getByRole("button", { name: /创建访谈|create.*interview/i })
      .last()
      .click()
    await expect(dialog).not.toBeVisible({ timeout: 10_000 })
    // PR #135：创建成功后跳 /interview/:id，.interview-card 是 Home 视图元素，
    // 必须先回 /home 再断言卡片 + 面板状态。.home-header 是 home 视图专属锚点
    // （sidebar / interview 视图都不渲染），避免误中。
    await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })
    await page.goto("/#/home")
    await page.locator(".home-header").waitFor({ state: "visible", timeout: 10_000 })
    await expect(page.locator(".interview-card").first()).toBeVisible({
      timeout: 10_000
    })
    await expect(panel).not.toBeVisible()

    // 4) 搜索无结果：显示 .filtered-empty 轻提示，不显示面板
    //    此时 page 已在 home 视图（.search-input / .filtered-empty 只在 home 渲染）。
    await page.locator(".search-input").fill("不存在的访谈关键字xyz")
    await expect(page.locator(".filtered-empty")).toBeVisible({
      timeout: 10_000
    })
    await expect(panel).not.toBeVisible()
  })
})
