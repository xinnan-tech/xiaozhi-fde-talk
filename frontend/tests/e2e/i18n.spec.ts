import { test, expect } from "@playwright/test"

// 切到 en-US：home 顶部 .locale-trigger（views/home/index.vue:354）外层 BaseSelect
// hover 触发 → BaseSelect 菜单 Teleport 到 body，role="listbox"，子项
// role="option"，label 取 localeOptions（"简体中文"/"繁體中文"/"English"/
// "Tiếng Việt"，home/index.vue:50），点击后 setLocale("en-US")，关键按钮文案
// home.create_interview 由「新建访谈」变为「New interview」。
//
// 起始语种不可控：detectBrowserLocale 依赖 navigator.language，headless chromium
// 默认 en-US，会直接进入英文态；用 localStorage[xz_locale] 钉成 zh-CN 后 reload
// 才稳。
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

  // hover .locale-trigger 父 BaseSelect 容器（mouseenter 才冒泡到外层监听器）；
  // base-select-menu Teleport 到 body，需要 :has 反向定位包含 locale-trigger 的
  // 那个 BaseSelect 实例。
  await page
    .locator(".base-select", { has: page.locator(".locale-trigger") })
    .hover()
  const menu = page.locator(".base-select-menu.is-open")
  await menu.waitFor({ state: "visible", timeout: 10_000 })

  // BaseSelect 菜单里 role="option"，按 label 正则匹配 English / en
  await menu.getByRole("option", { name: /english/i }).first().click()

  // 中文文案消失、英文出现
  await expect(
    page.getByRole("button", { name: /New interview/i })
  ).toBeVisible({ timeout: 15_000 })
})
