import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "cd ../backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --env-file .env.test",
      port: 8001,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        DATABASE_URL: "sqlite+aiosqlite:///./tests/e2e/.e2e.db",
      },
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "pnpm preview",
      port: 4173,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        NODE_ENV: "production",
      },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
})
