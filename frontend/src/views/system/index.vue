<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { extractBackendError } from "@/utils/error";
import { ElMessage, ElMessageBox } from "element-plus";
import { useUserStoreHook } from "@/store/modules/user";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { usePermissionStoreHook } from "@/store/modules/permission";
import { registrationStatusApi } from "@/api/user";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import {
  systemConfigApi,
  type SystemConfig,
  type SystemConfigSection,
  type SystemConfigValue,
  systemDiagnosticsApi,
  systemAsrDiagnosticsApi,
  systemLlmDiagnosticsApi,
  systemOcrDiagnosticsApi,
  systemConfigSaveApi
} from "@/api/system";
import { useRouter } from "vue-router";
import {
  listAdminTemplatesApi,
  deleteAdminTemplateApi,
  type AdminTemplateSummary
} from "@/api/admin";

defineOptions({
  name: "SystemConfig"
});

/** 页面编辑器使用的配置项值 */
type ConfigValue = string | boolean;
/** select 选项：asrTypeOptions 用纯 label 字面量（动态探测的 type 名），
 * 静态语种用 labelKey + i18n 翻译。两形态并存便于一处渲染。 */
type AsrTypeOption = { value: string; label: string };
type SelectOption = { value: string; label?: string; labelKey?: string };
/** select 渲染分支：radio 用于 ASR.type 这类 2~4 项的紧凑选择，
 * dropdown 用于语种这种 5+ 项的下拉。 */
type SelectVariant = "radio" | "dropdown";
type ConfigField = {
  /** 配置项key */
  key: string;
  /** 配置项label */
  label: string;
  /** 配置项类型 */
  type?: "text" | "password" | "checkbox" | "select";
  /** select 类型的选项列表 */
  options?: SelectOption[];
  /** select 类型的渲染分支；未设则按 key=='type' 推断 radio（ASR.type 兼容旧默认） */
  selectVariant?: SelectVariant;
};
type ConfigGroup = {
  /** 配置分组key */
  key: string;
  /** 配置分组title */
  title: string;
  /** 配置分组图标 */
  icon: ReturnType<typeof useRenderIcon>;
  fields: ConfigField[];
};
type CheckTarget = "all" | "asr" | "llm" | "ocr";
type CheckStatus = "normal" | "running" | "error";

/** 自检结果 */
type SelfCheckResult = {
  key: Exclude<CheckTarget, "all">;
  titleKey: string;
  description: string;
  detail: string;
  duration: string;
  model?: string;
  sample?: string;
  status: CheckStatus;
};

const userStore = useUserStoreHook();
const permissionStore = usePermissionStoreHook();
const { t, locale } = useI18n();

/** 配置项 field key 翻译为本地化 label，未匹配则回退 key。 */
const translateFieldLabel = (fieldKey: string): string => {
  const key = `system.field.${fieldKey}`;
  const translated = t(key);
  return translated === key ? fieldKey : translated;
};

/** 配置分组 key 翻译为本地化 title，未匹配则回退 key。 */
const translateGroupTitle = (groupKey: string): string => {
  const key = `system.group.${groupKey}`;
  const translated = t(key);
  return translated === key ? groupKey : translated;
};

const icons = {
  llm: useRenderIcon("tabler:robot"),
  asr: useRenderIcon("tabler:link"),
  vad: useRenderIcon("tabler:adjustments"),
  coach: useRenderIcon("tabler:school"),
  auth: useRenderIcon("tabler:lock"),
  session: useRenderIcon("tabler:clock"),
  plus: useRenderIcon("tabler:plus"),
  activity: useRenderIcon("jam:activity"),
  check: useRenderIcon("ep:circle-check-filled"),
  close: useRenderIcon("ep:close"),
  loading: useRenderIcon("ep:loading")
};

const activeGroup = ref("llm");
const configScroll = ref();
const configCards = ref<Record<string, HTMLElement | null>>({});
const config = reactive<Record<string, Record<string, ConfigValue>>>({});
const originalConfig = ref<Record<string, Record<string, ConfigValue>>>({});
const configGroups = ref<ConfigGroup[]>([]);
const selfCheckVisible = ref(false);
const selfCheckRunning = ref(false);
const selfCheckTarget = ref<CheckTarget>("all");
const selfCheckResults = reactive<SelfCheckResult[]>([]);
/** 敏感密码字段 */
const sensitiveKeys = ["api_key", "access_token", "secret_key"];
/** 复选框字段 */
const checkboxKeys = [
  "ws_verify_ssl",
  "allow_registration",
  "enable_multilingual"
];
/** select 字段的预定义选项。key 形如 "<group>.<field>"——与 config_store
 * 的存储路径一致，方便直接 lookup。
 *
 * 真相之源在 backend/app/core/config_store.py:ENUM_KEYS；本常量是 admin
 * UI 引导提示，让 admin 点选不手填。Doubao 完整 22 语种只暴露常用 10 个，
 * 其余 locale 切走时回退到 el-input 手动输入。改枚举时必须两边同步。 */
const SELECT_FIELD_OPTIONS: Record<string, SelectOption[]> = {
  "asr.funasr_server.language": [
    { value: "zh", labelKey: "config.opt.zh" },
    { value: "yue", labelKey: "config.opt.yue" },
    { value: "en", labelKey: "config.opt.en" }
  ],
  "asr.doubao_stream.language": [
    { value: "zh-CN", labelKey: "config.opt.zh_cn" },
    { value: "en-US", labelKey: "config.opt.en" },
    { value: "ja-JP", labelKey: "config.opt.ja_jp" },
    { value: "yue-CN", labelKey: "config.opt.yue" },
    { value: "ko-KR", labelKey: "config.opt.ko_kr" },
    { value: "es-MX", labelKey: "config.opt.es_mx" },
    { value: "fr-FR", labelKey: "config.opt.fr_fr" },
    { value: "de-DE", labelKey: "config.opt.de_de" },
    { value: "ru-RU", labelKey: "config.opt.ru_ru" },
    { value: "pt-BR", labelKey: "config.opt.pt_br" }
  ],
  "llm.output_language": [
    { value: "zh_cn", labelKey: "config.opt.zh_cn" },
    { value: "zh_tw", labelKey: "config.opt.zh_tw" },
    { value: "en", labelKey: "config.opt.en" }
  ]
};
/** ASR 类型选项（运行时从嵌套结构填充） */
const asrTypeOptions = ref<AsrTypeOption[]>([]);
/** ASR type → 该类型拥有的字段 key 集合（运行时填充） */
const asrTypeFieldKeys = reactive<Record<string, string[]>>({});
/** 当前 ASR 类型的可见字段 key 集合 */
const visibleAsrFieldKeys = computed(() => {
  const type = config.asr?.type as string;
  return asrTypeFieldKeys[type] ?? [];
});

/** 是否已登录 */
const isLoggedIn = computed(() => Boolean(userStore.accessToken));

