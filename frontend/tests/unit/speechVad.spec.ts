import { describe, it, expect } from "vitest";
import { SpectralEnergyVAD, VAD_FRAME_SAMPLES } from "@/utils/speechVad";

const SR = 16000;
const FRAME_MS = (VAD_FRAME_SAMPLES / SR) * 1000; // 20ms

/** 生成一帧指定幅度的正弦波（频率取 800Hz 居语音带正中）。 */
function sineFrame(
  freq: number,
  amp: number, // 0..1
  seedOffset = 0
): Int16Array {
  const n = VAD_FRAME_SAMPLES;
  const out = new Int16Array(n);
  for (let i = 0; i < n; i += 1) {
    const sample = amp * Math.sin((2 * Math.PI * freq * (i + seedOffset)) / SR);
    out[i] = sample * (sample < 0 ? 0x8000 : 0x7fff);
  }
  return out;
}

/** 生成一帧白噪声（Int16 域）。 */
function whiteNoiseFrame(amp: number, seed: number): Int16Array {
  // 简易 LCG 保证跨用例可复现
  let state = seed;
  const next = () => {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    return state / 0x7fffffff;
  };
  const n = VAD_FRAME_SAMPLES;
  const out = new Int16Array(n);
  for (let i = 0; i < n; i += 1) {
    const s = (next() * 2 - 1) * amp;
    out[i] = s * (s < 0 ? 0x8000 : 0x7fff);
  }
  return out;
}

/** 静默帧。 */
const silenceFrame = (): Int16Array => new Int16Array(VAD_FRAME_SAMPLES);

/** 连续喂 N 帧相同内容，返回 N 个判定结果。 */
function feedN(vad: SpectralEnergyVAD, frame: Int16Array, n: number): boolean[] {
  const out: boolean[] = [];
  for (let i = 0; i < n; i += 1) out.push(vad.feed(frame));
  return out;
}

