<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import Plus from "~icons/ep/plus";
import ChatDotRound from "~icons/ep/chat-dot-round";
import EditPen from "~icons/ep/edit-pen";
import RefreshLeft from "~icons/ep/refresh-left";
import Delete from "~icons/ep/delete";
import Download from "~icons/ep/download";
import { ElMessageBox } from "element-plus";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import LayFooter from "@/layout/components/lay-footer/index.vue";

defineOptions({
  name: "InterviewPage"
});

const router = useRouter();
const route = useRoute();
const backIcon = useRenderIcon("heroicons:arrow-long-left");
const eraserIcon = useRenderIcon("boxicons:eraser-filled");
const handwritingIcon = useRenderIcon("boxicons:pencil-draw");
const ignoreIcon = useRenderIcon("lucide:eye-off");
const aiLineIcon = useRenderIcon("si:ai-line");

const baseInterviewTitle = computed(() => {
  const title = route.query.title;
  if (typeof title === "string" && title.trim()) return title.trim();
  return "访谈";
});

const activeMode = ref("转录");
const activeMetric = ref("待追问");
const noteContent = ref("");
const signatureRef = ref();
const brushColorPresets = [
  "#1f2937",
  "#3b82f6",
  "#ef4444",
  "#10b981",
  "#f59e0b"
];
const selectedBrushColor = ref(brushColorPresets[0]);
const isEraserMode = ref(false);
const penStrokeWidth = 2.6;
const eraserStrokeWidth = 8;
const signatureOptions = computed(() => ({
  penColor: selectedBrushColor.value,
  backgroundColor: "rgb(255, 255, 255)",
  minWidth: isEraserMode.value ? eraserStrokeWidth : penStrokeWidth,
  maxWidth: isEraserMode.value ? eraserStrokeWidth : penStrokeWidth,
  throttle: 12,
  minDistance: 5,
  compositeOperation: isEraserMode.value ? "destination-out" : "source-over"
}));

const noteInputRef = ref();

type SuggestionCard = {
  index: number;
  title: string;
  tag: string;
  tagClass: string;
  status: "待追问" | "已覆盖" | "已忽略";
  goal: string;
  hint: string;
  ignoreCountdown: number | null;
  ignoreIntervalId: number | null;
  ignoreTimeoutId: number | null;
};

const suggestionCards = ref<SuggestionCard[]>([
  {
    index: 4,
    title: "既往用药依从性与血压监测",
    tag: "已覆盖",
    tagClass: "success",
    status: "已覆盖",
    goal: "已完成追问：确认长期用药与居家监测情况",
    hint: "患者表示规律服药，已说明近期血压波动与自测记录",
    ignoreCountdown: null,
    ignoreIntervalId: null,
    ignoreTimeoutId: null
  },
  {
    index: 5,
    title: "诱因分析（情绪/睡眠/饮食）",
    tag: "待追问",
    tagClass: "warning",
    status: "待追问",
    goal: "追问目的：寻找血压升高可逆因素",
    hint: "已提及睡眠不佳与家中琐事，需深入了解",
    ignoreCountdown: null,
    ignoreIntervalId: null,
    ignoreTimeoutId: null
  },
  {
    index: 6,
    title: "体格检查与辅助检查",
    tag: "待追问",
    tagClass: "warning",
    status: "待追问",
    goal: "追问目的：完善诊断依据",
    hint: "需测量坐位血压、心率，建议查肾功能电解质",
    ignoreCountdown: null,
    ignoreIntervalId: null,
    ignoreTimeoutId: null
  },
  {
    index: 7,
    title: "治疗方案调整与随访计划",
    tag: "待追问",
    tagClass: "warning",
    status: "待追问",
    goal: "追问目的：制定下一步治疗方案",
    hint: "待体格检查后综合判断",
    ignoreCountdown: null,
    ignoreIntervalId: null,
    ignoreTimeoutId: null
  }
]);

const suggestionListAnimationEnabled = ref(true);
let suggestionMetricAnimationToken = 0;

const interviewElapsedSeconds = ref(0);
let interviewTimerId: number | null = null;

const formatInterviewElapsedTime = (totalSeconds: number) => {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return [hours, minutes, seconds]
    .map(value => String(value).padStart(2, "0"))
    .join(":");
};

const transcribingElapsedTime = computed(() =>
  formatInterviewElapsedTime(interviewElapsedSeconds.value)
);

const stopInterviewTimer = () => {
  if (interviewTimerId !== null) {
    window.clearInterval(interviewTimerId);
    interviewTimerId = null;
  }
};

const startInterviewTimer = () => {
  stopInterviewTimer();
  interviewElapsedSeconds.value = 0;
  interviewTimerId = window.setInterval(() => {
    interviewElapsedSeconds.value += 1;
  }, 1000);
};

