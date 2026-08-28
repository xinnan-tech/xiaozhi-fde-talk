<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import dayjs from "dayjs";
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
import VideoPause from "~icons/ep/video-pause";
import CircleCheck from "~icons/ep/circle-check";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import ReSegmented from "@/components/ReSegmented";
import LayFooter from "@/layout/components/lay-footer/index.vue";
import { extractBackendError } from "@/utils/error";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  endInterviewApi,
  firstBatchInterviewApi,
  getInterviewDetailApi,
  ignoreInterviewItemApi,
  type InterviewDetailItem,
  type InterviewDetailType,
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
const { locale, t } = useI18n();
const backIcon = useRenderIcon("heroicons:arrow-long-left");
const eraserIcon = useRenderIcon("boxicons:eraser-filled");
const handwritingIcon = useRenderIcon("boxicons:pencil-draw");
const ignoreIcon = useRenderIcon("lucide:eye-off");
const aiLineIcon = useRenderIcon("si:ai-line");
const newItemIcon = useRenderIcon("clarity:new-solid");

/** 访谈详情 */
const interviewDetail = ref<InterviewDetailType>();
const startedAtDisplay = computed(() => {
  const startedAt = interviewDetail.value?.started_at;
  return startedAt ? dayjs(startedAt).format("YYYY-MM-DD HH:mm:ss") : "--";
});
const interviewStatusClass = computed(() => {
  const status = interviewDetail.value?.status;
  switch (status) {
    case "in_progress":
      return "status-in_progress";
    case "suspended":
      return "status-suspended";
    case "ended":
    case "extracting":
    case "done":
      return "status-ended";
    case "created":
    case "setting_up":
      return "status-created";
    default:
      return "";
  }
});

const controlButtonText = computed(() => {
  switch (interviewDetail.value?.status) {
    case "in_progress":
      return t("interview.action.pause");
    case "suspended":
      return t("interview.action.continue");
    case "ended":
    case "extracting":
    case "done":
      return t("interview.status.ended");
    default:
      return t("interview.action.start");
  }
});

const controlButtonIcon = computed(() => {
  switch (interviewDetail.value?.status) {
    case "in_progress":
      return VideoPause;
    case "suspended":
      return VideoPlay;
    case "ended":
    case "extracting":
    case "done":
      return CircleCheck;
    default:
      return VideoPlay;
  }
});

const isControlButtonDisabled = computed(() => {
  const status = interviewDetail.value?.status;
  return (
    !status ||
    status === "ended" ||
    status === "extracting" ||
    status === "done"
  );
});
const isInterviewInProgress = computed(
  () => interviewDetail.value?.status === "in_progress"
);
const activeMode = ref("transcript");
const activeModeIndex = ref(2);
type SuggestionStatus = InterviewDetailItem["status"];
type SuggestionMetric = SuggestionStatus | "all" | "pending";

const activeMetric = ref<SuggestionMetric>("pending");
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
  status: SuggestionStatus;
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
): SuggestionStatus => {
  if (ignoredIds.has(item.id)) return "ignored";
  return item.status as SuggestionStatus;
};

const suggestionStatusKey = (status: SuggestionStatus) => {
  switch (status) {
    case "new":
      return "interview.suggestion.pending";
    case "todo":
      return "interview.suggestion.pending";
    case "done":
      return "interview.suggestion.covered";
    case "ignored":
      return "interview.suggestion.ignored";
    case "skipped":
      return "interview.suggestion.skipped";
    default:
      return "interview.suggestion.pending";
  }
};

const suggestionStatusLabel = (status: SuggestionStatus) =>
  t(suggestionStatusKey(status));

const isPendingStatus = (status: SuggestionStatus) =>
  status === "new" || status === "todo";

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
      status === "done"
        ? "success"
        : status === "ignored" || status === "skipped"
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
        return !existingCards.has(item.id) && isPendingStatus(status);
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
const isFirstBatchPending = ref(false);
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

const startInterviewTimer = (reset = true) => {
  stopInterviewTimer();
  if (reset) interviewElapsedSeconds.value = 0;
  interviewTimerId = window.setInterval(() => {
    interviewElapsedSeconds.value += 1;
  }, 1000);
};

