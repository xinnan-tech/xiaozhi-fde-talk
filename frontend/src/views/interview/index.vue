<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import dayjs from "dayjs";
import Plus from "~icons/ep/plus";
import ChatDotRound from "~icons/ep/chat-dot-round";
import EditPen from "~icons/ep/edit-pen";
import RefreshLeft from "~icons/ep/refresh-left";
import Delete from "~icons/ep/delete";
import Download from "~icons/ep/download";
import Aim from "~icons/ep/aim";
import Calendar from "~icons/ep/calendar";
import SwitchButton from "~icons/ep/switch-button";
import User from "~icons/ep/user";
import VideoPlay from "~icons/ep/video-play";
import { ElMessage, ElMessageBox } from "element-plus";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import LayFooter from "@/layout/components/lay-footer/index.vue";
import {
  endInterviewApi,
  getInterviewDetailApi,
  ignoreInterviewItemApi,
  InterviewDetailType,
  unignoreInterviewItemApi
} from "@/api/interview";
import { useAudioRecorder } from "@/composables/useAudioRecorder";
import {
  useWebSocket,
  type InterviewServerMessage
} from "@/composables/useWebSocket";

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
const newItemIcon = useRenderIcon("clarity:new-solid");
const microphoneIcon = useRenderIcon("lucide:mic");
const microphoneOffIcon = useRenderIcon("lucide:mic-off");

const baseInterviewTitle = computed(() => {
  const title = route.query.title;
  if (typeof title === "string" && title.trim()) return title.trim();
  return "访谈";
});

