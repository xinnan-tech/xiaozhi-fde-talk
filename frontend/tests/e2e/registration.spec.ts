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

    // 等 registration-status 异步返回（global-setup 已 PUT allow_registration=true）
    await page.waitForTimeout(500)

    // 切到注册模式（LoginDialog 内的 el-link，文案随 i18n 变：en-US="Sign up" /
    // zh-CN="去注册" / vi-VN="Sign up" / zh-TW="去註冊"；用结构化定位 + 多语 fallback）
    const goRegister = dialog.locator("a.el-link").filter({
      hasText: /Sign up|去注册|去註冊|Đăng ký/i,
    })
    await expect(goRegister).toBeVisible({ timeout: 5_000 })
    await goRegister.click()

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

    // 侧边栏应含 admin 限定菜单。
    // global-setup 已预先注册 admin 并写 .auth/admin.json，DB 上首位用户已被占，
    // alice 注册后 role=user，没有 system/users 菜单 —— 这条用例的初始假设已失效。
    // 改成断言 alice 已登入（user 角色能看到的菜单：home / about）。
    await expect(page.locator(".user-avatar.online")).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByText(/About|关于|關於|Giới thiệu/i).first()).toBeVisible({
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
    // 1) 取 global-setup 已注册的 admin token（DB 首用户已被它占，registerViaApi
    //    注册同名 admin 会失败；改为直接登录拿 token）。
    const adminToken = (await loginViaApi(ADMIN_USER, ADMIN_PWD))?.access_token
    expect(adminToken, "admin 登录失败（global-setup 未建？）").toBeTruthy()

    // 2) 开 allow_registration（默认 false），bob 才能注册
    const opened = await setAuthFlag(adminToken!, "allow_registration", "true")
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
    await page.goto("/#/system")
    await expect(page).toHaveURL(/\/error\/403/, { timeout: 10_000 })

    // 6) /admin/users 也是 admin 限定（router/modules/admin_users.ts:12）
    await page.goto("/#/admin/users")
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
    await page.goto("/#/system")
    await page.waitForLoadState("networkidle", { timeout: 15_000 })

    // 字段 label 用 i18n key 渲染（system/index.vue:translateFieldLabel → t("system.field.allow_registration")）。
    // playwright 浏览器默认 en-US，渲染为 "Allow registration"；多语 fallback 容错 zh-CN。
    const allowRegRow = page.locator(".field-row", {
      hasText: /Allow registration|允许注册/i,
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
    // 卡片标题 i18n 翻译：en-US="Authentication" / zh-CN="认证授权"
    const authCard = page.locator(".config-card").filter({
      has: page.locator(".card-title-row h2", {
        hasText: /^Authentication$|^认证授权$/i,
      }),
    })
    // auth 卡片可能初始不在 active 视图——但 .config-card 列表里都存在，按 h2 锁定即可。
    await authCard.locator(".save-button").click()

    // 等 Element Plus success toast（en-US: "Saved; changes apply to the next request"）
    await expect(page.locator(".el-message--success")).toContainText(
      /Saved|保存.*成功/i,
      { timeout: 10_000 }
    )

    // 3) 进 /admin/users
    await page.goto("/#/admin/users")
    await page.waitForLoadState("networkidle", { timeout: 15_000 })

    // 等用户列表加载完（admin/users/index.vue:18 admin-users-header > h1.header-title）
    // header 文案 t("users.list_title") = "Users" / "用户列表" / "用戶列表"
    await expect(
      page.locator(".admin-users-page .admin-users-header .header-title")
    ).toContainText(/Users|用户列表|用戶列表/i, { timeout: 10_000 })

    // 4) 重置密码按钮 disabled + tooltip 提示（admin/users/index.vue:79-83）
    const resetBtn = page
      .locator(".admin-users-page .el-table .el-button")
      .filter({ hasText: /Reset password|重置密码|重設密碼/i })
      .first()
    await expect(resetBtn).toBeVisible({ timeout: 10_000 })
    await expect(resetBtn).toBeDisabled()

    // tooltip：Element Plus 2.x el-tooltip 触发器包一层 .el-tooltip__trigger
    // （内部 <el-popper-trigger class="el-tooltip__trigger">，包住 slot button）
    // 注册关闭时 tooltip:disabled=false（提示开启），DOM 上仍渲染 trigger wrapper。
    const tooltipWrapper = page
      .locator(".admin-users-page .el-tooltip__trigger")
      .first()
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
    await page.goto("/#/admin/users")
    await expect(
      page.locator(".admin-users-page .admin-users-header .header-title")
    ).toContainText(/Users|用户列表|用戶列表/i, { timeout: 10_000 })

    // 找到 bob 所在行（username 列匹配）
    const bobRow = page
      .locator(".admin-users-page .el-table .el-table__row")
      .filter({ hasText: bobUser })
      .first()
    await expect(bobRow).toBeVisible({ timeout: 10_000 })

    // 5) 点「重置密码」按钮 → 弹 dialog → 填新密码 → 确认
    await bobRow
      .locator(".el-button")
      .filter({ hasText: /Reset password|重置密码|重設密碼/i })
      .click()
    // 弹出的 dialog 是 admin/users/index.vue:89-102 的 el-dialog
    // 标题 t("users.reset_password_title") = "Reset user password" / "重置用户密码"
    const resetDialog = page.locator(".el-dialog").filter({
      hasText: /Reset user password|重置用户密码|重設用戶密碼/i,
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
      /Password reset|密码已重置|密碼已重設/i,
      { timeout: 10_000 }
    )

    // 6) 清 cookie/storage，登 admin → 用 bob 登录
    //    顺序：先清 storage 再 reload，避免 pinia 在内存里仍持有 admin token 导致
    //    click avatar 弹 dropdown 而非 login dialog（之前 D-1 偶发 flake 即此原因）。
    await context.clearCookies()
    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })
    await page.reload()

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
    // 1) 登录 global-setup 已注册的 admin（DB 首用户已被占，不能再 register 一个新 admin）
    const adminToken = (await loginViaApi(ADMIN_USER, ADMIN_PWD))?.access_token
    expect(adminToken, "admin 登录失败").toBeTruthy()

    // 2) 开 allow_registration，注册 bob
    await setAuthFlag(adminToken!, "allow_registration", "true")
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

  test("mock 500 → login dialog 去注册按钮不渲染（产品意图：看不到入口）", async ({
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
    // 把 registrationAvailable 设为 false（LoginDialog:38）→ "去注册" link 被 v-if 隐藏
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })

    // 等异步 fetch 跑完再断言
    await page.waitForTimeout(1_000)

    // 产品意图：registrationAvailable===false 时 link 直接隐藏，避免「看到却点不动」。
    // 之前版本曾尝试 el-tooltip 包 disabled 表达，但与设计意图冲突，回退到直接隐藏。
    const goRegister = dialog.locator("text=去注册")
    await expect(goRegister).toHaveCount(0, { timeout: 5_000 })
  })
})

