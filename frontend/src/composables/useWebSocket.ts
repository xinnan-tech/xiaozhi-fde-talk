import { computed, ref, toValue, type MaybeRefOrGetter } from "vue";
import { useWebSocket as useVueUseWebSocket } from "@vueuse/core";
import { useUserStoreHook } from "@/store/modules/user";

export const INTERVIEW_PROTOCOL_VERSION = 1;
export const MAX_WEBSOCKET_FRAME_SIZE = 64 * 1024;

export interface InterviewAudioParams {
  format: string;
  sample_rate: number;
  channels: number;
  frame_duration: number;
}

export interface InterviewHelloMessage {
  type: "hello";
  client_id: string;
  audio_params?: InterviewAudioParams;
  protocol_version?: number;
}

export interface InterviewAsrMessage {
  type: "asr";
  seg_id: string;
  start_ms: number;
  speaker: string;
  text: string;
  final: boolean;
}

export interface CoachingItem {
  id: string;
  text: string;
  status: "todo" | "new" | "done" | "skipped" | "ignored";
  reason: string;
  priority: number;
  desc: string;
}

export interface CoachingUpdateMessage {
  type: "coaching.update";
  phase: "recomputing" | "final";
  version: number;
  items: CoachingItem[];
  skipped_ack: string[];
}

export interface InterviewErrorMessage {
  type: "error";
  code: string;
  message: string;
}

export type InterviewServerMessage =
  | {
      type: "hello";
      session_id: string;
      audio_params: InterviewAudioParams | Record<string, never>;
      protocol_version: number;
      resume_from_seq: number;
    }
  | InterviewAsrMessage
  | CoachingUpdateMessage
  | InterviewErrorMessage
  | { type: "connection.conflict"; message: string }
  | { type: "connection.kicked"; reason: string }
  | { type: "session.ended"; session_id: string }
  | { type: "session.suspended"; session_id: string }
  | { type: "session.idle_warning"; suspend_in_s: number }
  | { type: "audio.low_level"; dbfs: number; message: string };

export type InterviewConnectionState =
  "idle" | "connecting" | "pending" | "connected" | "reconnecting" | "closed";

export interface useWebSocketOptions {
  interviewId: MaybeRefOrGetter<string>;
  token?: MaybeRefOrGetter<string | undefined>;
  wsBaseUrl?: MaybeRefOrGetter<string | undefined>;
  clientId?: MaybeRefOrGetter<string>;
  audioParams?: InterviewAudioParams;
  immediate?: boolean;
  autoReconnect?: boolean;
  onMessage?: (message: InterviewServerMessage) => void;
  onConnected?: (
    message: Extract<InterviewServerMessage, { type: "hello" }>
  ) => void;
  onTakeoverCompleted?: () => void;
  onDisconnected?: (event: CloseEvent) => void;
  onError?: (message: InterviewErrorMessage) => void;
}

const clientIdStorageKey = "xiaozhi-interview-client-id";

const createClientId = () => {
  if (typeof window === "undefined") return "interview-client";

  const storedClientId = window.sessionStorage.getItem(clientIdStorageKey);
  if (storedClientId) return storedClientId;

  const clientId =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  window.sessionStorage.setItem(clientIdStorageKey, clientId);
  return clientId;
};

export const getInterviewWebSocketUrl = (
  interviewId: string,
  wsBaseUrl?: string
) => {
  const path = `/ws/v1/interview/${encodeURIComponent(interviewId)}`;

  // 显式 wsBaseUrl 走自定义网关；其余一律走运行时宿主（dev vite proxy / prod 反代）
  if (wsBaseUrl) {
    const url = new URL(
      path,
      wsBaseUrl.endsWith("/") ? wsBaseUrl : `${wsBaseUrl}/`
    );
    if (url.protocol === "http:") url.protocol = "ws:";
    if (url.protocol === "https:") url.protocol = "wss:";
    return url.toString();
  }

  if (typeof window === "undefined") return undefined;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
};

const isInterviewServerMessage = (
  value: unknown
): value is InterviewServerMessage => {
  return Boolean(
    value &&
    typeof value === "object" &&
    "type" in value &&
    typeof value.type === "string"
  );
};