/** 是否为配置分组 */
const isConfigSection = (
  value: SystemConfigSection | SystemConfigValue | undefined | null
): value is SystemConfigSection =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/** 将后端值转换为表单可编辑的值 */
const toEditorValue = (key: string, value: SystemConfigValue): ConfigValue => {
  if (typeof value === "boolean") return value;
  if (checkboxKeys.includes(key)) return value === "true";
  return value == null ? "" : String(value);
};

/** 读取配置字段值（ASR 走嵌套路径） */
const getFieldValue = (
  groupKey: string,
  fieldKey: string
): ConfigValue | undefined => {
  if (groupKey === "asr") {
    const type = config.asr?.type as string;
    return config.asr?.[type]?.[fieldKey];
  }
  return config[groupKey]?.[fieldKey];
};

/** 写入配置字段值（ASR 走嵌套路径） */
const setFieldValue = (
  groupKey: string,
  fieldKey: string,
  value: ConfigValue
) => {
  if (groupKey === "asr") {
    const type = config.asr?.type as string;
    if (type && config.asr?.[type]) {
      (config.asr[type] as unknown as Record<string, ConfigValue>)[fieldKey] =
        value;
    }
  } else {
    config[groupKey][fieldKey] = value;
  }
};

/** 渲染时按当前 ASR type 解析选项。
 *
 * ASR 字段在 buildConfigGroups 时不烤入 options（不同 type 共享 fieldKey，
 * 例如 funasr_server 和 doubao_stream 都有 language，但选项集合完全不同）；
 * 改为渲染时按 config.asr.type 实时查表，避免 dedup 后切 type 时 options
 * 沿用第一个遍历到的 type。 */
const selectOptionsFor = (
  groupKey: string,
  fieldKey: string
): SelectOption[] | undefined => {
  if (groupKey === "asr") {
    const type = config.asr?.type as string;
    return SELECT_FIELD_OPTIONS[`asr.${type}.${fieldKey}`];
  }
  return SELECT_FIELD_OPTIONS[`${groupKey}.${fieldKey}`];
};

/** 获取配置分组图标 */
const getGroupIcon = (key: string) =>
  icons[key as keyof typeof icons] ?? useRenderIcon("tabler:settings");

const buildConfigGroups = (data: SystemConfig) => {
  const loadedConfig: Record<string, Record<string, ConfigValue>> = {};

  /** 根据实际响应动态生成分组，因此后端缺少或新增分组时页面都能正常展示。 */
  const groups = Object.entries(data).flatMap(([groupKey, section]) =>
    isConfigSection(section) ? [[groupKey, section] as const] : []
  );

  configGroups.value = groups.map(([groupKey, section]) => {
    let fields: ConfigField[];

    if (groupKey === "asr") {
      // ASR: type 字段 + 遍历所有嵌套类型的所有 key
      const sectionRec = section as Record<string, unknown>;
      const typeValue = (sectionRec["type"] as string) || "funasr_server";
      // 驱动：ASR 类型选项 + 每个类型的字段映射（供切换时过滤用）
      const detectedTypes = Object.keys(sectionRec).filter(
        k => k !== "type" && typeof sectionRec[k] === "object"
      );
      asrTypeOptions.value = detectedTypes.map(k => ({
        value: k,
        label: k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
      }));
      // 先清空再填充
      Object.keys(asrTypeFieldKeys).forEach(k => delete asrTypeFieldKeys[k]);
      detectedTypes.forEach(typeKey => {
        const nested = sectionRec[typeKey] as Record<string, SystemConfigValue>;
        asrTypeFieldKeys[typeKey] = Object.keys(nested);
      });

      fields = [
        {
          key: "type",
          label: translateFieldLabel("type"),
          type: "select" as const,
          options: asrTypeOptions.value as SelectOption[],
          selectVariant: "radio" as const
        }
      ];

      // 遍历所有嵌套类型，收集字段（去重，type 选项已覆盖的跳过）
      const seenKeys = new Set<string>();
      for (const typeKey of Object.keys(sectionRec)) {
        if (typeKey === "type" || typeof sectionRec[typeKey] !== "object")
          continue;
        const nested = sectionRec[typeKey] as Record<string, SystemConfigValue>;
        for (const [fieldKey] of Object.entries(nested)) {
          if (seenKeys.has(fieldKey)) continue;
          seenKeys.add(fieldKey);
          const isCheckbox = checkboxKeys.includes(fieldKey);
          const isPassword = sensitiveKeys.includes(fieldKey);
          // ASR 字段 options 不在 build 时烤入：不同 type 可能共享 fieldKey
          // （funasr_server / doubao_stream 都有 language 但选项不同），渲染时
          // 由 selectOptionsFor 按当前 config.asr.type 实时查。
          const hasSelectOptions =
            SELECT_FIELD_OPTIONS[`asr.${typeKey}.${fieldKey}`] !== undefined;
          fields.push({
            key: fieldKey,
            label: translateFieldLabel(fieldKey),
            type: isCheckbox
              ? ("checkbox" as const)
              : isPassword
                ? ("password" as const)
                : hasSelectOptions
                  ? ("select" as const)
                  : ("text" as const),
            ...(hasSelectOptions ? { selectVariant: "dropdown" as const } : {})
          });
        }
      }

      // loadedConfig 保持嵌套结构：{ type, funasr_server: {...}, doubao_stream: {...} }
      loadedConfig[groupKey] = { type: typeValue } as Record<
        string,
        ConfigValue
      >;
      for (const [k, v] of Object.entries(sectionRec)) {
        if (k === "type") {
          loadedConfig[groupKey]["type"] = toEditorValue(
            "type",
            v as SystemConfigValue
          );
        } else if (typeof v === "object" && v !== null) {
          // 每个 ASR 类型保持嵌套
          (
            loadedConfig[groupKey] as unknown as Record<
              string,
              Record<string, ConfigValue>
            >
          )[k] = Object.fromEntries(
            Object.entries(v as Record<string, SystemConfigValue>).map(
              ([subK, subV]) => [subK, toEditorValue(subK, subV)]
            )
          );
        }
      }
    } else {
      fields = Object.entries(section).map(([fieldKey, value]) => {
        const selectOptions = SELECT_FIELD_OPTIONS[`${groupKey}.${fieldKey}`];
        return {
          key: fieldKey,
          label: translateFieldLabel(fieldKey),
          type: checkboxKeys.includes(fieldKey)
            ? ("checkbox" as const)
            : sensitiveKeys.includes(fieldKey)
              ? ("password" as const)
              : typeof value === "boolean"
                ? ("checkbox" as const)
                : selectOptions
                  ? ("select" as const)
                  : ("text" as const),
          ...(selectOptions
            ? { options: selectOptions, selectVariant: "dropdown" as const }
            : {})
        };
      });

      loadedConfig[groupKey] = Object.fromEntries(
        Object.entries(section).map(([fieldKey, value]) => [
          fieldKey,
          toEditorValue(fieldKey, value)
        ])
      );
    }

    return {
      key: groupKey,
      title: translateGroupTitle(groupKey),
      icon: getGroupIcon(groupKey),
      fields
    };
  });

  /** 保存一份独立快照，后续点击“重载”时恢复接口加载时的值 */
  originalConfig.value = Object.fromEntries(
    Object.entries(loadedConfig).map(([key, values]) => [key, { ...values }])
  );
  Object.keys(config).forEach(key => delete config[key]);
  Object.assign(config, loadedConfig);
  /** 默认定位到接口返回的第一个分组 */
  activeGroup.value = configGroups.value[0]?.key ?? "";
};

