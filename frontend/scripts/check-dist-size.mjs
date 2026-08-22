#!/usr/bin/env node
// 前端 dist bundle 体积门禁
//
// 阈值依据（对齐 element-plus 全量引入的当前 vendor 拆分现状）：
//   - 单 chunk raw <= 1_000_000 B（约 977 KiB）：
//     element-plus 全量打包后单 chunk 约 800KB，是当前已知最大 vendor chunk，
//     待按需引入 follow-up 优化；阈值兜住「常规新增依赖」单点膨胀，不卡大库。
//   - 所有 JS+CSS chunk gzip 之和 <= 800_000 B（约 781 KiB）：
//     element-plus gzip 约 256KB + utils-vendor gzip 约 55KB + main gzip 约 32KB +
//     CSS gzip 约 80KB ≈ 420KB 当前基线；800KB 给多 locale 文本 / 新依赖留余量。
//
// 调整方法：直接改下面两个常量。常量集中在一处，PR 里 review 数字变更即可。

import { readdirSync, readFileSync, statSync, existsSync } from "node:fs"
import { join, basename } from "node:path"
import { gzipSync } from "node:zlib"

const DIST = "dist"
const PER_CHUNK_RAW_LIMIT = 1_000_000
const TOTAL_GZIP_LIMIT = 800_000

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
