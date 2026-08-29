import { defineConfig } from "@playwright/test"

// 手动跑 suspend 弹框 e2e（不用 webServer 自启 backend / frontend）：
//   pnpm exec playwright test --config=playwright.suspend.config.ts suspend-confirm.spec.ts
//
// 前置：backend 8181 + frontend preview 4174 已手动起来；DB 已 seed 完 admin + idle
// timeout 配置（20s/5s）；admin storageState 写好（tests/e2e/.auth/admin.json）。
// 不打 self-managed server，避免本机 8000/4173 与其它同事撞车。
export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /suspend-confirm\.spec\.ts$/,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4174",
    storageState: "tests/e2e/.auth/admin.json",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    launchOptions: {
      // 关掉 --use-file-for-fake-audio-capture：循环 interview.webm 会让 server
      // _touch 一直 fire、watchdog 永不触发。本测试用 MediaRecorder 静默 override
      // 模拟「会话中突然没了语音」的 idle 状态，需要 server 端 _touch 不再发生。
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream"
      ]
    },
    permissions: ["microphone"]
  }
})