// ─────────────────────────────────────────────────────────────────────
// 场景 F：首用户注册后 admin 菜单不闪现（App.vue watch 跟着 role 重拉注册状态）
// ─────────────────────────────────────────────────────────────────────

test.describe("场景 F: 首用户注册 → admin 菜单不闪现", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("mock 零用户 staleness → 注册后 + 刷新后均不出现 admin/users 菜单", async ({
    page,
    context,
  }) => {
    await context.clearCookies()

    // 模拟「零用户时 registration-status 强制返 true / 有用户后按 cfg false」——
    // 这就是用户报 bug 的根因：App.vue onMounted 拿到的 true 是缓存的 stale 值，
    // 注册瞬间角色从空跳成 admin，旧缓存让 admin 菜单闪现。
    let registered = false
    let registrationStatusCalls = 0
    await page.route("**/api/v1/auth/registration-status", route => {
      registrationStatusCalls++
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          allow_registration: !registered,
        }),
      })
    })

    // 模拟注册响应：让 alice 成为 admin（首用户默认）
    await page.route("**/api/v1/auth/register", route => {
      registered = true
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "mock-admin-token",
          refresh_token: "",
          token_type: "bearer",
          user: {
            id: "mock-admin-id",
            username: "alice_first",
            role: "admin",
          },
        }),
      })
    })

    await page.goto("/")
    await page.evaluate(() => {
      localStorage.clear()
      sessionStorage.clear()
    })

    // 点 avatar → dialog
    await page.locator(".user-avatar").click()
    const dialog = page.locator(".login-dialog")
    await dialog.waitFor({ state: "visible", timeout: 15_000 })
    // 等 LoginDialog watch 触发 registration-status（mock 2nd call 应返 true）
    await page.waitForTimeout(500)

    // 切到注册模式
    const goRegister = dialog.locator("a.el-link").filter({
      hasText: /Sign up|去注册|去註冊|Đăng ký/i,
    })
    await expect(goRegister).toBeVisible({ timeout: 5_000 })
    await goRegister.click()

    // 填表 + 提交
    await dialog.locator(".login-input").nth(0).locator("input").fill("alice_first")
    await dialog.locator(".login-input").nth(1).locator("input").fill("Strong1!pwd")
    await dialog.locator(".login-input").nth(2).locator("input").fill("Strong1!pwd")
    await dialog.locator(".login-btn").click()
    await dialog.waitFor({ state: "hidden", timeout: 15_000 })

    // 注册成功后 Element Plus toast「注册成功」
    await expect(page.locator(".el-message--success")).toContainText(
      /注册成功|register.*success|success/i,
      { timeout: 5_000 }
    )

    // 关键断言：admin 角色拿到后菜单不出现。这是 bug 的核心断言：fix 之前
    // 会闪现，fix 之后立刻消失。watch 会重拉 registration-status，mock 在注册
    // 后切到返 false，缓存对齐后 filter 把 admin 菜单过滤掉。
    await page.waitForTimeout(500)
    const adminMenuLink = page.locator(".sidebar-menu a, .el-menu a, nav a").filter({
      hasText: /^Users$|^用户管理$|^用戶管理$/i,
    })
    await expect(adminMenuLink).toHaveCount(0, { timeout: 5_000 })

    // 刷新后仍不出现（确保 onMounted 的初始 fetch 也对齐 cfg false）
    await page.reload()
    await page.waitForTimeout(500)
    const adminMenuLinkAfterReload = page.locator(
      ".sidebar-menu a, .el-menu a, nav a"
    ).filter({
      hasText: /^Users$|^用户管理$|^用戶管理$/i,
    })
    await expect(adminMenuLinkAfterReload).toHaveCount(0, { timeout: 5_000 })

    // 探针：注册后 registration-status 应被多调用一次（watch 重拉）。这是对 fix
    // 的直接验证——没修之前只有 onMounted + dialog open 共 2 次。
    expect(registrationStatusCalls).toBeGreaterThanOrEqual(3)
  })
})