describe("SpectralEnergyVAD", () => {
  describe("暖启动 / 开场保护", () => {
    it("开麦后 4 帧（80ms）暖启动期间沿用 prevDecision=true，避免第一句被切", () => {
      const vad = new SpectralEnergyVAD();
      // 1024 样本 / 320 样本每帧 = 3.2 → 4 帧填满 FFT 缓冲
      const decisions = feedN(vad, silenceFrame(), 4);
      expect(decisions.every(d => d)).toBe(true);
    });

    it("开麦即说话：暖启动 4 帧内全部放行 + 后续靠 energy attack 持续放行", () => {
      const vad = new SpectralEnergyVAD();
      const frame = sineFrame(800, 0.3);
      const decisions = feedN(vad, frame, 100);
      expect(decisions.every(d => d)).toBe(true);
    });
  });

  describe("稳态静音", () => {
    it("暖启动后纯静音 1 秒，VAD 稳定判定 silence（不再下发）", () => {
      const vad = new SpectralEnergyVAD();
      // 先暖启动 4 帧
      feedN(vad, silenceFrame(), 4);
      // 再喂 50 帧静音
      const decisions = feedN(vad, silenceFrame(), 50);
      // 第 1 帧是 transition（暖启动 true → 稳态 false），仍放行
      // 稳态部分应全部 false
      const steadyState = decisions.slice(2);
      expect(steadyState.every(d => !d)).toBe(true);
    });
  });

  describe("稳态语音", () => {
    it("持续 -20dBFS 语音（amp 0.1）应全部放行", () => {
      const vad = new SpectralEnergyVAD();
      // 暖启动 4 帧静音
      feedN(vad, silenceFrame(), 4);
      // 喂 100 帧持续语音
      const decisions = feedN(vad, sineFrame(800, 0.1), 100);
      expect(decisions.every(d => d)).toBe(true);
    });

    it("稳态语音中 RMS 短暂抖动不会导致漏帧", () => {
      const vad = new SpectralEnergyVAD();
      feedN(vad, silenceFrame(), 4);
      // 100 帧语音，每帧 amp 略有不同（模拟真实语音包络）
      const decisions: boolean[] = [];
      for (let i = 0; i < 100; i += 1) {
        const amp = 0.08 + 0.04 * Math.sin(i * 0.3);
        decisions.push(vad.feed(sineFrame(800, amp, i)));
      }
      expect(decisions.every(d => d)).toBe(true);
    });
  });

  describe("transition 边界", () => {
    it("静→音 transition：attack 帧 + 后续语音帧都应放行", () => {
      const vad = new SpectralEnergyVAD();
      // 先喂静音让 VAD 进入 silence 稳态
      feedN(vad, silenceFrame(), 200);
      // 突然开始说话（强语音，触发能量 attack）
      const decisions = feedN(vad, sineFrame(800, 0.3), 5);
      // 第一帧（attack）应放行
      expect(decisions[0]).toBe(true);
      // 后续全部放行
      expect(decisions.every(d => d)).toBe(true);
    });

    it("音→静 transition：稳态 speech 之后喂安静帧，VAD 最终进入 silence 稳态", () => {
      const vad = new SpectralEnergyVAD();
      // 暖启动 + 长语音，让 VAD 进入稳态 speech
      feedN(vad, sineFrame(800, 0.3), 100);
      // 用低能量粉噪模拟"安静房间"——非零样本，避免纯零截断正弦带来的
      // 频谱泄漏干扰 spectral 判别
      const quietFrame = whiteNoiseFrame(0.001, 999);
      // 50 帧以确保 padding 30 帧耗尽后还有富余帧可断言
      const decisions = feedN(vad, quietFrame, 50);
      // 关键断言：trailing padding 30 帧用完后，VAD 进入稳态 silence
      //（不关心具体哪一帧翻的，只保证最终进入稳态 silence，不会被残余
      // speech 永远拖着）。padding 由 speech 段 ≥ 30 帧触发（够格为一句）。
      const steady = decisions.slice(40);
      expect(steady.every(d => !d)).toBe(true);
    });
  });

  describe("嘈杂环境（白噪声稳态 + 间断语音）", () => {
    it("低能量白噪声下稳态应判定为 silence（不持续计费）", () => {
      const vad = new SpectralEnergyVAD();
      feedN(vad, silenceFrame(), 4);
      // 用低能量白噪声（amp 0.005，RMS ~116）— 不触发 energy attack（< 200）
      // 且 speech band ratio 0.39 < 0.6 → spectral 判 silence
      const decisions: boolean[] = [];
      for (let i = 0; i < 50; i += 1) {
        decisions.push(vad.feed(whiteNoiseFrame(0.005, 42 + i)));
      }
      // 稳态部分应判定为 silence
      const steady = decisions.slice(5);
      expect(steady.every(d => !d)).toBe(true);
    });

    it("白噪声背景下突发强语音，0 漏剪", () => {
      const vad = new SpectralEnergyVAD();
      // 暖启动
      feedN(vad, silenceFrame(), 4);
      // 50 帧低能量白噪声
      const noiseDecisions: boolean[] = [];
      for (let i = 0; i < 50; i += 1) {
        noiseDecisions.push(vad.feed(whiteNoiseFrame(0.005, 100 + i)));
      }
      // 100 帧强语音
      const speechDecisions: boolean[] = [];
      for (let i = 0; i < 100; i += 1) {
        speechDecisions.push(vad.feed(sineFrame(800, 0.3, i)));
      }
      // 第一帧（attack）必须放行
      expect(speechDecisions[0]).toBe(true);
      // 后续 99 帧应全部放行（不允许漏剪）
      expect(speechDecisions.every(d => d)).toBe(true);
    });
  });

  describe("状态重置", () => {
    it("reset() 后行为与新实例一致（保守开场）", () => {
      const vad = new SpectralEnergyVAD();
      // 让 VAD 进入 silence 稳态
      feedN(vad, silenceFrame(), 200);
      expect(vad.isSpeech).toBe(false);
      // 重置
      vad.reset();
      // 重置后应回到"假定语音"状态
      expect(vad.isSpeech).toBe(true);
      // 暖启动 4 帧（填满 FFT 缓冲）应全部放行
      const decisions = feedN(vad, silenceFrame(), 4);
      expect(decisions.every(d => d)).toBe(true);
    });
  });

  describe("调试 getter", () => {
    it("currentNoiseFloor 暴露当前噪声地板估计，且稳定在 NOISE_FLOOR_MIN 以上", () => {
      const vad = new SpectralEnergyVAD();
      // 暖启动
      feedN(vad, silenceFrame(), 4);
      // 喂 50 帧稳定低能量白噪声（amp 0.01 → RMS ~232，spectral 判 silence）
      // noiseFloor 应通过 EMA 收敛到 232 附近
      for (let i = 0; i < 50; i += 1) {
        vad.feed(whiteNoiseFrame(0.01, 200 + i));
      }
      const nf = vad.currentNoiseFloor;
      // 收敛后应抬到稳态 RMS 附近（> 100）
      expect(nf).toBeGreaterThan(100);
      // 不应无限趋近 0（NOISE_FLOOR_MIN 保底）
      expect(nf).toBeLessThan(2000);
    });
  });

  describe("边界情况", () => {
    it("空帧不改变状态", () => {
      const vad = new SpectralEnergyVAD();
      const initial = vad.isSpeech;
      const result = vad.feed(new Int16Array(0));
      expect(result).toBe(initial);
    });

    it("frame 长度非 320 也能工作", () => {
      const vad = new SpectralEnergyVAD();
      // 用 160 样本的帧（10ms），不严格要求 320
      const frame = new Int16Array(160);
      for (let i = 0; i < 160; i += 1) {
        frame[i] = Math.sin((i / SR) * 800 * 2 * Math.PI) * 0x7fff;
      }
      // 应能正常处理不抛错
      expect(() => feedN(vad, frame, 200)).not.toThrow();
    });
  });
});
