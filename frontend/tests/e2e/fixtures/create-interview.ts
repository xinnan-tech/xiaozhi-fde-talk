import type { Page } from "@playwright/test"

// CreateInterviewDialog 表单必填项：title / project / interviewee / start_time /
// duration / template_id / goal。2026-08-29 起表单不再预填演示值（旧版预填
// 「欣南科技/彭经理」假数据，用户不删就会带假数据建访谈），start_time 默认
// 「此刻」。这里显式填全部文本必填项保证断言值确定；duration 默认 "45"、
// template_id 由 dialog 打开时 loadInterviewTemplates 自动选第一项，无需覆盖。
// label 匹配兼容 zh-CN / en-US 两套文案（e2e 锁 zh-CN，但保持与旧正则同宽）。
const FIELDS: Array<[RegExp, (title: string, startTime: string) => string]> = [
  [/访谈名称|interview.*name/i, title => title],
  [/项目\/对象|project/i, title => `e2e-${title}`],
  [/访谈人|interviewee/i, () => "测试对象"],
  [/访谈时间|interview.*time/i, (_t, startTime) => startTime],
  [/访谈目标|interview.*goal/i, () => "e2e 测试访谈目标"]
]

export async function fillCreateInterviewForm(
  page: Page,
  title: string,
  startTime: string = "2026-08-18 16:00:00"
) {
  for (const [label, value] of FIELDS) {
    const field = page.getByLabel(label).first()
    await field.waitFor({ state: "visible", timeout: 10_000 })
    await field.fill(value(title, startTime))
  }
}