/** 访谈详情 */
const interviewDetail = ref<InterviewDetailType>();
const startedAtDisplay = computed(() => {
  const startedAt = interviewDetail.value?.started_at;
  return startedAt ? dayjs(startedAt).format("YYYY-MM-DD HH:mm:ss") : "--";
});
const startInterviewButtonText = computed(() => {
  const status = interviewDetail.value?.status;
  return status === "in_progress" || status === "suspended"
    ? "继续访谈"
    : "开始访谈";
});
const interviewStatusText = computed(() => {
  switch (interviewDetail.value?.status) {
    case "in_progress":
      return "进行中";
    case "suspended":
      return "已暂停";
    case "ended":
    case "extracting":
    case "done":
      return "已结束";
    default:
      return "待开始";
  }
});
const interviewStatusClass = computed(() => {
  switch (interviewDetail.value?.status) {
    case "in_progress":
      return "status-in_progress";
    case "suspended":
      return "status-suspended";
    case "ended":
    case "extracting":
    case "done":
      return "status-ended";
    default:
      return "status-created";
  }
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
  itemId: string;
  index: number;
  title: string;
  tag: string;
  tagClass: string;
  status: "待追问" | "已覆盖" | "已忽略";
  isNew: boolean;
  goal: string;
  hint: string;
  ignoreCountdown: number | null;
  ignoreIntervalId: number | null;
  ignoreTimeoutId: number | null;
};

type TranscriptEntry = {
  segId: string;
  startMs: number | null;
  role: string;
  time: string;
  text: string;
  tone: "blue" | "green";
};

const suggestionCards = ref<SuggestionCard[]>([]);

type SuggestionSourceItem = {
  id: string;
  text: string;
  status: string;
  priority: number;
  reason: string;
  desc: string;
};

const mapItemStatus = (
  item: SuggestionSourceItem,
  ignoredIds: Set<string>
): SuggestionCard["status"] => {
  if (
    ignoredIds.has(item.id) ||
    item.status === "skipped" ||
    item.status === "ignored"
  ) {
    return "已忽略";
  }
  if (item.status === "done") return "已覆盖";
  return "待追问";
};

const createSuggestionCardsFromItems = (
  items: SuggestionSourceItem[],
  ignoredIds: Set<string> = new Set(),
  newItemIds: Set<string> = new Set()
) => {
  // 新问题统一置顶；待追问问题按 priority 顺序排列，其他状态放在最后。
  const orderedItems = [...items].sort((left, right) => {
    const leftGroup =
      left.status === "new" ? 0 : left.status === "todo" ? 1 : 2;
    const rightGroup =
      right.status === "new" ? 0 : right.status === "todo" ? 1 : 2;

    if (leftGroup !== rightGroup) return leftGroup - rightGroup;
    return left.priority - right.priority;
  });

  return orderedItems.map((item, index) => {
    const status = mapItemStatus(item, ignoredIds);
    const tagClass =
      status === "已覆盖"
        ? "success"
        : status === "已忽略"
          ? "muted"
          : "warning";

    return {
      itemId: item.id,
      index: index + 1,
      title: item.text,
      tag: status,
      tagClass,
      status,
      isNew: newItemIds.has(item.id),
      goal: item.reason ? `${item.reason}` : "",
      hint: item.desc || "",
      ignoreCountdown: null,
      ignoreIntervalId: null,
      ignoreTimeoutId: null
    };
  });
};

const createSuggestionCards = (detail: InterviewDetailType) => {
  const ignoredIds = new Set([
    ...(detail.ignored_ids ?? []),
    ...(detail.skipped_ids ?? [])
  ]);
  const newItemIds = new Set(
    detail.items.filter(item => item.status === "new").map(item => item.id)
  );
  return createSuggestionCardsFromItems(detail.items, ignoredIds, newItemIds);
};

const mergeSuggestionCards = (items: SuggestionSourceItem[]) => {
  const existingCards = new Map(
    suggestionCards.value.map(card => [card.itemId, card])
  );
  const newItemIds = new Set(
    items
      .filter(item => {
        const status = mapItemStatus(item, new Set());
        return !existingCards.has(item.id) && status === "待追问";
      })
      .map(item => item.id)
  );
  const existingNewItemIds = new Set(
    suggestionCards.value.filter(card => card.isNew).map(card => card.itemId)
  );
  const nextCards = createSuggestionCardsFromItems(
    items,
    new Set(),
    new Set([...newItemIds, ...existingNewItemIds])
  );
  return nextCards;
};

const suggestionListAnimationEnabled = ref(true);
let suggestionMetricAnimationToken = 0;
const isCoachingRecomputing = ref(false);
const idleWarningSeconds = ref<number | null>(null);
let idleWarningTimerId: number | null = null;

const clearIdleWarning = () => {
  if (idleWarningTimerId !== null) {
    window.clearInterval(idleWarningTimerId);
    idleWarningTimerId = null;
  }
  idleWarningSeconds.value = null;
};

const startIdleWarning = (seconds: number) => {
  clearIdleWarning();
  idleWarningSeconds.value = Math.max(0, Math.round(seconds));
  idleWarningTimerId = window.setInterval(() => {
    if (idleWarningSeconds.value === null || idleWarningSeconds.value <= 1) {
      clearIdleWarning();
      return;
    }
    idleWarningSeconds.value -= 1;
  }, 1000);
};

const interviewElapsedSeconds = ref(0);
const isInterviewStarted = ref(false);
let interviewTimerId: number | null = null;

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

const handleStartInterview = async () => {
  if (isInterviewStarted.value) return;
  isInterviewStarted.value = true;
  startInterviewTimer();

  // 在点击事件中立即请求权限，避免等待 WebSocket 握手后丢失浏览器用户手势。
  shouldResumeMicrophone.value = true;
  const microphoneStarted = await startRecording();
  if (!microphoneStarted) {
    shouldResumeMicrophone.value = false;
    isInterviewStarted.value = false;
    stopInterviewTimer();
    ElMessage.error("无法开启麦克风，请检查浏览器权限");
    return;
  }

  if (interviewDetail.value) {
    interviewDetail.value.status = "in_progress";
  }

  openWebSocket();

  // WebSocket 已经连接时直接开始监听；尚未连接时由 onConnected 处理。
  if (isWebSocketConnected.value) {
    const listeningStarted = await openMicrophone();
    if (listeningStarted) shouldResumeMicrophone.value = false;
  }
};

const toggleMicrophone = async () => {
  if (!isInterviewStarted.value) return;
  if (isMicrophoneEnabled.value) {
    sendListenState("stop");
    stopRecording();
    return;
  }
  await openMicrophone();
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

const restoreIgnoredSuggestion = (itemId: string) => {
  const card = suggestionCards.value.find(item => item.itemId === itemId);
  if (!card) return;

  clearIgnoreTimer(card);
  card.status = "待追问";
  card.tag = "待追问";
  card.tagClass = "warning";
};

const setIgnoredSuggestion = (card: SuggestionCard) => {
  card.status = "已忽略";
  card.tag = "已忽略";
  card.tagClass = "muted";
};

const getInterviewSessionId = () =>
  interviewDetail.value?.id || (route.params.id as string);

const AUDIO_PARAMS = {
  format: "opus",
  sample_rate: 16000,
  channels: 1,
  frame_duration: 60
};

const shouldResumeMicrophone = ref(false);
const transcriptEntries = ref<TranscriptEntry[]>([]);
const transcriptScrollRef = ref<{
  setScrollTop: (scrollTop: number) => void;
} | null>(null);

const formatTranscriptTime = (startMs: number | null = null) => {
  if (startMs !== null && Number.isFinite(startMs) && startMs >= 0) {
    const totalSeconds = Math.floor(startMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds]
      .map(value => String(value).padStart(2, "0"))
      .join(":");
  }
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
};

const createTranscriptEntries = (transcript: unknown[]) => {
  return transcript
    .flatMap((item, index) => {
      if (!item || typeof item !== "object") return [];

      const record = item as Record<string, unknown>;
      const text = typeof record.text === "string" ? record.text : "";
      if (!text) return [];

      const startMs =
        typeof record.start_ms === "number" && Number.isFinite(record.start_ms)
          ? record.start_ms
          : null;
      const speaker =
        typeof record.speaker === "string" && record.speaker !== "unknown"
          ? record.speaker
          : "说话人1";

      return [
        {
          segId:
            typeof record.seg_id === "string"
              ? record.seg_id
              : `history-${index}`,
          startMs,
          role: speaker,
          time: formatTranscriptTime(startMs),
          text,
          tone: "blue" as const
        }
      ];
    })
    .reverse();
};

const scrollTranscriptToTop = async () => {
  await nextTick();
  transcriptScrollRef.value?.setScrollTop(0);
};

const appendAsrMessage = (
  message: Extract<InterviewServerMessage, { type: "asr" }>
) => {
  const existingEntry = transcriptEntries.value.find(
    entry => entry.segId === message.seg_id
  );
  const nextEntry = {
    segId: message.seg_id,
    startMs: message.start_ms,
    role: message.speaker === "unknown" ? "说话人1" : message.speaker,
    time: formatTranscriptTime(message.start_ms),
    text: message.text,
    tone: "blue" as const
  };

  if (existingEntry) {
    Object.assign(existingEntry, nextEntry);
  } else {
    transcriptEntries.value.unshift(nextEntry);
  }
  void scrollTranscriptToTop();
};

const handleTakeoverConflict = async (message: string) => {
  try {
    await ElMessageBox.confirm(
      message || "该访谈已在其他页面打开，是否接管？",
      "访谈连接冲突",
      {
        confirmButtonText: "接管",
        cancelButtonText: "取消",
        type: "warning"
      }
    );
    websocket.takeover();
  } catch {
    websocket.close();
    isInterviewStarted.value = false;
    stopInterviewTimer();
  }
};

let isAsrUnavailableDialogOpen = false;

const handleAsrUnavailable = async (message: string) => {
  if (isAsrUnavailableDialogOpen) return;

  isAsrUnavailableDialogOpen = true;
  try {
    await ElMessageBox.confirm(
      message || "语音识别服务暂时不可用，请检查系统配置。",
      "语音识别服务不可用",
      {
        confirmButtonText: "前往配置",
        cancelButtonText: "取消",
        type: "error"
      }
    );
    await router.push("/system/config");
  } catch {
    // 用户选择继续留在当前访谈页面。
  } finally {
    isAsrUnavailableDialogOpen = false;
  }
};

const handleServerMessage = (message: InterviewServerMessage) => {
  if (message.type === "asr") {
    appendAsrMessage(message);
    return;
  }

  if (message.type === "coaching.update") {
    if (message.phase === "recomputing") {
      isCoachingRecomputing.value = true;
      return;
    }
    if (message.phase === "final") {
      isCoachingRecomputing.value = false;
      suggestionCards.value = mergeSuggestionCards(message.items);
    }
    return;
  }

  if (message.type === "session.idle_warning") {
    startIdleWarning(message.suspend_in_s);
    return;
  }

  if (message.type === "connection.conflict") {
    void handleTakeoverConflict(message.message);
    return;
  }

  if (message.type === "connection.kicked") {
    shouldResumeMicrophone.value = false;
    stopRecording();
    isInterviewStarted.value = false;
    stopInterviewTimer();
    ElMessage.warning(message.reason || "当前访谈已被其他连接接管");
    return;
  }

  if (message.type === "audio.low_level") {
    console.warn("[InterviewPage] 收到低音量提醒", message);
    ElMessage.warning(message.message || "声音较小，请靠近麦克风");
    return;
  }

  if (message.type === "error") {
    if (message.code === "asr_unavailable") {
      void handleAsrUnavailable(message.message);
      return;
    }
    ElMessage.error(`${message.code}: ${message.message}`);
    return;
  }

  if (
    message.type === "session.ended" ||
    message.type === "session.suspended"
  ) {
    clearIdleWarning();
    isCoachingRecomputing.value = false;
    if (interviewDetail.value) {
      interviewDetail.value.status =
        message.type === "session.ended" ? "ended" : "suspended";
    }
    shouldResumeMicrophone.value = false;
    stopRecording();
    isInterviewStarted.value = false;
    stopInterviewTimer();
  }
};

const websocket = useWebSocket({
  interviewId: getInterviewSessionId,
  audioParams: AUDIO_PARAMS,
  immediate: false,
  onMessage: handleServerMessage,
  onConnected: message => {
    console.info("[InterviewPage] WebSocket 握手成功", message);
    if (!shouldResumeMicrophone.value) return;
    void openMicrophone().then(started => {
      if (started) shouldResumeMicrophone.value = false;
    });
  },
  onDisconnected: event => {
    console.warn("[InterviewPage] WebSocket 已断开", event.code, event.reason);
    if (!isMicrophoneEnabled.value) return;
    shouldResumeMicrophone.value = true;
    stopRecording();
  },
  onError: message => {
    console.error("[InterviewPage] WebSocket 错误", message);
  }
});

const {
  state: websocketState,
  open: openWebSocket,
  sendListenState,
  sendAudioFrame
} = websocket;
const isWebSocketConnected = computed(
  () => websocketState.value === "connected"
);

const {
  isRecording: isMicrophoneEnabled,
  startRecording,
  stopRecording
} = useAudioRecorder({
  audio: {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  },
  onAudioData: async audio => {
    const payload = await audio.arrayBuffer();
    if (!isMicrophoneEnabled.value) return;
    const sent = sendAudioFrame(payload);
    if (!sent) {
      console.warn("[InterviewPage] 音频片段未发送", {
        size: audio.size,
        websocketState: websocketState.value
      });
    }
  }
});

const openMicrophone = async () => {
  if (!isWebSocketConnected.value) {
    ElMessage.warning("WebSocket 尚未连接");
    return false;
  }
  if (!sendListenState("start")) {
    ElMessage.warning("无法开始监听，请稍后重试");
    return false;
  }
  const started = await startRecording();
  if (!started) sendListenState("stop");
  return started;
};

const handleIgnoreSuggestion = (itemId: string) => {
  const card = suggestionCards.value.find(item => item.itemId === itemId);
  if (!card || card.status !== "待追问") return;

  clearIgnoreTimer(card);
  card.ignoreCountdown = 3;
  card.ignoreIntervalId = window.setInterval(() => {
    if (card.ignoreCountdown !== null && card.ignoreCountdown > 1) {
      card.ignoreCountdown -= 1;
    }
  }, 1000);
  card.ignoreTimeoutId = window.setTimeout(async () => {
    clearIgnoreTimer(card);
    setIgnoredSuggestion(card);
    try {
      if (!websocket.ignoreCoachingItem(card.itemId)) {
        await ignoreInterviewItemApi(getInterviewSessionId(), card.itemId);
      }
    } catch {
      restoreIgnoredSuggestion(itemId);
      ElMessage.error("忽略问题失败，请稍后重试");
    }
  }, 3000);
};

const handleUndoIgnore = (itemId: string) => {
  const card = suggestionCards.value.find(item => item.itemId === itemId);
  if (!card || card.ignoreCountdown === null) return;
  restoreIgnoredSuggestion(itemId);
};

const handleUnignoreSuggestion = async (itemId: string) => {
  const card = suggestionCards.value.find(item => item.itemId === itemId);
  if (!card || card.status !== "已忽略") return;

  try {
    await unignoreInterviewItemApi(getInterviewSessionId(), itemId);
    restoreIgnoredSuggestion(itemId);
  } catch {
    ElMessage.error("取消忽略失败，请稍后重试");
  }
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
  clearIdleWarning();
  stopInterviewTimer();
  if (isMicrophoneEnabled.value) sendListenState("stop");
  stopRecording();
  websocket.close();
});

const handleBack = () => {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  router.push("/home");
};

const setMode = (mode: string) => {
  if (mode !== "转录") return;
  activeMode.value = mode;
  void scrollTranscriptToTop();
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
  } catch {
    return;
  }

  try {
    await endInterviewApi(getInterviewSessionId());
  } catch {
    ElMessage.error("结束访谈失败，请稍后重试");
    return;
  }

  stopInterviewTimer();
  isInterviewStarted.value = false;
  if (isMicrophoneEnabled.value) sendListenState("stop");
  stopRecording();
  websocket.close();
  router.push("/home");
};

