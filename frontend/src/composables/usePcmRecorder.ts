import { onBeforeUnmount, ref, shallowRef } from "vue";

export interface UsePcmRecorderOptions {
  audio?: MediaTrackConstraints;
  onAudioData?: (audio: ArrayBuffer) => void;
}

// PCM 16 kHz 单声道 s16 输出的目标参数。
// 实际上前端 AudioContext 可以接受任意 native rate（48/44.1/16/8 kHz），
// appendInput 会按 context.sampleRate / TARGET_SAMPLE_RATE 算 step 做重采样。
// TODO 后续：动态采样率切换。admin 配 ASR sample_rate 后，握手时把
// audio_params.sample_rate 同步成 context.sampleRate，后端用此值做
// init_msg.audio_fs（统一数据源）。当前前端硬写 16k，admin 改了不同步。
const TARGET_SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 320; // 20ms at 16kHz
// Vite 在 build 时会把 /xxx 静态资源替换为 base 路径，但运行时拼接的字符串
// 不会。.env.e2e-suspend 设 VITE_PUBLIC_PATH=./，worklet 必须用相对路径
// 否则 e2e 跑起来 addModule 404 → 用户看到「无法启动 PCM 录音」。
const WORKLET_URL = `${import.meta.env.VITE_PUBLIC_PATH || "/"}pcm-processor.js`.replace(/\/+/g, "/");

// 环形缓冲容量：
// - RESAMPLE_BUF_CAP 装的是麦克风原生采样率（典型 48 kHz）的输入样本。
//   AudioWorklet 每回调送 128 个样本，连续跑 1 分钟约 360K 样本；2048 远大于
//   单批 128，留足余量。
// - PCM_BUF_CAP 装的是重采样后 16 kHz 的 Int16 样本。每回调重采样后样本数
//   = ceil(128 * 16000 / context.sampleRate)，每帧 320 个；2048 留足 6 帧
//   缓冲。
// 容量选小了会 overflow（抛错），选大了浪费内存。2048×8B + 2048×2B ≈ 20KB，
// 完全可接受。
const RESAMPLE_BUF_CAP = 2048;
const PCM_BUF_CAP = 2048;

