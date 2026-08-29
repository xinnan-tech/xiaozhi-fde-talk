// 直接通过后端 /api/v1/auth/login 拿 access_token，写到 localStorage.user-info 与
// cookie.authorized-token（userStore getToken 兼容两者），跳过 UI 登录交互。
import { request as pwRequest } from "@playwright/test"
import { writeFileSync, mkdirSync } from "node:fs"
import { dirname } from "node:path"

const E2E_API = "http://127.0.0.1:8181"
const STATE_PATH = "tests/e2e/.auth/admin.json"
const ADMIN_USER = "admin"
const ADMIN_PWD = "Admin1234"

mkdirSync(dirname(STATE_PATH), { recursive: true })

async function main() {
  const api = await pwRequest.newContext({ baseURL: E2E_API })

  // 1. 注册首用户（count==0 时自动成 admin；已有则吞 409）
  try {
    const r = await api.post("/api/v1/auth/register", {
      data: {
        username: ADMIN_USER,
        password: ADMIN_PWD,
        confirm_password: ADMIN_PWD
      }
    })
    console.log("register status", r.status())
  } finally {
    /* swallow */
  }

  // 2. 登录拿 token + userId
  const loginResp = await api.post("/api/v1/auth/login", {
    data: { username: ADMIN_USER, password: ADMIN_PWD }
  })
  if (loginResp.status() !== 200) {
    throw new Error(`login failed status=${loginResp.status()} ${await loginResp.text()}`)
  }
  const loginJson = (await loginResp.json()) as {
    access_token: string
    user: { id: string; username: string; role: string }
  }
  await api.dispose()
  console.log("logged in as", loginJson.user.username, "role", loginJson.user.role)

  // 3. 构造 storageState：playwright 的 storageState 形状 {cookies, origins}
  //    user-info 写到 localStorage 让 userStore 识别登录态；role/userId 不能省，
  //    否则 getToken 会因兼容检查（utils/auth.ts:42-50）直接 removeToken。
  const state = {
    cookies: [],
    origins: [
      {
        origin: "http://127.0.0.1:4174",
        localStorage: [
          {
            name: "user-info",
            value: JSON.stringify({
              accessToken: loginJson.access_token,
              username: loginJson.user.username,
              userId: loginJson.user.id,
              role: loginJson.user.role
            })
          }
        ]
      }
    ]
  }
  writeFileSync(STATE_PATH, JSON.stringify(state, null, 2))
  console.log("wrote", STATE_PATH)
}

main().catch(e => {
  console.error(e)
  process.exit(1)
})