export function useWebSocket(options: useWebSocketOptions) {
  const userStore = useUserStoreHook();
  const clientId = toValue(options.clientId) || createClientId();
  const token = toValue(options.token) ?? userStore.accessToken;
  const isReconnectAllowed = ref(options.autoReconnect !== false);
  const isHandshakeComplete = ref(false);
  const isPendingTakeover = ref(false);
  const sequence = ref(0);
  const lastMessage = ref<InterviewServerMessage | null>(null);
  const lastError = ref<InterviewErrorMessage | null>(null);

  const url = computed(() => {
    const interviewId = toValue(options.interviewId);
    return interviewId && token
      ? getInterviewWebSocketUrl(interviewId, toValue(options.wsBaseUrl))
      : undefined;
  });

  const websocket = useVueUseWebSocket<string | ArrayBuffer | Blob>(url, {
    immediate: options.immediate ?? true,
    autoConnect: true,
    autoClose: true,
    protocols: token ? [`bearer.${token}`] : [],
    autoReconnect: {
      retries: (retried: number) => isReconnectAllowed.value && retried < 5,
      delay: (retried: number) => Math.min(1000 * 2 ** retried, 10000)
    },
    onConnected: () => {
      isHandshakeComplete.value = false;
      isPendingTakeover.value = false;
      // 发出 hello
      sendJson({
        type: "hello",
        client_id: clientId,
        audio_params: options.audioParams,
        protocol_version: INTERVIEW_PROTOCOL_VERSION
      });
    },
    onDisconnected: (_ws, event) => {
      isHandshakeComplete.value = false;
      isPendingTakeover.value = false;
      options.onDisconnected?.(event);
    },
    onError: () => undefined,
    onMessage: (_ws, event) => {
      if (typeof event.data !== "string") return;

      let parsedMessage: unknown;
      try {
        parsedMessage = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!isInterviewServerMessage(parsedMessage)) return;

      const message = parsedMessage;
      lastMessage.value = message;
      options.onMessage?.(message);

      if (message.type === "hello") {
        const takeoverCompleted = isPendingTakeover.value;
        // 接管复用现有 WebSocket，不会再次触发底层 onConnected；
        // hello 是接管完成的握手确认，必须同步退出 pending 状态。
        isPendingTakeover.value = false;
        isHandshakeComplete.value = true;
        sequence.value = message.resume_from_seq || 0;
        options.onConnected?.(message);
        if (takeoverCompleted) options.onTakeoverCompleted?.();
      } else if (message.type === "connection.conflict") {
        isPendingTakeover.value = true;
      } else if (message.type === "connection.kicked") {
        isReconnectAllowed.value = false;
        isHandshakeComplete.value = false;
      } else if (message.type === "error") {
        // 服务端发出错误后通常会关闭连接
        // 这时继续重连只会重复触发同一个错误
        isReconnectAllowed.value = false;
        lastError.value = message;
        options.onError?.(message);
      } else if (
        message.type === "session.ended" ||
        message.type === "session.suspended"
      ) {
        isReconnectAllowed.value = false;
      }
    }
  });

  const sendJson = (message: Record<string, unknown>) => {
    return websocket.send(JSON.stringify(message), false);
  };

  const sendListenState = (state: "start" | "stop") => {
    if (!isHandshakeComplete.value) return false;
    if (state === "start") sequence.value = 0;
    return sendJson({ type: "listen", state });
  };

  const sendAudioFrame = (opusPayload: ArrayBuffer | Uint8Array) => {
    if (!isHandshakeComplete.value || websocket.status.value !== "OPEN") {
      return false;
    }

    const payload =
      opusPayload instanceof Uint8Array
        ? opusPayload
        : new Uint8Array(opusPayload);
    const frame = new Uint8Array(4 + payload.byteLength);
    // 前四个字节是大端序的音频序号
    new DataView(frame.buffer).setUint32(0, sequence.value, false);
    frame.set(payload, 4);
    if (frame.byteLength > MAX_WEBSOCKET_FRAME_SIZE) return false;

    const sent = websocket.send(frame.buffer, false);
    if (sent) sequence.value += 1;
    return sent;
  };

  const skipCoachingItem = (id: string) =>
    isHandshakeComplete.value && sendJson({ type: "coaching.skip", id });

  const ignoreCoachingItem = (id: string) =>
    isHandshakeComplete.value && sendJson({ type: "coaching.ignore", id });

  const takeover = () =>
    isPendingTakeover.value && sendJson({ type: "connection.takeover" });

  const allowReconnect = () => {
    // 手动恢复可重连：被 session.suspended / error / connection.kicked 禁用后，
    // 用户从暂停弹框选「继续」时需复位，下一次断开 autoReconnect 才能再触发。
    isReconnectAllowed.value = true;
  };

  const close = (code?: number, reason?: string) => {
    isReconnectAllowed.value = false;
    websocket.close(code, reason);
  };

  const state = computed<InterviewConnectionState>(() => {
    if (isPendingTakeover.value) return "pending";
    if (websocket.status.value === "CONNECTING") {
      return websocket.ws.value ? "reconnecting" : "connecting";
    }
    if (isHandshakeComplete.value) return "connected";
    return websocket.status.value === "CLOSED" ? "closed" : "idle";
  });

  return {
    ...websocket,
    state,
    sequence,
    lastMessage,
    lastError,
    sendListenState,
    sendAudioFrame,
    skipCoachingItem,
    ignoreCoachingItem,
    takeover,
    allowReconnect,
    close
  };
}
