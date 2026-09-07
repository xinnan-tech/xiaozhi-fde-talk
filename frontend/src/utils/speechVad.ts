/**
 * 频谱 + 能量双层 VAD。
 *
 * 目的：避免静音/纯噪声时段持续往 ASR（按音频时长计费）灌无意义 PCM。
 *
 * 设计：见 docs/websocket-protocol.md 与 review 记录 "fix-cross-browser-pcm-streaming"。
 *   - 稳态判别：1024 点实数 FFT，统计 300-3400Hz 语音带功率比。低于阈值 = 噪声 / 静音。
 *   - 瞬态判别：单帧 RMS 超过 3× 噪声地板 → 视为语音 attack，立即放行。
 *     该机制解决"稳态判别有 1.28s 填充窗口，speech onset 会被吃掉"的问题。
 *   - 噪声地板用慢 EMA 跟踪（α=0.02），仅在判 silence 时更新——防止把语音当成底噪。
 *   - 状态机：开麦即假定语音（prevDecision = true），避免开麦后第一句被切；
 *     transition 帧（判别翻转）无条件放行，保证音节尾音不丢。
 *   - 条件式 trailing padding：仅当上一段 speech ≥ 30 帧 (600ms) 时才在
 *     speech→silence 后追加 30 帧静音送 ASR。600ms = FunASR 切句阈值，也
 *     是"够格作为一句"的最小语音长度，避免把句中短停顿 / "嗯""啊"误送
 *     padding（否则真实访谈音频误检会爆炸到 97%）。silence→speech 时撤销。
 *   - 暖启动：FFT 缓冲未满时直接沿用 prevDecision。
 *
 * 输入：16kHz mono Int16Array，每帧 320 样本（20ms）。
 * 输出：boolean — true 表示该帧应送 ASR；false 表示丢弃。
 */
export const VAD_FRAME_SAMPLES = 320;
const FFT_SIZE = 1024;
const BIN_HZ = 16000 / FFT_SIZE; // 15.625Hz/bin
// 语音带：300-3400Hz，对应 bin 索引 19-217
const SP_BIN_LO = Math.floor(300 / BIN_HZ);
const SP_BIN_HI = Math.ceil(3400 / BIN_HZ);
const SPECTRAL_RATIO_MIN = 0.6;
const ENERGY_ATTACK_RATIO = 3; // RMS > 3× 噪声地板 → attack
const ENERGY_ATTACK_FLOOR = 200; // 绝对下限，避免极低噪声地板下被低频噪声误触
const NOISE_FLOOR_ALPHA = 0.02;
const NOISE_FLOOR_MIN = 50; // 噪声地板下限，避免纯静音（rms=0）时无限趋近 0
const SPECTRAL_TOTAL_FLOOR = 0.01; // 总能量低于此值直接判 silence
// trailing silence padding：仅当上一段 speech 长度 ≥ MIN_SPEECH_FRAMES_FOR_PADDING
// 时才在 speech→silence 后追加 N 帧静音送 ASR，让 FunASR 内部 VAD 立即识别句尾
//（FunASR 最短静音阈值 ≥600ms）。否则 VAD 把所有静音都砍掉后 FunASR 看不到句尾
// 间隙、2pass 不切句 → 用户必须主动暂停才能拿到结果。
//   - 30 帧 = 600ms @ 20ms/帧 = FunASR 切句阈值
//   - MIN_SPEECH_FRAMES_FOR_PADDING = 30 也是「够格作为一句」的最小语音长度，
//     避免把"嗯""啊"等短回复 / 句中短停顿误送 padding（否则真实访谈音频
//     误检会从 ~50% 爆炸到 97%，见 review "fix-cross-browser-pcm-streaming"）。
const TRAILING_PADDING_FRAMES = 30;
const MIN_SPEECH_FRAMES_FOR_PADDING = 30;

// 1024 点 Hann 窗（预计算）
const HANN: Float32Array = (() => {
  const w = new Float32Array(FFT_SIZE);
  for (let i = 0; i < FFT_SIZE; i += 1) {
    w[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (FFT_SIZE - 1)));
  }
  return w;
})();