const metrics = computed(() => {
  const counts = suggestionCards.value.reduce(
    (acc, item) => {
      acc[item.status] = (acc[item.status] ?? 0) + 1;
      return acc;
    },
    {
      待追问: 0,
      已覆盖: 0,
      已忽略: 0
    } as Record<string, number>
  );

  return [
    {
      label: "待追问",
      value: counts["待追问"],
      tone: "warn",
      filter: "待追问"
    },
    {
      label: "已覆盖",
      value: counts["已覆盖"],
      tone: "success",
      filter: "已覆盖"
    },
    {
      label: "已忽略",
      value: counts["已忽略"],
      tone: "muted",
      filter: "已忽略"
    },
    {
      label: "总问题",
      value: suggestionCards.value.length,
      tone: "primary",
      filter: "总问题"
    }
  ];
});

const visibleSuggestionCards = computed(() => {
  if (activeMetric.value === "总问题") return suggestionCards.value;
  return suggestionCards.value.filter(
    item => item.status === activeMetric.value
  );
});

const handleMockNewSuggestion = () => {
  const nextIndex =
    suggestionCards.value.reduce(
      (maxIndex, item) => Math.max(maxIndex, item.index),
      0
    ) + 1;

  suggestionCards.value.unshift({
    index: nextIndex,
    title: "补充追问：请补充体位性头晕与服药情况",
    tag: "待追问",
    tagClass: "warning",
    status: "待追问",
    goal: "追问目的：补充更多病史，确定体位与高血压之间的关系",
    hint: "优先核对发作时间、持续时间、到位后是否可快速缓解等细节",
    ignoreCountdown: null,
    ignoreIntervalId: null,
    ignoreTimeoutId: null
  });
};

const clearIgnoreTimer = (card: SuggestionCard) => {
  if (card.ignoreIntervalId !== null) {
    window.clearInterval(card.ignoreIntervalId);
    card.ignoreIntervalId = null;
  }
  if (card.ignoreTimeoutId !== null) {
    window.clearTimeout(card.ignoreTimeoutId);
    card.ignoreTimeoutId = null;
  }
  card.ignoreCountdown = null;
};

const restoreIgnoredSuggestion = (index: number) => {
  const card = suggestionCards.value.find(item => item.index === index);
  if (!card) return;

  clearIgnoreTimer(card);
  card.status = "待追问";
  card.tag = "待追问";
  card.tagClass = "warning";
};

const handleIgnoreSuggestion = (index: number) => {
  const card = suggestionCards.value.find(item => item.index === index);
  if (!card || card.status !== "待追问") return;

  clearIgnoreTimer(card);
  card.ignoreCountdown = 3;
  card.ignoreIntervalId = window.setInterval(() => {
    if (card.ignoreCountdown !== null && card.ignoreCountdown > 1) {
      card.ignoreCountdown -= 1;
    }
  }, 1000);
  card.ignoreTimeoutId = window.setTimeout(() => {
    card.status = "已忽略";
    card.tag = "已忽略";
    card.tagClass = "muted";
    clearIgnoreTimer(card);
  }, 3000);
};

const handleUndoIgnore = (index: number) => {
  const card = suggestionCards.value.find(item => item.index === index);
  if (!card || card.ignoreCountdown === null) return;
  restoreIgnoredSuggestion(index);
};

const setMetric = async (metric: string) => {
  // 切换分类时只更新内容，不触发整组列表的进出场动画。
  const animationToken = ++suggestionMetricAnimationToken;
  suggestionListAnimationEnabled.value = false;
  activeMetric.value = metric;
  await nextTick();
  if (animationToken === suggestionMetricAnimationToken) {
    suggestionListAnimationEnabled.value = true;
  }
};

onBeforeUnmount(() => {
  suggestionCards.value.forEach(card => clearIgnoreTimer(card));
  stopInterviewTimer();
});

const transcriptEntries = [
  {
    role: "说话人1",
    time: "08:40:05",
    text: "王大爷您好，今天来主要是哪里不舒服？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:40:22",
    text: "李医生，我最近一个月老头晕，有时候站起来眼前发黑，血压也高了。",
    tone: "green"
  },
  {
    role: "说话人1",
    time: "08:40:58",
    text: "头晕大概什么时候开始的？是持续性的还是一阵一阵的？有没有什么诱因？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:41:35",
    text: "大概半个月前开始的，主要是一站起来或者转头的时候晕，坐着躺着就没事。最近睡眠也不好，家里有些事情操心。",
    tone: "green"
  },
  {
    role: "说话人1",
    time: "08:42:10",
    text: "嗯，休息不好确实会影响血压。您之前有高血压病史对吧？平时吃的什么药？最近量过血压吗？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:42:50",
    text: "高血压有八年了，一直吃苯磺酸氨氯地平，一天一片。以前血压基本 140/85 左右，最近自己在家量，最高到过 162/96。",
    tone: "green"
  },
  {
    role: "说话人1",
    time: "08:43:30",
    text: "162/96 确实偏高了。药有没有按时吃？最近有没有自行加量或者停过药？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:44:05",
    text: "药倒是天天吃，没断过。我看血压高了也没敢自己加，想着来看看医生再说。",
    tone: "green"
  }
];

const handleBack = () => {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  router.push("/home");
};

const setMode = (mode: string) => {
  activeMode.value = mode;
};