const router = useRouter();
const templateList = ref<AdminTemplateSummary[]>([]);
const templatesIcon = useRenderIcon("tabler:layout-list");

/** 静态「模板管理」分组：与动态 configGroups 同构，computed 保证 locale 切换重算 */
const templateGroup = computed<ConfigGroup>(() => ({
  key: "templates",
  title: translateGroupTitle("templates"),
  icon: templatesIcon,
  fields: []
}));

/** 侧边栏与卡片渲染用合并列表：动态分组在前，模板管理殿后 */
const allGroups = computed(() => [...configGroups.value, templateGroup.value]);

const loadTemplates = async () => {
  try {
    templateList.value = await listAdminTemplatesApi();
  } catch {
    templateList.value = [];
  }
};

const openTemplateEditor = (id?: string, copyFrom?: string) => {
  if (copyFrom)
    router.push({ path: "/system/templates/new", query: { copyFrom } });
  else if (id) router.push(`/system/templates/edit/${id}`);
  else router.push("/system/templates/new");
};

/** 列表里的更新时间：补零 + 去秒，别让 2026/8/29 16:11:23 这种裸 toLocaleString 吓到人 */
const formatTemplateTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
      })
    : "-";

const deleteTemplate = async (tpl: AdminTemplateSummary) => {
  try {
    await ElMessageBox.confirm(
      t("system.template.delete_confirm", { name: tpl.name }),
      { type: "warning" }
    );
  } catch {
    return; // 取消
  }
  const res = await deleteAdminTemplateApi(tpl.id).catch(e => e);
  if (res instanceof Error) {
    // HTTP 错误（409 被引用等）已由 axios 拦截器统一 toast，
    // 这里只兜底无响应的异常（断网），避免同一错误弹两次
    if (!(res as { response?: unknown }).response) {
      ElMessage.error(
        extractBackendError(res, t("system.template.delete_failed"))
      );
    }
    return;
  }
  if ((res as { ok?: boolean })?.ok !== true) {
    ElMessage.error(t("system.template.delete_failed"));
    return;
  }
  ElMessage.success(t("system.template.delete_success"));
  await loadTemplates();
};

const resetConfig = (key: string) => {
  config[key] = { ...(originalConfig.value[key] ?? {}) };
};

/** 设置配置卡片dom引用 */
const setConfigCardRef = (key: string, element: unknown) => {
  configCards.value[key] = element instanceof HTMLElement ? element : null;
};

