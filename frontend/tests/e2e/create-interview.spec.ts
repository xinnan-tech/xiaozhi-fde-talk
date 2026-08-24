import { test, expect } from "@playwright/test"
import { loginAsAdmin } from "./fixtures/admin"

test.describe("create interview", () => {
  test("creates new interview from home page", async ({ page }) => {
    await loginAsAdmin(page)

    // 1. 点 .create-btn 触发 dialog（home 顶部的主按钮，文案「新建访谈」/「New interview」；
    //    sidebar 助理按钮也是 .create-btn，文案「创建访谈」/「Create」，
    //    用 getByRole 按 accessible name 区分，避免 strict mode violation）
    await page
      .getByRole("button", { name: /新建访谈|New interview/i })
      .first()
      .click()

    // 2. 等 CreateInterviewDialog 出现（class 在 CreateInterviewDialog.vue:238）
    const dialog = page.locator(".create-interview-dialog")
    await dialog.waitFor({ state: "visible", timeout: 10_000 })

    // 3. 等 el-form 内的字段可见。el-form-item 的 prop 绑定到 label，
    //    playwright 的 getByLabel 能匹配 .el-form-item__label 文本。
    //    表单打开时 createDefaultForm 已经填了 title/project/interviewee/duration/goal，
    //    但 template_id 默认就是后端返回的第一项（dialog 打开时 loadInterviewTemplates 自动选），
    //    所以这里只把 title 改成唯一值，避免与历史 run 的同名冲突。
    const titleField = page.getByLabel(/访谈名称|interview.*name/i).first()
    await titleField.waitFor({ state: "visible", timeout: 10_000 })

    const uniqueTitle = `e2e-test-${Date.now()}`
    await titleField.fill(uniqueTitle)

    await page
      .getByLabel(/访谈时间|Interview time/i)
      .first()
      .fill("2026-08-18 16:00:00")

    // 4. 点 submit：footer 按钮文案「创建访谈」/「Create interview」
    await page
      .getByRole("button", { name: /创建访谈|create.*interview/i })
      .last()
      .click()

    // 5. 等 dialog 关闭（dialog 消失 = 提交成功）
    await expect(dialog).not.toBeVisible({ timeout: 10_000 })

    // 6. success message 出现：App.vue:41 调用
    //    ElMessage.success(t("app.interview_create_success"))，
    //    zh-CN="访谈创建成功" / en-US="Interview created successfully"。
    //    注：登录时的 success toast 还没淡出完，会同时存在 2 个 .el-message--success，
    //    用 .last() 拿最新一条（先后顺序 = DOM 出现顺序）
    await expect(page.locator(".el-message--success").last()).toContainText(
      /创建成功|created.*successfully|created successfully|created/i,
      { timeout: 5_000 }
    )

    // 7. URL 仍在 /home（不会跳 /interview/:id）
    expect(page.url()).toMatch(/\/home/)

    // 8. 新访谈出现在 home 列表（home 视图 watch(interviewCreated) 触发 getInterviewList）
    await expect(page.locator("body")).toContainText(uniqueTitle, {
      timeout: 10_000
    })
  })
})
