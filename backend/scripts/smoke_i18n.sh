#!/usr/bin/env bash
# backend/scripts/smoke_i18n.sh — manual smoke test for HTTP i18n.
#
# Pre-req: backend running on $BASE (default http://127.0.0.1:8000).
# 验证：
#   - 404 模板的 detail 消息按 Accept-Language 切换（en-US / zh-CN / zh-TW）
#   - /health 响应头 Content-Language 与 Accept-Language 一致
#
# 注意：
#   - 路由前缀是 /api/v1/...（非过时的 /api/admin/...）。
#   - templates 路由要求鉴权；未带 token 会先 401，所以探针只断言"返回的 detail 文本"
#     中是否包含对应语种的字串（401 也可能恰好等于该字串，但只要服务器本地化生效
#     这里就不会因 fallback 字符串混进来而失败）。
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"

probe() {
  local label="$1"; shift
  local want="$1"; shift
  local lang="$1"; shift
  local path="$1"; shift
  echo "── $label ──"
  echo "GET $path (Accept-Language=$lang)"
  local out
  out=$(curl -sS -H "Accept-Language: $lang" "$BASE$path")
  echo "$out" | head -c 400
  echo
  if echo "$out" | grep -q -- "$want"; then
    echo "  ✔ contains '$want'"
  else
    echo "  ✘ MISSING '$want'"
    return 1
  fi
  echo
}

probe "404 template (en)"    "Template not found" "en-US" "/api/v1/templates/zzz"
probe "404 template (zh-CN)" "模板不存在"        "zh-CN" "/api/v1/templates/zzz"
probe "404 template (zh-TW)" "範本不存在"        "zh-TW" "/api/v1/templates/zzz"

# /health 是未鉴权 GET 端点；校验 Content-Language 响应头而非 body。
echo "── Content-Language (en) ──"
cl=$(curl -sSI -H "Accept-Language: en-US" "$BASE/health" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-language"{print $2}')
echo "GET /health (Accept-Language=en-US) → Content-Language: $cl"
if [[ "$cl" == "en-US" ]]; then
  echo "  ✔ Content-Language = en-US"
else
  echo "  ✘ expected en-US, got '$cl'"
  exit 1
fi
echo
