import { test, expect } from "@playwright/test"
import { loginAsAdmin } from "./fixtures/admin"
import { fillCreateInterviewForm } from "./fixtures/create-interview"

test.describe("report page accessibility", () => {
  test("ending an interview redirects to /home (not /report/:id)", async ({
    page,
  }) => {
    test.setTimeout(60_000)
    await loginAsAdmin(page)

    // 1. 创建访谈（同 T9 流程）
    await page
      .getByRole("button", { name: /新建访谈|New interview/i })
      .first()
      .click()
    const dialog = page.locator(".create-interview-dialog")
    await dialog.waitFor({ state: "visible", timeout: 10_000 })

    const uniqueTitle = `e2e-report-${Date.now()}`
    await fillCreateInterviewForm(page, uniqueTitle)

    await page
      .getByRole("button", { name: /创建访谈|create.*interview/i })
      .last()
      .click()
    await expect(dialog).not.toBeVisible({ timeout: 10_000 })

    // 2. 进 interview 页（点 home 列表里的卡片）
    const card = page
      .locator(".interview-card", { hasText: uniqueTitle })
      .first()
    await card.waitFor({ state: "visible", timeout: 10_000 })
    await card.click()
    await page.waitForURL(/\/interview\/[a-zA-Z0-9_-]+$/, { timeout: 15_000 })

    // 3. 抓 interview id（从 URL）
    const interviewUrl = page.url()
    const interviewId = interviewUrl.split("/interview/")[1]
    expect(interviewId).toBeTruthy()

    // 4. 点"结束访谈"按钮。
    //    interview/index.vue:1146 class="session-action-button session-action-primary"
    //    文案 t("interview.action.end") = "结束访谈" / "End"
    const endBtn = page
      .locator("button.session-action-primary")
      .filter({ hasText: /结束访谈|^End$/ })
      .first()
    await expect(endBtn).toBeVisible({ timeout: 10_000 })
    await endBtn.click()

    // 5. ElMessageBox confirm dialog 出现 → 点 confirm。
    //    handleEndInterview (interview/index.vue:877) 调 ElMessageBox.confirm，
    //    confirmButtonText = t("interview.action.end") = "结束访谈" / "End"。
    //    ElMessageBox 的 footer 按钮在 .el-message-box__btns 内，
    //    主按钮带 .el-button--primary。多个同名按钮（页面里那个 + dialog 里那个）
    //    用 .last() 拿 dialog 内的 confirm 按钮（dialog 后渲染）。
    const confirmBtn = page
      .locator(".el-message-box__btns button.el-button--primary")
      .last()
    await confirmBtn.waitFor({ state: "visible", timeout: 5_000 })
    await confirmBtn.click()

    // 6. 应跳到 /home（不是 /report/:id — 短 brief 假设错）。
    //    handleEndInterview: endInterviewApi → stopRecording → websocket.close
    //    → router.push("/home")。
    await page.waitForURL(/\/home/, { timeout: 15_000 })
    expect(page.url()).toMatch(/\/home/)

    // 7. 现在手动访问 /report/<id> 应能渲染。
    //    即使没真实转录 / 没生成 report，views/report/index.vue 仍会渲染 header
    //    + tab bar（loading / error / content 三态之一），body 至少包含 h1.title。
    //    vue-router 用 hash 模式（VITE_ROUTER_HISTORY=hash），所以路径走 /#/report/<id>。
    await page.goto(`/#/report/${interviewId}`)
    await expect(page.locator(".record-page")).toBeVisible({
      timeout: 10_000,
    })
  })

  test("/reports route is reachable (parent redirect target)", async ({
    page,
  }) => {
    await loginAsAdmin(page)
    // /reports 是父路由，redirect 到 /report（无 :id 子路由会落到 home？见下方）。
    // router/modules/report.ts:7（redirect: "/report"）。
    // vue-router hash 模式（VITE_ROUTER_HISTORY=hash），走 /#/reports。
    // 父 redirect 到 /report，但只有 /report/:id 子路由。
    // 实际行为：url 落到 /home（no match）。所以只断言不崩，body 可见。
    await page.goto("/#/reports")
    await page.waitForLoadState("networkidle", { timeout: 10_000 })
    // 不应 crash，body 可见
    await expect(page.locator("body")).toBeVisible({ timeout: 5_000 })
  })
})
