import { onBeforeUnmount, ref, shallowRef } from "vue";
import { useAudioRecorder } from "@/composables/useAudioRecorder";
import { isBootstrapped } from "@/utils/auth";
import { refreshApi } from "@/api/user";

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

  /** WS 401 重连上限：握手阶段 + 已开麦被服务端 close 各允许一次 refresh 后重连。
   *  refresh 自身若仍 401（refresh cookie 也过期），停止重试，把控制权交还业务
   *  路径（axios 401 拦截器会清 Pinia + 跳登录）。 */
  const MAX_RECONNECT_AFTERS = 1;

  /** WS close code 处理策略：只有 1006/1011 才视为「可能是鉴权失效或服务端
   *  临时抽风」，允许 refreshApi + 重连一次。
   *
   *  - 1000 正常关、1001 端点离开（服务重启）、1005 无 status：业务态决定；
   *    不盲目刷 refresh——服务重启每次录音都刷 refresh 浪费配额。
   *  - 1008 策略违规：脚本 / chaos 客户端误用 subprotocol 之类，与鉴权无关，
   *    不重试。
   *  - 其他 1xxx：服务端 bug，按 1011 同款处理。
   *
   * 早版本对所有 close code 一律 refresh + 重连，被服务重启测试场景打到
   * 后台日志刷一片 refreshApi——记录在 PR 评论里。 */
  const SHOULD_REFRESH_CLOSE_CODES: ReadonlySet<number> = new Set([1006, 1011]);

  /** 触发 refreshApi 换新 access cookie 后再尝试一次 WS 握手。 */
  const refreshAccessAndReconnect = async (
    url: string,
    attempt: number
  ): Promise<WebSocket | null> => {
    if (attempt >= MAX_RECONNECT_AFTERS) return null;
    try {
      await refreshApi();
    } catch (err) {
      // refresh 也 401：refresh cookie 过期 / 被吊销。axios 401 拦截器会接
      // 下来清 Pinia + 跳登录；本端无需继续。
      console.warn(
        "[useAsrRecorder] refreshApi failed, giving up WS reconnect:",
        err
      );
      return null;
    }
    return await openAsrSocketInternal(url, attempt + 1);
  };

  /** 真正发起 WS 握手 + 挂监听。失败由调用方按 attempt 决定是否触发 refresh。 */
  const openAsrSocketInternal = (
    url: string,
    attempt: number
  ): Promise<WebSocket | null> => {
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    ws.value = socket;
    return new Promise<WebSocket | null>(resolve => {
      let settled = false;
      const settle = (value: WebSocket | null) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      socket.onopen = () => {
        // 已开麦前，收到 onopen 才算成功
        settle(socket);
        // 装好业务监听（含后续 close code 分支）
        socket.onmessage = handleServerMessage;
        socket.onerror = () => socket.close();
        socket.onclose = async (event: CloseEvent) => {
          // 服务端中途关闭。按 close code 区分：
          //   - 1006 / 1011：refresh + 重连一次（鉴权中途吊销 / 服务临时抽风）
          //   - 其他：业务态已变（用户停 / 服务重启 / 网络错），直接 stop
          if (ws.value !== socket) return;
          ws.value = null;
          const code = event?.code ?? 1005;
          const shouldRetry =
            SHOULD_REFRESH_CLOSE_CODES.has(code) &&
            attempt < MAX_RECONNECT_AFTERS;
          if (!shouldRetry) {
            void stop("server");
            return;
          }
          const retried = await refreshAccessAndReconnect(url, attempt);
          if (!retried) {
            void stop("server");
          }
        };
      };
      socket.onerror = () => settle(null);
      socket.onclose = () => settle(null);
    });
  };

  /** WS 握手 + 401 自动续 access 重连。握手失败时 refresh + 重连一次。 */
  const openAsrSocketWithRefresh = async (
    url: string,
    attempt: number
  ): Promise<WebSocket | null> => {
    const first = await openAsrSocketInternal(url, attempt);
    if (first) return first;
    // 握手阶段就失败（cookie 已过期 / 被吊销）：先 refresh 再来一次
    return await refreshAccessAndReconnect(url, attempt);
  };

  const start = async () => {
    if (state.value !== "idle") return false;

    const url = getAsrWebSocketUrl();
    if (!url) {
      error.value = new Error("WebSocket unavailable");
      return false;
    }

    // HttpOnly cookie 由浏览器在 WS upgrade 时自动带——服务端
    // transport/websocket/asr_handler.py 优先读 cookie 鉴权；前端不传 token 也可。
    // isBootstrapped() 是「曾成功调过 /auth/me」的乐观判断，cookie 真失效会由
    // 服务端 WS handshake 返 401 / 403 时再处理（前端会拿到 close event）。
    if (!isBootstrapped()) {
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

    // WS 握手 + 401 自动续 access 重连。retry 上限 MAX_RECONNECT_AFTERS：
    // 握手阶段 + 已开麦后被服务端 close（1006）各允许一次 refreshApi 重连。
    // 上限不设大是防后端鉴权整体被改坏后无限循环刷 refresh（refresh 自身有 401
    // 拦截器兜底，但浏览器仍要开 WS、占连接池）。
    const socket = await openAsrSocketWithRefresh(url, 0);
    if (!socket) {
      error.value = new Error("ASR WebSocket connection failed");
      return false;
    }
    // openAsrSocketWithRefresh 已挂 onmessage/onerror/onclose（含 401 重连分支）
    // ——直接进开麦。

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
