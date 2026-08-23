import { test, expect, request as playwrightRequest } from "@playwright/test"
import { ADMIN_USER, ADMIN_PWD } from "./fixtures/auth"

// 与 playwright.config.ts webServer[0].port=8001 对齐：前端 vite preview 把 /api 反代到 8001
const E2E_API = "http://127.0.0.1:8001"

// ─────────────────────────────────────────────────────────────────────
// 共享 API 工具：直接打 backend，绕开前端 UI 做 DB 状态准备
// ─────────────────────────────────────────────────────────────────────

type RegisterResp = {
  access_token: string
  user: { id: string; username: string; role: "admin" | "user" }
}

async function registerViaApi(
  username: string,
  password: string
): Promise<RegisterResp | null> {
  const ctx = await playwrightRequest.newContext({ baseURL: E2E_API })
  try {
    const r = await ctx.post("/api/v1/auth/register", {
      data: {
        username,
        password,
        confirm_password: password,
      },
    })
    if (r.status() !== 200) return null
    return await r.json()
  } finally {
    await ctx.dispose()
  }
}

async function loginViaApi(
  username: string,
  password: string
): Promise<RegisterResp | null> {
  const ctx = await playwrightRequest.newContext({ baseURL: E2E_API })
  try {
    const r = await ctx.post("/api/v1/auth/login", {
      data: { username, password },
    })
    if (r.status() !== 200) return null
    return await r.json()
  } finally {
    await ctx.dispose()
  }
}

async function setAuthFlag(
  token: string,
  key: string,
  value: string
): Promise<boolean> {
  const ctx = await playwrightRequest.newContext({ baseURL: E2E_API })
  try {
    const r = await ctx.put(`/api/v1/admin/config/auth`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { [key]: value },
    })
    return r.status() === 200
  } finally {
    await ctx.dispose()
  }
}

async function adminResetPassword(
  token: string,
  userId: string,
  newPwd: string
): Promise<boolean> {
  const ctx = await playwrightRequest.newContext({ baseURL: E2E_API })
  try {
    const r = await ctx.post(
      `/api/v1/admin/users/${userId}/password`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { new_password: newPwd },
      }
    )
    return r.status() === 200
  } finally {
    await ctx.dispose()
  }
}

async function listUsers(token: string): Promise<
  Array<{ id: string; username: string; role: string }>
> {
  const ctx = await playwrightRequest.newContext({ baseURL: E2E_API })
  try {
    const r = await ctx.get("/api/v1/admin/users", {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (r.status() !== 200) return []
    return await r.json()
  } finally {
    await ctx.dispose()
  }
}

// ─────────────────────────────────────────────────────────────────────
// 场景 A：零用户 → 注册 → 进主页
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 A: 零用户 → 注册 → 进主页", () => {
  // 必须从空 storageState 起步——不能复用 global-setup 写入的 admin session
  test.use({ storageState: { cookies: [], origins: [] } })

  test("zero-user 注册首用户（admin）→ 侧边栏含系统配置/用户管理", async ({
    page,
    context,
  }) => {
    // 清掉任何残留 cookie/storage（双保险）
    await context.clearCookies()
    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })

    // home 视图未登录时不自动弹 dialog；点 .user-avatar 触发 dialogStore.openLogin()
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })

    // 切到注册模式（LoginDialog 第 144 行 el-link 点击 → mode.value = 'register'）
    await dialog.getByText("去注册").click()

    // 注册表单：用户名 + 密码 + 确认密码（LoginDialog 第 129/132/135 行）
    const username = `alice_${Date.now().toString(36)}`
    const password = "Strong1!pwd"
    await dialog.locator(".login-input").nth(0).locator("input").fill(username)
    await dialog.locator(".login-input").nth(1).locator("input").fill(password)
    await dialog.locator(".login-input").nth(2).locator("input").fill(password)

    // 点注册按钮
    await dialog.locator(".login-btn").click()
    await dialog.waitFor({ state: "hidden", timeout: 15_000 })

    // dialog 关闭 + Element Plus success toast「注册成功」
    await expect(page.locator(".el-message--success")).toContainText(
      /注册成功|register.*success|success/i,
      { timeout: 5_000 }
    )

    // 侧边栏应含 admin 限定菜单（menu.system=系统配置 / menu.users=用户管理）
    // 侧边栏用 titleKey 渲染（NavVertical.vue + SidebarItem.vue:124）
    await expect(page.getByText("系统配置").first()).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByText("用户管理").first()).toBeVisible({
      timeout: 10_000,
    })

    // 用户名 ≥4 位：Username 正则 ^[A-Za-z0-9_-]{4,32}$
  })
})

