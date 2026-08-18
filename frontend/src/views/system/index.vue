<script setup lang="ts">
import { ElMessage } from "element-plus";
import { computed, nextTick, reactive, ref, watch } from "vue";
import { useUserStoreHook } from "@/store/modules/user";
import { useDialogStoreHook } from "@/store/modules/dialog";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import {
  systemConfigApi,
  type SystemConfig,
  type SystemConfigValue,
  systemDiagnosticsApi,
  systemAsrDiagnosticsApi,
  systemLlmDiagnosticsApi,
  systemConfigSaveApi
} from "@/api/system";

defineOptions({
  name: "SystemConfig"
});

/** 页面编辑器使用的配置项值 */
type ConfigValue = string | boolean;
type ConfigField = {
  /** 配置项key */
  key: string;
  /** 配置项label */
  label: string;
  /** 配置项类型 */
  type?: "text" | "password" | "checkbox";
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
type CheckTarget = "all" | "asr" | "llm";
type CheckStatus = "normal" | "running" | "error";

/** 自检结果 */
type SelfCheckResult = {
  key: Exclude<CheckTarget, "all">;
  title: string;
  description: string;
  detail: string;
  duration: string;
  model?: string;
  sample?: string;
  status: CheckStatus;
};

const userStore = useUserStoreHook();

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
const sensitiveKeys = ["api_key"];
/** 复选框字段 */
const checkboxKeys = ["ws_verify_ssl"];

/** 是否已登录 */
const isLoggedIn = computed(() => Boolean(userStore.accessToken));

/** 是否为配置分组 */
const isConfigSection = (
  value: SystemConfigValue | SystemConfig["llm"]
): value is Record<string, SystemConfigValue> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/** 将后端值转换为表单可编辑的值 */
const toEditorValue = (key: string, value: SystemConfigValue): ConfigValue => {
  if (typeof value === "boolean") return value;
  if (checkboxKeys.includes(key)) return value === "true";
  return value == null ? "" : String(value);
};

/** 获取配置分组图标 */
const getGroupIcon = (key: string) =>
  icons[key as keyof typeof icons] ?? useRenderIcon("tabler:settings");

const buildConfigGroups = (data: SystemConfig) => {
  const loadedConfig: Record<string, Record<string, ConfigValue>> = {};

  /** 根据实际响应动态生成分组，因此后端缺少或新增分组时页面都能正常展示。 */
  const groups = Object.entries(data).filter(([, section]) =>
    isConfigSection(section)
  );

  configGroups.value = groups.map(([groupKey, section]) => {
    /** 配置分组字段 */
    const fields = Object.entries(section).map(([fieldKey, value]) => ({
      key: fieldKey,
      label: fieldKey,
      type: checkboxKeys.includes(fieldKey)
        ? ("checkbox" as const)
        : sensitiveKeys.includes(fieldKey)
          ? ("password" as const)
          : typeof value === "boolean"
            ? ("checkbox" as const)
            : ("text" as const)
    }));

    loadedConfig[groupKey] = Object.fromEntries(
      Object.entries(section).map(([fieldKey, value]) => [
        fieldKey,
        toEditorValue(fieldKey, value)
      ])
    );

    return {
      key: groupKey,
      title: groupKey,
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

  const singleConfig = { ...config[group.key] };
  /** 转换 boolean 类型为字符串 */
  for (let key in singleConfig) {
    if (typeof singleConfig[key] === "boolean") {
      singleConfig[key] = singleConfig[key].toString();
    }
  }

  const res = await systemConfigSaveApi<Record<string, ConfigValue>>(
    group.key,
    singleConfig
  );
  if (res.ok) {
    ElMessage.success(`已保存，下一次请求生效`);
    await initCofig();
  } else {
    ElMessage.error(`保存 ${group.title} 配置失败：${getErrorMessage(res)}`);
  }
};

const openSelfCheck = () => {
  if (!userStore.accessToken) {
    ElMessage({
      message: "请先登录",
      type: "warning"
    });
    useDialogStoreHook().openLogin();
    return;
  }
  selfCheckVisible.value = true;
};

const getErrorMessage = (error: unknown) => {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "object" && error !== null && "message" in error) {
    return String(error.message);
  }
  return "诊断接口请求失败";
};

const getOrCreateResult = (key: SelfCheckResult["key"]) => {
  const existing = selfCheckResults.find(result => result.key === key);
  if (existing) return existing;

  const result: SelfCheckResult = {
    key,
    title: key === "asr" ? "ASR 语音识别" : "LLM 大语言模型",
    description: "正在检测",
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
  target.description = result.message || "ASR 连通 + 转写成功";
  target.detail = `转写：${result.detail?.utterances?.join("、") || "无返回内容"}`;
  target.sample =
    result.detail?.sample === "real"
      ? "真实音频"
      : result.detail?.sample || "-";
  target.duration = `${result.latency_ms} ms`;
};

/** 更新 LLM 接口结果 */
const updateLlmResult = (
  result: Awaited<ReturnType<typeof systemLlmDiagnosticsApi>>
) => {
  const target = getOrCreateResult("llm");

  target.status = result.ok ? "normal" : "error";
  target.description = result.message || "LLM 连接 + 返回完成";
  target.detail = `LLM 回复：${result.detail?.reply || "无返回内容"}`;
  target.duration = `${result.latency_ms} ms`;
  target.model = result.detail?.model || "-";
};

/** 单项检测保留另一张卡片的位置；只有“运行全部”才会先清空整个结果列表 */
const setRunningState = (target: CheckTarget, status: CheckStatus) => {
  const keys: SelfCheckResult["key"][] =
    target === "all" ? ["asr", "llm"] : [target];
  keys.forEach(key => {
    const result = getOrCreateResult(key);
    result.status = status;
    result.description = "正在检测";
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
    } else if (target === "asr") {
      updateAsrResult(await systemAsrDiagnosticsApi());
    } else {
      updateLlmResult(await systemLlmDiagnosticsApi());
    }

    const hasError = selfCheckResults.some(
      result =>
        (target === "all" || result.key === target) && result.status === "error"
    );
    if (hasError) {
      ElMessage.warning("自检完成，但部分服务异常");
    }
  } catch (error) {
    const message = getErrorMessage(error);
    selfCheckResults.forEach(result => {
      if (target === "all" || result.key === target) {
        result.status = "error";
        result.description = "诊断接口请求失败";
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
</script>

<template>
  <div class="system">
    <header class="system-header">
      <div class="header-left">
        <h1 class="header-title">后端配置</h1>
        <p class="header-subtitle">
          修改后点击【保存】立即生效（LLM/ASR 客户端会自动重载）。敏感字段显示为
          ************，留空 = 保留原值。
        </p>
      </div>
      <el-button
        plain
        class="self-check-button"
        :icon="icons.activity"
        @click="openSelfCheck"
      >
        运行自检
      </el-button>
    </header>

    <div class="system-body">
      <aside v-if="configGroups.length > 0" class="config-groups">
        <el-scrollbar class="groups-scroll">
          <div class="groups-header">
            <span>配置分组</span>
          </div>
          <div class="groups-list">
            <div
              v-for="group in configGroups"
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
            v-for="group in configGroups"
            :id="`config-${group.key}`"
            :ref="element => setConfigCardRef(group.key, element)"
            :key="group.key"
            class="config-card"
            :class="{ highlighted: activeGroup === group.key }"
          >
            <div class="card-title-row">
              <component :is="group.icon" class="card-icon" />
              <h2>{{ group.title }}</h2>
            </div>
            <div class="field-list">
              <label
                v-for="field in group.fields"
                :key="field.key"
                class="field-row"
              >
                <span class="field-label">{{ field.label }}</span>
                <el-input
                  v-if="field.type !== 'checkbox'"
                  v-model="config[group.key][field.key] as string"
                  :type="field.type ?? 'text'"
                  class="field-input"
                  :aria-label="field.label"
                  :placeholder="
                    sensitiveKeys.includes(field.key) ? '************' : ''
                  "
                />
                <el-checkbox
                  v-else
                  v-model="config[group.key][field.key]"
                  class="field-checkbox"
                  :aria-label="field.label"
                />
              </label>
            </div>
            <div class="card-actions">
              <el-button class="reset-button" @click="resetConfig(group.key)">
                重载
              </el-button>
              <el-button
                type="primary"
                class="save-button"
                @click="saveConfig(group)"
              >
                保存 {{ group.title }}
              </el-button>
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
              <h2>运行自检</h2>
            </div>
            <p>
              点这里测试整套服务是否正常：ASR 连通 + 转写，LLM 连通 + 回复。
              部署后建议先跑一遍，发现问题不用等到真正访谈时才发现。
            </p>
          </div>
          <el-button
            text
            circle
            class="self-check-close-button"
            :icon="icons.close"
            title="关闭"
            @click="selfCheckVisible = false"
          />
        </div>

        <div class="self-check-toolbar">
          <el-button
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'all'"
            @click="runSelfCheck('all')"
          >
            运行全部
          </el-button>
          <el-button
            plain
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'asr'"
            @click="runSelfCheck('asr')"
          >
            仅 ASR
          </el-button>
          <el-button
            plain
            type="primary"
            :loading="selfCheckRunning && selfCheckTarget === 'llm'"
            @click="runSelfCheck('llm')"
          >
            仅 LLM
          </el-button>
        </div>

        <div class="self-check-results">
          <el-empty
            v-if="!selfCheckResults.length"
            description="暂无检测结果"
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
                <h3>{{ result.title }}</h3>
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
                      ? "检测中"
                      : result.status === "error"
                        ? "异常"
                        : "正常"
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
              <p v-if="result.sample">样本：{{ result.sample }}</p>
              <p v-if="result.model" class="self-check-model">
                模型：{{ result.model }}
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
    padding: 0 16px 20px;
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
  }

  .self-check-close-button {
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    margin: -4px -8px 0 0;
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
      margin-bottom: 6px;
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
        margin-bottom: 6px;
      }
    }

    &-grid {
      display: grid;
      flex: 1;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-auto-rows: minmax(300px, 1fr);
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

    &-checkbox {
      margin: 0;

      :deep(.el-checkbox__label) {
        display: none;
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
  margin: -4px -8px 0 0;
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
