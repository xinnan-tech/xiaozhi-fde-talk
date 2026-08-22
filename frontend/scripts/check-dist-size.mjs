#!/usr/bin/env node
// 前端 dist bundle 体积门禁
//
// 阈值依据：
//   - 单 chunk raw > 500_000 B（约 488 KiB）：
//     对齐 vite 默认 chunkSizeWarningLimit（500KB）。本仓 vite.config.ts 已经把警告阈值
//     抬到 4000KB 来压住打包告警，因此门禁用更严的 500KB 来兜住单点膨胀。
//     注意：当前 `pnpm build` 基线下，主入口单 chunk raw ≈ 1.05 MB，会触发此门禁；
//     这是预期行为——门禁的本意就是「先看到超阈，再决定是否拆 vendor / 砍依赖」。
//   - 所有 JS+CSS chunk gzip 之和 > 600_000 B（约 586 KiB）：
//     当前基线 gzip 总量约 515 KB（主入口 340KB gzip + 其它 CSS/JS 散片），
//     600KB 留约 17% 余量，足以容纳偶发新增依赖或多 locale 文本膨胀。
//
// 调整方法：直接改下面两个常量即可。常量集中在一处，方便在 PR 里 review 数字变更。

import { readdirSync, readFileSync, statSync, existsSync } from "node:fs"
import { join, basename } from "node:path"
import { gzipSync } from "node:zlib"

const DIST = "dist"
const PER_CHUNK_RAW_LIMIT = 500_000
const TOTAL_GZIP_LIMIT = 600_000

// 双路径探测：vite 默认 chunkFileNames 用 static/js|static/css，
// 但部分老配置会把资源放到 assets/（典型是 create-vite 模板）；同时兼容。
const SCAN_DIRS = [
  join(DIST, "static", "js"),
  join(DIST, "static", "css"),
  join(DIST, "assets")
]

if (!existsSync(DIST)) {
  console.warn(`[check-dist-size] ${DIST}/ not found, skip (run \`pnpm build\` first).`)
  process.exit(0)
}

const rows = []
let totalGzip = 0
const offenders = []

for (const dir of SCAN_DIRS) {
  if (!existsSync(dir)) continue
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (!statSync(p).isFile()) continue
    const buf = readFileSync(p)
    const raw = buf.length
    const gz = gzipSync(buf, { level: 9 }).length
    rows.push({ file: `${basename(dir)}/${name}`, raw, gzip: gz })
    totalGzip += gz
    if (raw > PER_CHUNK_RAW_LIMIT) {
      offenders.push({ file: name, kind: "raw", over: raw - PER_CHUNK_RAW_LIMIT, raw })
    }
  }
}

if (rows.length === 0) {
  console.warn(`[check-dist-size] no js/css chunks under ${DIST}, skip.`)
  process.exit(0)
}

const w = Math.max(...rows.map(r => r.file.length), 10)
console.log("")
console.log(
  `thresholds: per-chunk raw <= ${PER_CHUNK_RAW_LIMIT.toLocaleString()} B, ` +
    `total gzip <= ${TOTAL_GZIP_LIMIT.toLocaleString()} B`
)
console.log("")
console.log(
  `${"file".padEnd(w)}  ${"raw".padStart(12)}  ${"gzip".padStart(12)}`
)
console.log(
  `${"-".repeat(w)}  ${"-".repeat(12)}  ${"-".repeat(12)}`
)
for (const r of rows) {
  console.log(
    `${r.file.padEnd(w)}  ${r.raw.toLocaleString().padStart(12)}  ${r.gzip.toLocaleString().padStart(12)}`
  )
}
console.log(
  `${"TOTAL".padEnd(w)}  ${rows.reduce((a, b) => a + b.raw, 0).toLocaleString().padStart(12)}  ` +
    `${totalGzip.toLocaleString().padStart(12)}`
)
console.log("")

let failed = false
if (offenders.length > 0) {
  failed = true
  for (const o of offenders) {
    console.error(
      `[check-dist-size] FAIL ${o.file} raw ${o.raw.toLocaleString()} B ` +
        `exceeds per-chunk limit by ${o.over.toLocaleString()} B`
    )
  }
}
if (totalGzip > TOTAL_GZIP_LIMIT) {
  failed = true
  console.error(
    `[check-dist-size] FAIL total gzip ${totalGzip.toLocaleString()} B ` +
      `exceeds limit by ${(totalGzip - TOTAL_GZIP_LIMIT).toLocaleString()} B`
  )
}

if (failed) {
  console.error("[check-dist-size] dist size gate FAILED")
  process.exit(1)
}
console.log("[check-dist-size] dist size gate OK")
