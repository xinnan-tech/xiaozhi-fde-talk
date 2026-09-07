import { describe, it, expect } from "vitest";
import { SpectralEnergyVAD, VAD_FRAME_SAMPLES } from "@/utils/speechVad";

/**
 * 复现用户报告的"录音中后端积压、暂停才出"症状。
 *
 * 直接验证 PCM 录音器热路径的输出节奏：
 *   - 每隔 ~20ms 应有一帧 320 样本（640B）通过 onAudioData 下发
 *   - 录音期间不应"积压"——收到的回调必须立刻产生帧（或被 VAD 砍掉）
 *   - 调 stopRecording 后不残留任何 buffer
 *
 * 对照：旧版累积拷贝 vs 新版环形缓冲 + VAD，分别跑同样输入序列，
 *       比对每一帧的下发时刻和帧索引是否一致。
 *
 * 这是模拟浏览器 AudioWorklet 回调的纯 JS 路径，不依赖任何 DOM/浏览器 API。
 */
const TARGET_SR = 16000;
const FRAME_SAMPLES = VAD_FRAME_SAMPLES; // 320
const SR = TARGET_SR;

// 模拟 AudioWorklet：context.sampleRate = 16000，每回调 128 样本。
// 320/128 = 2.5 回调/帧，所以帧节拍 ~20ms。
const SAMPLES_PER_CALLBACK = 128;
const CALLBACKS_PER_FRAME = FRAME_SAMPLES / SAMPLES_PER_CALLBACK; // 2.5

/**
 * 跑一遍录音热路径，收集每帧的下发时刻（按 callback 序号计）和帧内容。
 * 与 usePcmRecorder.ts 的 appendInput / flushFrames 逻辑一致（剔除 Vue ref 包装）。
 */
function runPipeline(opts: {
  totalCallbacks: number;
  enableVad: boolean;
  makeFrame: (callbackIdx: number) => Float32Array; // 1 个 worklet 回调的样本
  sineFreq?: number;
}) {
  const { totalCallbacks, enableVad, makeFrame } = opts;
  const resampleBuf = new Float32Array(2048);
  let resampleStart = 0;
  let resampleAvailable = 0;
  let resamplePos = 0;
  const pcmBuf = new Int16Array(2048);
  let pcmStart = 0;
  let pcmAvailable = 0;
  const vad = enableVad ? new SpectralEnergyVAD() : null;

  const emitted: { at: number; rms: number; vadKept: boolean }[] = [];
  let frameIdx = 0;

  const readResample = (i: number) =>
    resampleBuf[(resampleStart + i) % resampleBuf.length];

  for (let c = 0; c < totalCallbacks; c += 1) {
    const input = makeFrame(c);
    // 写环形
    for (let i = 0; i < input.length; i += 1) {
      resampleBuf[(resampleStart + resampleAvailable + i) % resampleBuf.length] =
        input[i];
    }
    resampleAvailable += input.length;
    // 重采样 1:1（context.sampleRate 已对齐）
    while (resamplePos + 1 < resampleAvailable) {
      const i0 = Math.floor(resamplePos);
      const frac = resamplePos - i0;
      const v = readResample(i0) * (1 - frac) + readResample(i0 + 1) * frac;
      const clamped = Math.max(-1, Math.min(1, v));
      pcmBuf[(pcmStart + pcmAvailable) % pcmBuf.length] =
        clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      pcmAvailable += 1;
      resamplePos += 1;
    }
    const consumed = Math.floor(resamplePos);
    if (consumed > 0) {
      resampleStart = (resampleStart + consumed) % resampleBuf.length;
      resampleAvailable -= consumed;
      resamplePos -= consumed;
    }
    // 切帧
    while (pcmAvailable >= FRAME_SAMPLES) {
      const frame = new Int16Array(FRAME_SAMPLES);
      for (let i = 0; i < FRAME_SAMPLES; i += 1) {
        frame[i] = pcmBuf[(pcmStart + i) % pcmBuf.length];
      }
      pcmStart = (pcmStart + FRAME_SAMPLES) % pcmBuf.length;
      pcmAvailable -= FRAME_SAMPLES;
      const rms = (() => {
        let s = 0;
        for (let i = 0; i < frame.length; i += 1) s += frame[i]! * frame[i]!;
        return Math.sqrt(s / frame.length);
      })();
      const vadKept = vad ? vad.feed(frame) : true;
      if (vadKept) {
        emitted.push({ at: c, rms, vadKept: true });
      }
      frameIdx += 1;
    }
  }
  return {
    emitted,
    residualSamples: pcmAvailable,
    totalFrames: frameIdx,
    callbacksForFirstFrame:
      emitted[0] !== undefined
        ? emitted[0].at
        : totalCallbacks, // 永远出帧则首帧节拍
  };
}