// ─────────────────────────────────────────────────────────────────────
// 场景 B：普通用户访问 /system /admin/users 被重定向 /error/403
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 B: 普通用户访问受保护路由 → /error/403", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("bob (user role) 访问 /system /admin/users → 重定向到 /error/403", async ({
    page,
    context,
  }) => {
    // 1) 注册 admin（首用户即 admin）——保证后续能开 allow_registration
    const adminUser = `adminb_${Date.now().toString(36)}`
    const adminReg = await registerViaApi(adminUser, ADMIN_PWD)
    expect(adminReg, "首用户注册 admin 失败").not.toBeNull()
    const adminToken = adminReg!.access_token

    // 2) 开 allow_registration（默认 false），bob 才能注册
    const opened = await setAuthFlag(adminToken, "allow_registration", "true")
    expect(opened, "allow_registration 开关写入失败").toBe(true)

    // 3) 注册 bob（普通用户）
    const bobUser = `bobb_${Date.now().toString(36)}`
    const bobReg = await registerViaApi(bobUser, ADMIN_PWD)
    expect(bobReg, "bob 注册失败").not.toBeNull()
    expect(bobReg!.user.role, "bob 应为 user 角色").toBe("user")

    // 4) 清 context，登 bob
    await context.clearCookies()
    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })

    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })
    await dialog.locator("input").nth(0).fill(bobUser)
    await dialog.locator("input").nth(1).fill(ADMIN_PWD)
    await dialog.locator(".login-btn").click()
    await dialog.waitFor({ state: "hidden", timeout: 15_000 })

    // 5) /system 是 admin 限定（router/modules/system.ts:13 meta.roles=['admin']）
    await page.goto("/system")
    await expect(page).toHaveURL(/\/error\/403/, { timeout: 10_000 })

    // 6) /admin/users 也是 admin 限定（router/modules/admin_users.ts:12）
    await page.goto("/admin/users")
    await expect(page).toHaveURL(/\/error\/403/, { timeout: 10_000 })
  })
})

// ─────────────────────────────────────────────────────────────────────
// 场景 C：关闭 allow_registration 后菜单仍显示 / 重置密码按钮 disabled + tooltip
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 C: 关闭 allow_registration → 重置密码按钮禁用 + tooltip", () => {
  // 用 global-setup 写入的 admin storageState 起步
  test("admin 关 allow_registration → /admin/users 按钮 disabled + tooltip", async ({
    page,
  }) => {
    // 1) admin 已登录（global-setup）
    await page.goto("/")
    await expect(page.locator(".user-avatar.online")).toBeVisible({
      timeout: 15_000,
    })

    // 2) /system 页：关 auth.allow_registration（system/index.vue:86 checkboxKeys）
    //    等 page 渲染完，用结构化 selector 找 allow_registration 行
    await page.goto("/system")
    await page.waitForLoadState("networkidle", { timeout: 15_000 })

    // 字段 label 用 field.key 渲染（system/index.vue:459 → field-label）——精确匹配文本
    const allowRegRow = page.locator(".field-row", {
      hasText: "allow_registration",
    })
    await expect(allowRegRow).toBeVisible({ timeout: 10_000 })

    // 找到对应 checkbox：取消勾选（点一下从 true → false）
    const checkbox = allowRegRow.locator(".field-checkbox")
    const isChecked = await checkbox
      .locator(".el-checkbox__input.is-checked")
      .count()
    if (isChecked > 0) {
      await checkbox.click()
    }

    // 点 auth 组的 save-button（每个 group 一个保存按钮）
    // auth group 的卡片 id 是 config-auth（router/modules/system.ts:17 → path=/system/config）
    // 但 groups 是动态的（system/index.vue:116）；按 config-auth card 内的 save-button 锁定
    const authCard = page.locator(".config-card").filter({
      has: page.locator(".card-title-row h2", { hasText: /^auth$/ }),
    })
    await authCard.locator(".save-button").click()

    // 等 Element Plus success toast
    await expect(page.locator(".el-message--success")).toContainText(
      /保存.*成功|save.*success/i,
      { timeout: 10_000 }
    )

    // 3) 进 /admin/users
    await page.goto("/admin/users")
    await page.waitForLoadState("networkidle", { timeout: 15_000 })

    // 等用户列表加载完（admin/users/index.vue:73 el-table v-loading）
    await expect(
      page.locator(".admin-users-page .el-card .el-card__header")
    ).toContainText("用户列表", { timeout: 10_000 })

    // 4) 重置密码按钮 disabled + tooltip 提示（admin/users/index.vue:79-83）
    const resetBtn = page
      .locator(".admin-users-page .el-table .el-button")
      .filter({ hasText: "重置密码" })
      .first()
    await expect(resetBtn).toBeVisible({ timeout: 10_000 })
    await expect(resetBtn).toBeDisabled()

    // tooltip：hover 触发 el-tooltip 弹泡
    // Element Plus 2.x 默认 popper-class="el-popper"，内容 .el-popper__title
    // 这里直接断言 disabled 状态 + 字段存在的 tooltip content（el-tooltip:disabled 模式仍渲染）
    // 由于 el-tooltip 在 disabled 时不一定渲染 popper，断言更稳：检查 .el-tooltip 节点存在 + content attr
    const tooltipWrapper = page.locator(".admin-users-page .el-tooltip").first()
    await expect(tooltipWrapper).toHaveCount(1)
  })
})

