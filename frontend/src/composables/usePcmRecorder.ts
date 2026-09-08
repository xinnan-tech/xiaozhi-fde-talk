import { onBeforeUnmount, ref, shallowRef } from "vue";

export interface UsePcmRecorderOptions {
  audio?: MediaTrackConstraints;
  onAudioData?: (audio: ArrayBuffer) => void;
}

const TARGET_SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 320; // 20ms at 16kHz
const WORKLET_URL = "/pcm-processor.js";

// 环形缓冲容量：
// - RESAMPLE_BUF_CAP 装的是麦克风原生采样率（典型 48kHz）的输入样本。
//   AudioWorklet 每回调送 128 个样本，连续跑 1 分钟约 360K 样本；2048 远大于
//   单批 128，留足余量。
// - PCM_BUF_CAP 装的是重采样后 16kHz 的 Int16 样本。每回调重采样后约 42 个
//   样本，每帧 320 个；2048 留足 6 帧缓冲。
// 容量选小了会 overflow（抛错），选大了浪费内存。2048×8B + 2048×2B ≈ 20KB，
// 完全可接受。
const RESAMPLE_BUF_CAP = 2048;
const PCM_BUF_CAP = 2048;

/** Captures microphone audio as stable 16kHz mono PCM for streaming ASR. */
export function usePcmRecorder(options: UsePcmRecorderOptions = {}) {
  const { onAudioData } = options;
  const mediaStream = shallowRef<MediaStream | null>(null);
  const audioContext = shallowRef<AudioContext | null>(null);
  const audioSource = shallowRef<MediaStreamAudioSourceNode | null>(null);
  const audioNode = shallowRef<AudioWorkletNode | null>(null);
  const isRecording = ref(false);
  const error = ref<Error | DOMException | null>(null);

  // 预分配的环形缓冲（模块级一次分配，跨会话复用，只挪指针）
  const resampleBuf = new Float32Array(RESAMPLE_BUF_CAP);
  // [resampleStart, resampleStart + resampleAvailable) 区间是有效样本，
  // 通过 % RESAMPLE_BUF_CAP 映射到物理位置。
  let resampleStart = 0;
  let resampleAvailable = 0;
  // 分数读位置，0..resampleAvailable，表示下次要读的"逻辑索引"
  let resamplePos = 0;

  const pcmBuf = new Int16Array(PCM_BUF_CAP);
  let pcmStart = 0;
  let pcmAvailable = 0;

  const resetRingBuffers = () => {
    resampleStart = 0;
    resampleAvailable = 0;
    resamplePos = 0;
    pcmStart = 0;
    pcmAvailable = 0;
  };

  const acquireStream = async () => {
    if (mediaStream.value) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      error.value = new Error("mic_unavailable_insecure_origin");
      return false;
    }
    try {
      mediaStream.value = await navigator.mediaDevices.getUserMedia({
        audio: options.audio ?? true,
        video: false
      });
      error.value = null;
      return true;
    } catch (cause) {
      error.value =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法开启麦克风");
      return false;
    }
  };

  /**
   * 从 resampleBuf 读取 logicalIdx 位置的样本（环形索引）。
   * 性能关键路径：JIT 会内联，~1ns/次。
   */
  const readResample = (logicalIdx: number): number => {
    return resampleBuf[(resampleStart + logicalIdx) % RESAMPLE_BUF_CAP];
  };

  /**
   * 把一个 pcm 样本写入 pcmBuf 环形缓冲（同时做 Float32→Int16 转换）。
   */
  const writePcm = (sample: number): void => {
    if (pcmAvailable >= PCM_BUF_CAP) {
      throw new Error("pcm ring buffer overflow");
    }
    const clamped = Math.max(-1, Math.min(1, sample));
    const writeIdx = (pcmStart + pcmAvailable) % PCM_BUF_CAP;
    pcmBuf[writeIdx] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    pcmAvailable += 1;
  };

  /**
   * 从 pcmBuf 复制一帧出来（用于交给 WebSocket，必须复制避免环形缓冲覆写）。
   * 一次 320 样本 = 640 字节的拷贝，是热路径里唯一剩余的固定分配。
   */
  const takeFrame = (): Int16Array => {
    const frame = new Int16Array(FRAME_SAMPLES);
    for (let i = 0; i < FRAME_SAMPLES; i += 1) {
      frame[i] = pcmBuf[(pcmStart + i) % PCM_BUF_CAP];
    }
    pcmStart = (pcmStart + FRAME_SAMPLES) % PCM_BUF_CAP;
    pcmAvailable -= FRAME_SAMPLES;
    return frame;
  };

  /** 把凑齐的 PCM 帧依次下发给 onAudioData。 */
  const flushFrames = (): void => {
    while (pcmAvailable >= FRAME_SAMPLES) {
      const frame = takeFrame();
      // Int16Array.buffer 在 TS 里是 ArrayBufferLike（含 SharedArrayBuffer），
      // 但 takeFrame() 是用 new Int16Array(FRAME_SAMPLES) 新建的，普通 ArrayBuffer。
      onAudioData?.(frame.buffer as ArrayBuffer);
    }
  };

  const appendInput = (input: Float32Array, inputRate: number) => {
    if (input.length === 0) return;

    // 1. 把新输入写入 resampleBuf 环形（无拷贝：直接按物理位置写入）
    if (resampleAvailable + input.length > RESAMPLE_BUF_CAP) {
      throw new Error("resample ring buffer overflow");
    }
    for (let i = 0; i < input.length; i += 1) {
      const physicalIdx =
        (resampleStart + resampleAvailable + i) % RESAMPLE_BUF_CAP;
      resampleBuf[physicalIdx] = input[i];
    }
    resampleAvailable += input.length;

    // 2. 重采样：分数步进读取 + 线性插值，直接写入 pcmBuf
    const step = inputRate / TARGET_SAMPLE_RATE;
    while (resamplePos + 1 < resampleAvailable) {
      const i0 = Math.floor(resamplePos);
      const frac = resamplePos - i0;
      const interp =
        readResample(i0) * (1 - frac) + readResample(i0 + 1) * frac;
      writePcm(interp);
      resamplePos += step;
    }

    // 3. 推进 resampleStart（无拷贝：只挪指针）
    const consumed = Math.floor(resamplePos);
    if (consumed > 0) {
      resampleStart = (resampleStart + consumed) % RESAMPLE_BUF_CAP;
      resampleAvailable -= consumed;
      resamplePos -= consumed;
    }

    // 4. 凑齐 320 样本就切一帧下发
    flushFrames();
  };

  const startRecording = async () => {
    if (isRecording.value) return true;
    if (!(await acquireStream())) return false;

    try {
      if (!("AudioWorkletNode" in window)) {
        throw new Error("当前浏览器不支持 AudioWorklet");
      }
      const context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      // 先把 context 记账，让 catch / stopRecording 在 addModule 失败时能 close 它；
      // 否则 context 不会被 close 回收（addModule 失败后 audioContext.value 仍为 null）。
      audioContext.value = context;
      await context.audioWorklet.addModule(WORKLET_URL);
      const source = context.createMediaStreamSource(mediaStream.value!);
      const node = new AudioWorkletNode(context, "pcm-capture-processor");
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      source.connect(node).connect(silentGain).connect(context.destination);
      node.port.onmessage = event => {
        if (isRecording.value && event.data instanceof Float32Array) {
          appendInput(event.data, context.sampleRate);
        }
      };
      await context.resume();
      audioSource.value = source;
      audioNode.value = node;
      resetRingBuffers();
      isRecording.value = true;
      error.value = null;
      return true;
    } catch (cause) {
      stopRecording();
      error.value =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法启动 PCM 录音");
      return false;
    }
  };

  const stopRecording = () => {
    isRecording.value = false;
    audioNode.value?.disconnect();
    audioSource.value?.disconnect();
    audioNode.value = null;
    audioSource.value = null;
    const context = audioContext.value;
    audioContext.value = null;
    if (context) void context.close();
    mediaStream.value?.getTracks().forEach(track => track.stop());
    mediaStream.value = null;
    resetRingBuffers();
  };

  onBeforeUnmount(stopRecording);

  return {
    mediaStream,
    isRecording,
    error,
    acquireStream,
    startRecording,
    stopRecording
  };
}