/** Captures microphone audio as PCM and downsamples to 16 kHz mono s16. */
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

  /**
   * 获取麦克风 + 初始化 AudioContext + 加载 worklet + resume。
   *
   * 全部三个操作必须在**用户手势栈**内完成：
   * - getUserMedia 需要用户激活
   * - AudioContext 构造在 Safari 上需要手势栈
   * - context.resume() 在 Chrome 自动播放策略下需用户激活（否则挂起/拒绝，
   *   AudioWorkletNode.process() 永远不被调度——isRecording 写 true 但一帧
   *   PCM 都收不到）。
   *
   * 业务流程：用户点「开始访谈」→ handleStartInterview（用户手势）→
   * acquireStream()（同步抢手势内的 quota）→ ... → WS onConnected（非手势）
   * → startRecording() 此时 context 已经在跑。
   *
   * AudioContext 构造：先试 16 kHz（最常见 + 协议层期望）。Safari/iOS 上
   * 16 kHz 抛 NotSupportedError / 旧版 Android WebView 静默改用硬件
   * 44.1/48 k —— appendInput 接受实际 context.sampleRate，按 step 重采样。
   * TODO 后续：动态采样率工作——admin 配置不同 / 浏览器实际 sampleRate 与
   * 期望不一致时明确提示或拒握（当前静默回退到硬件率，协议边界模糊）。
   */
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
    } catch (cause) {
      error.value =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法开启麦克风");
      return false;
    }
    if (!("AudioWorkletNode" in window)) {
      error.value = new Error("当前浏览器不支持 AudioWorklet");
      mediaStream.value?.getTracks().forEach(t => t.stop());
      mediaStream.value = null;
      return false;
    }
    // 优先 16 kHz；浏览器拒收时静默改用硬件默认（48/44.1），由 appendInput
    // 的动态 step 重采样兜底。
    let context: AudioContext;
    try {
      context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
    } catch (cause) {
      // 16 kHz 被拒，退到浏览器默认（48/44.1）；appendInput 重采样
      try {
        context = new AudioContext();
      } catch (fallbackCause) {
        error.value =
          fallbackCause instanceof Error || fallbackCause instanceof DOMException
            ? fallbackCause
            : new Error("无法创建 AudioContext");
        mediaStream.value?.getTracks().forEach(t => t.stop());
        mediaStream.value = null;
        return false;
      }
    }
    audioContext.value = context;
    try {
      await context.audioWorklet.addModule(WORKLET_URL);
      await context.resume();
    } catch (cause) {
      // 失败回滚：context / stream 都要关掉，否则下次重入会撞到旧 context。
      audioContext.value = null;
      void context.close();
      mediaStream.value?.getTracks().forEach(t => t.stop());
      mediaStream.value = null;
      error.value =
        cause instanceof Error || cause instanceof DOMException
          ? cause
          : new Error("无法加载 PCM worklet 或 resume AudioContext");
      return false;
    }
    error.value = null;
    return true;
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

  /**
   * 把 worklet 送来的麦克风 PCM 写入环形缓冲 + 重采样到 16 kHz + 凑帧下发。
   *
   * 动态采样率兼容：inputRate 是 context.sampleRate 的实际值（16/48/44.1），
   * step = inputRate / 16000。TODO 后续：握手时把 audio_params.sample_rate
   * = context.sampleRate 上报后端，ASR provider 用此值做 init_msg.audio_fs
   *（替代当前 admin 配的 self._sample_rate）。
   */
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

    // 3. 推进 resampleStart（无拷贝：只挪指针）。
    // 钳制 consumed ≤ resampleAvailable：高采样率（48 k → step=3）下最后一
    // 次迭代 resamplePos += step 可能越过 resampleAvailable - 1，导致
    // resampleAvailable -= consumed 变负、环形索引不变量破坏。钳制后剩余
    // 样本在下一批继续消费（流式连续，无丢失）。
    const consumed = Math.min(Math.floor(resamplePos), resampleAvailable);
    if (consumed > 0) {
      resampleStart = (resampleStart + consumed) % RESAMPLE_BUF_CAP;
      resampleAvailable -= consumed;
      resamplePos -= consumed;
    }

    // 4. 凑齐 320 样本就切一帧下发
    flushFrames();
  };

  /**
   * 把麦克风 → worklet 接好，开始往 onAudioData 推帧。
   *
   * 假定 acquireStream 已成功（context 已建好 + 已 resume + worklet 已加载），
   * 本函数只挂 source / worklet node / 接线，不做可能触发 autoplay 限制的
   * 操作——WS onConnected 是网络回调、脱离用户手势栈。
   */
  const startRecording = async () => {
    if (isRecording.value) return true;
    const context = audioContext.value;
    const stream = mediaStream.value;
    if (!context || !stream) {
      // 调用顺序错了：startRecording 必须在 acquireStream 成功后调用。
      // 把错误显式化便于诊断，UI 会展示 error.value。
      error.value = new Error("startRecording 前必须先 acquireStream 成功");
      return false;
    }

    try {
      const source = context.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(context, "pcm-capture-processor");
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      source.connect(node).connect(silentGain).connect(context.destination);
      // onmessage 内的异常冒到 message handler 边界被浏览器 console.error
      // 吞掉，isRecording 已 true 不会回滚——UI 永远停不下来且服务端此后
      // 一帧 PCM 都收不到。包 try/catch 显式 stop + 设 error 让 UI 可恢复。
      const inputRate = context.sampleRate;
      node.port.onmessage = event => {
        if (!isRecording.value) return;
        if (!(event.data instanceof Float32Array)) return;
        try {
          appendInput(event.data, inputRate);
        } catch (cause) {
          const err =
            cause instanceof Error || cause instanceof DOMException
              ? cause
              : new Error("PCM 录音处理失败");
          error.value = err;
          isRecording.value = false;
          // 拆节点：source/node/gain/stream——但 context 不关，因为
          // 下次 startRecording 还要复用。关 stream 让浏览器麦图标消失。
          try {
            node.disconnect();
            source.disconnect();
            silentGain.disconnect();
            stream.getTracks().forEach(t => t.stop());
            mediaStream.value = null;
          } catch {
            // best-effort：拆失败也不阻断 error 上抛
          }
          resetRingBuffers();
          audioNode.value = null;
          audioSource.value = null;
        }
      };
      audioSource.value = source;
      audioNode.value = node;
      resetRingBuffers();
      isRecording.value = true;
      error.value = null;
      return true;
    } catch (cause) {
      error.value =
        cause instanceof Error || cause instanceof DOMException
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
    // context 留作下次复用：acquireStream 拿过，stopRecording 不应 close。
    // 真正 close 在组件 unmount 或显式 teardown。
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
