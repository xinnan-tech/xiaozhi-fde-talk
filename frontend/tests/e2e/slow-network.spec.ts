import { test, expect } from "@playwright/test"

// 弱网首屏时延 spec
//
// 场景假设：用户在 100.x LAN 段（典型 NAT 后家庭网络）+ 1Mbps 下行 / 500Kbps 上行
// / 200ms RTT 下访问 https://...:4173/ 首屏 domcontentloaded 应在 8s 内。
//
// 阈值 8s 出处：编译产物首屏 raw chunk ≈ 1.05 MB，1Mbps 下行（125 KB/s）光下载
// ≈ 8.4s，加上 200ms RTT 与若干请求的握手 / DNS 累计；正常编译产物应刚好擦边
// 通过。如首次跑挂在 8s 边缘，把 8s 放宽到 10s 并在 commit body 注释依据。
//
// CDP Network.emulateNetworkConditions 单位是 bytes/s（不是 bits/s）：
//   1 Mbps    = 1_000_000 / 8 = 125_000 bytes/s
//   500 Kbps  =   500_000 / 8 =  62_500 bytes/s
// 通过 throughput = -1 / latency = 0 复位 throttle。

test("1Mbps/200ms RTT 弱网下首屏 domcontentloaded < 8s", async ({
  browser,
}) => {
  test.setTimeout(30_000)

  const context = await browser.newContext()
  try {
    const page = await context.newPage()
    const cdp = await context.newCDPSession(page)
    await cdp.send("Network.enable")
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      downloadThroughput: 125_000,
      uploadThroughput: 62_500,
      latency: 200,
    })

    const start = Date.now()
    await page.goto("/", { waitUntil: "domcontentloaded" })

    // 取 navigation timing：domContentLoadedEventEnd 相对 startTime 的偏移
    const t = await page.evaluate(() => {
      const nav = performance.getEntriesByType(
        "navigation"
      )[0] as PerformanceNavigationTiming
      return nav.domContentLoadedEventEnd - nav.startTime
    })

    const wallClock = Date.now() - start
    // 软断言：navigation timing 优先；wall-clock 作为兜底日志便于 trace 排查
    expect(t).toBeLessThan(8_000)

    // 复位 throttle（CDP 协议要求 throughput = -1 表示不限速）
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      downloadThroughput: -1,
      uploadThroughput: -1,
      latency: 0,
    })

    // 简单 sanity：navigation timing 应 < wall-clock（CDP 拦截不影响 wall-clock 起点）
    expect(t).toBeLessThanOrEqual(wallClock + 50)
  } finally {
    await context.close()
  }
})
