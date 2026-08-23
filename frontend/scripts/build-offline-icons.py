#!/usr/bin/env python3
"""把白名单里的 iconify 图标 body 从
node_modules/@iconify/json/json/<prefix>.json 抄成离线注册包。

跑法：python3 scripts/build-offline-icons.py
产物：src/components/ReIcon/src/offlineIconBundle.generated.ts

要新增/移除离线图标：直接编辑下方 NEEDED 字典，再跑一次本脚本。
不要直接手改 generated.ts，否则下次重生会被冲掉。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS_DIR = os.path.join(ROOT, "node_modules", "@iconify", "json", "json")
OUT = os.path.join(
    ROOT, "src", "components", "ReIcon", "src", "offlineIconBundle.generated.ts"
)

# 用到在线通道 "prefix:name" 的全部图标（前端 useRenderIcon 字符串）。
# 前缀/名字都要跟 useRenderIcon 调用方保持一致；漏一个就走在线通道。
NEEDED = {
    "tabler": [
        "search", "x", "plus", "message-chatbot-filled", "circle-check-filled",
        "folder-open-filled", "clock", "checkbox", "message", "key", "logout",
        "robot", "link", "adjustments", "school", "lock", "settings",
        "settings-filled", "users", "info-circle-filled", "file-text",
        "user", "calendar", "microphone", "camera", "clipboard-text",
    ],
    "majesticons": ["bell", "note-text"],
    "flowbite": ["language-outline"],
    "flat-color-icons": ["businessman"],
    "heroicons": ["arrow-long-left"],
    "boxicons": ["eraser-filled", "pencil-draw"],
    "lucide": ["eye-off", "mic", "mic-off"],
    "si": ["ai-line"],
    "clarity": ["new-solid"],
    "quill": ["share", "meatballs-h"],
    "ep": ["download", "delete", "refresh", "circle-check-filled", "close", "loading"],
    "jam": ["activity"],
    "ri": ["information-line"],
}


def main() -> int:
    missing: list[tuple[str, str]] = []
    for prefix in NEEDED:
        path = os.path.join(SETS_DIR, f"{prefix}.json")
        if not os.path.exists(path):
            sys.stderr.write(f"!! {prefix} set not found at {path}\n")
            return 2

    entries: list[str] = []
    for prefix, names in NEEDED.items():
        with open(os.path.join(SETS_DIR, f"{prefix}.json")) as f:
            data = json.load(f)
        have = set(data["icons"].keys())
        for name in names:
            if name not in have:
                missing.append((prefix, name))
                continue
            icon = data["icons"][name]
            body = icon["body"]
            # 模板字符串需要转义反引号 / 反斜杠 / ${...}
            escaped = (
                body.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            )
            parts = [f"body: `{escaped}`"]
            if icon.get("width") is not None:
                parts.append(f"width: {icon['width']}")
            if icon.get("height") is not None:
                parts.append(f"height: {icon['height']}")
            entries.append(f'  ["{prefix}:{name}", {{ ' + ", ".join(parts) + " }}],")

    if missing:
        sys.stderr.write("missing icons:\n")
        for prefix, name in missing:
            sys.stderr.write(f"  - {prefix}:{name}\n")
        return 3

    head = """// Auto-generated. Do not edit by hand.
// 从 node_modules/@iconify/json/json/<prefix>.json 把白名单内的图标 body 抄成离线包，
// 让内网环境（无 api.iconify.design）也能渲染 useRenderIcon("prefix:name")。
// 改白名单：编辑 scripts/build-offline-icons.py 重跑：python3 scripts/build-offline-icons.py

import { addIcon } from "@iconify/vue/dist/offline";

type IconBody = { body: string; width?: number; height?: number };

export const offlineIconEntries: Array<[string, IconBody]> = [
"""
    tail = """];

offlineIconEntries.forEach(([name, data]) => addIcon(name, data));
"""
    with open(OUT, "w") as f:
        f.write(head + "\n".join(entries) + "\n" + tail)
    total = sum(len(v) for v in NEEDED.values())
    sys.stdout.write(f"wrote {len(NEEDED)} sets / {total} icons -> {os.path.relpath(OUT, ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