/** 切换配置分组 */
const selectGroup = async (key: string) => {
  activeGroup.value = key;

  await nextTick();
  const targetCard = configCards.value[key];
  if (targetCard) {
    // 滚动到卡片offsetTop位置
    const stickyOffset = 28;
    const pageScrollWrap = document.querySelector<HTMLElement>(
      ".content-scroll .el-scrollbar__wrap"
    );
    let scrollWrap: HTMLElement | null =
      pageScrollWrap &&
      pageScrollWrap.scrollHeight > pageScrollWrap.clientHeight
        ? pageScrollWrap
        : (configScroll.value?.wrapRef?.value ?? null);
    while (
      scrollWrap &&
      scrollWrap.scrollHeight <= scrollWrap.clientHeight &&
      scrollWrap.parentElement
    ) {
      scrollWrap = scrollWrap.parentElement;
    }
    const targetTop = scrollWrap
      ? targetCard.getBoundingClientRect().top -
        scrollWrap.getBoundingClientRect().top +
        scrollWrap.scrollTop -
        stickyOffset
      : targetCard.offsetTop - stickyOffset;

    if (scrollWrap) {
      scrollWrap.scrollTop = Math.max(0, targetTop);
    } else {
      targetCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
};

const saveConfig = async (group: ConfigGroup) => {
  if (!userStore.accessToken) {
    ElMessage.warning("请先登录");
    useDialogStoreHook().openLogin();
    return;
  }

  let payload: Record<string, unknown>;

  if (group.key === "asr") {
    // ASR: 嵌套结构 { type, funasr_server: {...}, doubao_stream: {...} }
    payload = { type: config.asr?.type };
    const fieldKeys = asrTypeFieldKeys ?? {};
    for (const typeKey of Object.keys(fieldKeys)) {
      const fields: Record<string, unknown> = {};
      for (const fieldKey of fieldKeys[typeKey] ?? []) {
        let val = config.asr?.[typeKey]?.[fieldKey];
        if (typeof val === "boolean") val = val.toString();
        fields[fieldKey] = val;
      }
      payload[typeKey] = fields;
    }
  } else {
    // 其他分组：扁平 { key: value }
    payload = { ...config[group.key] };
    for (const key in payload) {
      if (typeof payload[key] === "boolean") {
        payload[key] = (payload[key] as boolean).toString();
      }
    }
  }

  // 仅把 PUT 调用本身包在 try 中：响应拦截器已对 response.status 弹 toast，
  // 此 catch 仅兜底断网 / 超时 / 取消 / 拦截器自身异常等无 response 的失败。
  let res: Awaited<
    ReturnType<typeof systemConfigSaveApi<Record<string, ConfigValue>>>
  >;
  try {
    res = await systemConfigSaveApi<Record<string, ConfigValue>>(
      group.key,
      payload as Record<string, ConfigValue>
    );
  } catch (err) {
    // 可验证约束：调用方必须保证 response.status 存在时已由拦截器 toast；
    // 否则此 catch 必须补一条错误反馈，禁止静默吞掉。
    if (!(err as { response?: unknown })?.response) {
      ElMessage.error(
        t("system.save_failed", {
          group: group.title,
          message: getErrorMessage(err)
        })
      );
    }
    console.warn("[system] saveConfig rejected without toast", err);
    return;
  }

  if (res.ok) {
    ElMessage.success(t("system.save_success"));
    // 本地刷新失败不应抹掉"保存成功"反馈，单独 try 兜底并给提示。
    try {
      await initCofig();
    } catch {
      ElMessage.warning(t("system.save_refresh_failed"));
    }
    // auth.allow_registration 改变后，把最新值喂给 permission store 以刷新
    // 「用户管理」菜单可见性；此 try 仅保护该同步，与 initCofig 完全独立。
    if (group.key === "auth") {
      try {
        const r = await registrationStatusApi();
        permissionStore.setRegistrationAllowed(r.allow_registration);
      } catch {
        /* 取值失败不阻塞保存成功的提示 */
      }
    }
  } else {
    ElMessage.error(
      t("system.save_failed", {
        group: group.title,
        message: getErrorMessage(res)
      })
    );
  }
};

const openSelfCheck = () => {
  if (!userStore.accessToken) {
    useDialogStoreHook().openLogin();
    return;
  }
  selfCheckVisible.value = true;
};

const getErrorMessage = (error: unknown) => {
  // 后端 I18nError 已在 detail 里返回精确文案；其它异常再退回到 message / 兜底。
  return extractBackendError(error, t("system.diagnostics.request_failed"));
};

const getOrCreateResult = (key: SelfCheckResult["key"]) => {
  const existing = selfCheckResults.find(result => result.key === key);
  if (existing) return existing;

  const result: SelfCheckResult = {
    key,
    titleKey:
      key === "asr"
        ? "system.diagnostics.asr"
        : key === "llm"
          ? "system.diagnostics.llm"
          : "system.diagnostics.ocr",
    description: t("system.diagnostics.running"),
    detail: "",
    duration: "-",
    status: "running"
  };
  selfCheckResults.push(result);
  return result;
};

/** 更新 ASR 接口结果 */
const updateAsrResult = (
  result: Awaited<ReturnType<typeof systemAsrDiagnosticsApi>>
) => {
  const target = getOrCreateResult("asr");

  target.status = result.ok ? "normal" : "error";
  target.description = result.message || t("system.diagnostics.asr_success");
  target.detail = t("system.diagnostics.transcription", {
    text: result.detail?.utterances?.join("、") || t("system.no_result")
  });
  target.sample =
    result.detail?.sample === "real"
      ? t("system.diagnostics.real_audio")
      : result.detail?.sample || "-";
  target.duration = `${result.latency_ms} ms`;
};

/** 更新 LLM 接口结果 */
const updateLlmResult = (
  result: Awaited<ReturnType<typeof systemLlmDiagnosticsApi>>
) => {
  const target = getOrCreateResult("llm");

  target.status = result.ok ? "normal" : "error";
  target.description = result.message || t("system.diagnostics.llm_success");
  target.detail = t("system.diagnostics.llm_reply", {
    text: result.detail?.reply || t("system.no_result")
  });
  target.duration = `${result.latency_ms} ms`;
  target.model = result.detail?.model || "-";
};

/** 更新 OCR 接口结果 */
const updateOcrResult = (
  result: Awaited<ReturnType<typeof systemOcrDiagnosticsApi>>
) => {
  const target = getOrCreateResult("ocr");

  target.status = result.ok ? "normal" : "error";
  target.description = result.message || t("system.diagnostics.ocr_success");
  target.detail = t("system.diagnostics.ocr_reply", {
    text: result.detail?.reply || t("system.no_result")
  });
  target.duration = `${result.latency_ms} ms`;
  target.model = result.detail?.model || "-";
};

/** 单项检测保留另一张卡片的位置；只有“运行全部”才会先清空整个结果列表 */
const setRunningState = (target: CheckTarget, status: CheckStatus) => {
  const keys: SelfCheckResult["key"][] =
    target === "all" ? ["asr", "llm", "ocr"] : [target];
  keys.forEach(key => {
    const result = getOrCreateResult(key);
    result.status = status;
    result.description = t("system.diagnostics.running");
    result.detail = "";
    result.duration = "";
    result.model = undefined;
    result.sample = undefined;
  });
};

/** 运行自检 */
const runSelfCheck = async (target: CheckTarget) => {
  if (selfCheckRunning.value || !userStore.accessToken) return;

  selfCheckTarget.value = target;
  selfCheckRunning.value = true;
  // 单项检测只重置当前项目，避免另一项结果被删除或改变顺序
  if (target === "all") {
    selfCheckResults.splice(0);
  }
  setRunningState(target, "running");

  try {
    if (target === "all") {
      const result = await systemDiagnosticsApi();
      updateAsrResult(result.asr);
      updateLlmResult(result.llm);
      updateOcrResult(result.ocr);
    } else if (target === "asr") {
      updateAsrResult(await systemAsrDiagnosticsApi());
    } else if (target === "llm") {
      updateLlmResult(await systemLlmDiagnosticsApi());
    } else {
      updateOcrResult(await systemOcrDiagnosticsApi());
    }

    const hasError = selfCheckResults.some(
      result =>
        (target === "all" || result.key === target) && result.status === "error"
    );
    if (hasError) {
      ElMessage.warning(t("system.diagnostics.partial_failure"));
    }
  } catch (error) {
    const message = getErrorMessage(error);
    selfCheckResults.forEach(result => {
      if (target === "all" || result.key === target) {
        result.status = "error";
        result.description = t("system.diagnostics.request_failed");
        result.detail = message;
        result.duration = "-";
      }
    });
    ElMessage.error(message);
  } finally {
    selfCheckRunning.value = false;
  }
};

/** 初始化配置 */
const initCofig = async () => {
  // 请求系统配置，再根据响应生成分组、字段和表单初始值
  const res = await systemConfigApi();
  buildConfigGroups(res);
  await loadTemplates();
};

watch(
  isLoggedIn,
  async (loggedIn: boolean) => {
    if (!loggedIn) {
      return;
    }
    await initCofig();
  },
  { immediate: true }
);

/** locale 切换时重算 title/label，原 configGroups 已缓存翻译后的字符串 */
watch(locale, () => {
  if (configGroups.value.length === 0) return;
  configGroups.value = configGroups.value.map(group => ({
    ...group,
    title: translateGroupTitle(group.key),
    fields: group.fields.map(field => ({
      ...field,
      label: translateFieldLabel(field.key)
    }))
  }));
});
</script>

<template>
  <div class="system">
    <header class="system-header">
      <div class="header-left">
        <h1 class="header-title">{{ t("system.title") }}</h1>
        <p class="header-subtitle">
          {{ t("system.save_hint") }}{{ t("system.sensitive_hint") }}
        </p>
      </div>
      <el-button
        plain
        class="self-check-button"
        :icon="icons.activity"
        @click="openSelfCheck"
      >
        {{ t("system.run_check") }}
      </el-button>
    </header>

    <div class="system-body">
      <aside v-if="configGroups.length > 0" class="config-groups">
        <el-scrollbar class="groups-scroll">
          <div class="groups-header">
            <span>{{ t("system.group_title") }}</span>
          </div>
          <div class="groups-list">
            <div
              v-for="group in allGroups"
              :key="group.key"
              class="group-item"
              :class="{ active: activeGroup === group.key }"
              :aria-current="activeGroup === group.key ? 'true' : undefined"
              @click="selectGroup(group.key)"
            >
              <component :is="group.icon" />
              <span>{{ group.title }}</span>
            </div>
          </div>
        </el-scrollbar>
      </aside>

      <el-scrollbar ref="configScroll" class="config-scroll">
        <main class="config-grid">
          <section
            v-for="group in allGroups"
            :id="`config-${group.key}`"
            :ref="element => setConfigCardRef(group.key, element)"
            :key="group.key"
            class="config-card"
            :data-group="group.key"
            :class="{ highlighted: activeGroup === group.key }"
          >
            <div class="card-title-row">
              <component :is="group.icon" class="card-icon" />
              <h2>{{ group.title }}</h2>
            </div>
            <!-- 模板管理卡片：列表 + 行内操作（非 KV 字段表单） -->
            <div
              v-if="group.key === 'templates'"
              class="template-list"
              data-testid="template-list"
            >
              <p class="template-hint">{{ t("system.template.hint") }}</p>
              <el-empty
                v-if="templateList.length === 0"
                :description="t('system.template.empty')"
                :image-size="72"
              />
              <div
                v-for="tpl in templateList"
                :key="tpl.id"
                class="template-row"
                :data-id="tpl.id"
              >
                <div class="tpl-info">
                  <div class="tpl-title-line">
                    <span class="tpl-name">{{ tpl.name }}</span>
                    <span class="tpl-version">v{{ tpl.version }}</span>
                  </div>
                  <span class="tpl-updated">
                    {{ t("system.template.updated_at") }}
                    {{ formatTemplateTime(tpl.updated_at) }}
                  </span>
                </div>
                <span class="tpl-actions">
                  <el-button
                    text
                    size="small"
                    data-action="edit"
                    @click="openTemplateEditor(tpl.id)"
                  >
                    {{ t("system.template.edit") }}
                  </el-button>
                  <el-button
                    text
                    size="small"
                    data-action="copy"
                    @click="openTemplateEditor(undefined, tpl.id)"
                  >
                    {{ t("system.template.copy") }}
                  </el-button>
                  <el-button
                    text
                    size="small"
                    type="danger"
                    data-action="delete"
                    @click="deleteTemplate(tpl)"
                  >
                    {{ t("system.template.delete") }}
                  </el-button>
                </span>
              </div>
            </div>
            <div v-else class="field-list">
              <template v-for="field in group.fields" :key="field.key">
                <label
                  v-if="
                    group.key !== 'asr' ||
                    field.key === 'type' ||
                    visibleAsrFieldKeys.includes(field.key)
                  "
                  class="field-row"
                >
                  <span class="field-label">{{ field.label }}</span>
                  <!-- select 类型：radio-button（紧凑 2~4 项）或 dropdown（5+ 项） -->
                  <template v-if="field.type === 'select'">
                    <div
                      v-if="field.selectVariant === 'radio'"
                      class="asr-type-radios"
                    >
                      <el-radio-group
                        v-model="config[group.key][field.key] as string"
                        size="small"
                      >
                        <el-radio-button
                          v-for="opt in field.options"
                          :key="opt.value"
                          :value="opt.value"
                        >
                          {{ opt.label }}
                        </el-radio-button>
                      </el-radio-group>
                    </div>
                    <el-select
                      v-else
                      :model-value="
                        getFieldValue(group.key, field.key) as string
                      "
                      class="field-input field-select"
                      :aria-label="field.label"
                      @update:model-value="
                        setFieldValue(
                          group.key,
                          field.key,
                          $event as ConfigValue
                        )
                      "
                    >
                      <el-option
                        v-for="opt in field.options ??
                        selectOptionsFor(group.key, field.key) ??
                        []"
                        :key="opt.value"
                        :value="opt.value"
                        :label="opt.labelKey ? t(opt.labelKey) : opt.label"
                      />
                    </el-select>
                  </template>
                  <el-input
                    v-else-if="field.type !== 'checkbox'"
                    :model-value="getFieldValue(group.key, field.key) as string"
                    :type="field.type ?? 'text'"
                    class="field-input"
                    :aria-label="field.label"
                    :placeholder="
                      sensitiveKeys.includes(field.key) ? '************' : ''
                    "
                    @update:model-value="
                      setFieldValue(group.key, field.key, $event as ConfigValue)
                    "
                  />
                  <el-checkbox
                    v-else
                    :model-value="getFieldValue(group.key, field.key)"
                    class="field-checkbox"
                    :aria-label="field.label"
                    @update:model-value="
                      setFieldValue(group.key, field.key, $event as ConfigValue)
                    "
                  />
                </label>
              </template>
            </div>
            <div class="card-actions">
              <!-- 模板卡片的主动作：新建模板（与其他卡片的保存按钮同位同款，底部居右） -->
              <el-button
                v-if="group.key === 'templates'"
                type="primary"
                class="save-button"
                data-action="new"
                @click="openTemplateEditor()"
              >
                {{ t("system.template.new") }}
              </el-button>
              <template v-else>
                <el-button class="reset-button" @click="resetConfig(group.key)">
                  {{ t("system.reload") }}
                </el-button>
                <el-button
                  type="primary"
                  class="save-button"
                  @click="saveConfig(group)"
                >
                  {{
                    t("system.save_group", {
                      group: group.title
                    })
                  }}
                </el-button>
              </template>
            </div>
          </section>
        </main>
      </el-scrollbar>
    </div>
  </div>

  <el-drawer
    v-model="selfCheckVisible"
    direction="rtl"
    size="min(100%, 620px)"
    :with-header="false"
    :teleported="false"
    class="self-check-drawer"
  >
    <div class="self-check-panel">
      <el-scrollbar class="self-check-scroll">
        <div class="self-check-panel-header">
          <div class="self-check-heading">
            <div class="self-check-title-row">
              <component :is="icons.activity" class="self-check-icon" />
              <h2>{{ t("system.run_check") }}</h2>
            </div>
            <p>
              {{ t("system.diagnostics.help") }}
            </p>
          </div>
          <el-button
            text
            circle
            class="self-check-close-button"
            :icon="icons.close"
            :title="t('system.close')"
            @click="selfCheckVisible = false"
          />
        </div>

        <div class="self-check-toolbar">
          <el-button
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'all'"
            @click="runSelfCheck('all')"
          >
            {{ t("system.run_all") }}
          </el-button>
          <el-button
            plain
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'asr'"
            @click="runSelfCheck('asr')"
          >
            {{ t("system.asr_only") }}
          </el-button>
          <el-button
            plain
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'llm'"
            @click="runSelfCheck('llm')"
          >
            {{ t("system.llm_only") }}
          </el-button>
          <el-button
            plain
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'ocr'"
            @click="runSelfCheck('ocr')"
          >
            {{ t("system.ocr_only") }}
          </el-button>
        </div>

        <div class="self-check-results">
          <el-empty
            v-if="!selfCheckResults.length"
            :description="t('system.no_result')"
            :image-size="88"
          />
          <template v-else>
            <el-card
              v-for="result in selfCheckResults"
              :key="result.key"
              shadow="never"
              class="self-check-card"
            >
              <div class="self-check-card-heading">
                <h3>{{ t(result.titleKey) }}</h3>
                <el-tag
                  size="small"
                  :type="
                    result.status === 'running'
                      ? 'warning'
                      : result.status === 'error'
                        ? 'danger'
                        : 'success'
                  "
                >
                  <el-icon v-if="result.status === 'normal'">
                    <component :is="icons.check" />
                  </el-icon>
                  {{
                    result.status === "running"
                      ? t("system.diagnostics.running")
                      : result.status === "error"
                        ? t("system.diagnostics.error")
                        : t("system.diagnostics.normal")
                  }}
                </el-tag>
                <span class="self-check-duration">{{ result.duration }}</span>
                <el-icon
                  v-if="result.status === 'running'"
                  class="is-loading self-check-loading-icon"
                >
                  <component :is="icons.loading" />
                </el-icon>
              </div>
              <strong>{{ result.description }}</strong>
              <p>{{ result.detail }}</p>
              <p v-if="result.sample">
                {{ t("system.diagnostics.sample") }}：{{ result.sample }}
              </p>
              <p v-if="result.model" class="self-check-model">
                {{ t("system.diagnostics.model") }}：{{ result.model }}
              </p>
            </el-card>
          </template>
        </div>
      </el-scrollbar>
    </div>
  </el-drawer>
</template>

<style lang="scss" scoped>
.system {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 30px 8px 0 16px;
  overflow: visible;
  container-type: inline-size;

  &-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    flex-shrink: 0;
    padding: 8px 16px 20px;
  }

  &-body {
    display: flex;
    flex: 1;
    min-height: 0;
  }

  .header {
    &-title {
      margin: 0;
      color: #1a1a1a;
      font-size: 28px;
      font-weight: 600;
    }

    &-subtitle {
      margin: 6px 0 0;
      color: #718096;
      font-size: 14px;
      line-height: 1.5;
    }
  }

  .self-check-button {
    flex-shrink: 0;
    margin-bottom: 1px;
    border-radius: 8px;
  }

  .self-check-drawer {
    top: 16px;
    right: 16px;
    bottom: 16px;
    width: min(100%, 620px);
    height: auto;
    padding: 16px;
    box-sizing: border-box;
    background: transparent;
    box-shadow: none;
    overflow: visible;

    :deep(.el-drawer__body) {
      padding: 0;
      overflow: hidden;
    }
  }

  .self-check-panel {
    height: 100%;
    min-height: 0;
    padding: 28px 24px 32px;
    box-sizing: border-box;
    background: #fff;
    border-radius: 16px;
    box-shadow: 0 12px 32px rgb(31 41 55 / 16%);
    overflow: auto;
  }

  .self-check-panel-header {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    justify-content: space-between;
    position: relative;
    padding-right: 8px;
    box-sizing: border-box;
  }

  .self-check-close-button {
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    color: #718096;
    font-size: 18px;
  }

  .self-check-heading {
    .self-check-title-row {
      display: flex;
      gap: 10px;
      align-items: center;
    }

    h2 {
      margin: 0;
      color: #3988ee;
      font-size: 22px;
      font-weight: 600;
    }

    p {
      max-width: 560px;
      margin: 12px 0 0;
      color: #718096;
      font-size: 14px;
      line-height: 1.65;
    }
  }

  .self-check-icon {
    width: 22px;
    height: 22px;
    color: #3988ee;
  }

  .self-check-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    margin-top: 20px;

    .el-button {
      margin: 0;
      border-radius: 8px;
    }
  }

  .self-check-summary {
    display: inline-flex;
    gap: 5px;
    align-items: center;
    color: #718096;
    font-size: 14px;
  }

  .self-check-check-icon {
    width: 16px;
    height: 16px;
    color: #67c23a;

    &.running {
      color: #e6a23c;
    }
  }

  .self-check-results {
    display: grid;
    gap: 14px;
    margin-top: 20px;
  }

  .self-check-card {
    border-color: #e9eef5;
    border-radius: 10px;
    background: #fff;

    :deep(.el-card__body) {
      padding: 18px 16px;
    }

    .self-check-card-heading {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }

    h3 {
      margin: 0;
      color: #1f2937;
      font-size: 18px;
      font-weight: 600;
    }

    strong {
      display: block;
      margin-top: 12px;
      color: #1f2937;
      font-size: 14px;
    }

    p {
      margin: 6px 0 0;
      color: #718096;
      font-size: 14px;
      line-height: 1.65;
      overflow-wrap: anywhere;
    }
  }

  .self-check-duration {
    color: #718096;
    font-size: 14px;
  }

  .self-check-model {
    margin-top: 10px !important;
  }

  .config {
    &-groups,
    &-card {
      box-sizing: border-box;
      border: 1px solid rgb(255 255 255 / 75%);
      border-radius: 16px;
      background: rgb(255 255 255 / 65%);
      box-shadow: 0 0 10px rgb(0 0 0 / 8%);
      backdrop-filter: blur(4px);
    }

    &-groups {
      flex: 0 0 228px;
      align-self: flex-start;
      height: fit-content;
      min-height: 0;
      margin-bottom: 24px;
      padding: 18px 0;
      position: sticky;
      top: 24px;
    }

    &-scroll {
      flex: 1;
      height: auto;
      min-width: 0;
      min-height: 0;

      :deep(.el-scrollbar__wrap) {
        overflow: visible;
      }

      :deep(.el-scrollbar__view) {
        padding: 0 8px 0 16px;
        margin-bottom: 24px;
      }
    }

    &-grid {
      display: grid;
      flex: 1;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      // 行高取 max(300px, 内容高)：模板管理卡片内容长也不会把同网格其它
      // 卡片一起撑高（align-items: start 配合，避免 1fr 等高带来的大面积空白）
      grid-auto-rows: minmax(300px, auto);
      align-items: start;
      gap: 16px;
      min-width: 0;
      min-height: 100%;
    }

    &-card {
      display: flex;
      flex-direction: column;
      min-height: 0;
      padding: 14px 20px;
      transition:
        border-color 0.2s ease,
        box-shadow 0.2s ease,
        transform 0.2s ease;

      &.highlighted {
        border-color: #5a9df5;
        box-shadow:
          0 0 0 2px rgb(90 157 245 / 15%),
          0 8px 18px rgb(64 158 255 / 16%);
        animation: config-card-highlight 0.45s ease-out;
      }
    }
  }

  .groups {
    &-scroll {
      height: auto;

      :deep(.el-scrollbar__wrap) {
        overflow-x: hidden;
      }

      :deep(.el-scrollbar__view) {
        min-height: 100%;
        padding: 0 16px;
      }
    }

    &-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
      color: #344054;
      font-size: 14px;
      font-weight: 600;
    }

    &-list {
      display: grid;
      gap: 10px;
      margin-top: 20px;
    }
  }

  .text-action,
  .new-config-button {
    display: flex;
    gap: 5px;
    align-items: center;
    color: #3988ee;
    font-size: 13px;
    cursor: pointer;
    background: transparent;
    border: 0;

    :deep(svg) {
      width: 16px;
      height: 16px;
    }
  }

  .text-action {
    min-height: auto;
    padding: 0;
  }

  .group-item {
    position: relative;
    display: flex;
    width: 100%;
    gap: 12px;
    align-items: center;
    min-height: 43px;
    padding: 0 14px;
    color: #667085;
    font-size: 14px;
    text-align: left;
    cursor: pointer;
    background: rgb(255 255 255 / 35%);
    border: 1px solid rgb(230 235 244 / 65%);
    border-radius: 8px;
    transition: 0.2s ease;

    &::before {
      position: absolute;
      left: -1px;
      width: 3px;
      height: 0;
      content: "";
      background: #3988ee;
      border-radius: 0 3px 3px 0;
      transition: height 0.2s ease;
    }

    svg {
      width: 17px;
      height: 17px;
    }

    &:hover,
    &.active,
    &.is-active {
      color: #3988ee;
      background: rgb(232 241 255 / 75%);
      border-color: #5a9df5;
    }

    &.active::before {
      height: 22px;
    }
  }

  .new-config-button {
    width: 100%;
    justify-content: flex-start;
    min-height: 44px;
    padding: 0 14px;
    border: 1px dashed #a9c9f7;
    border-radius: 8px;
  }

  .card {
    &-title-row {
      display: flex;
      flex-shrink: 0;
      gap: 8px;
      align-items: center;
      color: #3988ee;

      h2 {
        margin: 0;
        font-size: 17px;
        font-weight: 600;
      }
    }

    &-icon {
      width: 18px;
      height: 18px;
    }

    &-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      align-items: center;
      margin-top: auto;
      padding-top: 8px;
    }
  }

  .template {
    &-list {
      display: grid;
      gap: 10px;
      max-height: 480px;
      margin-top: 16px;
      overflow-y: auto;
    }

    &-hint {
      margin: 0;
      color: #667085;
      font-size: 12px;
      line-height: 1.5;
    }

    /* 名称+版本 / 更新时间 | 操作 两栏：主体信息与操作分居两侧 */
    &-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 10px 14px;
      background: rgb(255 255 255 / 65%);
      border: 1px solid #e9eef5;
      border-radius: 12px;
      transition:
        border-color 0.2s,
        box-shadow 0.2s;

      &:hover {
        border-color: #b6d4f5;
        box-shadow: 0 2px 8px rgb(57 136 238 / 10%);
      }
    }
  }

  .tpl {
    &-info {
      min-width: 0;
    }

    &-title-line {
      display: flex;
      gap: 8px;
      align-items: center;
    }

    &-name {
      overflow: hidden;
      color: #1a2233;
      font-size: 14px;
      font-weight: 600;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    &-version {
      flex-shrink: 0;
      padding: 0 7px;
      color: #5b8ac7;
      font-size: 11px;
      line-height: 18px;
      background: #eef5fd;
      border-radius: 999px;
    }

    &-updated {
      display: block;
      margin-top: 2px;
      color: #98a2b3;
      font-size: 12px;
    }

    &-actions {
      display: inline-flex;
      gap: 2px;
      align-items: center;
    }
  }

  .field {
    &-list {
      display: grid;
      gap: 6px;
      margin-top: 16px;
    }

    &-row {
      display: grid;
      grid-template-columns: 132px minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      min-height: 26px;
    }

    &-label {
      overflow: visible;
      color: #667085;
      font-size: 12px;
      line-height: 1.25;
      overflow-wrap: anywhere;
      white-space: normal;
    }

    &-input {
      box-sizing: border-box;
      width: 100%;
      height: 28px;
      color: #344054;
      font-size: 12px;
      outline: none;
      background: rgb(255 255 255 / 48%);
      border: 1px solid #dfe5ee;
      border-radius: 6px;
      transition: 0.2s ease;

      :deep(.el-input__wrapper) {
        min-height: 28px;
        padding: 0 12px;
        background: rgb(255 255 255 / 48%);
        border: 1px solid #dfe5ee;
        border-radius: 6px;
        box-shadow: none;

        &.is-focus {
          background: #fff;
          border-color: #5a9df5;
          box-shadow: 0 0 0 2px rgb(64 158 255 / 12%);
        }
      }

      :deep(.el-input__inner) {
        height: 28px;
        color: #344054;
        font-size: 12px;
      }

      &:focus {
        background: #fff;
        border-color: #5a9df5;
        box-shadow: 0 0 0 2px rgb(64 158 255 / 12%);
      }
    }

    /* el-select 内部覆盖：高度与 el-input 对齐（28px），字号与其他输入框一致（12px）。
     * el-select 默认 wrapper min-height ~32px、字号 14px，单独压不住父容器。 */
    &-select {
      :deep(.el-select__wrapper) {
        min-height: 28px;
        height: 28px;
        padding: 0 12px;
        background: rgb(255 255 255 / 48%);
        border: 1px solid #dfe5ee;
        border-radius: 6px;
        box-shadow: none;

        &.is-focused,
        &.is-hovering:not(.is-disabled) {
          background: #fff;
          border-color: #5a9df5;
          box-shadow: 0 0 0 2px rgb(64 158 255 / 12%);
        }
      }

      :deep(.el-select__selected-item),
      :deep(.el-select__placeholder),
      :deep(.el-select__input) {
        height: 28px;
        line-height: 28px;
        color: #344054;
        font-size: 12px;
      }
    }

    &-checkbox {
      margin: 0;

      :deep(.el-checkbox__label) {
        display: none;
      }
    }

    &-radios {
      display: flex;
      align-items: center;

      :deep(.el-radio-group) {
        flex-wrap: wrap;
        gap: 4px;
      }

      :deep(.el-radio-button__inner) {
        height: 26px;
        padding: 0 10px;
        font-size: 12px;
        border-radius: 6px;
      }
    }
  }

  .save-button,
  .reset-button {
    height: 28px;
    margin: 0;
    padding: 0 13px;
    font-size: 12px;
    cursor: pointer;
    border-radius: 8px;
    transition: 0.2s ease;
  }

  .save-button {
    color: #fff;
    background: #409eff;
    border: 1px solid #409eff;

    &:hover {
      background: #66b1ff;
      border-color: #66b1ff;
    }
  }

  .reset-button {
    color: #667085;
    background: rgb(255 255 255 / 55%);
    border: 1px solid #cbd5e1;

    &:hover {
      color: #3988ee;
      border-color: #8dbcf5;
    }
  }
}

