import { defineConfig } from "@playwright/test"

// 手动跑 fix-web-status 暂停/恢复 e2e（不用 webServer 自启 backend / frontend）：
//   pnpm exec playwright test --config=playwright.pause-status.config.ts pause-status.spec.ts
//
// 前置：backend 8181 + frontend preview 4174 已手动起来；DB 已 seed 完 admin + idle
// timeout 配置（30s/5s）、ASR=funasr_mock、LLM=stub（通过 admin API 设置）。
// admin storageState 写好（tests/e2e/.auth/admin.json）。
// 不打 self-managed server，避免本机 8000/4173 与其它同事撞车。
export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /pause-status\.spec\.ts$/,
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
      // 用真 9min16s 访谈录音 webm 让 MediaRecorder 持续 _touch server 的
      // _last_activity_at（避开 30s idle watchdog 抢在我们的手动暂停前触发），
      // 同时保证 openMicrophone() 返回 true，否则 onConnected 会调
      // suspendLocalInterview 在没走 suspend API 的情况下翻 status，污染断言。
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        `--use-file-for-fake-audio-capture=${process.cwd()}/../backend/tests/e2e/audio/interview.webm`
      ]
    },
    permissions: ["microphone"]
  }
})