const handleStartInterview = async () => {
  // 会话已结束时不可重启：等待确认期间后端可能再推 session.ended，
  // 此处若不拦就把 ended 改回 in_progress，状态机被弹框异步路径撕坏。
  // 每个 await 之后再各查一次，覆盖 acquireStream / openMicrophone 窗口。
  if (interviewDetail.value?.status === "ended") return;
  if (isInterviewStarted.value) return;
  isInterviewStarted.value = true;
  const wasSuspended = interviewDetail.value?.status === "suspended";
  startInterviewTimer(!wasSuspended);

  // 在点击事件中立即请求权限，避免等待 WebSocket 握手后丢失浏览器用户手势。
  shouldResumeMicrophone.value = true;
  const microphoneStarted = await acquireStream();
  // 显式标注 string | undefined，避免 TS 沿入口守卫控制流把 ended /
  // suspended 收窄掉——handleServerMessage 在 await 期间可异步改写 status。
  const statusAfterAcquire: string | undefined = interviewDetail.value?.status;
  // ended 是终态；suspended 仅当「入口非 suspended、await 期间被改写」才算异常：
  // 入口本就是 suspended 的合法 continue 路径要走完重连，否则自废。
  if (
    statusAfterAcquire === "ended" ||
    (statusAfterAcquire === "suspended" && !wasSuspended)
  ) {
    // await 期间后端推了 session.ended / 再次 suspended：handleServerMessage
    // 已清理状态/麦/表（suspended 会另起一个确认框），这里不写回 in_progress。
    shouldResumeMicrophone.value = false;
    isInterviewStarted.value = false;
    stopInterviewTimer();
    return;
  }
  if (!microphoneStarted) {
    shouldResumeMicrophone.value = false;
    isInterviewStarted.value = false;
    stopInterviewTimer();
    ElMessage.error(t("interview.runtime.mic_permission"));
    return;
  }

  if (interviewDetail.value) {
    interviewDetail.value.status = "in_progress";
  }

  // 暂停后 WS 层 isReconnectAllowed=false，需手动复位才能再次重连。
  allowReconnect();
  openWebSocket();

  // WebSocket 已经连接时直接开始监听；尚未连接时由 onConnected 处理。
  if (isWebSocketConnected.value) {
    const listeningStarted = await openMicrophone();
    const statusAfterMic: string | undefined = interviewDetail.value?.status;
    if (
      statusAfterMic === "ended" ||
      (statusAfterMic === "suspended" && !wasSuspended)
    ) {
      // 麦克风热启等待期间后端推了 ended / 再次 suspended，同上不写回。
      shouldResumeMicrophone.value = false;
      isInterviewStarted.value = false;
      stopInterviewTimer();
      return;
    }
    if (listeningStarted) shouldResumeMicrophone.value = false;
  }
};

const handlePauseInterview = () => {
  if (!isInterviewStarted.value) return;
  sendListenState("stop");
  stopRecording();
  isInterviewStarted.value = false;
  stopInterviewTimer();
  if (interviewDetail.value) {
    interviewDetail.value.status = "suspended";
  }
};

const handleControlButtonClick = () => {
  const status = interviewDetail.value?.status;
  if (status === "created" || status === "suspended") {
    void handleStartInterview();
  } else if (status === "in_progress") {
    handlePauseInterview();
  }
};

const metrics = computed<
  Array<{
    label: string;
    value: number;
    tone: string;
    filter: SuggestionMetric;
  }>
>(() => {
  const counts = suggestionCards.value.reduce(
    (acc, item) => {
      acc[item.status] = (acc[item.status] ?? 0) + 1;
      return acc;
    },
    {} as Record<SuggestionStatus, number>
  );

  return [
    {
      label: t("interview.suggestion.pending"),
      value: (counts.new ?? 0) + (counts.todo ?? 0),
      tone: "warn",
      filter: "pending"
    },
    {
      label: t("interview.suggestion.covered"),
      value: counts.done ?? 0,
      tone: "success",
      filter: "done"
    },
    {
      label: t("interview.suggestion.ignored"),
      value: counts.ignored ?? 0,
      tone: "muted",
      filter: "ignored"
    },
    {
      label: t("interview.suggestion.total"),
      value: suggestionCards.value.length,
      tone: "primary",
      filter: "all"
    }
  ];
});

