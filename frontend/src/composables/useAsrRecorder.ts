import { onBeforeUnmount, ref, shallowRef } from "vue";
import { useAudioRecorder } from "@/composables/useAudioRecorder";
import { useUserStoreHook } from "@/store/modules/user";

/** 停止后等待尾句转写到达的缓冲时间 */
const TRAILING_RESULT_DELAY_MS = 800;

export type AsrRecorderState = "idle" | "recording" | "stopping";

/** /ws/v1/asr 服务端消息：逐句转写 + 60s 上限自动停止通知 */
interface AsrServerMessage {
  type: "asr" | "stopped";
  text?: string;
  final?: boolean;
}

const getAsrWebSocketUrl = () => {
  // 与 useWebSocket.getInterviewWebSocketUrl 同款构造：dev 走 vite 代理，prod 走反代
  if (typeof window === "undefined") return undefined;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/v1/asr`;
};

/**
 * 创建访谈表单的语音转写录音。
 *
 * 协议（backend/app/transport/websocket/asr_handler.py）：
 *   鉴权与访谈会话 WS 同款——token 走 Sec-WebSocket-Protocol 子协议
 *   bearer.<jwt>，缺失/无效握手被 403 拒绝；无 hello 握手，客户端直发原始
 *   WebM 二进制分片（无 4 字节 seq 头，区别于访谈会话 WS），服务端回推
 *   {type:"asr",text} 与 {type:"stopped"}（60s 上限自动停）。
 */
export function useAsrRecorder() {
  const state = ref<AsrRecorderState>("idle");
  const transcript = ref("");
  const elapsedSeconds = ref(0);
  const error = ref<Error | null>(null);
  // 停止来源：用户主动停止，还是服务端断开（60s 上限 / ASR 服务不可用）
  const stopReason = ref<"user" | "server">("user");
  // start() 完整成功过才允许服务端断开触发自动提取（启动即断开按失败处理）
  const everRecorded = ref(false);

  const ws = shallowRef<WebSocket | null>(null);
  let transcriptParts: string[] = [];
  let durationTimer: number | null = null;
  let stopPromise: Promise<string> | null = null;

  const {
    mediaStream,
    isRecording,
    error: recorderError,
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
      // 原始分片直发（无 seq 头）；仅在连接存活时发送
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN) return;
      const buffer = await audio.arrayBuffer();
      if (ws.value?.readyState === WebSocket.OPEN) {
        ws.value.send(buffer);
      }
    }
  });

  const clearDurationTimer = () => {
    if (durationTimer !== null) {
      window.clearInterval(durationTimer);
      durationTimer = null;
    }
  };

  const handleServerMessage = (event: MessageEvent) => {
    if (typeof event.data !== "string") return;

    let message: AsrServerMessage;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }

    if (message.type === "asr" && message.text) {
      transcriptParts.push(message.text);
      transcript.value = transcriptParts.join(" ");
    } else if (message.type === "stopped") {
      // 服务端 60s 上限：视同用户主动停止
      void stop("server");
    }
  };

  /** 停止录音并返回最终转写文本（幂等：重复调用返回同一 Promise）。 */
  const stop = (reason: "user" | "server" = "user"): Promise<string> => {
    if (stopPromise) return stopPromise;
    stopReason.value = reason;

    state.value = "stopping";
    stopPromise = (async () => {
      stopRecording();
      const socket = ws.value;
      ws.value = null;
      if (socket) {
        // onclose/onerror 先摘（ws.value 已置空，断开事件不会二次触发 stop）；
        // onmessage 保留到下方尾句窗口结束——关闭握手期间仍在途的最后一句
        // asr 帧要照常进 transcript（对齐 backend/static/index.html recordStop）
        socket.onclose = null;
        socket.onerror = null;
        if (socket.readyState === WebSocket.OPEN) {
          try {
            socket.close();
          } catch {
            // 关闭失败由 unmount 兜底
          }
        }
      }
      clearDurationTimer();
      // 尾句兜底：等最后一段转写推达再交给提取流程
      await new Promise(resolve =>
        setTimeout(resolve, TRAILING_RESULT_DELAY_MS)
      );
      if (socket) socket.onmessage = null; // 窗口结束，之后到帧不再计入
      state.value = "idle";
      return transcript.value;
    })();
    return stopPromise;
  };

  /** 取消录音，不提取转写结果，立即释放麦克风和 WebSocket。 */
  const cancel = () => {
    stopRecording();
    clearDurationTimer();

    const socket = ws.value;
    ws.value = null;
    stopPromise = null;

    if (socket) {
      // 连接仍在建立时，保留初始 onclose 以结束 start() 的等待。
      if (socket.readyState !== WebSocket.CONNECTING) {
        socket.onmessage = null;
        socket.onclose = null;
        socket.onerror = null;
      }
      try {
        socket.close();
      } catch {
        // 忽略：连接可能已经关闭
      }
    }

    state.value = "idle";
  };

  const start = async () => {
    if (state.value !== "idle") return false;

    const url = getAsrWebSocketUrl();
    if (!url) {
      error.value = new Error("WebSocket unavailable");
      return false;
    }

    // token 只走子协议（与 useWebSocket 同款）：服务端在 accept 前校验
    const token = useUserStoreHook().accessToken;
    if (!token) {
      error.value = new Error("Not authenticated");
      return false;
    }

    transcriptParts = [];
    transcript.value = "";
    elapsedSeconds.value = 0;
    stopPromise = null;
    stopReason.value = "user";
    everRecorded.value = false;
    error.value = null;

    // 先建 WS，等 onopen 再开麦，避免开头音频帧被丢掉
    const socket = new WebSocket(url, [`bearer.${token}`]);
    socket.binaryType = "arraybuffer";
    ws.value = socket;

    const opened = await new Promise<boolean>(resolve => {
      let settled = false;
      const settle = (value: boolean) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      socket.onopen = () => settle(true);
      socket.onerror = () => settle(false);
      socket.onclose = () => settle(false);
    });

    if (!opened || ws.value !== socket) {
      error.value = new Error("ASR WebSocket connection failed");
      if (ws.value === socket) ws.value = null;
      return false;
    }

    socket.onmessage = handleServerMessage;
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (ws.value === socket) {
        ws.value = null;
        void stop("server");
      }
    };

    const started = await startRecording();
    if (!started || ws.value !== socket) {
      // 开麦失败，或开麦期间连接已被服务端关闭（如 ASR 服务未启动）
      error.value = recorderError.value ?? new Error("ASR connection lost");
      stopRecording();
      if (ws.value === socket) {
        socket.onclose = null;
        socket.close();
        ws.value = null;
      }
      return false;
    }

    everRecorded.value = true;
    state.value = "recording";
    durationTimer = window.setInterval(() => {
      elapsedSeconds.value += 1;
    }, 1000);
    return true;
  };

  onBeforeUnmount(() => {
    clearDurationTimer();
    if (ws.value) {
      const socket = ws.value;
      ws.value = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      try {
        socket.close();
      } catch {
        // 忽略：组件销毁时连接可能已断
      }
    }
  });
  // useAudioRecorder 自带 onBeforeUnmount(stopRecording)，麦克风无需重复清理

  return {
    mediaStream,
    isRecording,
    state,
    transcript,
    elapsedSeconds,
    stopReason,
    everRecorded,
    // 暴露底层录音错误，供表单页区分非安全源和普通失败。
    error,
    start,
    stop,
    cancel
  };
}
