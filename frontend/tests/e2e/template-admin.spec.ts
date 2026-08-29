import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./fixtures/admin";

test.describe("template admin", () => {
  test.beforeEach(async ({ page }) => {
    // 锁 zh-CN：避免 macOS 系统 en-US 让 copy_suffix（走 t()）翻成 "Copy" 而断言「副本」失配；
    // json-errors 面板「第 X 行」也按 zh-CN 文案断言。
    await page.addInitScript(() => {
      localStorage.setItem("xz_locale", "zh-CN");
    });
    await loginAsAdmin(page);
  });

  test("config page shows template card with seeded PM template", async ({
    page
  }) => {
    await page.goto("/#/system/config");
    const card = page.locator('[data-group="templates"]');
    await expect(card).toBeVisible();
    await expect(
      card.locator('.template-row[data-id="pm-research"]')
    ).toBeVisible();
  });

  test("create template end-to-end via form mode", async ({ page }) => {
    await page.goto("/#/system/config");
    await page.locator('[data-group="templates"] [data-action="new"]').click();
    await expect(page.locator('[data-testid="tpl-editor"]')).toBeVisible();

    // 基本信息：限定到 BaseInfoSection 的 field-row（不含顶部 el-radio-button 的原生 input）
    const basicInputs = page.locator(
      '[data-testid="tpl-editor"] .field-row .el-input input'
    );
    await basicInputs.nth(0).fill("e2e-demo");
    await basicInputs.nth(1).fill("E2E 演示模板");

    // 保存 → 跳编辑形态 → 卡片可见
    await page.locator('[data-testid="tpl-save"]').click();
    await expect(page).toHaveURL(/\/system\/templates\/edit\/e2e-demo/);
    await page.goto("/#/system/config");
    await expect(
      page.locator('.template-row[data-id="e2e-demo"]')
    ).toBeVisible();
  });

  test("json mode reports syntax error and gates switching", async ({
    page
  }) => {
    await page.goto("/#/system/templates/new");
    await page.locator('[data-testid="mode-json"]').click();
    const editor = page.locator('[data-testid="json-editor"]');
    await expect(editor).toBeVisible();

    // 粘贴坏 JSON（少右括号）→ 错误面板出现行列信息
    await editor.click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.insertText('{"id": "x", "name": "y"');
    await expect(page.locator('[data-testid="json-errors"]')).toContainText(
      /第 \d+ 行/
    );

    // 切回表单被闸门拦下：仍停留在 JSON 模式
    await page.locator('[data-testid="mode-form"]').click();
    await expect(page.locator('[data-testid="json-editor"]')).toBeVisible();
  });

  test("copy seeds editor from source template", async ({ page }) => {
    await page.goto("/#/system/config");
    await page
      .locator('.template-row[data-id="pm-research"] [data-action="copy"]')
      .click();
    await expect(page).toHaveURL(
      /\/system\/templates\/new\?copyFrom=pm-research/
    );
    await expect(page.locator('[data-testid="tpl-editor"]')).toBeVisible();
    // 名称带「副本」、id 为空待填
    const name = await page
      .locator('[data-testid="tpl-editor"] .field-row .el-input input')
      .nth(1)
      .inputValue();
    await expect(name).toContain("副本");
  });
});