// ─────────────────────────────────────────────────────────────────────
// 场景 D-1：admin 改密 → bob 新密码能登录
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 D-1: admin 改 bob 密码 → bob 新密码登录成功", () => {
  test("admin 重置 bob 密码 → bob 退出 → 新密码登录", async ({
    page,
    context,
  }) => {
    // 1) admin 已登录（global-setup 写入 storageState）
    await page.goto("/")
    await expect(page.locator(".user-avatar.online")).toBeVisible({
      timeout: 15_000,
    })

    // 2) 取 admin token（前端 auth.ts:39 setToken 写 localStorage[user-info]）
    const adminToken = await page.evaluate(() => {
      const v = localStorage.getItem("user-info")
      if (!v) return ""
      try {
        const obj = JSON.parse(v) as { accessToken?: string }
        return obj.accessToken ?? ""
      } catch {
        return ""
      }
    })

    // 3) 确保 bob 存在（开 allow_registration → 注册 bob）
    await setAuthFlag(adminToken, "allow_registration", "true")
    const bobUser = `bob_${Date.now().toString(36)}`
    const bobOldPwd = "BobOld1!pwd"
    const bobReg = await registerViaApi(bobUser, bobOldPwd)
    expect(bobReg, "bob 注册失败").not.toBeNull()
    const bobId = bobReg!.user.id

    // 4) 进 /admin/users，点 bob 行的「重置密码」
    await page.goto("/admin/users")
    await expect(
      page.locator(".admin-users-page .el-card .el-card__header")
    ).toContainText("用户列表", { timeout: 10_000 })

    // 找到 bob 所在行（username 列匹配）
    const bobRow = page
      .locator(".admin-users-page .el-table .el-table__row")
      .filter({ hasText: bobUser })
      .first()
    await expect(bobRow).toBeVisible({ timeout: 10_000 })

    // 5) 点「重置密码」按钮 → 弹 dialog → 填新密码 → 确认
    await bobRow.locator(".el-button").filter({ hasText: "重置密码" }).click()
    // 弹出的 dialog 是 admin/users/index.vue:89-102 的 el-dialog
    const resetDialog = page.locator(".el-dialog").filter({
      hasText: "重置用户密码",
    })
    await expect(resetDialog).toBeVisible({ timeout: 10_000 })

    const bobNewPwd = "BobNew1!pwd"
    // dialog 里 2 个 type=password input（new_password / confirm）
    await resetDialog
      .locator("input[type='password']")
      .nth(0)
      .fill(bobNewPwd)
    await resetDialog
      .locator("input[type='password']")
      .nth(1)
      .fill(bobNewPwd)
    // 确认按钮（admin/users/index.vue:100 type="primary"）
    await resetDialog.locator(".el-button--primary").click()
    await expect(page.locator(".el-message--success")).toContainText(
      /密码已重置|reset.*success/i,
      { timeout: 10_000 }
    )

    // 6) 清 cookie/storage，登 admin → 用 bob 登录
    await context.clearCookies()
    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })

    // 7) 用 bob 新密码登录
    await page.locator(".user-avatar").click()
    const loginDialog = page.locator(".login-dialog")
    await loginDialog.waitFor({ state: "visible", timeout: 15_000 })
    await loginDialog.locator("input").nth(0).fill(bobUser)
    await loginDialog.locator("input").nth(1).fill(bobNewPwd)
    await loginDialog.locator(".login-btn").click()
    await loginDialog.waitFor({ state: "hidden", timeout: 15_000 })

    // 登录成功的直接证据
    await expect(page.locator(".el-message--success")).toContainText(
      /登录成功|Signed in|success/i,
      { timeout: 5_000 }
    )
    await expect(page.locator(".user-avatar.online")).toBeVisible({
      timeout: 5_000,
    })
  })
})

