/**
 * 模板 JSON 客户端校验（JSON 模式用）。
 *
 * 后端 pydantic + service 校验是最终闸门；这里做先行反馈：
 * - parseJsonSafe：语法错误换算行列（各引擎 JSON.parse 消息里的定位信息）
 * - validateTemplateStructure：与后端 _validate 同规则的结构检查，
 *   dot-path 报错（如 session.base_fields[2].key: 字段键重复）
 */

export type StructError = { path: string; message: string };

export function parseJsonSafe(text: string): {
  data?: unknown;
  error?: { line: number; column: number; message: string };
} {
  try {
    return { data: JSON.parse(text) };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    // 各引擎的错误消息定位格式不同，按优先级提取（均为 1 基）：
    // - 新版 V8（结构性错误）与 SpiderMonkey：直接带 "line X column Y"
    // - 旧版 V8：只带 "position N"，换算行列
    // - 新版 V8 的 "Unexpected token" 家族与 JSC：无定位，退化为 1/1
    let line = 1;
    let column = 1;
    const mLC = msg.match(/line (\d+) column (\d+)/);
    const mPos = msg.match(/position (\d+)/);
    if (mLC) {
      line = Number(mLC[1]);
      column = Number(mLC[2]);
    } else if (mPos) {
      const pos = Number(mPos[1]);
      const before = text.slice(0, pos);
      line = before.split("\n").length;
      column = pos - before.lastIndexOf("\n");
    }
    return { error: { line, column, message: msg } };
  }
}

export function validateTemplateStructure(data: unknown): StructError[] {
  const errors: StructError[] = [];
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return [{ path: "$", message: "根节点必须是对象" }];
  }
  const obj = data as Record<string, unknown>;

  // id/name 允许暂时为空（模式切换是视图操作，不该被未填完卡死）；
  // 格式错了才拦——这类数据进了表单也改不对。留空由保存时的后端校验兜底。
  const id = typeof obj.id === "string" ? obj.id : "";
  if (id && !/^[a-z0-9-]+$/.test(id))
    errors.push({ path: "id", message: "仅允许小写字母、数字、连字符" });

  const session = obj.session;
  if (typeof session !== "object" || session === null)
    return [...errors, { path: "session", message: "缺失或不是对象" }];
  const s = session as Record<string, unknown>;

  const fields = Array.isArray(s.base_fields) ? s.base_fields : [];
  const keys: string[] = [];
  fields.forEach((f, i) => {
    const p = `session.base_fields[${i}]`;
    if (typeof f !== "object" || f === null) {
      errors.push({ path: p, message: "必须是对象" });
      return;
    }
    const k = (f as Record<string, unknown>).key;
    if (typeof k !== "string" || !k.trim())
      errors.push({ path: `${p}.key`, message: "字段键必填" });
    else keys.push(k);
  });
  const dup = keys.filter((k, i) => keys.indexOf(k) !== i);
  if (dup.length)
    errors.push({
      path: "session.base_fields[].key",
      message: `重复字段：${[...new Set(dup)].join("、")}`
    });

  const setup =
    typeof s.setup === "object" && s.setup !== null
      ? (s.setup as Record<string, unknown>)
      : {};
  // goal / end_time 是保留字段：goal 不在 base_fields 里，end_time 是
  // 创建访谈时由时长算出的运行时字段（历史模板的 extract_to 会引用）
  const known = new Set([...keys, "goal", "end_time"]);
  for (const attr of ["extract_to", "required"] as const) {
    const list = Array.isArray(setup[attr]) ? (setup[attr] as unknown[]) : [];
    const missing = list.filter(
      k => typeof k === "string" && !known.has(k)
    ) as string[];
    if (missing.length)
      errors.push({
        path: `session.setup.${attr}`,
        message: `引用了未定义字段：${missing.join("、")}`
      });
  }

  const coaching = obj.coaching;
  const c =
    typeof coaching === "object" && coaching !== null
      ? (coaching as Record<string, unknown>)
      : {};
  const items = Array.isArray(c.must_ask) ? c.must_ask : [];
  const ids = items
    .filter(
      it =>
        typeof it === "object" &&
        it !== null &&
        (it as Record<string, unknown>).id
    )
    .map(it => String((it as Record<string, unknown>).id));
  const dupIds = ids.filter((v, i) => ids.indexOf(v) !== i);
  if (dupIds.length)
    errors.push({
      path: "coaching.must_ask[].id",
      message: `重复 id：${[...new Set(dupIds)].join("、")}`
    });

  return errors;
}
