import type { Page } from "@playwright/test"

// CreateInterviewDialog 表单：title / goal 是固定伪字段，业务字段按所选模板
// 的 base_fields 动态渲染，label 取模板「显示名」（种子模板：项目/对象、
// 受访者、开始时间、访谈时长）。这里显式填文本必填项保证断言值确定；
// duration 默认 "45"、template_id 由 dialog 打开时自动选第一项，无需覆盖。
// label 匹配兼容 zh-CN / en-US 与旧版固定文案（e2e 锁 zh-CN，保持同宽）。
const FIELDS: Array<[RegExp, (title: string, startTime: string) => string]> = [
  [/访谈名称|interview.*name/i, title => title],
  [/项目\/对象|project/i, title => `e2e-${title}`],
  [/受访者|访谈人|interviewee/i, () => "测试对象"],
  [/开始时间|访谈时间|interview.*time/i, (_t, startTime) => startTime],
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