const visibleSuggestionCards = computed(() => {
  if (activeMetric.value === "all") return suggestionCards.value;
  if (activeMetric.value === "pending") {
    return suggestionCards.value.filter(item => isPendingStatus(item.status));
  }
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
  card.status = "todo";
  card.tag = "todo";
  card.tagClass = "warning";
};

const setIgnoredSuggestion = (card: SuggestionCard) => {
  card.status = "ignored";
  card.tag = "ignored";
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
          : t("interview.runtime.speaker", { number: 1 });

      return [
        {
          segId:
            typeof record.seg_id === "string"
              ? record.seg_id
              : `history-${index}`,
          startMs,
          role: speaker,
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

// 接管后获取最新访谈转录
const refreshInterviewTranscript = async () => {
  const sessionId = getInterviewSessionId();
  if (!sessionId) return;

  try {
    const detail = await getInterviewDetailApi(sessionId);
    if (route.params.id !== sessionId) return;

    interviewDetail.value = detail;
    transcriptEntries.value = createTranscriptEntries(detail.transcript);
    void scrollTranscriptToTop();
  } catch (error) {
    console.warn("[InterviewPage] 接管后刷新访谈详情失败", error);
  }
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
    role:
      message.speaker === "unknown"
        ? t("interview.runtime.speaker", { number: 1 })
        : message.speaker,
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
      message || t("interview.runtime.connection_conflict"),
      t("interview.runtime.connection_conflict_title"),
      {
        confirmButtonText: t("interview.runtime.takeover"),
        cancelButtonText: t("home.cancel"),
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
let isSuspendConfirmDialogOpen = false;

const handleAsrUnavailable = async (message: string) => {
  if (isAsrUnavailableDialogOpen) return;

  isAsrUnavailableDialogOpen = true;
  try {
    await ElMessageBox.confirm(
      message || t("interview.runtime.asr_unavailable"),
      t("interview.runtime.asr_unavailable_title"),
      {
        confirmButtonText: t("interview.runtime.go_config"),
        cancelButtonText: t("home.cancel"),
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

// 后端检测到长静默会推 session.suspended：仅更新状态不够明显，弹一个
// 确认框让用户感知到「音频已暂停」、确认后由前端重启麦克风 + WebSocket
// 重连回 in_progress。取消则停留在 suspended 状态，控制按钮仍可继续。
const handleSessionSuspended = async () => {
  if (isSuspendConfirmDialogOpen) return;
  isSuspendConfirmDialogOpen = true;
  try {
    await ElMessageBox.confirm(
      t("interview.runtime.suspend_dialog.message"),
      t("interview.runtime.suspend_dialog.title"),
      {
        confirmButtonText: t("interview.runtime.suspend_dialog.confirm"),
        cancelButtonText: t("interview.runtime.suspend_dialog.cancel"),
        type: "warning"
      }
    );
    // 弹框等待期间后端可能再推 session.ended：用户点「继续」之前再查一次，
    // 命中即 toast 告知「会话已结束」，避免 handleStartInterview 入口守卫
    // 静默吞掉、用户毫无反馈。
    if (interviewDetail.value?.status === "ended") {
      ElMessage.warning(t("interview.runtime.suspend_dialog.ended_while_waiting"));
      return;
    }
    await handleStartInterview();
    // post-await 守卫对 ended 静默 return：handleStartInterview 只回滚
    // 状态不自 toast。这里再查一次 status，给用户感知到「会话已结束」
    // 而非被静默吞掉；正常恢复路径下 status 已被 handleStartInterview
    // 写过 in_progress，不会命中。用 string | undefined 承接避开上面
    // 入口守卫把 ended 收窄掉导致的 TS2367。
    const statusAfterResume: string | undefined = interviewDetail.value?.status;
    if (statusAfterResume === "ended") {
      ElMessage.warning(t("interview.runtime.suspend_dialog.ended_while_waiting"));
    }
  } catch (error) {
    // Element Plus 用户取消 confirm 时 reject 的值是字符串 'cancel' /
    // 'close'（distinguishCancelAndClose 默认 false，只会有 'cancel'）。
    // 其他异常来自 handleStartInterview 内部抛出（除麦权限失败等已被
    // 内部 toast 的路径外），属于意外，需给一条兜底提示并打日志，
    // 否则用户点「继续」后毫无反馈、状态卡死。
    if (error === "cancel" || error === "close") {
      // 弹框被外部关闭（用户取消或 handleServerMessage 主动 close）时，
      // 若关闭原因是后端推了 ended，则需要给一条 ended_while_waiting
      // 兜底提示——handleServerMessage 只 close 弹框不直接 toast，避免
      // 与 post-await 守护路径双弹。
      if (interviewDetail.value?.status === "ended") {
        ElMessage.warning(t("interview.runtime.suspend_dialog.ended_while_waiting"));
      }
      return;
    }
    console.error("[handleSessionSuspended] resume failed:", error);
    ElMessage.error(t("interview.runtime.suspend_dialog.resume_failed"));
  } finally {
    isSuspendConfirmDialogOpen = false;
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
    ElMessage.warning(message.reason || t("interview.runtime.kicked"));
    return;
  }

  if (message.type === "audio.low_level") {
    console.warn("[InterviewPage] 收到低音量提醒", message);
    ElMessage.warning(message.message || t("interview.runtime.low_volume"));
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
    // session.suspended 在弹框流程仍在处理时（用户点继续但
    // handleStartInterview 尚未跑完）跳过 status 覆写与本端 cleanup——
    // 否则 in-flight 的 handleStartInterview 写回 in_progress 时若被
    // 中途再推的 suspended 把 status 翻回去，post-await 守卫因
    // wasSuspended=true 漏命中、函数正常返回，遗留
    // status=suspended / isInterviewStarted=true 的半开状态，用户再
    // 点「继续」会被入口守卫静默吞。session.ended 是终态不受此保护，
    // 永远改写 status 并清理。
    const skipLocalCleanup =
      message.type === "session.suspended" && isSuspendConfirmDialogOpen;
    if (!skipLocalCleanup && interviewDetail.value) {
      interviewDetail.value.status =
        message.type === "session.ended" ? "ended" : "suspended";
      shouldResumeMicrophone.value = false;
      stopRecording();
      isInterviewStarted.value = false;
      stopInterviewTimer();
    }
    // ended 落地时如果弹框仍开着（用户在等点「继续」或 handleStartInterview
    // 在 await 窗口），主动关掉弹框——否则 dialog 文案「暂停」与 status=ended
    // 撕裂、用户点取消 finally 关弹框全程无 ended 反馈。toast 由
    // handleSessionSuspended 的 catch / post-await re-check 统一发，避免
    // 与 post-await 守护路径双弹。
    if (message.type === "session.ended" && isSuspendConfirmDialogOpen) {
      ElMessageBox.close();
    }
    if (message.type === "session.suspended") {
      void handleSessionSuspended();
    }
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
      else suspendLocalInterview();
    });
  },
  onTakeoverCompleted: () => {
    void refreshInterviewTranscript();
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
  sendAudioFrame,
  allowReconnect
} = websocket;
const isWebSocketConnected = computed(
  () => websocketState.value === "connected"
);

const {
  isRecording: isMicrophoneEnabled,
  acquireStream,
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
    ElMessage.warning(t("interview.runtime.ws_not_connected"));
    return false;
  }
  if (!sendListenState("start")) {
    ElMessage.warning(t("interview.runtime.listen_failed"));
    return false;
  }
  const started = await startRecording();
  if (!started) sendListenState("stop");
  return started;
};

function suspendLocalInterview() {
  shouldResumeMicrophone.value = false;
  stopRecording();
  isInterviewStarted.value = false;
  stopInterviewTimer();
  if (interviewDetail.value?.status === "in_progress") {
    interviewDetail.value.status = "suspended";
  }
}

const resumeInterviewAfterReload = async (detail: InterviewDetailType) => {
  if (detail.status !== "in_progress") return;

  // 页面刷新会丢失组件内状态，但服务端会话仍处于进行中。恢复本地状态并
  // 重新握手，握手完成后由 onConnected 发送 listen:start 和启动录音。
  isInterviewStarted.value = true;
  startInterviewTimer();
  shouldResumeMicrophone.value = true;
  openWebSocket();

  // WebSocket 可能因已有连接而立即可用；否则由 onConnected 接管启动录音。
  if (isWebSocketConnected.value) {
    const started = await openMicrophone();
    if (started) shouldResumeMicrophone.value = false;
    else suspendLocalInterview();
  }
};

const handleIgnoreSuggestion = (itemId: string) => {
  const card = suggestionCards.value.find(item => item.itemId === itemId);
  if (!card || !isPendingStatus(card.status)) return;

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
    } catch (e: unknown) {
      restoreIgnoredSuggestion(itemId);
      // 后端 4xx/5xx 已由 http 响应拦截器统一 toast；这里只在网络层异常时给兜底。
      const hasResponse = (e as { response?: unknown })?.response !== undefined;
      if (!hasResponse) {
        ElMessage.error(t("interview.suggestion.ignore_failed"));
      }
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
  if (!card || card.status !== "ignored") return;

  try {
    await unignoreInterviewItemApi(getInterviewSessionId(), itemId);
    restoreIgnoredSuggestion(itemId);
  } catch (e: unknown) {
    // 后端 4xx/5xx 已由 http 响应拦截器统一 toast；这里只在网络层异常时给兜底。
    const hasResponse = (e as { response?: unknown })?.response !== undefined;
    if (!hasResponse) {
      ElMessage.error(t("interview.suggestion.unignore_failed"));
    }
  }
};

const setMetric = async (metric: SuggestionMetric) => {
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
  if (mode !== "transcript") return;
  activeMode.value = mode;
  void scrollTranscriptToTop();
};

const isKeyboardMode = computed(() => activeMode.value === "keyboard");
const isHandwritingMode = computed(() => activeMode.value === "handwriting");

const transcriptPanelTitle = computed(() => {
  if (isHandwritingMode.value) return t("interview.panel.handwriting");
  return isKeyboardMode.value
    ? t("interview.panel.notes")
    : t("interview.panel.transcript");
});

const modeOptions = computed(() => [
  {
    value: "handwriting",
    label: t("interview.mode.handwriting"),
    disabled: true
  },
  {
    value: "keyboard",
    label: t("interview.mode.keyboard"),
    disabled: true
  },
  {
    value: "transcript",
    label: t("interview.mode.transcript")
  }
]);

const handleModeChange = ({ option }: { option: { value?: unknown } }) => {
  if (typeof option.value === "string") setMode(option.value);
};

const handwritingActions = computed(() => [
  {
    key: "undo",
    label: t("interview.handwriting.undo"),
    icon: RefreshLeft,
    handler: handleUndo
  },
  {
    key: "clear",
    label: t("interview.handwriting.clear"),
    icon: Delete,
    handler: handleClear
  },
  {
    key: "export",
    label: t("interview.handwriting.export"),
    icon: Download,
    handler: handleExportSignature
  }
]);

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
    await ElMessageBox.confirm(
      t("interview.end_confirm"),
      t("interview.end_title"),
      {
        confirmButtonText: t("interview.action.end"),
        cancelButtonText: t("home.cancel"),
        type: "warning"
      }
    );
  } catch {
    return;
  }

  try {
    await endInterviewApi(getInterviewSessionId());
  } catch (e: unknown) {
    ElMessage.error(extractBackendError(e, t("interview.end_failed")));
    return;
  }

  stopInterviewTimer();
  isInterviewStarted.value = false;
  if (isMicrophoneEnabled.value) sendListenState("stop");
  stopRecording();
  websocket.close();
  router.push("/home");
};

const kickFirstBatchIfNeeded = (detail: InterviewDetailType) => {
  // 与测试 harness (static/index_test_harness.html:865) 一致：首评未生成、访谈未开聊、未结束
  // 时预热生成定制问题。LLM 同步调用可能耗时，fire-and-forget，不阻塞页面渲染。
  // 回调里再校验当前 route.params，避免用户中途切访谈把旧结果写回。
  if (
    detail.first_batch_generated ||
    (Array.isArray(detail.transcript) && detail.transcript.length > 0) ||
    detail.status === "ended" ||
    detail.status === "extracting" ||
    detail.status === "done"
  ) {
    return;
  }
  const sessionId = detail.id;
  isFirstBatchPending.value = true;
  void (async () => {
    try {
      const g = await firstBatchInterviewApi(sessionId);
      if (route.params.id !== sessionId) return;
      if (g && g.generated && Array.isArray(g.items)) {
        if (interviewDetail.value) {
          interviewDetail.value.first_batch_generated = true;
          interviewDetail.value.items = g.items;
        }
        suggestionCards.value = createSuggestionCards({
          ...detail,
          items: g.items,
          first_batch_generated: true
        });
        ElMessage.success(t("msg.first_batch_done"));
      } else {
        ElMessage.warning(t("msg.first_batch_partial"));
      }
    } catch (e: unknown) {
      // 后端 4xx/5xx 已由 http 响应拦截器统一 toast；这里只在网络层异常时给兜底。
      const hasResponse = (e as { response?: unknown })?.response !== undefined;
      if (!hasResponse) {
        ElMessage.warning(t("msg.first_batch_partial"));
      }
    } finally {
      if (route.params.id === sessionId) {
        isFirstBatchPending.value = false;
      }
    }
  })();
};

const getInterviewDetail = async () => {
  const id = route.params.id as string;
  if (!id) return;
  const res = await getInterviewDetailApi(id);
  interviewDetail.value = res;
  suggestionCards.value = createSuggestionCards(res);
  transcriptEntries.value = createTranscriptEntries(res.transcript);
  void scrollTranscriptToTop();
  kickFirstBatchIfNeeded(res);
  await resumeInterviewAfterReload(res);
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
            {{ $t("interview.back") }}
          </el-button>
          <h1 class="page-title">
            {{
              interviewDetail?.base_info?.title || $t("interview.default_title")
            }}
          </h1>
        </div>
      </header>

      <main class="workspace">
        <aside class="left-panel glass-card">
          <div class="left-panel-header">
            <div class="panel-title">
              <component :is="aiLineIcon" class="panel-icon" />
              <span>{{ $t("interview.panel.coaching") }}</span>
              <span
                v-if="isCoachingRecomputing"
                class="panel-status panel-status-thinking"
              >
                {{ $t("interview.panel.thinking") }}
              </span>
              <span
                v-if="isFirstBatchPending"
                class="panel-status panel-status-thinking"
              >
                {{ $t("msg.first_batch_running") }}
              </span>
              <span
                v-if="idleWarningSeconds !== null"
                class="panel-status panel-status-idle"
              >
                {{
                  $t("interview.panel.pause_in", {
                    seconds: idleWarningSeconds
                  })
                }}
              </span>
            </div>
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
                  ignored: item.status === 'ignored',
                  covered: item.status === 'done' || item.status === 'skipped'
                }"
              >
                <component
                  :is="newItemIcon"
                  v-if="item.isNew && isPendingStatus(item.status)"
                  class="suggestion-new-icon"
                  :aria-label="$t('interview.suggestion.new_question')"
                />
                <div class="suggestion-head">
                  <h3 class="suggestion-title">
                    <span class="suggestion-title-text">{{ item.title }}</span>
                  </h3>
                  <span class="suggestion-tag" :class="item.tagClass">
                    {{ suggestionStatusLabel(item.status) }}
                  </span>
                </div>
                <div
                  v-if="
                    item.goal ||
                    (item.isNew && isPendingStatus(item.status)) ||
                    isPendingStatus(item.status) ||
                    item.status === 'ignored' ||
                    item.ignoreCountdown !== null
                  "
                  class="suggestion-goal-row"
                >
                  <p v-if="item.goal" class="suggestion-goal">
                    <strong>{{ $t("interview.suggestion.goal") }}</strong>
                    <span>{{ item.goal }}</span>
                  </p>
                  <div
                    v-if="
                      (item.isNew && isPendingStatus(item.status)) ||
                      isPendingStatus(item.status) ||
                      item.status === 'ignored' ||
                      item.ignoreCountdown !== null
                    "
                    class="suggestion-head-actions"
                  >
                    <button
                      v-if="
                        isPendingStatus(item.status) ||
                        item.status === 'ignored' ||
                        item.ignoreCountdown !== null
                      "
                      type="button"
                      class="suggestion-ignore-button"
                      :class="{ countdown: item.ignoreCountdown !== null }"
                      :aria-label="
                        $t(
                          item.ignoreCountdown !== null
                            ? 'interview.suggestion.undo_ignore'
                            : item.status === 'ignored'
                              ? 'interview.suggestion.unignore'
                              : 'interview.suggestion.ignore'
                        )
                      "
                      @click="
                        item.ignoreCountdown !== null
                          ? handleUndoIgnore(item.itemId)
                          : item.status === 'ignored'
                            ? handleUnignoreSuggestion(item.itemId)
                            : handleIgnoreSuggestion(item.itemId)
                      "
                    >
                      <component
                        :is="ignoreIcon"
                        v-if="item.status !== 'ignored'"
                        class="suggestion-ignore-icon"
                      />
                      <span>{{
                        item.ignoreCountdown !== null
                          ? `${item.ignoreCountdown}s`
                          : item.status === "ignored"
                            ? $t("interview.suggestion.unignore")
                            : $t("interview.suggestion.ignore_short")
                      }}</span>
                    </button>
                  </div>
                </div>
                <p class="suggestion-hint">{{ item.hint }}</p>
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
                    <span>{{ $t("interview.meta.interviewee") }}</span>
                  </span>
                  <strong
                    :title="interviewDetail?.base_info?.interviewee || '--'"
                  >
                    {{ interviewDetail?.base_info?.interviewee || "--" }}
                  </strong>
                </div>
              </div>
              <div
                v-if="startedAtDisplay !== '--'"
                class="session-meta-item session-meta-time"
              >
                <div class="session-meta-copy">
                  <span class="session-meta-label">
                    <Calendar class="session-meta-icon" />
                    <span>{{ $t("interview.meta.start_time") }}</span>
                  </span>
                  <strong>{{ startedAtDisplay }}</strong>
                </div>
              </div>
              <div class="session-meta-item session-meta-goal">
                <div class="session-meta-copy">
                  <span class="session-meta-label">
                    <Aim class="session-meta-icon" />
                    <span>{{ $t("interview.meta.goal") }}</span>
                  </span>
                  <strong :title="interviewDetail?.goal">{{
                    interviewDetail?.goal || "--"
                  }}</strong>
                </div>
              </div>
            </div>

            <div class="session-actions">
              <el-button
                class="session-action-button session-control-button"
                :class="interviewStatusClass"
                :icon="controlButtonIcon"
                :disabled="isControlButtonDisabled"
                @click="handleControlButtonClick"
              >
                <span
                  v-if="isInterviewInProgress"
                  class="rec-badge"
                  aria-hidden="true"
                >
                  <span class="rec-dot" />
                  <span class="rec-text">REC</span>
                </span>
                <span class="session-action-label">{{
                  controlButtonText
                }}</span>
              </el-button>
              <el-button
                type="primary"
                class="session-action-button session-action-primary"
                :icon="SwitchButton"
                @click="handleEndInterview"
              >
                <span class="session-action-label">{{
                  $t("interview.action.end")
                }}</span>
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

              <ReSegmented
                v-model="activeModeIndex"
                :options="modeOptions"
                @change="handleModeChange"
              />
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
                      <span class="seg-id">{{ item.segId }}</span>
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
                  :placeholder="$t('interview.notes.placeholder')"
                  resize="none"
                />
              </div>
            </el-scrollbar>

            <div v-else class="handwriting-shell">
              <div class="handwriting-toolbar">
                <div class="handwriting-toolbar-group">
                  <span class="handwriting-group-label">{{
                    $t("interview.handwriting.common")
                  }}</span>
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
                      <span>
                        {{
                          isEraserMode
                            ? $t("interview.handwriting.erasing")
                            : $t("interview.handwriting.eraser")
                        }}
                      </span>
                    </button>
                  </div>
                </div>

                <div class="handwriting-toolbar-group">
                  <span class="handwriting-group-label">{{
                    $t("interview.handwriting.color")
                  }}</span>
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
  background: url("@/assets/images/bg.webp") no-repeat;
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
    position: relative;
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
    gap: 12px;
    align-items: center;
    justify-content: flex-end;
    min-height: 26px;
    flex-shrink: 0;
  }

  /* .suggestion-head-actions::before {
  width: 1px;
  height: 22px;
  content: "";
  background: rgb(148 163 184 / 35%);
} */

  .suggestion-title {
    display: block;
    min-width: 0;
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    line-height: 1.5;
    color: #24324a;
    overflow-wrap: anywhere;
  }

  .suggestion-title-text {
    overflow-wrap: anywhere;
    vertical-align: middle;
  }

  .suggestion-tag {
    align-self: flex-start;
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
    position: absolute;
    top: -8px;
    left: 6px;
    z-index: 2;
    width: 30px;
    height: 30px;
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

  .suggestion-goal-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-top: 12px;
  }

  .suggestion-goal-row .suggestion-goal {
    flex: 1;
    min-width: 0;
    margin-top: 0;
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

  .session-meta-interviewee {
    flex: 0 1 7em;
    max-width: 7em;
  }

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
    width: 100%;
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
    line-clamp: 2;
    -webkit-line-clamp: 2;
  }

  .session-meta-interviewee .session-meta-copy strong {
    display: -webkit-box;
    overflow: hidden;
    white-space: normal;
    overflow-wrap: anywhere;
    -webkit-box-orient: vertical;
    line-clamp: 2;
    -webkit-line-clamp: 2;
  }

  .session-actions {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-shrink: 0;
    margin-left: auto;
  }

  .session-control-button.el-button {
    min-width: 120px;
    color: #64748b;
    background: #fff;
    border-color: #cbd5e1;
    transition: all 0.2s ease;
  }

  .session-control-button.el-button:hover,
  .session-control-button.el-button:focus-visible {
    color: #475569;
    background: #f1f5f9;
    border-color: #94a3b8;
  }

  .session-control-button.status-created.el-button {
    color: #fff;
    background: #2563eb;
    border-color: #2563eb;
  }

  .session-control-button.status-created.el-button:hover,
  .session-control-button.status-created.el-button:focus-visible {
    color: #fff;
    background: #1d4ed8;
    border-color: #1d4ed8;
  }

  .session-control-button.status-in_progress.el-button {
    color: #fff;
    background: #10b981;
    border-color: #10b981;
    animation: controlButtonPulse 1.6s ease-in-out infinite;
  }

  .session-control-button.status-in_progress.el-button:hover,
  .session-control-button.status-in_progress.el-button:focus-visible {
    color: #fff;
    background: #059669;
    border-color: #059669;
  }

  .session-control-button.status-suspended.el-button {
    color: #fff;
    background: #f59e0b;
    border-color: #f59e0b;
  }

  .session-control-button.status-suspended.el-button:hover,
  .session-control-button.status-suspended.el-button:focus-visible {
    color: #fff;
    background: #d97706;
    border-color: #d97706;
  }

  .session-control-button.status-ended.el-button,
  .session-control-button.status-ended.el-button:hover,
  .session-control-button.status-ended.el-button:focus-visible {
    color: #fff;
    cursor: not-allowed;
    background: #94a3b8;
    border-color: #94a3b8;
  }

  .rec-badge {
    position: absolute;
    top: -6px;
    right: -6px;
    display: inline-flex;
    gap: 3px;
    align-items: center;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 700;
    line-height: 1;
    color: #fff;
    background: #ef4444;
    border-radius: 999px;
    box-shadow: 0 2px 6px rgb(239 68 68 / 40%);
  }

  .rec-dot {
    width: 6px;
    height: 6px;
    background: #fff;
    border-radius: 999px;
    animation: recPulse 1.2s ease-in-out infinite;
  }

  .session-action-button.el-button {
    position: relative;
    flex-direction: column;
    gap: 5px;
    min-width: 92px;
    height: 56px;
    margin-left: 0;
    padding: 8px 12px;
    font-weight: 600;
    border-radius: 8px;
  }

  :deep(.session-action-button.el-button [class*="el-icon"] + span) {
    margin-left: 0 !important;
    margin-inline-start: 0 !important;
  }

  :deep(.session-action-button.el-button > span) {
    margin-left: 0 !important;
    margin-inline-start: 0 !important;
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
    color: #ef4444;
    background: #fff;
    border-color: #ef4444;
  }

  .session-action-primary.el-button:hover,
  .session-action-primary.el-button:focus-visible {
    color: #fff;
    background: #ef4444;
    border-color: #ef4444;
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

  .transcript-head :deep(.pure-segmented) {
    position: relative;
    padding: 4px;
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 22px;
    box-shadow: 0 4px 20px rgb(0 0 0 / 8%);
    backdrop-filter: blur(4px);
  }

  .transcript-head :deep(.pure-segmented-item) {
    border-radius: 18px;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .transcript-head :deep(.pure-segmented-item > div) {
    min-height: 34px;
    padding: 0 20px;
    font-size: 14px;
    font-weight: 500;
    line-height: 34px;
    color: rgb(31 35 41 / 60%);
    transition: color 0.25s;
  }

  .transcript-head :deep(.pure-segmented-item:hover) {
    background: rgb(255 255 255 / 35%);
    border-radius: 18px;
  }

  .transcript-head :deep(.pure-segmented-item-disabled) {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .transcript-head :deep(.pure-segmented-item-disabled:hover) {
    background: transparent;
  }

  .transcript-head :deep(.pure-segmented-item:hover > div) {
    color: rgb(31 35 41 / 85%);
  }

  .transcript-head :deep(.pure-segmented-item-selected > div) {
    color: rgb(31 35 41 / 95%);
  }

  .transcript-head :deep(.pure-segmented-item-selected) {
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 18px;
    box-shadow:
      0 2px 6px rgb(31 35 41 / 8%),
      0 4px 12px rgb(31 35 41 / 6%);
    backdrop-filter: blur(4px);
  }

  .transcript-head :deep(.pure-segmented-group) {
    gap: 6px;
  }

  @keyframes controlButtonPulse {
    0% {
      box-shadow: 0 0 0 0 rgb(16 185 129 / 40%);
    }

    70% {
      box-shadow: 0 0 0 10px rgb(16 185 129 / 0%);
    }

    100% {
      box-shadow: 0 0 0 0 rgb(16 185 129 / 0%);
    }
  }

  @keyframes recPulse {
    0% {
      opacity: 1;
      transform: scale(1);
    }

    50% {
      opacity: 0.5;
      transform: scale(0.75);
    }

    100% {
      opacity: 1;
      transform: scale(1);
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

  .transcript-meta .seg-id {
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

  .interview-page .session-control-button.el-button {
    min-width: 100px;
    height: 40px;
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

  .interview-page .session-control-button.el-button {
    min-width: 0;
    padding: 0 6px;
    font-size: 12px;
  }

  .interview-page .transcript-head {
    padding: 14px;
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
