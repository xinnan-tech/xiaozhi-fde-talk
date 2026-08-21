#!/usr/bin/env node
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs"
import { join, extname } from "node:path"

const DIST = "dist"
if (!existsSync(DIST)) process.exit(0)
const FORBIDDEN = [
  "192.168", "100.76", "100.64", "100.65", "100.66", "100.67", "100.68",
  "localhost", "127.0.0.1"
]

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if ([".js", ".css", ".html"].includes(extname(p))) out.push(p)
  }
  return out
}

let failed = false
for (const f of walk(DIST)) {
  const content = readFileSync(f, "utf8")
  for (const word of FORBIDDEN) {
    if (content.includes(word)) {
      console.error(`FAIL: ${f} contains "${word}"`)
      failed = true
    }
  }
}
process.exit(failed ? 1 : 0)
