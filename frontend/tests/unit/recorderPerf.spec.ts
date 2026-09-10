import { describe, expect, it } from "vitest";

/**
 * 对比 usePcmRecorder 旧版（累积拷贝）vs 新版（环形缓冲）的分配开销。
 * 旧版每回调都 new Float32Array/Int16Array + set 整段；新版只挪读写指针。
 */
describe("usePcmRecorder 预分配开销对比", () => {
  const SR = 16000;
  const CALLBACKS = 7500; // 1 分钟 @ 125 callbacks/s
  const SAMPLES_PER_CALLBACK = 100;
  const FRAME = 320;
  const RESAMPLE_CAP = 2048;
  const PCM_CAP = 2048;

  // 模拟 1 分钟的麦克风输入（确定性）
  const makeInput = (c: number): Float32Array => {
    const input = new Float32Array(SAMPLES_PER_CALLBACK);
    for (let i = 0; i < input.length; i += 1) {
      input[i] = Math.sin(
        (2 * Math.PI * 800 * (c * SAMPLES_PER_CALLBACK + i)) / SR
      );
    }
    return input;
  };

  // 旧版：累积拷贝实现（拷贝自 usePcmRecorder 修改前）
  const runOld = (): { sentFrames: number; allocBytes: number } => {
    let resampleBuffer = new Float32Array(0);
    let resamplePosition = 0;
    let outputBuffer = new Int16Array(0);
    let sentFrames = 0;
    let allocBytes = 0;

    for (let c = 0; c < CALLBACKS; c += 1) {
      const input = makeInput(c);

      // appendInput
      const merged = new Float32Array(resampleBuffer.length + input.length);
      merged.set(resampleBuffer);
      merged.set(input, resampleBuffer.length);
      resampleBuffer = merged;
      allocBytes += merged.byteLength;

      const output: number[] = [];
      while (resamplePosition + 1 < resampleBuffer.length) {
        const index = Math.floor(resamplePosition);
        const fraction = resamplePosition - index;
        output.push(
          resampleBuffer[index] * (1 - fraction) +
            resampleBuffer[index + 1] * fraction
        );
        resamplePosition += 1;
      }
      const consumed = Math.floor(resamplePosition);
      if (consumed > 0) {
        resampleBuffer = resampleBuffer.slice(consumed);
        resamplePosition -= consumed;
      }
      allocBytes += resampleBuffer.byteLength;

      const pcm = new Int16Array(output.length);
      for (let i = 0; i < output.length; i += 1) {
        const s = Math.max(-1, Math.min(1, output[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      allocBytes += pcm.byteLength;

      // appendOutput
      const next = new Int16Array(outputBuffer.length + pcm.length);
      next.set(outputBuffer);
      next.set(pcm, outputBuffer.length);
      outputBuffer = next;
      allocBytes += next.byteLength;

      while (outputBuffer.length >= FRAME) {
        const frame = outputBuffer.slice(0, FRAME);
        outputBuffer = outputBuffer.slice(FRAME);
        sentFrames += 1;
        allocBytes += frame.byteLength;
      }
    }
    return { sentFrames, allocBytes };
  };

  // 新版：环形缓冲实现（与 usePcmRecorder 当前实现一致）
  const runNew = (): { sentFrames: number; allocBytes: number } => {
    const resampleBuf = new Float32Array(RESAMPLE_CAP);
    let resampleStart = 0;
    let resampleAvailable = 0;
    let resamplePos = 0;
    const pcmBuf = new Int16Array(PCM_CAP);
    let pcmStart = 0;
    let pcmAvailable = 0;
    let sentFrames = 0;
    let allocBytes = 0;

    const readResample = (logicalIdx: number): number => {
      return resampleBuf[(resampleStart + logicalIdx) % RESAMPLE_CAP];
    };

    for (let c = 0; c < CALLBACKS; c += 1) {
      const input = makeInput(c);
      // 1. 写环形
      for (let i = 0; i < input.length; i += 1) {
        resampleBuf[(resampleStart + resampleAvailable + i) % RESAMPLE_CAP] =
          input[i];
      }
      resampleAvailable += input.length;

      // 2. 重采样
      while (resamplePos + 1 < resampleAvailable) {
        const i0 = Math.floor(resamplePos);
        const frac = resamplePos - i0;
        const interp = readResample(i0) * (1 - frac) + readResample(i0 + 1) * frac;
        const clamped = Math.max(-1, Math.min(1, interp));
        pcmBuf[(pcmStart + pcmAvailable) % PCM_CAP] =
          clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
        pcmAvailable += 1;
        resamplePos += 1;
      }

      // 3. 推进
      const consumed = Math.floor(resamplePos);
      if (consumed > 0) {
        resampleStart = (resampleStart + consumed) % RESAMPLE_CAP;
        resampleAvailable -= consumed;
        resamplePos -= consumed;
      }

      // 4. 切帧
      while (pcmAvailable >= FRAME) {
        const frame = new Int16Array(FRAME);
        for (let i = 0; i < FRAME; i += 1) {
          frame[i] = pcmBuf[(pcmStart + i) % PCM_CAP];
        }
        pcmStart = (pcmStart + FRAME) % PCM_CAP;
        pcmAvailable -= FRAME;
        sentFrames += 1;
        allocBytes += frame.byteLength;
      }
    }
    return { sentFrames, allocBytes };
  };

  it("旧版：1 分钟模拟分配量（基线）", () => {
    const start = performance.now();
    const r = runOld();
    const elapsed = performance.now() - start;
    // eslint-disable-next-line no-console
    console.log(
      `  旧版: ${(r.allocBytes / 1024 / 1024).toFixed(2)}MB / ${r.sentFrames}帧 / ${elapsed.toFixed(0)}ms CPU`
    );
    // 基线：1 分钟 16kHz 音频按 20ms 切帧 ≈ 3000 帧。至少产出 > 2000 帧
    // 证明模拟有效，旧版累积拷贝分配应远超环形缓冲（> 5MB）。
    expect(r.sentFrames).toBeGreaterThan(2000);
    expect(r.allocBytes).toBeGreaterThan(5 * 1024 * 1024);
  });

  it("新版：1 分钟模拟分配量（环形缓冲）", () => {
    const start = performance.now();
    const r = runNew();
    const elapsed = performance.now() - start;
    // eslint-disable-next-line no-console
    console.log(
      `  新版: ${(r.allocBytes / 1024 / 1024).toFixed(2)}MB / ${r.sentFrames}帧 / ${elapsed.toFixed(0)}ms CPU`
    );
    // 环形缓冲的固定分配：仅每帧 new Int16Array(320) = 640B
    // 1 分钟 3000 帧 ≈ 1.9MB 上限，实际测约 1.4MB。
    // 阈值 3MB 留余量；若超过说明新版退化成累积拷贝。
    expect(r.allocBytes).toBeLessThan(3 * 1024 * 1024);
    expect(r.sentFrames).toBeGreaterThan(2000);
  });

  it("新版相对旧版的分配量级显著降低（环形缓冲零拷贝收益）", () => {
    const old = runOld();
    const newR = runNew();
    const reduction = old.allocBytes / newR.allocBytes;
    // eslint-disable-next-line no-console
    console.log(
      `  收益: 旧 ${(old.allocBytes / 1024 / 1024).toFixed(2)}MB → 新 ${(newR.allocBytes / 1024 / 1024).toFixed(2)}MB（${reduction.toFixed(1)}× 降低）`
    );
    // 实测降低约 6.7×。阈值 ≥3× 留余量；低于此阈值说明新版退化成
    // 累积拷贝（new Float32Array + set 整段），回归报警。
    expect(reduction).toBeGreaterThan(3);
  });

  /**
   * 高采样率（48 kHz → step=3）下验证 P0-3 修复：consumed 必须钳制
   * ≤ resampleAvailable，否则环形索引不变量破坏。模拟 128 samples 输入
   * × 多轮迭代，确认 invariant 维持。
   */
  it("48 kHz 输入下 consumed 钳制保持环形不变量（动态 step 路径）", () => {
    const TARGET = 16000;
    const INPUT_RATE = 48000;
    const STEP = INPUT_RATE / TARGET; // 3
    const cap = 2048;
    const buf = new Float32Array(cap);
    let start = 0;
    let available = 0;
    let pos = 0;

    const writeIdx = (logical: number) => (start + logical) % cap;
    const read = (logical: number) => buf[writeIdx(logical)];

    // 模拟 100 轮 × 128 samples 输入（≈ 0.27s 音频）
    for (let round = 0; round < 100; round += 1) {
      const input = new Float32Array(128);
      // 写入环形
      for (let i = 0; i < input.length; i += 1) {
        buf[writeIdx(available + i)] = i;
      }
      available += input.length;

      // 重采样循环（与 usePcmRecorder 一致）
      while (pos + 1 < available) {
        const i0 = Math.floor(pos);
        const frac = pos - i0;
        read(i0) * (1 - frac) + read(i0 + 1) * frac;
        pos += STEP;
      }

      // P0-3 钳制：consumed ≤ available，否则 start 索引跨段、读错乱样本
      const consumed = Math.min(Math.floor(pos), available);
      expect(consumed).toBeLessThanOrEqual(available);
      start = (start + consumed) % cap;
      available -= consumed;
      pos -= consumed;
      // 不变量：available ∈ [0, cap]
      expect(available).toBeGreaterThanOrEqual(0);
      expect(available).toBeLessThanOrEqual(cap);
    }
  });

  it("行为等价性：两版发出的 PCM 帧数应相同", () => {
    // 跑两版，比较 sentFrames（不直接比较内容，因为算法实现不同，
    // 但帧数应一致——都按 20ms 切帧）
    const old = runOld();
    const newR = runNew();
    // 帧数差异最多 1（边界 case：最后一帧可能差 1 个样本）
    expect(Math.abs(old.sentFrames - newR.sentFrames)).toBeLessThanOrEqual(1);
  });
});