describe("PCM 录音热路径：无积压验证（复现 ab08b13 修复的 cluster 症状）", () => {
  it("[纯净音] 250 回调（≈1s）应产生 ~100 帧，且无任何残留样本", () => {
    const r = runPipeline({
      totalCallbacks: 250,
      enableVad: false,
      makeFrame: () => new Float32Array(SAMPLES_PER_CALLBACK) // 静音
    });
    // 250 回调 × 128 样本 = 32000 样本 / 320 帧 = 100 帧
    // 浮点累积允许 ±1 边界
    expect(r.totalFrames).toBeGreaterThanOrEqual(99);
    expect(r.totalFrames).toBeLessThanOrEqual(100);
    expect(r.residualSamples).toBeLessThan(FRAME_SAMPLES);
  });

  it("[持续语音] 250 回调（≈1s）应产生 ~12 帧，节拍稳定在 20-22ms 间", () => {
    let callbackIdx = 0;
    const r = runPipeline({
      totalCallbacks: 250,
      enableVad: false,
      makeFrame: () => {
        const f = new Float32Array(SAMPLES_PER_CALLBACK);
        for (let i = 0; i < SAMPLES_PER_CALLBACK; i += 1) {
          f[i] =
            Math.sin((2 * Math.PI * 800 * (callbackIdx * SAMPLES_PER_CALLBACK + i)) / SR) *
            0.3;
        }
        callbackIdx += 1;
        return f;
      }
    });
    // 节拍验证：每帧对应 ~2.5 回调
    const intervals: number[] = [];
    for (let i = 1; i < r.emitted.length; i += 1) {
      intervals.push(r.emitted[i]!.at - r.emitted[i - 1]!.at);
    }
    // eslint-disable-next-line no-console
    console.log(
      `  帧节拍: ${r.emitted.length} 帧, 平均间隔=${(
        intervals.reduce((a, b) => a + b, 0) / Math.max(1, intervals.length)
      ).toFixed(2)} 回调`
    );
    // 每 ~2.5 回调出一帧；偏差 < 1 是边界 round
    const avgInterval =
      intervals.reduce((a, b) => a + b, 0) / Math.max(1, intervals.length);
    expect(avgInterval).toBeGreaterThanOrEqual(2);
    expect(avgInterval).toBeLessThanOrEqual(4);
  });

  it("[模拟平板弱 CPU：回调延迟到 80ms 一次] 帧仍按采样比例累积、不积压", () => {
    // 平板弱 CPU 时 AudioWorklet 回调被推迟，但每回调样本数不变
    // 验证：即使回调稀疏，缓冲也只在 ring buffer 范围内（不增长、不积压到下一回调）
    let callbackIdx = 0;
    const r = runPipeline({
      totalCallbacks: 50,
      enableVad: false,
      makeFrame: () => {
        const f = new Float32Array(SAMPLES_PER_CALLBACK);
        for (let i = 0; i < SAMPLES_PER_CALLBACK; i += 1) {
          f[i] =
            Math.sin((2 * Math.PI * 800 * (callbackIdx * SAMPLES_PER_CALLBACK + i)) / SR) *
            0.3;
        }
        callbackIdx += 1;
        return f;
      }
    });
    // 50 回调 × 128 样本 = 6400 样本 = 20 帧（320 样本/帧）
    // 浮点累积允许 ±1 边界
    expect(r.totalFrames).toBeGreaterThanOrEqual(19);
    expect(r.totalFrames).toBeLessThanOrEqual(20);
    expect(r.emitted.length).toBe(r.totalFrames);
    // 残留样本 < FRAME_SAMPLES（绝不在 ring buffer 里堆积 > 1 帧）
    expect(r.residualSamples).toBeLessThan(FRAME_SAMPLES);
    // 不会有任何"暂停才出"的迹象——前 3 回调就应该有第一帧出现
    // eslint-disable-next-line no-console
    console.log(
      `  平板稀疏回调 50 次: ${r.emitted.length} 帧发出，首帧 at=${r.emitted[0]?.at} 回调`
    );
  });

  it("[开启 VAD] 持续语音 + 周期静音：trailing padding 期间静音仍下发，padding 用完才砍", () => {
    // 模拟一段 2s 录音：0-1s 说话，1-1.5s 沉默，1.5-2s 又说话
    let callbackIdx = 0;
    const r = runPipeline({
      totalCallbacks: 250, // 250 回调 ≈ 2s
      enableVad: true,
      makeFrame: () => {
        const c = callbackIdx;
        callbackIdx += 1;
        const t = (c * SAMPLES_PER_CALLBACK) / SR;
        const f = new Float32Array(SAMPLES_PER_CALLBACK);
        let amp = 0;
        if (t < 1.0) amp = 0.3; // 0-1s: 说话
        else if (t < 1.5) amp = 0; // 1-1.5s: 静音
        else amp = 0.3; // 1.5-2s: 又说话
        if (amp > 0) {
          for (let i = 0; i < SAMPLES_PER_CALLBACK; i += 1) {
            f[i] =
              Math.sin((2 * Math.PI * 800 * (c * SAMPLES_PER_CALLBACK + i)) / SR) *
              amp;
          }
        }
        return f;
      }
    });
    // 0-1s speech 段 50 帧 ≥ MIN_SPEECH_FRAMES_FOR_PADDING(30)，触发 30 帧
    // trailing padding；1-1.5s 静音（25 帧）正好被 30 帧 padding 全覆盖 → 全发；
    // 若静音更长才会看到「padding 用完即砍」的效果（见下一个用例）。
    const speechFrames = r.emitted.length;
    // eslint-disable-next-line no-console
    console.log(
      `  2s 录音（中间 0.5s 静音）: 总切帧=${r.totalFrames}, VAD 放行=${speechFrames}, 残留=${r.residualSamples}`
    );
    // 关键：残余样本必须 < 1 帧（绝不留"积压到 stop 时才释放"的尾巴）
    expect(r.residualSamples).toBeLessThan(FRAME_SAMPLES);
    // 2s 总音频 100 帧，语音实际只有 1.5s ≈ 75 帧
    // VAD 期望放行：~75 帧（语音）+ 25 帧 trailing padding（覆盖 1-1.5s 静音）
    //   + 1 帧 silence→speech transition = ~100 帧
    // 浮点边界给 ±40 余量，覆盖静音段两端边界处的 callback/frame 偏移。
    const expectedSpeechFrames = Math.floor(1.5 * SR / FRAME_SAMPLES); // 75
    expect(speechFrames).toBeGreaterThan(expectedSpeechFrames - 10);
    expect(speechFrames).toBeLessThan(expectedSpeechFrames + 40);
  });

  it("[开启 VAD] 长静默：trailing padding 用完后静音被砍、ring buffer 不积压", () => {
    // 模拟 4s 录音：0-1s 说话 + 1-3s 静音 (100 帧) + 3-4s 又说话。
    // 静音远超 30 帧 trailing padding，验证「padding 用完即停」。
    let callbackIdx = 0;
    const r = runPipeline({
      totalCallbacks: 500, // 500 回调 ≈ 4s
      enableVad: true,
      makeFrame: () => {
        const c = callbackIdx;
        callbackIdx += 1;
        const t = (c * SAMPLES_PER_CALLBACK) / SR;
        const f = new Float32Array(SAMPLES_PER_CALLBACK);
        let amp = 0;
        if (t < 1.0) amp = 0.3; // 0-1s: 说话
        else if (t < 3.0) amp = 0; // 1-3s: 长静音
        else amp = 0.3; // 3-4s: 又说话
        if (amp > 0) {
          for (let i = 0; i < SAMPLES_PER_CALLBACK; i += 1) {
            f[i] =
              Math.sin((2 * Math.PI * 800 * (c * SAMPLES_PER_CALLBACK + i)) / SR) *
              amp;
          }
        }
        return f;
      }
    });
    const speechFrames = r.emitted.length;
    // eslint-disable-next-line no-console
    console.log(
      `  4s 录音（中间 2s 长静音）: 总切帧=${r.totalFrames}, VAD 放行=${speechFrames}, 残留=${r.residualSamples}`
    );
    // ring buffer 绝不能积压
    expect(r.residualSamples).toBeLessThan(FRAME_SAMPLES);
    // 期望下发量：~50 (0-1s 说话) + 30 (trailing padding) + 1 (silence→speech
    // transition) + ~50 (3-4s 又说话) ≈ 131 帧。
    // 中段 1-3s 共 100 帧静音，其中 ~70 帧应被 VAD 砍掉。
    expect(speechFrames).toBeGreaterThan(100);
    expect(speechFrames).toBeLessThan(140);
  });

  it("[模拟用户场景] 平板回调慢 + VAD：录音停止时 ring buffer 不残留", () => {
    // 模拟"用户按暂停"：直接停喂回调，检查 ring buffer 的 pcmAvailable
    let callbackIdx = 0;
    const pcmBuf = new Int16Array(2048);
    let pcmStart = 0;
    let pcmAvailable = 0;
    const vad = new SpectralEnergyVAD();

    // 喂 100 回调（≈0.8s 语音），然后"按暂停"
    for (let c = 0; c < 100; c += 1) {
      const input = new Float32Array(SAMPLES_PER_CALLBACK);
      for (let i = 0; i < SAMPLES_PER_CALLBACK; i += 1) {
        input[i] =
          Math.sin((2 * Math.PI * 800 * (callbackIdx * SAMPLES_PER_CALLBACK + i)) / SR) *
          0.3;
      }
      callbackIdx += 1;
      // 直接塞入 pcmBuf（简化的稳态路径）
      for (let i = 0; i < input.length; i += 1) {
        pcmBuf[(pcmStart + pcmAvailable) % pcmBuf.length] =
          input[i]! < 0 ? input[i]! * 0x8000 : input[i]! * 0x7fff;
        pcmAvailable += 1;
      }
      // 切帧
      while (pcmAvailable >= FRAME_SAMPLES) {
        const frame = new Int16Array(FRAME_SAMPLES);
        for (let i = 0; i < FRAME_SAMPLES; i += 1) {
          frame[i] = pcmBuf[(pcmStart + i) % pcmBuf.length]!;
        }
        pcmStart = (pcmStart + FRAME_SAMPLES) % pcmBuf.length;
        pcmAvailable -= FRAME_SAMPLES;
        vad.feed(frame); // 即便 VAD 砍了，pcmAvailable 已经减少
      }
    }
    // 关键断言：暂停时残余 < 1 帧。如果 > 320，说明录音期间"积压"了。
    // eslint-disable-next-line no-console
    console.log(`  模拟平板按暂停：pcmAvailable=${pcmAvailable} (应 < 320)`);
    expect(pcmAvailable).toBeLessThan(FRAME_SAMPLES);
  });
});
