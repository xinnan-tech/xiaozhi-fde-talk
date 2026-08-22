import { test, expect } from "@playwright/test"

// 切到 en-US：home 顶部 .locale-trigger（views/home/index.vue:338）hover 触发
// .locale-dropdown → .locale-menu 内 .el-dropdown-menu__item，label 取
// localeOptions（"简体中文"/"繁體中文"/"English"），点击后 setLocale("en-US")，
// 关键按钮文案 home.create_interview 由「新建访谈」变为「New interview」。
//
// 起始语种不可控：detectBrowserLocale 依赖 navigator.language，
// headless chromium 默认 en-US，会直接进入英文态；用 localStorage[xz_locale]
// 钉成 zh-CN 后 reload 才稳。
test("切换 i18n 到英文后 /home 关键文案翻成英文", async ({ page }) => {
  test.setTimeout(30_000)

  await page.goto("/")
  await page.evaluate(() => localStorage.setItem("xz_locale", "zh-CN"))
  await page.reload()
  await page.waitForLoadState("domcontentloaded")

  // 中文态：新建访谈按钮
  await expect(
    page.getByRole("button", { name: /新建访谈/i })
  ).toBeVisible({ timeout: 15_000 })

  // hover .locale-trigger（home/index.vue:332 trigger="hover"，click 不开 dropdown）
  await page.locator(".locale-trigger").hover()
  // 选 English；用 menuitem role 抓，按 label 正则匹配 English / en
  await page
    .getByRole("menuitem", { name: /english/i })
    .first()
    .click()

  // 中文文案消失、英文出现
  await expect(
    page.getByRole("button", { name: /New interview/i })
  ).toBeVisible({ timeout: 15_000 })
})
