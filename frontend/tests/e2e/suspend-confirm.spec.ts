import { test, expect, type Page } from "@playwright/test"
import { fillCreateInterviewForm } from "./fixtures/create-interview"
import { loginAsAdmin } from "./fixtures/admin"

// 复现并验证 fix/issue-13-suspend-confirm-dialog 的核心契约：
// 1. 后端 watchdog 在 idle 超时后真的推 session.suspended 给前端 WS
// 2. 前端 handleSessionSuspended 真的弹 ElMessageBox.confirm，含「继续/暂不」按钮
// 3. 点「继续」能重连 WS 并把 status 翻回 in_progress
//
// 前置：backend 8181 + frontend 4174 + admin storageState。系统配置 idle_timeout_s=20s、
// idle_check_interval_s=5s，ASR=funasr_mock，LLM=stub（无需真实密钥）。
//
// HttpOnly cookie 由 storageState 直接持久 + 浏览器自动
// 带；F5 / 进程退出再开仍持登录态。loginAsAdmin() 兼容幂等（已登录态
// .online 直接 return）。下同（pause-status.spec.ts）。

test("suspend confirm dialog: idle → suspend → dialog → continue → in_progress", async ({
  page
}: { page: Page }) => {
  test.setTimeout(80_000)

  // 在 app 加载前注入 worklet stub：拦截 /pcm-processor.js fetch，返回一个空
  // processor（process() 不产出任何 Float32Array，不触发 port.postMessage）。
  // 链路：usePcmRecorder 加载 fake worklet 成功 → AudioWorkletNode 实例化 OK
  // → context.resume() OK → isRecording=true → 但 onAudioData 永远不被调，
  // server 不再收 PCM 帧、_last_activity_at 不再被 _touch。listen_start 仍能
  // 正常推进 session 到 IN_PROGRESS 并在那一瞬设 _touch；20s 后 watchdog 触发。
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = function (input, init) {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : (input as Request).url
      if (url.endsWith("/pcm-processor.js")) {
        const source = `
          class PCMCaptureProcessor extends AudioWorkletProcessor {
            process() {
              return true
            }
          }
          registerProcessor("pcm-capture-processor", PCMCaptureProcessor)
        `
        return Promise.resolve(
          new Response(source, {
            status: 200,
            headers: { "Content-Type": "application/javascript" }
          })
        )
      }
      return originalFetch(input, init)
    }
  })

  await page.goto("/")
  // HttpOnly cookie 由 storageState 持久 + 浏览器自动带。
  // loginAsAdmin() 兼容幂等（已登录态 .online 直接 return）。
  await loginAsAdmin(page)

  // 1. 创建访谈
  await page
    .getByRole("button", { name: /新建访谈|New interview/i })
    .first()
    .click()
  const dialog = page.locator(".create-interview-dialog")
  await dialog.waitFor({ state: "visible", timeout: 10_000 })
  // 等模板接口返回、第一项被 form.template_id 选中（resetForm line 211）。
  // 不等直接 submit 会被 el-form rule "template_required" 卡住、dialog 不关。
  // el-select 选中态：placeholder 元素 textContent 变为模板名（如「产品经理」）
  // 而非默认占位符。占位符判定按英文 / 中文两套，文案国际化切换时也认得。
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
  const title = `e2e-suspend-${Date.now()}`
  await fillCreateInterviewForm(page, title)
  await page
    .getByRole("button", { name: /创建访谈|create.*interview/i })
    .last()
    .click()
  await expect(dialog).not.toBeVisible({ timeout: 10_000 })

  // 2. 进访谈详情
  await page
    .locator(".interview-card", { hasText: title })
    .first()
    .click()
  await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })

  // 3. 点开始：handleStartInterview 走 acquireStream → openMicrophone → listen:start
  //    服务端 runtime.listen_start 触发 _touch 把 _last_activity_at 设到现在；之后
  //    PCM 帧被静默 worklet 截掉、再无 touch。20s idle 阈值后 watchdog 推 session.suspended。
  const startBtn = page
    .getByRole("button", { name: /开始访谈|^Start$|Start interview/i })
    .first()
  await expect(startBtn).toBeVisible({ timeout: 15_000 })
  await startBtn.click()

  // 4. 等控制按钮翻「暂停」= status==in_progress；说明 listen:start 已生效
  const controlBtn = page
    .getByRole("button", { name: /暂停访谈|Pause/i })
    .first()
  await expect(controlBtn).toBeVisible({ timeout: 20_000 })

  // 5. 等 watchdog 触发（idle 20s + check 间隔 5s 内必定有 loop 命中）。
  //    ElMessageBox.confirm 的标题是「访谈已暂停」/ "Interview paused"。
  const dialogTitle = page
    .locator(".el-message-box")
    .filter({ hasText: /访谈已暂停|Interview paused/i })
  await expect(dialogTitle).toBeVisible({ timeout: 40_000 })

  // 6. 弹框里应有「继续」/ "Continue" 按钮（i18n suspend_dialog.confirm）
  const continueBtn = dialogTitle
    .getByRole("button", { name: /^(继续|Continue)$/ })
    .first()
  await expect(continueBtn).toBeVisible({ timeout: 5_000 })
  await continueBtn.click()

  // 7. 弹框应被关闭，控制按钮重新显示「暂停」（status==in_progress）。
  //    handleStartInterview 在 allowReconnect → openWebSocket → 麦重开后把
  //    interviewDetail.status 写回 in_progress。
  await expect(dialogTitle).not.toBeVisible({ timeout: 20_000 })
  await expect(controlBtn).toBeVisible({ timeout: 20_000 })
})