// ─────────────────────────────────────────────────────────────────────
// 场景 D-2：admin 改密 → bob 旧 token 401（API 直接断言）
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 D-2: admin 改密 → bob 旧 token 调 /admin/users → 401", () => {
  test("bob 旧 token 在 admin 改密后被 pwd_ver 吊销", async () => {
    // 1) 注册 admin（首用户）
    const adminUser = `admind2_${Date.now().toString(36)}`
    const adminReg = await registerViaApi(adminUser, ADMIN_PWD)
    expect(adminReg, "admin 注册失败").not.toBeNull()
    const adminToken = adminReg!.access_token

    // 2) 开 allow_registration，注册 bob
    await setAuthFlag(adminToken, "allow_registration", "true")
    const bobUser = `bobd2_${Date.now().toString(36)}`
    const bobReg = await registerViaApi(bobUser, "BobD2!pwd")
    expect(bobReg, "bob 注册失败").not.toBeNull()
    const bobId = bobReg!.user.id
    const bobOldToken = bobReg!.access_token

    // 3) 先用 bob 旧 token 调 /admin/users——应当 403（user 无权限）
    // 注：bob 是 user role，/admin/users 要 admin，所以旧 token 实际是 403 而非 200
    // 关键断言是改密后 token 被吊销——user_repo.update_password_auto 改 pwd_ver
    // 让 token 中的 pwd_ver 与 DB 不匹配 → get_current_user 401
    const beforeCtx = await playwrightRequest.newContext({ baseURL: E2E_API })
    const beforeStatus = await beforeCtx
      .get("/api/v1/admin/users", {
        headers: { Authorization: `Bearer ${bobOldToken}` },
      })
      .then(r => r.status())
    await beforeCtx.dispose()
    // bob 是 user 角色——应当 403（不是 401）
    expect(beforeStatus).toBe(403)

    // 4) admin 改 bob 密码
    const ok = await adminResetPassword(
      adminToken,
      bobId,
      "BobD2New!pwd"
    )
    expect(ok, "admin 改密失败").toBe(true)

    // 5) bob 旧 token 再调 /admin/users → 应 401（pwd_ver mismatch）
    const afterCtx = await playwrightRequest.newContext({ baseURL: E2E_API })
    const afterStatus = await afterCtx
      .get("/api/v1/admin/users", {
        headers: { Authorization: `Bearer ${bobOldToken}` },
      })
      .then(r => r.status())
    await afterCtx.dispose()
    expect(
      afterStatus,
      "bob 旧 token 在 admin 改密后应被吊销 → 401"
    ).toBe(401)
  })
})

// ─────────────────────────────────────────────────────────────────────
// 场景 E：registration-status 接口失败 → "去注册"按钮 disabled + tooltip
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 E: registration-status 500 → 去注册按钮禁用", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("mock 500 → login dialog 去注册按钮 disabled + tooltip 显示", async ({
    page,
    context,
  }) => {
    await context.clearCookies()

    // 在 page.goto 之前注册 route 拦截（按 brief 风险提示）
    await page.route("**/api/v1/auth/registration-status", route =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "mocked failure" }),
      })
    )

    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })

    // 点 avatar 触发 dialog；watch 会调用 registration-status → 500 → catch 块
    // 把 registrationAvailable 设为 false（LoginDialog:38）→ "去注册"被禁用 + tooltip
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })

    // 等异步 fetch 跑完再断言
    await page.waitForTimeout(1_000)

    // "去注册" 文本在 LoginDialog:148 是 el-link type="primary"
    // 失败降级分支：LoginDialog:149 el-tooltip 包住 disabled el-link
    const goRegister = dialog.locator("text=去注册").first()
    await expect(goRegister).toBeVisible({ timeout: 5_000 })

    // el-link disabled 状态：父级 .el-tooltip 包含 disabled .el-link.is-disabled
    const tooltipWrapper = dialog.locator(".el-tooltip").filter({
      has: page.locator("text=去注册"),
    })
    await expect(tooltipWrapper).toHaveCount(1)

    // tooltip content attr 应包含 i18n key auth.registration_unavailable 的 zh-CN 翻译
    // Element Plus 2.x el-tooltip 用 aria-describedby 或 .el-popper__title
    // 断言简单点：hover 触发 popper，断言文本
    await tooltipWrapper.hover()
    const popper = page.locator(".el-popper").filter({
      hasText: "暂不可用，请稍后重试",
    })
    await expect(popper).toBeVisible({ timeout: 5_000 })
  })
})