/**
 * 原地 1024 点 radix-2 FFT（Cooley-Tukey，decimation-in-time）。
 * 输入 re/im 必须为长度 1024 的 Float32Array。im 在调用前清零。
 */
function fft1024(re: Float32Array, im: Float32Array): void {
  const N = FFT_SIZE;
  // 1. bit-reverse 重排
  let j = 0;
  for (let i = 1; i < N; i += 1) {
    let bit = N >> 1;
    for (; j & bit; bit >>= 1) {
      j ^= bit;
    }
    j ^= bit;
    if (i < j) {
      const tr = re[i];
      re[i] = re[j];
      re[j] = tr;
      const ti = im[i];
      im[i] = im[j];
      im[j] = ti;
    }
  }
  // 2. 蝶形
  for (let size = 2; size <= N; size <<= 1) {
    const half = size >> 1;
    const phaseStep = (-2 * Math.PI) / size;
    for (let start = 0; start < N; start += size) {
      for (let k = 0; k < half; k += 1) {
        const phase = phaseStep * k;
        const cos = Math.cos(phase);
        const sin = Math.sin(phase);
        const aRe = re[start + k];
        const aIm = im[start + k];
        const bReRaw = re[start + k + half];
        const bImRaw = im[start + k + half];
        const bRe = bReRaw * cos - bImRaw * sin;
        const bIm = bReRaw * sin + bImRaw * cos;
        re[start + k] = aRe + bRe;
        im[start + k] = aIm + bIm;
        re[start + k + half] = aRe - bRe;
        im[start + k + half] = aIm - bIm;
      }
    }
  }
}

/** 单帧 RMS（Int16 域，0..32767 量级）。 */
function frameRms(frame: Int16Array): number {
  let sumSq = 0;
  for (let i = 0; i < frame.length; i += 1) {
    const s = frame[i];
    sumSq += s * s;
  }
  return Math.sqrt(sumSq / frame.length);
}

export class SpectralEnergyVAD {
  private readonly buf = new Float32Array(FFT_SIZE);
  private readonly re = new Float32Array(FFT_SIZE);
  private readonly im = new Float32Array(FFT_SIZE);
  private filled = 0;
  private noiseFloor = 200;
  private prevDecision = true;
  // speech→silence 翻转后追加的 trailing silence 倒计时（帧数）。
  // > 0 时无论 VAD 判定如何都返回 true，让 ASR 看到句尾间隙。
  // 仅在上一段 speech ≥ MIN_SPEECH_FRAMES_FOR_PADDING 时才启动，避免短
  // 语音 / 句中停顿触发的 transition 也打 padding。
  private trailingCountdown = 0;
  // 当前 speech 段已连续多少帧。仅在判定 isSpeech=true 时累加，
  // 用于在 speech→silence 翻转时判断本段是否够格触发 padding。
  private speechSegmentFrames = 0;

  /** 当前判定的"语音"状态（外部调试用）。 */
  get isSpeech(): boolean {
    return this.prevDecision;
  }

  /** 当前噪声地板估计（外部调试用）。 */
  get currentNoiseFloor(): number {
    return this.noiseFloor;
  }

