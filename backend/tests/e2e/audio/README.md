# 测试音频 fixture

本目录的二进制样本用于不同测试层，**不要相互替换或删除**：

## `interview.webm`
- **用途**：chromium 的 `--use-file-for-fake-audio-capture` 假麦克风源
- **格式**：opus 32 kbps mono 16 kHz，封装在 WebM
- **路径引用**：`frontend/playwright.config.ts:80`、
  `frontend/tests/e2e/recording.spec.ts`
- **不要**直接喂给后端 pipeline——后端已切到 PCM 直通路径（不再解码 WebM）。

## `interview.pcm`
- **用途**：e2e 链路直接灌裸 PCM 给 `AudioPipeline.feed()`，跑断线/重连/抢占等
  chaos 场景
- **格式**：s16le mono 16 kHz，45 秒，1,440,000 字节（= 16000 × 1 × 2 × 45）
- **路径引用**：`backend/tests/e2e/chaos.py`
- **生成命令**（从 interview.webm 抽取，需要仓库历史曾依赖 ffmpeg；当前已删
  PyAV/ffmpeg 依赖，本命令仅作历史重现用，新 fixture 请另找工具或自合成）：
  ```bash
  ffmpeg -i interview.webm -ar 16000 -ac 1 -f s16le -ss 0 -t 45 interview.pcm
  ```
- **完整性校验**：`backend/tests/unit/test_pcm_fixture.py` 跑 sanity check（长度、
  对齐、首尾非静、振幅区间、RMS 下限）。更新 fixture 后务必让该测试通过。

## 如何区分
两条测试链走不同入口——浏览器侧走 `getUserMedia + AudioWorklet → PCM`，后端
chaos 侧走「直接给 PCM」绕开浏览器层。所以两个 fixture 不是冗余。