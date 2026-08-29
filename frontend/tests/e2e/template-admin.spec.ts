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
    // 空白新建默认落在 AI 生成 tab，手工建表单先切表单模式
    await page.locator('[data-testid="mode-form"]').click();

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

  test("AI generate mode: brief → form auto-filled → save", async ({
    page
  }) => {
    // mock 生成端点：验证请求 brief 后返回一份完整模板（id 留空由用户定）
    const canned = {
      id: "",
      version: "1",
      icon_url: "",
      icon_alt: "📋",
      name: "售后回访",
      session: {
        name: "客户回访",
        goal: "说明本次回访目的",
        base_fields: [
          { key: "customer", label: "客户", type: "text", required: true },
          { key: "visit_time", label: "回访时间", type: "datetime", required: false }
        ],
        setup: {
          intro: "一句话说清回访对象与目的",
          extract_to: ["customer"],
          required: ["customer"]
        }
      },
      coaching: {
        playbook: "你是客服回访教练",
        must_ask: [
          { id: "q1", text: "满意度打几分", priority: 1, desc: "" },
          { id: "q2", text: "续约意向如何", priority: 2, desc: "" }
        ]
      },
      report: { doc: "# {{session.customer}} 回访报告\n\n## 小结" },
      safety: []
    };
    await page.route("**/api/v1/admin/templates/generate", async route => {
      const brief = (route.request().postDataJSON() as { brief: string }).brief;
      expect(brief).toContain("售后回访");
      await route.fulfill({ json: canned });
    });

    await page.goto("/#/system/templates/new");
    // 空白新建默认 AI 生成 tab：面板可见、保存禁用（还没东西可保存）
    await expect(page.locator('[data-testid="ai-section"]')).toBeVisible();
    await expect(page.locator('[data-testid="tpl-save"]')).toBeDisabled();

    // 示例 chip 一键填入 → 生成（el-input 的透传 attr 落在原生 textarea 上）
    await page.locator(".ai-example-chip").first().click();
    await expect(page.locator('[data-testid="ai-brief"]')).not.toBeEmpty();
    await page.locator('[data-testid="ai-generate"]').click();

    // 成功 → 自动切表单模式，名称已带出，保存恢复可用
    const basicInputs = page.locator(
      '[data-testid="tpl-editor"] .field-row .el-input input'
    );
    await expect(basicInputs.nth(1)).toHaveValue("售后回访");
    await expect(page.locator('[data-testid="tpl-save"]')).toBeEnabled();

    // id 留空由用户定 → 填 id 保存走真实落库
    await basicInputs.nth(0).fill("ai-demo");
    await page.locator('[data-testid="tpl-save"]').click();
    await expect(page).toHaveURL(/\/system\/templates\/edit\/ai-demo/);
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
    // 已有内容可调：复制入口不提供 AI 生成 tab（只有表单 / JSON 两模式）
    await expect(page.locator('[data-testid="mode-ai"]')).toHaveCount(0);
    // 名称带「副本」、id 为空待填
    const name = await page
      .locator('[data-testid="tpl-editor"] .field-row .el-input input')
      .nth(1)
      .inputValue();
    await expect(name).toContain("副本");
  });
});
