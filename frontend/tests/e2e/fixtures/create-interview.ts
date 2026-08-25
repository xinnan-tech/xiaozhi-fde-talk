import type { Page } from "@playwright/test"

// CreateInterviewDialog 表单必填项：title / project / interviewee / start_time /
// duration / template_id / goal。其中 title / project / interviewee / duration /
// goal 由 createDefaultForm（CreateInterviewDialog.vue:68）预填，template_id 由
// dialog 打开时 loadInterviewTemplates 自动选第一项；只有 start_time 默认是空串，
// 故调用方需显式填一个未来时刻，否则 el-form 校验卡住 dialog 不关。
// 2026-08-18 16:00:00 与 create-interview.spec.ts 历史值一致，便于回归对比。
export async function fillCreateInterviewForm(
  page: Page,
  title: string,
  startTime: string = "2026-08-18 16:00:00"
) {
  const titleField = page
    .getByLabel(/访谈名称|interview.*name/i)
    .first()
  await titleField.waitFor({ state: "visible", timeout: 10_000 })
  await titleField.fill(title)
  await page
    .getByLabel(/访谈时间|Interview time/i)
    .first()
    .fill(startTime)
}