const isKeyboardMode = computed(() => activeMode.value === "键盘");
const isHandwritingMode = computed(() => activeMode.value === "手写");

const transcriptPanelTitle = computed(() => {
  if (isHandwritingMode.value) return "手写记录";
  return isKeyboardMode.value ? "我的笔记" : "实时转录";
});

const handwritingActions = [
  {
    key: "undo",
    label: "撤销",
    icon: RefreshLeft,
    handler: handleUndo
  },
  {
    key: "clear",
    label: "清空",
    icon: Delete,
    handler: handleClear
  },
  {
    key: "export",
    label: "导出",
    icon: Download,
    handler: handleExportSignature
  }
];

const focusNoteEditor = () => {
  noteInputRef.value?.focus?.();
};

const setBrushColor = (color: string) => {
  selectedBrushColor.value = color;
  isEraserMode.value = false;
};

const toggleEraserMode = () => {
  isEraserMode.value = !isEraserMode.value;
};

function handleUndo() {
  signatureRef.value?.undo?.();
}

function handleClear() {
  signatureRef.value?.clear?.();
}

function handleExportSignature() {
  const signature = signatureRef.value;
  if (!signature) return;

  const trimmed = signature.trim?.({
    format: "image/png",
    backgroundColor: "rgb(255, 255, 255)"
  });

  const dataUrl = trimmed?.dataUrl ?? signature.save?.("image/png");

  if (!dataUrl) return;

  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = `handwriting-${Date.now()}.png`;
  link.click();
}

const handleEndInterview = async () => {
  try {
    await ElMessageBox.confirm("确定结束当前访谈吗？", "结束访谈", {
      confirmButtonText: "结束",
      cancelButtonText: "取消",
      type: "warning"
    });
    stopInterviewTimer();
    router.push("/home");
  } catch {
    // 取消时不做处理
  }
};

onMounted(() => {
  startInterviewTimer();
});
</script>

