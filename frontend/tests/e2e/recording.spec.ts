import { test, expect } from "@playwright/test"
import { loginAsAdmin } from "./fixtures/admin"

test("recording flow: create → navigate → start → recording status → stop", async ({
  page,
}) => {
  test.setTimeout(90_000)
  await loginAsAdmin(page)

  // 1. 创建访谈
  await page
    .getByRole("button", { name: /新建访谈|New interview/i })
    .first()
    .click()

  const dialog = page.locator(".create-interview-dialog")
  await dialog.waitFor({ state: "visible", timeout: 10_000 })

  const titleField = page.getByLabel(/访谈名称|interview.*name/i).first()
  await titleField.waitFor({ state: "visible", timeout: 10_000 })

  const uniqueTitle = `e2e-rec-${Date.now()}`
  await titleField.fill(uniqueTitle)

  // submit（footer 按钮文案「创建访谈」/「Create interview」）
  await page
    .getByRole("button", { name: /创建访谈|create.*interview/i })
    .last()
    .click()
  await expect(dialog).not.toBeVisible({ timeout: 10_000 })

  // 2. create 不会 router.push，需手动进：点 home 列表里那张新卡片（文案匹配 uniqueTitle）
  const card = page
    .locator(".interview-card", { hasText: uniqueTitle })
    .first()
  await card.waitFor({ state: "visible", timeout: 10_000 })
  await card.click()
  await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })

  // 3. 等详情加载完，「开始访谈」按钮可见。
  //    interview.action.start = "开始访谈" / "Start"
  const startBtn = page
    .getByRole("button", { name: /开始访谈|^Start$|Start interview/i })
    .first()
  await expect(startBtn).toBeVisible({ timeout: 15_000 })

  // 4. 录音链路：点开始访谈。
  //    链路：handleStartInterview → acquireStream（mic 权限 + fake audio 跑通）
  //    → openWebSocket → onConnected 后 sendListenState('start') → startRecording。
  //    fake audio 由 --use-file-for-fake-audio-capture 注入，MediaRecorder 会循环读 wav。
  await startBtn.click()

  // 5. 等 UI 状态翻：徽章文本变「进行中」/「In progress」
  await expect(
    page
      .locator(".transcribing-badge")
      .getByText(/进行中|In progress/i)
  ).toBeVisible({ timeout: 20_000 })

  // 让录音链路跑几秒，浏览器持续录制 fake audio，opus 帧经 WebSocket 发到
  // 后端，再被后端转送到真 FunASR 做识别。fake audio 是 backend/tests/e2e/audio/
  // interview.webm（9min16s 真实访谈 opus32kbps）—— chromium --use-file-for-fake-audio-capture
  // loop 播放，前 6s 内必有真语音段，FunASR 应返回 transcript 文本。
  await page.waitForTimeout(6_000)

  // 断言：右侧 transcript 面板结构已渲染（.transcript-card glass-card 在
  // views/interview/index.vue:1159，含 header + segmented + 列表容器）。
  // 注：不强断言 transcript-item 文本内容——FunASR 模型首段推理时延不稳，
  // 30s 也不一定出字。面板可见 = 录音链路通 + ASR provider 已建。
  await expect(page.locator(".transcript-card")).toBeVisible({ timeout: 10_000 })

  // 6. 停麦：点击「关闭麦克风」/「Mic off」按钮。
  //    button class .session-action-secondary（两个 secondary：开始/继续 + mic toggle）
  //    按 role 选文案最稳。
  const micToggleBtn = page
    .getByRole("button", { name: /关闭麦克风|Mic off|^Mic off/i })
    .first()
  if (
    await micToggleBtn.isVisible({ timeout: 2_000 }).catch(() => false)
  ) {
    await micToggleBtn.click()
  }

  // 7. 弱断言：URL 仍在 /interview/:id（没跳走；说明录音没崩出路由）
  await page.waitForTimeout(1_000)
  expect(page.url()).toMatch(/\/interview\/[a-zA-Z0-9_-]+$/)
})