/* Element Plus renders the drawer shell outside the page's scoped layout. */
:global(.self-check-drawer) {
  position: fixed !important;
  top: 24px !important;
  right: 16px !important;
  bottom: 24px !important;
  left: auto !important;
  width: min(calc(100vw - 32px), 620px) !important;
  height: auto !important;
  padding: 0 !important;
  box-sizing: border-box !important;
  background: transparent !important;
  box-shadow: none !important;
  overflow: visible !important;
}

:global(.self-check-drawer .el-drawer__body) {
  padding: 0 !important;
  overflow: hidden !important;
}

:global(.self-check-drawer .self-check-panel) {
  height: 100%;
  min-height: 0;
  padding: 28px 24px 32px;
  box-sizing: border-box;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 12px 32px rgb(31 41 55 / 16%);
  overflow: hidden;
}

:global(.self-check-drawer .self-check-scroll) {
  height: 100%;
}

:global(.self-check-drawer .self-check-scroll .el-scrollbar__wrap) {
  overflow-x: hidden !important;
}

:global(.self-check-drawer .self-check-scroll .el-scrollbar__view) {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

:global(
  .self-check-drawer .self-check-scroll .el-scrollbar__bar.is-horizontal
) {
  display: none !important;
}

:global(.self-check-drawer .self-check-panel-header) {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  position: relative;
  padding-right: 8px;
  box-sizing: border-box;
}

:global(.self-check-drawer .self-check-title-row) {
  display: flex;
  gap: 10px;
  align-items: center;
}

:global(.self-check-drawer .self-check-heading h2) {
  margin: 0;
  color: #3988ee;
  font-size: 22px;
  font-weight: 600;
}

:global(.self-check-drawer .self-check-heading p) {
  max-width: 560px;
  margin: 12px 0 0;
  color: #718096;
  font-size: 14px;
  line-height: 1.65;
}

:global(.self-check-drawer .self-check-icon) {
  width: 22px;
  height: 22px;
  color: #3988ee;
}

:global(.self-check-drawer .self-check-close-button) {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  color: #718096;
  font-size: 18px;

  &:not(.is-disabled):hover {
    background: transparent !important;
  }
}

:global(.self-check-drawer .self-check-toolbar) {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 20px;
}

:global(.self-check-drawer .self-check-toolbar .el-button) {
  margin: 0;
  border-radius: 8px;
}

:global(.self-check-drawer .self-check-summary) {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  color: #718096;
  font-size: 14px;
}

:global(.self-check-drawer .self-check-check-icon) {
  width: 16px;
  height: 16px;
  color: #67c23a;
}

:global(.self-check-drawer .self-check-check-icon.running) {
  color: #e6a23c;
}

:global(.self-check-drawer .self-check-check-icon.error) {
  color: #f56c6c;
}

:global(.self-check-drawer .self-check-check-icon.idle) {
  color: #909399;
}

:global(.self-check-drawer .self-check-loading-icon) {
  width: 16px;
  height: 16px;
  color: #409eff;
}

:global(.self-check-drawer .self-check-card .self-check-loading-icon) {
  margin-left: -6px;
}

:global(.self-check-drawer .self-check-results) {
  display: grid;
  gap: 14px;
  margin-top: 20px;
}

:global(.self-check-drawer .self-check-card) {
  border-color: #e9eef5;
  border-radius: 10px;
  background: #fff;
}

:global(.self-check-drawer .self-check-card .el-card__body) {
  padding: 18px 16px;
}

:global(.self-check-drawer .self-check-card-heading) {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

:global(.self-check-drawer .self-check-card h3) {
  margin: 0;
  color: #1f2937;
  font-size: 18px;
  font-weight: 600;
}

:global(.self-check-drawer .self-check-card strong) {
  display: block;
  margin-top: 12px;
  color: #1f2937;
  font-size: 14px;
}

:global(.self-check-drawer .self-check-card p) {
  margin: 6px 0 0;
  color: #718096;
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

:global(.self-check-drawer .self-check-duration) {
  color: #718096;
  font-size: 14px;
}

:global(.self-check-drawer .self-check-model) {
  margin-top: 10px !important;
}

@media (max-width: 520px) {
  :global(.self-check-drawer) {
    top: 16px !important;
    right: 12px !important;
    bottom: 16px !important;
    left: auto !important;
    width: calc(100vw - 24px) !important;
    padding: 0 !important;
  }

  :global(.self-check-drawer .self-check-panel) {
    padding: 22px 16px 28px;
  }

  :global(.self-check-drawer .self-check-heading p) {
    font-size: 13px;
  }

  :global(.self-check-drawer .self-check-card .el-card__body) {
    padding: 16px 14px;
  }

  :global(.self-check-drawer .self-check-card h3) {
    font-size: 16px;
  }
}

@keyframes config-card-highlight {
  0% {
    transform: translateY(4px);
    box-shadow:
      0 0 0 4px rgb(90 157 245 / 24%),
      0 10px 24px rgb(64 158 255 / 22%);
  }

  100% {
    transform: translateY(0);
  }
}

@media (max-width: 760px) {
  .system {
    padding: 20px 12px 12px;

    &-header {
      align-items: flex-start;
      flex-direction: column;
      padding: 0 8px 16px;
    }

    &-body {
      flex-direction: column;
      overflow: hidden;
    }

    .header {
      &-title {
        font-size: 24px;
      }

      &-subtitle {
        font-size: 12px;
      }
    }

    .self-check-button {
      align-self: flex-end;
    }

    .config {
      &-groups {
        flex: 0 0 auto;
        align-self: stretch;
        width: auto;
        max-height: 220px;
        margin-right: 8px;
        margin-left: 8px;
        padding: 14px;
        position: static;
      }

      &-grid {
        flex: none;
        grid-template-columns: 1fr;
        grid-auto-rows: auto;
      }

      &-scroll {
        flex: 1;
        height: 100%;

        :deep(.el-scrollbar__view) {
          padding-right: 8px;
          padding-left: 8px;
        }
      }

      &-card {
        min-height: 300px;
      }
    }

    .groups {
      &-scroll {
        height: 190px;
      }

      &-list {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        margin-top: 12px;
      }
    }

    .group-item,
    .new-config-button {
      min-height: 38px;
      padding: 0 10px;
    }
  }
}

@media (max-width: 520px) {
  .system {
    .groups-list {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .field-row {
      grid-template-columns: minmax(116px, 38%) minmax(0, 1fr);
      gap: 8px;
    }
  }

  :global(.self-check-drawer) {
    top: 12px;
    right: 12px;
    bottom: 12px;
    width: calc(100% - 24px) !important;
    height: auto;
    padding: 12px;
  }

  .self-check-panel {
    padding: 22px 16px 28px;
  }

  .self-check-heading p {
    font-size: 13px;
  }

  .self-check-card {
    :deep(.el-card__body) {
      padding: 16px 14px;
    }

    h3 {
      font-size: 16px;
    }
  }
}
</style>