  /**
   * 喂一帧 20ms（320 样本）音频，返回是否应发送给 ASR。
   * 帧长不严格等于 320 时按实际长度处理（兼容外部 buffer 边界）。
   */
  feed(frame: Int16Array): boolean {
    if (frame.length === 0) return this.prevDecision;

    // 1. 能量 attack 检测（瞬态响应，1 帧延迟）
    const rms = frameRms(frame);
    const energyAttack =
      rms >= this.noiseFloor * ENERGY_ATTACK_RATIO &&
      rms >= ENERGY_ATTACK_FLOOR;

    // 2. 滑动窗口写环形缓冲（容量 FFT_SIZE）
    const n = frame.length;
    const normalized = new Float32Array(n);
    for (let i = 0; i < n; i += 1) {
      normalized[i] = frame[i] / 32768;
    }
    if (this.filled < FFT_SIZE) {
      const take = Math.min(n, FFT_SIZE - this.filled);
      this.buf.set(normalized.subarray(0, take), this.filled);
      this.filled += take;
      if (this.filled < FFT_SIZE) {
        // 暖启动：缓冲未满，prevDecision 默认 true（保守开场保护首句）。
        // 此时不更新噪声地板——既未确认是 silence，也不应假设是 silence。
        return this.prevDecision;
      }
      // 缓冲刚满：处理掉 normalize 后的剩余样本
      const rest = n - take;
      if (rest > 0) {
        // 直接覆盖尾部（环形效果：保留 normalized 的末尾 rest 个）
        for (let i = 0; i < FFT_SIZE - rest; i += 1) {
          this.buf[i] = this.buf[i + rest];
        }
        this.buf.set(normalized.subarray(take), FFT_SIZE - rest);
      }
    } else {
      // 缓冲已满：左移 n 位，覆写尾部
      if (n >= FFT_SIZE) {
        this.buf.set(normalized.subarray(n - FFT_SIZE), 0);
      } else {
        this.buf.copyWithin(0, n);
        this.buf.set(normalized, FFT_SIZE - n);
      }
    }

    // 3. 频谱判别
    for (let i = 0; i < FFT_SIZE; i += 1) {
      this.re[i] = this.buf[i] * HANN[i];
      this.im[i] = 0;
    }
    fft1024(this.re, this.im);

    let speechBand = 0;
    let total = 0;
    const half = FFT_SIZE / 2;
    for (let k = 0; k <= half; k += 1) {
      const reK = this.re[k];
      const imK = this.im[k];
      const mag = reK * reK + imK * imK;
      total += mag;
      if (k >= SP_BIN_LO && k <= SP_BIN_HI) {
        speechBand += mag;
      }
    }
    const ratio = total > 0 ? speechBand / total : 0;
    const spectralSpeech =
      ratio >= SPECTRAL_RATIO_MIN && total >= SPECTRAL_TOTAL_FLOOR;

    // 4. 双层综合
    const isSpeech = spectralSpeech || energyAttack;

    // 5. 噪声地板仅在 silence 时更新
    this.updateNoiseFloor(rms, isSpeech);

    // 6. 状态机：
    //    - transition 帧无条件放行；
    //    - speech→silence 时，若本段 speech ≥ MIN_SPEECH_FRAMES_FOR_PADDING，
    //      启动 trailingCountdown 倒计时（让 FunASR 切句）；
    //      否则只放 transition 帧本身，silence 立即丢弃（避免白送 ASR）。
    //    - silence→speech 时撤销倒计时。
    const transition = isSpeech !== this.prevDecision;
    this.prevDecision = isSpeech;

    if (transition) {
      if (isSpeech) {
        // silence→speech：撤销 padding，speech 段重新计时
        this.trailingCountdown = 0;
        this.speechSegmentFrames = 1;
      } else {
        // speech→silence：先取本段长度，再视长度决定是否启动 padding
        const speechWas = this.speechSegmentFrames;
        this.speechSegmentFrames = 0;
        if (speechWas >= MIN_SPEECH_FRAMES_FOR_PADDING) {
          this.trailingCountdown = TRAILING_PADDING_FRAMES;
        } else {
          this.trailingCountdown = 0;
        }
      }
      return true;
    }

    if (isSpeech) {
      this.speechSegmentFrames += 1;
      return true;
    }

    // 纯 silence（非 transition）：消耗 countdown；用完即停
    if (this.trailingCountdown > 0) {
      this.trailingCountdown -= 1;
      return true;
    }
    return false;
  }

  private updateNoiseFloor(rms: number, isSpeech: boolean): void {
    if (isSpeech) return;
    // rms 极小时不更新——量化底/真静音会把地板拉穿，导致后续稍大一点的
    // 噪声就触发 energy attack
    if (rms < NOISE_FLOOR_MIN) return;
    const updated =
      (1 - NOISE_FLOOR_ALPHA) * this.noiseFloor + NOISE_FLOOR_ALPHA * rms;
    this.noiseFloor = Math.max(updated, NOISE_FLOOR_MIN);
  }

  /** 复位 VAD 状态（新会话开始时调用）。 */
  reset(): void {
    this.buf.fill(0);
    this.filled = 0;
    this.noiseFloor = 200;
    this.prevDecision = true;
    this.trailingCountdown = 0;
    this.speechSegmentFrames = 0;
  }
}