const getInterviewDetail = async () => {
  const id = route.params.id as string;
  if (!id) return;
  const res = await getInterviewDetailApi(id);
  interviewDetail.value = res;
  suggestionCards.value = createSuggestionCards(res);
  transcriptEntries.value = createTranscriptEntries(res.transcript);
  void scrollTranscriptToTop();
};

onMounted(() => {
  getInterviewDetail();
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
          <h1 class="page-title">
            {{ interviewDetail?.base_info?.title || "访谈" }}
          </h1>
        </div>
      </header>

      <main class="workspace">
        <aside class="left-panel glass-card">
          <div class="left-panel-header">
            <div class="panel-title">
              <component :is="aiLineIcon" class="panel-icon" />
              <span>AI 追问建议与覆盖</span>
              <span
                v-if="isCoachingRecomputing"
                class="panel-status panel-status-thinking"
              >
                AI 思考中
              </span>
              <span
                v-if="idleWarningSeconds !== null"
                class="panel-status panel-status-idle"
              >
                即将暂停 {{ idleWarningSeconds }} 秒
              </span>
            </div>
            <!-- <el-button
              class="panel-action"
              text
              :icon="Plus"
              @click="handleMockNewSuggestion"
            >
              模拟新建议
            </el-button> -->
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
                :key="`${item.itemId}-${item.status}`"
                class="suggestion-card"
                :class="{
                  ignored: item.status === '已忽略',
                  covered: item.status === '已覆盖'
                }"
              >
                <div class="suggestion-head">
                  <h3 class="suggestion-title">
                    <span class="suggestion-title-text">{{ item.title }}</span>
                    <component
                      :is="newItemIcon"
                      v-if="item.isNew && item.status === '待追问'"
                      class="suggestion-new-icon"
                      aria-label="新增问题"
                    />
                  </h3>
                  <span class="suggestion-tag" :class="item.tagClass">
                    {{ item.tag }}
                  </span>
                </div>
                <p v-if="item.goal" class="suggestion-goal">
                  <strong>追问目的：</strong>
                  <span>{{ item.goal }}</span>
                </p>
                <p class="suggestion-hint">{{ item.hint }}</p>
                <div
                  v-if="
                    (item.isNew && item.status === '待追问') ||
                    item.status === '待追问' ||
                    item.status === '已忽略' ||
                    item.ignoreCountdown !== null
                  "
                  class="suggestion-head-actions"
                >
                  <button
                    v-if="
                      item.status === '待追问' ||
                      item.status === '已忽略' ||
                      item.ignoreCountdown !== null
                    "
                    type="button"
                    class="suggestion-ignore-button"
                    :class="{ countdown: item.ignoreCountdown !== null }"
                    :aria-label="
                      item.ignoreCountdown !== null
                        ? '撤销忽略'
                        : item.status === '已忽略'
                          ? '取消忽略'
                          : '忽略问题'
                    "
                    @click="
                      item.ignoreCountdown !== null
                        ? handleUndoIgnore(item.itemId)
                        : item.status === '已忽略'
                          ? handleUnignoreSuggestion(item.itemId)
                          : handleIgnoreSuggestion(item.itemId)
                    "
                  >
                    <component
                      :is="ignoreIcon"
                      v-if="item.status !== '已忽略'"
                      class="suggestion-ignore-icon"
                    />
                    <span>{{
                      item.ignoreCountdown !== null
                        ? `${item.ignoreCountdown}s`
                        : item.status === "已忽略"
                          ? "取消忽略"
                          : "忽略"
                    }}</span>
                  </button>
                </div>
              </article>
            </TransitionGroup>
          </el-scrollbar>
        </aside>

        <section class="right-panel">
          <div class="session-bar glass-card">
            <div class="session-meta">
              <div class="session-meta-item session-meta-interviewee">
                <div class="session-meta-copy">
                  <span class="session-meta-label">
                    <User class="session-meta-icon" />
                    <span>受访者</span>
                  </span>
                  <strong>{{
                    interviewDetail?.base_info?.interviewee || "--"
                  }}</strong>
                </div>
              </div>
              <div
                v-if="startedAtDisplay !== '--'"
                class="session-meta-item session-meta-time"
              >
                <div class="session-meta-copy">
                  <span class="session-meta-label">
                    <Calendar class="session-meta-icon" />
                    <span>访谈时间</span>
                  </span>
                  <strong>{{ startedAtDisplay }}</strong>
                </div>
              </div>
              <div class="session-meta-item session-meta-goal">
                <div class="session-meta-copy">
                  <span class="session-meta-label">
                    <Aim class="session-meta-icon" />
                    <span>访谈目标</span>
                  </span>
                  <strong>{{ interviewDetail?.goal || "--" }}</strong>
                </div>
              </div>
            </div>

            <div class="session-actions">
              <span class="transcribing-badge" :class="interviewStatusClass">
                <span class="transcribing-main">
                  <span class="transcribing-dot" />
                  <span>访谈中</span>
                </span>
                <small>{{ interviewStatusText }}</small>
              </span>
              <el-button
                class="session-action-button session-action-secondary"
                :icon="VideoPlay"
                :disabled="isInterviewStarted"
                @click="handleStartInterview"
              >
                <span class="session-action-label">{{
                  startInterviewButtonText
                }}</span>
              </el-button>
              <el-button
                class="session-action-button session-action-secondary"
                :icon="isMicrophoneEnabled ? microphoneIcon : microphoneOffIcon"
                :disabled="!isInterviewStarted || !isWebSocketConnected"
                @click="toggleMicrophone"
              >
                <span class="session-action-label session-microphone-label">
                  {{ isMicrophoneEnabled ? "关闭麦克风" : "开启麦克风" }}
                </span>
              </el-button>
              <el-button
                type="primary"
                class="session-action-button session-action-primary"
                :icon="SwitchButton"
                @click="handleEndInterview"
              >
                <span class="session-action-label">结束访谈</span>
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
                  :disabled="mode !== '转录'"
                  :title="mode !== '转录' ? `${mode}功能暂未开放` : undefined"
                  @click="setMode(mode)"
                >
                  {{ mode }}
                </button>
              </div>
            </div>

            <el-scrollbar
              v-if="!isKeyboardMode && !isHandwritingMode"
              ref="transcriptScrollRef"
              class="transcript-scroll"
            >
              <div class="transcript-list">
                <article
                  v-for="item in transcriptEntries"
                  :key="item.segId"
                  class="transcript-item"
                >
                  <div class="transcript-content">
                    <div class="transcript-meta">
                      <time>{{ item.time }}</time>
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
  padding: 38px 16px 0;
  background: url("@/assets/images/bg.png") no-repeat;
  background-size: cover;
  overflow: hidden;
}

