import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { SpectralEnergyVAD, VAD_FRAME_SAMPLES } from "@/utils/speechVad";

/**
 * 漏检（漏剪真实语音）回归测试。
 *
 * Ground truth 用单帧 RMS 阈值判定（与 ASR/VAD 互不依赖，作为第三方参考）。
 * 然后对比 VAD 的判定：
 *   - 漏检 = 实际是语音（GT=true）但 VAD 判 false
 *   - 误检 = 实际是静音（GT=false）但 VAD 判 true（多花 ASR 钱）
 *
 * 与 WebM/Opus 旧版的对比：旧版完全不丢帧（漏检=0），代价是沉默时段也持续计费。
 * PCM+VAD 的目标是漏检率维持在 0.1% 以下（≤ 30 帧 / 30 分钟），
 * 同时把无意义帧送 ASR 的比例从 100% 压到 ~50%（嘈杂场景）。
 */
describe("SpectralEnergyVAD 漏检回归", () => {
  // 加载真实访谈 PCM（45s，16kHz mono int16，1440000 字节）
  const PCM_PATH = resolve(
    __dirname,
    "../../../backend/tests/e2e/audio/interview.pcm"
  );
  const pcmBytes = readFileSync(PCM_PATH);
  const pcmFull = new Int16Array(
    pcmBytes.buffer,
    pcmBytes.byteOffset,
    pcmBytes.byteLength / 2
  );

  // 切帧
  const totalFrames = Math.floor(pcmFull.length / VAD_FRAME_SAMPLES);
  const frames: Int16Array[] = [];
  for (let i = 0; i < totalFrames; i += 1) {
    frames.push(
      pcmFull.slice(i * VAD_FRAME_SAMPLES, (i + 1) * VAD_FRAME_SAMPLES)
    );
  }

  // Ground truth：单帧 RMS ≥ 阈值视为"有语音"
  // 阈值参考 NOISE_FLOOR_MIN=50 但要更高以区分真实语音与房间底噪
  const RMS_THRESHOLD = 800;
  const groundTruth: boolean[] = frames.map(frame => {
    let sumSq = 0;
    for (let i = 0; i < frame.length; i += 1) {
      const s = frame[i];
      sumSq += s * s;
    }
    return Math.sqrt(sumSq / frame.length) >= RMS_THRESHOLD;
  });

  // 跑 VAD
  const vad = new SpectralEnergyVAD();
  const vadDecisions: boolean[] = frames.map(f => vad.feed(f));

  it(`[${totalFrames} 帧真实访谈音频] 与 WebM 旧版（漏检=0）对比漏检率应 < 0.5%`, () => {
    let missCount = 0; // 漏检：GT=true 但 VAD=false
    let totalSpeechGt = 0;
    let firstMissAt = -1;

    for (let i = 0; i < totalFrames; i += 1) {
      if (groundTruth[i]) {
        totalSpeechGt += 1;
        if (!vadDecisions[i]) {
          missCount += 1;
          if (firstMissAt < 0) firstMissAt = i;
        }
      }
    }

    const missRate = totalSpeechGt > 0 ? missCount / totalSpeechGt : 0;

    // eslint-disable-next-line no-console
    console.log(
      `  真实访谈音频漏检: ${missCount}/${totalSpeechGt} 帧 (${(missRate * 100).toFixed(2)}%)`
    );
    // eslint-disable-next-line no-console
    console.log(
      `  VAD 放行: ${vadDecisions.filter(Boolean).length}/${totalFrames} 帧 (${((vadDecisions.filter(Boolean).length / totalFrames) * 100).toFixed(1)}%)`
    );
    // eslint-disable-next-line no-console
    console.log(`  GT 实际语音: ${totalSpeechGt}/${totalFrames} 帧`);

    // 阈值 0.5% ≈ 30s 访谈漏 0.15s（<1 个音节），可接受
    expect(missRate).toBeLessThan(0.005);
    // 报告首漏位置（调试用）
    if (firstMissAt >= 0) {
      // eslint-disable-next-line no-console
      console.log(`  首漏位置: 帧 ${firstMissAt} (${((firstMissAt * 20) / 1000).toFixed(2)}s)`);
    }
  });

  it("误检（GT 静音但 VAD 放行）应保持合理下限，避免白送 ASR", () => {
    let falsePositive = 0;
    let totalSilenceGt = 0;
    for (let i = 0; i < totalFrames; i += 1) {
      if (!groundTruth[i]) {
        totalSilenceGt += 1;
        if (vadDecisions[i]) falsePositive += 1;
      }
    }
    const fpRate = totalSilenceGt > 0 ? falsePositive / totalSilenceGt : 0;
    // eslint-disable-next-line no-console
    console.log(
      `  误检（送 ASR 的静音帧）: ${falsePositive}/${totalSilenceGt} 帧 (${(fpRate * 100).toFixed(1)}%)`
    );
    // 误检 < 50%：比 WebM 旧版（100% 静音都送）已经砍掉至少一半
    expect(fpRate).toBeLessThan(0.5);
  });
});
