import { test, expect, type Page } from "@playwright/test"
import { fillCreateInterviewForm } from "./fixtures/create-interview"

// 验证 PR #105（fix-web-status）对 issue 91 的修复：
// - 点暂停按钮：DB status=suspended 立即落盘，列表页不依赖 WS 异步更新
// - 进行中点返回：handleBack 也走 suspend 路径，避免遗漏暂停
// - 恢复：suspended 状态详情页显示「继续」，点恢复后回到 in_progress
//
// 前置：backend 8181 + frontend preview 4174 + admin storageState。系统配置
// idle_timeout_s=30s、idle_check_interval_s=5s（e2e 用，避免 idle watchdog 抢占
// 我们的暂停流程），ASR=funasr_mock、LLM=stub（无需真实密钥）。

const LOCALE_TEXT = {
  "zh-CN": { suspended: "已暂停", inProgress: "进行中", pause: "暂停访谈", resume: "继续访谈", start: "开始访谈", back: "返回" },
  "zh-TW": { suspended: "已暫停", inProgress: "進行中", pause: "暫停訪談", resume: "繼續訪談", start: "開始訪談", back: "返回" },
  "en-US": { suspended: "Paused", inProgress: "In progress", pause: "Pause", resume: "Resume", start: "Start", back: "Back" },
  "vi-VN": { suspended: "Đã tạm dừng", inProgress: "Đang diễn ra", pause: "Tạm dừng", resume: "Tiếp tục", start: "Bắt đầu", back: "Quay lại" }
} as const
type Locale = keyof typeof LOCALE_TEXT

async function detectLocale(page: Page): Promise<Locale> {
  const lang = await page.evaluate(() => document.documentElement.lang || "zh-CN")
  return (lang in LOCALE_TEXT ? lang : "zh-CN") as Locale
}

async function createInterviewAndStart(page: Page, locale: Locale, title: string) {
  // 不静默 MediaRecorder：必须让 fake audio 帧持续 _touch server 的
  // _last_activity_at，让 idle watchdog（30s）不会抢在我们的用户手动暂停
  // 之前触发 session.suspended；同时保证 openMicrophone() 成功返回 true，
  // 否则 onConnected → suspendLocalInterview() 会在没调 suspend API 的情况
  // 下把 status 翻 suspended，污染测试断言。
  // launchOptions 给的是 --use-fake-device-for-media-stream + --use-fake-ui-for-media-stream，
  // Chrome 会用 440Hz tone 喂 MediaRecorder，正常产出 dataavailable 事件。

  await page.goto("/")
  await page.locator(".user-avatar.online").waitFor({ state: "visible", timeout: 15_000 })

  // 创建访谈
  await page.getByRole("button", { name: /新建访谈|New interview/i }).first().click()
  const dialog = page.locator(".create-interview-dialog")
  await dialog.waitFor({ state: "visible", timeout: 10_000 })
  await page
    .locator(".create-interview-dialog .template-field")
    .waitFor({ state: "visible", timeout: 10_000 })
  await page.waitForFunction(
    () => {
      const ph = document.querySelector(
        ".create-interview-dialog .template-field .el-select__placeholder"
      )
      if (!ph) return false
      const text = ph.textContent?.trim() ?? ""
      return text && text !== "Select an interview template" && text !== "请选择访谈模板"
    },
    null,
    { timeout: 10_000 }
  )
  await fillCreateInterviewForm(page, title)
  await page
    .getByRole("button", { name: /创建访谈|create.*interview/i })
    .last()
    .click()
  await expect(dialog).not.toBeVisible({ timeout: 10_000 })

  // 进详情
  await page.locator(".interview-card", { hasText: title }).first().click()
  await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })

  // 点开始：handleStartInterview → resumeInterviewApi（如果 suspended 路径）
  // → WS listen:start → status 翻 in_progress → 控制按钮翻「暂停」
  const startBtn = page.locator(".session-control-button").first()
  await expect(startBtn).toBeVisible({ timeout: 15_000 })
  await startBtn.click()

  // 等控制按钮 .session-action-label 翻「暂停」= status==in_progress
  await page.waitForFunction(
    () => {
      const el = document.querySelector(
        ".session-control-button .session-action-label"
      )
      const text = el?.textContent?.trim() ?? ""
      return (
        text === "暂停访谈" ||
        text === "暫停訪談" ||
        text === "Pause" ||
        text === "Tạm dừng"
      )
    },
    null,
    { timeout: 20_000 }
  )
}