.interview-page {
  .page-shell {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: calc(100vh - 56px);
    min-height: calc(100vh - 56px);
  }

  .page-header {
    display: flex;
    align-items: flex-start;
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
    font-size: 24px;
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

  .panel-status {
    display: inline-flex;
    align-items: center;
    min-height: 20px;
    padding: 0 7px;
    font-size: 11px;
    font-weight: 600;
    line-height: 20px;
    color: #64748b;
    background: rgb(241 245 249 / 88%);
    border-radius: 10px;
  }

  .panel-status-thinking {
    color: #d97706;
    background: rgb(255 247 237 / 92%);
  }

  .panel-status-idle {
    color: #b45309;
    background: rgb(254 249 195 / 94%);
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
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
  }

  .suggestion-head-actions {
    display: inline-flex;
    margin-top: 10px;
    gap: 12px;
    align-items: center;
    justify-content: flex-end;
    min-height: 26px;
  }

  /* .suggestion-head-actions::before {
  width: 1px;
  height: 22px;
  content: "";
  background: rgb(148 163 184 / 35%);
} */

  .suggestion-title {
    display: flex;
    gap: 5px;
    align-items: center;
    min-width: 0;
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    line-height: 1.5;
    color: #24324a;
    overflow-wrap: anywhere;
  }

  .suggestion-title-text {
    min-width: 0;
    overflow-wrap: anywhere;
    vertical-align: middle;
  }

  .suggestion-tag {
    display: inline-flex;
    grid-column: 2;
    grid-row: 1;
    align-self: center;
    align-items: center;
    justify-content: center;
    justify-self: end;
    white-space: nowrap;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    border-radius: 14px;
  }

  .suggestion-tag.warning {
    color: #d97706;
    background: rgb(245 158 11 / 14%);
  }

  .suggestion-new-icon {
    display: inline-block;
    flex: 0 0 34px;
    width: 34px;
    height: 34px;
    vertical-align: middle;
    color: #dc2626;
  }

  .suggestion-new-icon :deep(svg) {
    display: block;
    width: 100%;
    height: 100%;
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

  .suggestion-card.covered .suggestion-title {
    color: #0f172a;
  }

  .suggestion-card.covered .suggestion-goal,
  .suggestion-card.covered .suggestion-hint {
    color: #5b7288;
  }

  .suggestion-card.ignored .suggestion-title,
  .suggestion-card.ignored .suggestion-goal,
  .suggestion-card.ignored .suggestion-hint {
    color: #94a3b8;
  }

  .suggestion-goal {
    margin-top: 12px;
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
    gap: 18px;
    min-width: 0;
    padding: 18px 22px;
  }

  .session-meta {
    display: flex;
    flex: 1;
    gap: 0;
    align-items: stretch;
    min-width: 0;
  }

  .session-meta-item {
    display: flex;
    align-items: flex-start;
    min-width: 0;
    padding: 2px 18px;
    border-right: 1px solid rgb(203 213 225 / 72%);
  }

  .session-meta-item:first-child {
    padding-left: 0;
  }

  .session-meta-item:last-child {
    padding-right: 0;
    border-right: 0;
  }

  .session-meta-interviewee,
  .session-meta-time {
    flex: 0 0 auto;
  }

  .session-meta-goal {
    flex: 1 1 230px;
  }

  .session-meta-icon {
    flex: 0 0 auto;
    width: 14px;
    height: 14px;
    color: #334155;
  }

  .session-meta-copy {
    display: grid;
    gap: 6px;
    min-width: 0;
    align-content: start;
  }

  .session-meta-label {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    height: 17px;
    font-size: 12px;
    line-height: 1.25;
    color: #64748b;
  }

  .session-meta-copy strong {
    overflow: hidden;
    font-size: 13px;
    font-weight: 600;
    line-height: 1.35;
    color: #334155;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .session-meta-goal .session-meta-copy strong {
    display: -webkit-box;
    overflow: hidden;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .session-actions {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-shrink: 0;
    margin-left: auto;
  }

  .transcribing-badge {
    display: inline-flex;
    flex-direction: column;
    gap: 2px;
    align-items: center;
    justify-content: center;
    min-width: 104px;
    height: 56px;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 600;
    color: #334155;
    background: rgb(255 255 255 / 92%);
    border: 1px solid rgb(219 227 240 / 95%);
    border-radius: 8px;
  }

  .transcribing-main {
    display: inline-flex;
    gap: 7px;
    align-items: center;
  }

  .transcribing-badge small {
    font-size: 12px;
    font-weight: 400;
    color: #64748b;
  }

  .transcribing-badge.status-created {
    color: #722ed1;
  }

  .transcribing-badge.status-created .transcribing-dot {
    background: #722ed1;
    box-shadow: none;
    animation: none;
  }

  .transcribing-badge.status-in_progress {
    color: #409eff;
  }

  .transcribing-badge.status-in_progress .transcribing-dot {
    background: #409eff;
    box-shadow: none;
  }

  .transcribing-badge.status-suspended {
    color: #d48806;
  }

  .transcribing-badge.status-suspended .transcribing-dot {
    background: #d48806;
    box-shadow: none;
    animation: none;
  }

  .transcribing-badge.status-ended {
    color: #8c8c8c;
  }

  .transcribing-badge.status-ended .transcribing-dot {
    background: #8c8c8c;
    box-shadow: none;
    animation: none;
  }

  .transcribing-dot {
    width: 10px;
    height: 10px;
    background: #10b981;
    border-radius: 999px;
    box-shadow: 0 0 0 4px rgb(16 185 129 / 14%);
    animation: transcribingPulse 1.6s ease-in-out infinite;
  }

  .session-action-button.el-button {
    flex-direction: column;
    gap: 5px;
    min-width: 92px;
    height: 56px;
    margin-left: 0;
    padding: 8px 12px;
    font-weight: 600;
    border-radius: 8px;
  }

  .session-action-button .el-icon,
  .session-action-button :deep(svg) {
    width: 18px;
    height: 18px;
  }

  .session-action-secondary.el-button {
    color: #2563eb;
    background: rgb(239 246 255 / 94%);
    border-color: transparent;
  }

  .session-action-secondary.el-button:hover,
  .session-action-secondary.el-button:focus-visible {
    color: #1d4ed8;
    background: rgb(219 234 254 / 98%);
    border-color: transparent;
  }

  .session-action-primary.el-button {
    background: #2878e8;
    border-color: #2878e8;
  }

  .session-action-primary.el-button:hover,
  .session-action-primary.el-button:focus-visible {
    background: #1f6ed8;
    border-color: #1f6ed8;
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

  .mode-button:disabled {
    cursor: not-allowed;
    opacity: 0.45;
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
    padding: 6px 12px 0 6px;
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
    display: block;
    padding: 14px 16px;
    border-bottom: 1px solid rgb(221 226 236 / 84%);
  }

  .transcript-item:last-child {
    border-bottom: 0;
  }

  .transcript-content {
    min-width: 0;
  }

  .transcript-meta {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
  }

  .transcript-meta time {
    font-size: 13px;
    font-weight: 600;
    color: #94a3b8;
  }

  .transcript-content p {
    margin: 0;
    font-size: 14px;
    line-height: 1.75;
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

@media (max-width: 1400px) {
  .interview-page .session-bar {
    gap: 12px;
    padding: 12px 16px;
  }

  .interview-page .session-meta-time {
    display: none;
  }

  .interview-page .session-meta-item {
    padding: 2px 10px;
  }

  .interview-page .session-action-button.el-button {
    flex-direction: row;
    gap: 6px;
    min-width: 80px;
    height: 40px;
    padding: 0 10px;
  }

  .interview-page .session-action-button .el-icon,
  .interview-page .session-action-button :deep(svg) {
    width: 16px;
    height: 16px;
  }

  .interview-page .transcribing-badge {
    min-width: 82px;
    height: 45px;
    padding: 0 10px;
  }
}

@media (max-width: 1280px) {
  .interview-page .workspace {
    grid-template-columns: 400px minmax(0, 1fr);
  }

  .interview-page .session-meta-item {
    padding: 2px 12px;
  }

  .interview-page .session-action-button.el-button {
    min-width: 40px;
    padding: 8px 10px;
  }

  .interview-page .session-microphone-label {
    font-size: 0;
  }

  .interview-page .session-microphone-label::after {
    font-size: 13px;
    content: "麦克风";
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
    width: 100%;
  }

  .interview-page .session-meta {
    width: 100%;
  }

  .interview-page .session-meta-goal {
    min-width: 0;
  }

  .interview-page .page-title {
    font-size: 17px;
  }

  .interview-page .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .interview-page .suggestion-head {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .interview-page .suggestion-tag {
    grid-column: 2;
    justify-self: end;
  }

  .interview-page .suggestion-head-actions {
    grid-column: 2 / -1;
    grid-row: 2;
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
    padding: 12px 8px;
  }

  .interview-page .session-bar {
    padding: 14px;
  }

  .interview-page .session-meta-time {
    display: none;
  }

  .interview-page .session-meta-item {
    padding: 2px 12px;
  }

  .interview-page .session-actions {
    justify-content: space-between;
  }

  .interview-page .session-action-button.el-button {
    flex: 1;
    min-width: 0;
    height: 36px;
  }

  .interview-page .transcribing-badge {
    width: 76px;
    min-width: 76px;
    padding: 0 6px;
    font-size: 12px;
  }

  .interview-page .transcribing-badge small {
    display: none;
  }

  .interview-page .transcribing-main {
    gap: 5px;
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
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .interview-page .session-meta-goal {
    display: none;
  }

  .interview-page .session-actions {
    gap: 6px;
  }

  .interview-page .session-action-label {
    display: none;
  }

  .interview-page .session-action-button.el-button {
    height: 40px;
    padding: 0;
  }
}
</style>
