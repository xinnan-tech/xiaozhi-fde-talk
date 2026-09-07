import { describe, it, expect } from "vitest";
import { SpectralEnergyVAD, VAD_FRAME_SAMPLES } from "@/utils/speechVad";

/**
 * 性能基准：VAD 在 20ms 帧预算下应远低于 1ms 单帧耗时，
 * 否则会在主流水线（AudioWorklet 8ms tick + onmessage 回调）累积成可感卡顿。
 *
 * 实测对象：纯静音（最坏情况，FFT 必跑）+ 稳态语音（FFT + 攻击检测都跑）。
 */
describe("SpectralEnergyVAD 性能", () => {
  it("纯静音 1000 帧（20s）总耗时 < 3000ms（< 3ms/帧，留 20× 余量）", () => {
    const vad = new SpectralEnergyVAD();
    const frame = new Int16Array(VAD_FRAME_SAMPLES); // 全零
    // 预热（V8 JIT 优化）
    for (let i = 0; i < 200; i += 1) vad.feed(frame);
    // 正式测量
    const start = performance.now();
    for (let i = 0; i < 1000; i += 1) vad.feed(frame);
    const elapsed = performance.now() - start;
    // 1000 帧 = 20s 音频。阈值放宽到 3ms/帧（实测 ~0.14ms/帧），兼容全量
    // 测试时 CPU 被其他 spec 抢占导致单测耗时偏高的场景
    expect(elapsed).toBeLessThan(3000);
    // eslint-disable-next-line no-console
    console.log(`  纯静音 1000 帧: ${elapsed.toFixed(1)}ms (${(elapsed / 1000).toFixed(3)}ms/帧)`);
  });

  it("稳态语音 1000 帧总耗时 < 3000ms", () => {
    const vad = new SpectralEnergyVAD();
    const n = VAD_FRAME_SAMPLES;
    const frame = new Int16Array(n);
    for (let i = 0; i < n; i += 1) {
      frame[i] = Math.sin((i / 16000) * 800 * 2 * Math.PI) * 0x7fff;
    }
    for (let i = 0; i < 200; i += 1) vad.feed(frame);
    const start = performance.now();
    for (let i = 0; i < 1000; i += 1) vad.feed(frame);
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(3000);
    // eslint-disable-next-line no-console
    console.log(`  稳态语音 1000 帧: ${elapsed.toFixed(1)}ms (${(elapsed / 1000).toFixed(3)}ms/帧)`);
  });

  it("静→音 transition 100 帧 < 500ms", () => {
    const vad = new SpectralEnergyVAD();
    // 先填静音让 VAD 进入稳态
    const silence = new Int16Array(VAD_FRAME_SAMPLES);
    for (let i = 0; i < 100; i += 1) vad.feed(silence);
    // 单帧语音（800Hz 正弦）
    const n = VAD_FRAME_SAMPLES;
    const speech = new Int16Array(n);
    for (let i = 0; i < n; i += 1) {
      speech[i] = Math.sin((i / 16000) * 800 * 2 * Math.PI) * 0x7fff;
    }
    // 测量 100 次 transition（最坏路径：滚动 + 完整 FFT + attack）
    const start = performance.now();
    for (let i = 0; i < 100; i += 1) vad.feed(speech);
    const elapsed = performance.now() - start;
    // eslint-disable-next-line no-console
    console.log(
      `  静→音 100 帧: ${elapsed.toFixed(1)}ms (${(elapsed / 100).toFixed(3)}ms/帧)`
    );
    expect(elapsed).toBeLessThan(500);
  });
});