<template>
  <div class="interview-page">
    <div class="page-shell">
      <header class="page-header">
        <div class="header-left">
          <el-button
            class="back-button"
            :icon="backIcon"
            text
            @click="handleBack"
          >
            返回
          </el-button>
          <h1 class="page-title">{{ baseInterviewTitle }}</h1>
        </div>
      </header>

      <main class="workspace">
        <aside class="left-panel glass-card">
          <div class="left-panel-header">
            <div class="panel-title">
              <component :is="aiLineIcon" class="panel-icon" />
              <span>AI 追问建议与覆盖</span>
            </div>
            <el-button
              class="panel-action"
              text
              :icon="Plus"
              @click="handleMockNewSuggestion"
            >
              模拟新建议
            </el-button>
          </div>

          <section class="metric-grid">
            <article
              v-for="item in metrics"
              :key="item.label"
              class="metric-item"
              :class="[item.tone, { active: activeMetric === item.filter }]"
              role="button"
              tabindex="0"
              @click="setMetric(item.filter)"
              @keydown.enter="setMetric(item.filter)"
              @keydown.space.prevent="setMetric(item.filter)"
            >
              <strong>{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </article>
          </section>

          <el-scrollbar class="suggestion-scroll">
            <TransitionGroup
              tag="div"
              class="suggestion-list"
              :css="suggestionListAnimationEnabled"
              enter-active-class="animate__animated animate__fadeInLeft animate__faster"
              leave-active-class="animate__animated animate__fadeOutRightBig animate__faster"
            >
              <article
                v-for="item in visibleSuggestionCards"
                :key="item.index"
                class="suggestion-card"
                :class="{
                  ignored: item.status === '已忽略',
                  covered: item.status === '已覆盖'
                }"
              >
                <div class="suggestion-head">
                  <span class="suggestion-index">{{ item.index }}</span>
                  <h3 class="suggestion-title">{{ item.title }}</h3>
                  <div class="suggestion-head-actions">
                    <span class="suggestion-tag" :class="item.tagClass">
                      {{ item.tag }}
                    </span>
                    <button
                      v-if="
                        item.status === '待追问' ||
                        item.ignoreCountdown !== null
                      "
                      type="button"
                      class="suggestion-ignore-button"
                      :class="{ countdown: item.ignoreCountdown !== null }"
                      :aria-label="
                        item.ignoreCountdown !== null ? '撤销忽略' : '忽略问题'
                      "
                      @click="
                        item.ignoreCountdown !== null
                          ? handleUndoIgnore(item.index)
                          : handleIgnoreSuggestion(item.index)
                      "
                    >
                      <component
                        :is="ignoreIcon"
                        class="suggestion-ignore-icon"
                      />
                      <span>{{
                        item.ignoreCountdown !== null
                          ? `${item.ignoreCountdown}s`
                          : "忽略"
                      }}</span>
                    </button>
                  </div>
                </div>
                <p class="suggestion-goal">{{ item.goal }}</p>
                <p class="suggestion-hint">{{ item.hint }}</p>
              </article>
            </TransitionGroup>
          </el-scrollbar>
        </aside>

        <section class="right-panel">
          <div class="session-bar glass-card">
            <div class="session-meta">
              <span>受访者：王大爷</span>
              <span>开始于 今天 08:40</span>
              <span class="word-count">
                <EditPen class="meta-icon" />
                1,238 字
              </span>
            </div>

            <div class="session-actions">
              <span class="transcribing-badge">
                <span class="transcribing-dot" />
                访谈中 {{ transcribingElapsedTime }}
              </span>
              <el-button
                type="primary"
                class="end-btn"
                @click="handleEndInterview"
              >
                结束访谈
              </el-button>
            </div>
          </div>

          <div class="transcript-card glass-card">
            <div class="transcript-head">
              <div class="transcript-title">
                <EditPen v-if="isKeyboardMode" class="panel-icon" />
                <component
                  :is="handwritingIcon"
                  v-else-if="isHandwritingMode"
                  class="panel-icon"
                />
                <ChatDotRound v-else class="panel-icon" />
                <span>{{ transcriptPanelTitle }}</span>
              </div>

              <div class="mode-switch">
                <button
                  v-for="mode in ['手写', '键盘', '转录']"
                  :key="mode"
                  class="mode-button"
                  :class="{ active: activeMode === mode }"
                  @click="setMode(mode)"
                >
                  {{ mode }}
                </button>
              </div>
            </div>

            <el-scrollbar
              v-if="!isKeyboardMode && !isHandwritingMode"
              class="transcript-scroll"
            >
              <div class="transcript-list">
                <article
                  v-for="(item, index) in transcriptEntries"
                  :key="`${item.role}-${item.time}-${index}`"
                  class="transcript-item"
                >
                  <div class="speaker-badge" :class="item.tone">
                    {{ item.role === "说话人1" ? "1" : "2" }}
                  </div>

                  <div class="transcript-content">
                    <div class="transcript-meta">
                      <strong>{{ item.role }}</strong>
                      <span>{{ item.time }}</span>
                    </div>
                    <p>{{ item.text }}</p>
                  </div>
                </article>
              </div>
            </el-scrollbar>

            <el-scrollbar
              v-else-if="isKeyboardMode"
              class="note-scroll"
              @click="focusNoteEditor"
            >
              <div class="note-editor">
                <el-input
                  ref="noteInputRef"
                  v-model="noteContent"
                  class="note-input"
                  type="textarea"
                  placeholder="在这里记录你的访谈笔记..."
                  resize="none"
                />
              </div>
            </el-scrollbar>

            <div v-else class="handwriting-shell">
              <div class="handwriting-toolbar">
                <div class="handwriting-toolbar-group">
                  <span class="handwriting-group-label">常用</span>
                  <div class="handwriting-tools">
                    <button
                      v-for="action in handwritingActions"
                      :key="action.key"
                      type="button"
                      class="handwriting-tool"
                      @click="action.handler"
                    >
                      <component :is="action.icon" class="tool-icon" />
                      <span>{{ action.label }}</span>
                    </button>
                    <button
                      type="button"
                      class="handwriting-tool"
                      :class="{ active: isEraserMode }"
                      @click="toggleEraserMode"
                    >
                      <component :is="eraserIcon" class="tool-icon" />
                      <span>{{ isEraserMode ? "正在擦除" : "橡皮擦" }}</span>
                    </button>
                  </div>
                </div>

                <div class="handwriting-toolbar-group">
                  <span class="handwriting-group-label">颜色</span>
                  <div class="handwriting-colors">
                    <button
                      v-for="color in brushColorPresets"
                      :key="color"
                      type="button"
                      class="color-swatch"
                      :class="{ active: selectedBrushColor === color }"
                      :style="{ '--swatch-color': color }"
                      @click="setBrushColor(color)"
                    />
                    <el-color-picker
                      v-model="selectedBrushColor"
                      class="color-picker"
                      size="small"
                      :predefine="brushColorPresets"
                      @change="setBrushColor"
                    />
                  </div>
                </div>
              </div>

              <div class="handwriting-pad">
                <Vue3Signature
                  ref="signatureRef"
                  class="signature-canvas"
                  :sigOption="signatureOptions"
                  :w="'100%'"
                  :h="'100%'"
                  :clearOnResize="false"
                />
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
    <LayFooter />
  </div>
</template>

<style lang="scss" scoped>
.interview-page {
  min-height: 100vh;
  padding: 30px 16px 0;
  background: url("@/assets/images/bg.png") no-repeat;
  background-size: cover;
  overflow: hidden;
}