test.describe.serial("fix-web-status: pause/resume should reflect status immediately", () => {
  let title: string
  let locale: Locale

  test.beforeAll(async ({ browser }) => {
    // 单独起一个 page 仅用于探测 locale（避免在主 spec 里 init MediaRecorder）
    const ctx = await browser.newContext()
    const page = await ctx.newPage()
    await page.goto("/")
    await page.locator(".user-avatar").first().waitFor({ state: "visible", timeout: 15_000 })
    locale = await detectLocale(page)
    await ctx.close()
  })

  test.beforeEach(async ({ page }) => {
    title = `e2e-pause-${Date.now()}`
  })

  test("scenario A: clicking pause button → list shows suspended immediately", async ({
    page
  }: { page: Page }) => {
    test.setTimeout(60_000)

    await createInterviewAndStart(page, locale, title)

    const pauseBtn = page.locator(".session-control-button").first()

    // 点击暂停按钮；handlePauseInterview 是 async，先 await suspend API 落盘
    // 再 sendListenState("stop")、stopRecording、isInterviewStarted=false、
    // interviewDetail.value.status="suspended"。控制按钮随后翻「继续」。
    const clickAt = Date.now()
    await pauseBtn.click()

    // 等控制按钮 .session-action-label 翻「继续」= suspend API 已落盘成功
    await page.waitForFunction(
      () => {
        const el = document.querySelector(
          ".session-control-button .session-action-label"
        )
        const text = el?.textContent?.trim() ?? ""
        return (
          text === "继续访谈" ||
          text === "繼續訪談" ||
          text === "Resume" ||
          text === "Tiếp tục"
        )
      },
      null,
      { timeout: 10_000 }
    )
    const suspendConfirmedAt = Date.now()

    // 立即（不等待 backend 异步处理）导航回列表页
    const backBtn = page.locator(".back-button").first()
    await backBtn.click()

    // 列表页：等 interview-card 的 status 翻 suspended。等候超时 ≤3s，
    // 因为 DB 已落盘，列表 GET 应立即返回 suspended。
    const card = page.locator(".interview-card", { hasText: title }).first()
    await card.waitFor({ state: "visible", timeout: 10_000 })
    const cardShownSuspendedAt = await page.evaluate(() => Date.now())

    const elapsedFromSuspendToListShown = cardShownSuspendedAt - suspendConfirmedAt
    console.log(
      `[scenario A] elapsed from suspend API confirmed to list showing 'suspended': ${elapsedFromSuspendToListShown} ms`
    )

    // 卡片 DOM 上必须立刻是 suspended，不能等 1s 才看到
    await expect(card.locator(".status-suspended")).toBeVisible({ timeout: 3_000 })
    await expect(card.locator(".status-suspended .status-text")).toHaveText(
      new RegExp(
        `${LOCALE_TEXT["zh-CN"].suspended}|${LOCALE_TEXT["zh-TW"].suspended}|${LOCALE_TEXT["en-US"].suspended}|${LOCALE_TEXT["vi-VN"].suspended}`
      )
    )

    // 把 title 留给后续 scenario C 用（list 页读到的是 DB 真实状态，suspended）
  })

  test("scenario B: clicking back while in_progress → list shows suspended (race-tolerant)", async ({
    page
  }: { page: Page }) => {
    test.setTimeout(60_000)

    await createInterviewAndStart(page, locale, title)

    // 直接点返回：handleBack 是 async，但用 void fire-and-forget suspend API
    // 然后立即 router.back()。home remount → 列表 GET 与 suspend API 竞速。
    // 由于 DB 状态变化发生在 home fetch 完成前后都可能，wait 略放宽到 5s。
    const backBtn = page.locator(".back-button").first()
    const clickAt = Date.now()
    await backBtn.click()

    const card = page.locator(".interview-card", { hasText: title }).first()
    await card.waitFor({ state: "visible", timeout: 10_000 })

    // 必须最终翻 suspended；不像场景 A 那样要求「立刻」，因为存在竞速窗口
    await expect(card.locator(".status-suspended")).toBeVisible({ timeout: 5_000 })
    const cardShownSuspendedAt = await page.evaluate(() => Date.now())
    const elapsedFromBackToListShown = cardShownSuspendedAt - clickAt
    console.log(
      `[scenario B] elapsed from back click to list showing 'suspended': ${elapsedFromBackToListShown} ms (includes suspend API + list fetch race)`
    )
  })

  test("scenario C: resume from suspended → status flips back to in_progress", async ({
    page
  }: { page: Page }) => {
    test.setTimeout(60_000)

    // 自包含：自己创建并 suspend，留给 resume 用。
    // 不用 scenario A 的 title 是因为 beforeEach 会刷新 title，跨场景状态不可靠。
    await createInterviewAndStart(page, locale, title)

    // 暂停（直接走 pause 按钮，跳过 back 路径，确保 status 翻 suspended）
    const pauseBtn = page.locator(".session-control-button").first()
    await pauseBtn.click()
    await page.waitForFunction(
      () => {
        const el = document.querySelector(
          ".session-control-button .session-action-label"
        )
        const text = el?.textContent?.trim() ?? ""
        return (
          text === "继续访谈" ||
          text === "繼續訪談" ||
          text === "Resume" ||
          text === "Tiếp tục"
        )
      },
      null,
      { timeout: 10_000 }
    )

    // 回到列表
    const toListBackBtn = page.locator(".back-button").first()
    await toListBackBtn.click()

    // 列表确认 suspended
    const card = page.locator(".interview-card", { hasText: title }).first()
    await card.waitFor({ state: "visible", timeout: 10_000 })
    await expect(card.locator(".status-suspended")).toBeVisible({ timeout: 3_000 })

    // 点回详情
    await card.click()
    await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })

    // 详情页控制按钮显示「继续」（suspended 状态）
    await page.waitForFunction(
      () => {
        const el = document.querySelector(
          ".session-control-button .session-action-label"
        )
        const text = el?.textContent?.trim() ?? ""
        return (
          text === "继续访谈" ||
          text === "繼續訪談" ||
          text === "Resume" ||
          text === "Tiếp tục"
        )
      },
      null,
      { timeout: 10_000 }
    )
    const resumeBtn = page.locator(".session-control-button").first()

    // 点继续 → handleStartInterview 走 wasSuspended 分支 → resumeInterviewApi
    // → DB 转 in_progress → 控制按钮翻「暂停」
    const clickAt = Date.now()
    await resumeBtn.click()

    await page.waitForFunction(
      () => {
        const el = document.querySelector(
          ".session-control-button .session-action-label"
        )
        const text = el?.textContent?.trim() ?? ""
        return (
          text === "暂停访谈" ||
          text === "暫停訪談" ||
          text === "Pause" ||
          text === "Tạm dừng"
        )
      },
      null,
      { timeout: 10_000 }
    )
    const flippedAt = Date.now()
    console.log(
      `[scenario C] elapsed from resume click to button flipping to 'pause': ${flippedAt - clickAt} ms`
    )

    // 验证 resume 成功到此为止。理论上可以再点 back 验证列表翻 in_progress，
    // 但 PR #105 的 handleBack 设计是：只要 isInterviewStarted=true，点 back
    // 就会调 handlePauseInterview 再次 suspend——所以「resume 后立即 back」
    // 会让列表翻回 suspended，那是 fix 的预期行为，不是 bug。
    // 因此 resume 是否成功，看详情页控制按钮翻「暂停」就够：
    //   - DB status = in_progress（resume API 落盘）
    //   - interviewDetail.value.status = in_progress（getInterviewDetail 拉到）
    //   - 控制按钮 .session-action-label 显示「暂停」
  })
})