.interview-page {
  .page-shell {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: calc(100vh - 48px);
    min-height: calc(100vh - 48px);
  }

  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
    margin-bottom: 20px;
    padding: 0 16px;
    background: transparent;
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }

  .back-button {
    flex-shrink: 0;
    height: 32px;
    min-height: 32px;
    padding: 0;
    font-size: 13px;
    font-weight: 500;
    color: #64748b;
  }

  .back-button:hover {
    color: #4a90e2;
  }

  .back-button:focus-visible {
    color: #4a90e2;
  }

  .back-button :deep(.el-icon),
  .back-button :deep(svg) {
    width: 18px;
    height: 18px;
  }

  .back-button:hover,
  .back-button:focus-visible {
    background: transparent !important;
  }

  .page-title {
    margin: 0;
    overflow: hidden;
    font-size: 28px;
    font-weight: 600;
    color: #1a1a1a;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .workspace {
    flex: 1;
    display: grid;
    grid-template-columns: 480px minmax(0, 1fr);
    gap: 16px;
    align-items: stretch;
    margin-bottom: 6px;
    width: 100%;
    min-height: 0;
  }

  .glass-card {
    background: rgb(255 255 255 / 68%);
    border: 1px solid rgb(255 255 255 / 72%);
    border-radius: 16px;
    box-shadow: 0 14px 40px rgb(31 47 86 / 10%);
    backdrop-filter: blur(10px);
  }

  .left-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    padding: 16px;
  }

  .left-panel-header,
  .session-bar,
  .transcript-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .left-panel-header {
    margin-bottom: 14px;
  }

  .panel-title,
  .transcript-title {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    font-size: 16px;
    font-weight: 700;
    color: #24324a;
  }

  .panel-icon,
  .meta-icon {
    width: 16px;
    height: 16px;
  }

  .panel-action {
    height: 34px;
    padding: 0 2px;
    font-size: 13px;
    color: #64748b;
  }

  .panel-action:hover {
    color: #4a90e2;
    background: transparent !important;
  }

  .panel-action:focus-visible {
    color: #4a90e2;
    background: transparent !important;
  }

  .metric-grid {
    flex-shrink: 0;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    padding: 0 0 14px;
    margin-bottom: 14px;
    border-bottom: 1px solid rgb(221 226 236 / 90%);
  }

  .metric-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 82px;
    padding: 8px 4px;
    border: 1px solid rgb(219 227 240 / 96%);
    border-radius: 8px;
    background: rgb(255 255 255 / 58%);
    cursor: pointer;
    transition:
      transform 0.2s ease,
      box-shadow 0.2s ease,
      border-color 0.2s ease,
      background-color 0.2s ease;
  }

  .metric-item:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 20px rgb(31 47 86 / 8%);
  }

  .metric-item.active {
    border-color: rgb(74 144 226 / 35%);
    background: rgb(74 144 226 / 10%);
    box-shadow: 0 12px 24px rgb(74 144 226 / 10%);
  }

  .metric-item strong {
    font-size: 24px;
    font-weight: 700;
    line-height: 1.1;
  }

  .metric-item span {
    margin-top: 6px;
    font-size: 13px;
    color: #64748b;
  }

  .metric-item.warn strong {
    color: #f59e0b;
  }

  .metric-item.success strong {
    color: #0ea76a;
  }

  .metric-item.muted strong {
    color: #64748b;
  }

  .metric-item.primary strong {
    color: #1f4ed8;
  }

  .suggestion-list {
    display: grid;
    gap: 12px;
  }

  .suggestion-scroll {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  .suggestion-card {
    padding: 16px 16px 14px;
    background: rgb(255 255 255 / 70%);
    border: 1px solid rgb(219 227 240 / 96%);
    border-radius: 16px;
  }

  .suggestion-head {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
  }

  .suggestion-head-actions {
    display: inline-flex;
    gap: 12px;
    align-items: center;
  }

  /* .suggestion-head-actions::before {
  width: 1px;
  height: 22px;
  content: "";
  background: rgb(148 163 184 / 35%);
} */

  .suggestion-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    font-size: 14px;
    font-weight: 700;
    color: #ef4444;
    background: rgb(239 68 68 / 10%);
    border-radius: 999px;
  }

  .suggestion-title {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    color: #24324a;
  }

  .suggestion-tag {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 700;
    border-radius: 20px;
  }

  .suggestion-tag.warning {
    color: #d97706;
    background: rgb(245 158 11 / 14%);
  }

  .suggestion-tag.success {
    color: #0f9d63;
    background: rgb(16 185 129 / 14%);
  }

  .suggestion-tag.muted {
    color: #64748b;
    background: rgb(148 163 184 / 16%);
  }

  .suggestion-ignore-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    height: 26px;
    min-width: 60px;
    padding: 0 12px;
    font-size: 12px;
    font-weight: 700;
    color: #334155;
    cursor: pointer;
    background: rgb(255 255 255 / 64%);
    border: 1px dashed rgb(148 163 184 / 70%);
    border-radius: 8px;
    transition:
      transform 0.2s ease,
      color 0.2s ease,
      border-color 0.2s ease,
      box-shadow 0.2s ease,
      background-color 0.2s ease;
  }

  .suggestion-ignore-button:hover {
    color: #1e293b;
    background: rgb(248 250 252 / 98%);
    border-color: rgb(100 116 139 / 70%);
    box-shadow: 0 8px 16px rgb(30 41 59 / 9%);
    transform: translateY(-1px);
  }

  .suggestion-ignore-button.countdown {
    color: #2563eb;
    background: rgb(239 246 255 / 92%);
    border-color: rgb(147 197 253 / 90%);
  }

  .suggestion-ignore-button.countdown:hover {
    color: #1d4ed8;
    background: rgb(219 234 254 / 98%);
    border-color: rgb(96 165 250 / 92%);
    box-shadow: 0 8px 16px rgb(59 130 246 / 12%);
  }

  .suggestion-ignore-icon {
    width: 14px;
    height: 14px;
  }

  .suggestion-card.ignored {
    opacity: 0.78;
    background: rgb(248 250 252 / 82%);
    border-style: dashed;
  }

  .suggestion-card.covered {
    background: linear-gradient(
      180deg,
      rgb(236 253 245 / 88%),
      rgb(255 255 255 / 76%)
    );
    border-color: rgb(167 243 208 / 98%);
  }

  .suggestion-card.covered .suggestion-index {
    color: #0f9d63;
    background: rgb(16 185 129 / 12%);
  }

  .suggestion-card.covered .suggestion-title {
    color: #0f172a;
  }

  .suggestion-card.covered .suggestion-goal,
  .suggestion-card.covered .suggestion-hint {
    color: #5b7288;
  }

  .suggestion-card.ignored .suggestion-index {
    color: #64748b;
    background: rgb(148 163 184 / 14%);
  }

  .suggestion-card.ignored .suggestion-title,
  .suggestion-card.ignored .suggestion-goal,
  .suggestion-card.ignored .suggestion-hint {
    color: #94a3b8;
  }

  .suggestion-goal {
    margin: 12px 0 8px;
    font-size: 13px;
    color: #64748b;
  }

  .suggestion-hint {
    margin: 0;
    font-size: 13px;
    line-height: 1.7;
    color: #64748b;
  }

  .ignore-undo-stack {
    position: fixed;
    right: 24px;
    bottom: 24px;
    z-index: 40;
    display: grid;
    gap: 10px;
    width: min(360px, calc(100vw - 32px));
    pointer-events: none;
  }

  .ignore-undo-toast {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 16px;
    pointer-events: auto;
  }

  .ignore-undo-copy {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .ignore-undo-copy strong {
    font-size: 13px;
    font-weight: 800;
    color: #ef4444;
  }

  .ignore-undo-copy span {
    overflow: hidden;
    font-size: 13px;
    line-height: 1.5;
    color: #334155;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ignore-undo-button {
    flex-shrink: 0;
    height: 32px;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 700;
    color: #1f4ed8;
    cursor: pointer;
    background: rgb(219 234 254 / 96%);
    border: 1px solid rgb(147 197 253 / 92%);
    border-radius: 999px;
    transition:
      transform 0.2s ease,
      box-shadow 0.2s ease,
      background-color 0.2s ease;
  }

  .ignore-undo-button:hover {
    background: rgb(191 219 254 / 98%);
    box-shadow: 0 8px 18px rgb(59 130 246 / 12%);
    transform: translateY(-1px);
  }

  .undo-toast-enter-active,
  .undo-toast-leave-active {
    transition:
      opacity 0.22s ease,
      transform 0.22s ease;
  }

  .undo-toast-enter-from,
  .undo-toast-leave-to {
    opacity: 0;
    transform: translateY(10px);
  }

  .right-panel {
    display: grid;
    gap: 16px;
    height: 100%;
    min-width: 0;
    min-height: 0;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .session-bar {
    flex-shrink: 0;
    gap: 16px;
    padding: 16px;
  }

  .session-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    min-width: 0;
    font-size: 13px;
    color: #64748b;
  }

  .word-count {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 600;
    color: #64748b;
    background: #f2f5f9;
    border-radius: 999px;
  }

  .session-actions {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-shrink: 0;
    margin-left: auto;
  }

  .transcribing-badge {
    display: inline-flex;
    gap: 8px;
    align-items: center;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 600;
    color: #334155;
    background: rgb(255 255 255 / 92%);
    border: 1px solid rgb(219 227 240 / 95%);
    border-radius: 20px;
    box-shadow: 0 8px 18px rgb(31 47 86 / 8%);
  }

  .transcribing-dot {
    width: 10px;
    height: 10px;
    background: #10b981;
    border-radius: 999px;
    box-shadow: 0 0 0 4px rgb(16 185 129 / 14%);
    animation: transcribingPulse 1.6s ease-in-out infinite;
  }

  .end-btn {
    height: 36px;
    border-radius: 8px;
  }

  .transcript-card {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    max-height: 100%;
    overflow: hidden;
  }

  .transcript-head {
    padding: 16px;
    border-bottom: 1px solid rgb(221 226 236 / 90%);
  }

  .mode-switch {
    display: inline-flex;
    padding: 4px;
    background: rgb(241 245 249 / 96%);
    border-radius: 999px;
  }

  .mode-button {
    height: 32px;
    padding: 0 18px;
    font-size: 13px;
    font-weight: 600;
    color: #64748b;
    background: transparent;
    border: 0;
    border-radius: 999px;
    cursor: pointer;
    transition:
      color 0.2s ease,
      background-color 0.2s ease,
      box-shadow 0.2s ease;
  }

  .mode-button.active {
    color: #24324a;
    background: rgb(255 255 255 / 96%);
    box-shadow: 0 10px 24px rgb(31 47 86 / 10%);
  }

  @keyframes transcribingPulse {
    0% {
      transform: scale(0.88);
      box-shadow: 0 0 0 0 rgb(16 185 129 / 24%);
      opacity: 0.72;
    }

    50% {
      transform: scale(1);
      box-shadow: 0 0 0 8px rgb(16 185 129 / 0%);
      opacity: 1;
    }

    100% {
      transform: scale(0.88);
      box-shadow: 0 0 0 0 rgb(16 185 129 / 0%);
      opacity: 0.72;
    }
  }

  .transcript-scroll {
    flex: 1;
    height: 0;
    min-height: 0;
    max-height: 100%;
  }

  .note-scroll {
    flex: 1;
    height: 0;
    min-height: 0;
    max-height: 100%;
    overflow: hidden;
  }

  .transcript-list {
    min-height: 100%;
    padding: 6px 12px 12px 6px;
  }

  .note-editor {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    padding: 16px 0 16px 16px;
  }

  .handwriting-shell {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
    gap: 12px;
    padding: 16px;
  }

  .handwriting-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 14px;
    padding: 10px 16px;
    background: rgb(241 245 249 / 92%);
    border: 1px solid rgb(226 232 240 / 90%);
    border-radius: 16px;
    box-shadow: 0 8px 18px rgb(31 47 86 / 5%);
  }

  .handwriting-toolbar-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }

  .handwriting-group-label {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #64748b;
  }

  .handwriting-tools,
  .handwriting-colors,
  .handwriting-sizes {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }

  .handwriting-tool {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 32px;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 600;
    color: #334155;
    cursor: pointer;
    background: rgb(255 255 255 / 92%);
    border: 1px solid rgb(226 232 240 / 96%);
    border-radius: 8px;
    transition:
      transform 0.2s ease,
      border-color 0.2s ease,
      box-shadow 0.2s ease,
      color 0.2s ease;
  }

  .handwriting-tool:hover {
    color: #24324a;
    border-color: rgb(74 144 226 / 35%);
    box-shadow: 0 10px 20px rgb(74 144 226 / 10%);
    transform: translateY(-1px);
  }

  .handwriting-tool.active {
    color: #1f4ed8;
    background: rgb(219 234 254 / 95%);
    border-color: rgb(96 165 250 / 45%);
  }

  .tool-icon {
    width: 16px;
    height: 16px;
  }

  .color-swatch {
    width: 28px;
    height: 28px;
    padding: 0;
    background: var(--swatch-color);
    border: 2px solid rgb(255 255 255 / 96%);
    border-radius: 999px;
    box-shadow: 0 4px 10px rgb(31 47 86 / 10%);
    cursor: pointer;
    transition:
      transform 0.2s ease,
      box-shadow 0.2s ease,
      border-color 0.2s ease;
  }

  .color-swatch:hover {
    transform: translateY(-1px) scale(1.03);
    box-shadow: 0 8px 16px rgb(31 47 86 / 12%);
  }

  .color-swatch.active {
    border-color: rgb(37 99 235 / 45%);
    box-shadow: 0 0 0 3px rgb(59 130 246 / 16%);
  }

  .color-picker {
    margin-left: 2px;
  }

  .color-picker :deep(.el-color-picker__trigger) {
    width: 28px;
    height: 28px;
    padding: 0;
    border: 2px solid rgb(255 255 255 / 96%);
    border-radius: 999px;
    box-shadow: 0 4px 10px rgb(31 47 86 / 10%);
  }

  .handwriting-pad {
    flex: 1;
    min-height: 0;
    padding: 12px;
    overflow: hidden;
    background: linear-gradient(
      180deg,
      rgb(255 255 255 / 94%),
      rgb(250 252 255 / 92%)
    );
    border: 1px solid rgb(219 227 240 / 96%);
    border-radius: 16px;
    box-shadow: 0 10px 24px rgb(31 47 86 / 7%);
  }

  .signature-canvas {
    display: block;
    width: 100%;
    height: 100%;
  }

  .note-input {
    display: flex;
    width: 100%;
    height: 100%;
    min-height: 0;
  }

  .note-input :deep(.el-textarea) {
    display: flex;
    flex: 1;
    height: 100%;
    min-height: 0;
  }

  .note-input :deep(.el-textarea__inner) {
    width: 100%;
    height: 100%;
    min-height: 0;
    padding: 0 4px 0 0;
    font-size: 15px;
    line-height: 1.8;
    color: #334155;
    background: transparent;
    border: none;
    box-shadow: none;
    resize: none;
    scrollbar-width: thin;
    scrollbar-color: rgb(148 163 184 / 70%) transparent;
  }

  .note-input :deep(.el-textarea__inner:focus) {
    box-shadow: none;
  }

  .note-input :deep(.el-textarea__inner::placeholder) {
    color: #94a3b8;
  }

  .note-input :deep(.el-textarea__inner::-webkit-scrollbar) {
    width: 8px;
    height: 8px;
  }

  .note-input :deep(.el-textarea__inner::-webkit-scrollbar-track) {
    background: transparent;
  }

  .note-input :deep(.el-textarea__inner::-webkit-scrollbar-thumb) {
    background: rgb(148 163 184 / 70%);
    border: 2px solid transparent;
    border-radius: 999px;
    background-clip: content-box;
  }

  .note-input :deep(.el-input__wrapper) {
    display: flex;
    flex: 1;
    height: 100%;
    min-height: 0;
    padding: 0;
    background: transparent;
    box-shadow: none;
  }

  .note-input :deep(.el-input__wrapper:hover) {
    box-shadow: none;
  }

  .transcript-item {
    display: grid;
    grid-template-columns: 40px minmax(0, 1fr);
    gap: 14px;
    padding: 18px 12px;
    border-bottom: 1px solid rgb(221 226 236 / 84%);
  }

  .transcript-item:last-child {
    border-bottom: 0;
  }

  .speaker-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    font-size: 14px;
    font-weight: 700;
    color: #fff;
    border-radius: 999px;
  }

  .speaker-badge.blue {
    background: linear-gradient(135deg, #2f6fed 0%, #2458d9 100%);
  }

  .speaker-badge.green {
    background: linear-gradient(135deg, #16b981 0%, #0ea76a 100%);
  }

  .transcript-content {
    min-width: 0;
  }

  .transcript-meta {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
  }

  .transcript-meta strong {
    font-size: 14px;
    font-weight: 700;
    color: #334155;
  }

  .transcript-meta span {
    font-size: 13px;
    font-weight: 600;
    color: #94a3b8;
  }

  .transcript-content p {
    margin: 0;
    font-size: 14px;
    line-height: 1.8;
    color: #334155;
  }

  .suggestion-scroll :deep(.el-scrollbar__wrap),
  .transcript-scroll :deep(.el-scrollbar__wrap),
  .note-scroll :deep(.el-scrollbar__wrap) {
    scrollbar-gutter: stable;
  }

  .suggestion-scroll :deep(.el-scrollbar__view),
  .transcript-scroll :deep(.el-scrollbar__view),
  .note-scroll :deep(.el-scrollbar__view) {
    box-sizing: border-box;
    height: 100%;
    padding-right: 12px;
  }

  .suggestion-scroll :deep(.el-scrollbar__bar.is-vertical),
  .transcript-scroll :deep(.el-scrollbar__bar.is-vertical),
  .note-scroll :deep(.el-scrollbar__bar.is-vertical) {
    right: 2px;
  }
}

@media (max-width: 1280px) {
  .interview-page .workspace {
    grid-template-columns: 400px minmax(0, 1fr);
  }
}

@media (max-width: 1080px) {
  .interview-page .page-shell {
    height: auto;
    min-height: calc(100vh - 46px);
  }

  .interview-page .workspace {
    grid-template-columns: 1fr;
  }

  .interview-page .left-panel,
  .interview-page .transcript-card {
    min-height: auto;
  }

  .interview-page .left-panel {
    max-height: 58vh;
  }

  .interview-page .right-panel {
    min-height: 0;
    height: auto;
  }

  .interview-page .transcript-card {
    max-height: 62vh;
    flex: initial;
  }
}

@media (max-width: 820px) {
  .interview-page .page-header,
  .interview-page .session-bar,
  .interview-page .transcript-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .interview-page .session-actions {
    margin-left: 0;
  }

  .interview-page .page-title {
    font-size: 17px;
  }

  .interview-page .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .interview-page .suggestion-head {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .interview-page .suggestion-tag {
    justify-self: start;
  }
}

@media (max-width: 640px) {
  .interview-page {
    padding: 10px;
  }

  .interview-page .page-shell {
    min-height: calc(100vh - 20px);
  }

  .interview-page .page-header {
    /* padding: 6px 10px; */
    margin-bottom: 6px;
  }

  .interview-page .page-title {
    font-size: 17px;
    white-space: normal;
  }

  .interview-page .back-button {
    font-size: 13px;
  }

  .interview-page .workspace {
    gap: 12px;
  }

  .interview-page .glass-card {
    border-radius: 16px;
  }

  .interview-page .left-panel {
    padding: 14px;
  }

  .interview-page .panel-title,
  .interview-page .transcript-title {
    font-size: 15px;
  }

  .interview-page .metric-item strong {
    font-size: 22px;
  }

  .interview-page .transcript-item {
    grid-template-columns: 32px minmax(0, 1fr);
    gap: 10px;
    padding: 14px 8px;
  }

  .interview-page .session-bar {
    padding: 14px;
  }

  .interview-page .transcript-head {
    padding: 14px;
  }

  .interview-page .mode-switch {
    width: 100%;
    justify-content: space-between;
  }

  .interview-page .mode-button {
    flex: 1;
    padding: 0 12px;
  }
}

@media (max-width: 520px) {
  .interview-page .suggestion-head {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .interview-page .suggestion-head-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}
</style>
