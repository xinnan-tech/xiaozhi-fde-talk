<script setup lang="ts">
import { ref, computed } from "vue";
import MarkdownIt from "markdown-it";
import ReSegmented from "@/components/ReSegmented";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import reportContent from "./report-content.md?raw";

defineOptions({
  name: "Report"
});

const shareIcon = useRenderIcon("quill:share");
const moreIcon = useRenderIcon("quill:meatballs-h");
const locationIcon = useRenderIcon("boxicons:location");

// 初始化 markdown-it
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true
});

// 渲染 markdown 内容
const renderedReport = computed(() => {
  return md.render(reportContent);
});

interface Question {
  num: string;
  warm: boolean;
  title: string;
  purpose: string;
  note: string;
  status: "已覆盖" | "待追问";
}

const tabOptions = [
  { key: "report", label: "访谈报告" },
  { key: "transcript", label: "转录" },
  { key: "note", label: "笔记" }
];

const tabValue = ref(0);
const activeTab = computed(() => tabOptions[tabValue.value].key);

// 转录数据
const transcriptEntries = [
  {
    role: "说话人1",
    time: "08:40:05",
    text: "王大爷您好，今天来主要是哪里不舒服？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:40:22",
    text: "李医生，我最近一个月老头晕，有时候站起来眼前发黑，血压也高了。",
    tone: "green"
  },
  {
    role: "说话人1",
    time: "08:40:58",
    text: "头晕大概什么时候开始的？是持续性的还是一阵一阵的？有没有什么诱因？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:41:35",
    text: "大概半个月前开始的，主要是一站起来或者转头的时候晕，坐着躺着就没事。最近睡眠也不好，家里有些事情操心。",
    tone: "green"
  },
  {
    role: "说话人1",
    time: "08:42:10",
    text: "嗯，休息不好确实会影响血压。您之前有高血压病史对吧？平时吃的什么药？最近量过血压吗？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:42:50",
    text: "高血压有八年了，一直吃苯磺酸氨氯地平，一天一片。以前血压基本 140/85 左右，最近自己在家量，最高到过 162/96。",
    tone: "green"
  },
  {
    role: "说话人1",
    time: "08:43:30",
    text: "162/96 确实偏高了。药有没有按时吃？最近有没有自行加量或者停过药？",
    tone: "blue"
  },
  {
    role: "说话人2",
    time: "08:44:05",
    text: "药倒是天天吃，没断过。我看血压高了也没敢自己加，想着来看看医生再说。",
    tone: "green"
  }
];
const stats = [
  { value: "92%", label: "问题覆盖" },
  { value: "323字", label: "转录文本" },
  { value: "38轮", label: "对话" }
];

const questions = ref<Question[]>([
  {
    num: "1",
    warm: false,
    title: "决策人是谁，谁拍板？",
    purpose: "追问目的：明确实际决策链与影响人",
    note: "对方已明确总监拍板",
    status: "已覆盖"
  },
  {
    num: "2",
    warm: false,
    title: "预算 / 时间线 / 其他约束",
    purpose: "追问目的：评估可行性与排期",
    note: "已给出预算 5 万，年中前",
    status: "已覆盖"
  },
  {
    num: "3",
    warm: false,
    title: "现在怎么解决 / 有没有竞品",
    purpose: "追问目的：了解替代方案与满意度",
    note: "已说明 Excel + 群聊，试用两个竞品",
    status: "已覆盖"
  },
  {
    num: "4",
    warm: true,
    title: "怎么衡量成功没做成（可量化指标）",
    purpose: "追问目的：明确成功标准，便于后续验证",
    note: "尚未覆盖",
    status: "待追问"
  },
  {
    num: "5",
    warm: true,
    title: "对方桌上流程是什么（动机 / 目标）",
    purpose: "追问目的：挖掘决策层最本质的真实目标",
    note: "尚未覆盖",
    status: "待追问"
  }
]);
</script>

<template>
  <div class="record-page">
    <header class="record-header">
      <div class="header-left">
        <h1 class="header-title">智能潜水艇系统访谈</h1>
        <p class="header-subtitle">林晓 · 2026年8月9日 14:30 · 60分钟</p>
      </div>
      <div class="header-actions">
        <button type="button" aria-label="分享">
          <component :is="shareIcon" />
        </button>
        <button type="button" aria-label="更多">
          <component :is="moreIcon" />
        </button>
      </div>
    </header>

    <div class="record-body">
      <div class="tab-bar">
        <ReSegmented v-model="tabValue" :options="tabOptions" />
      </div>

      <div class="content-grid">
        <aside class="insight-card">
          <div class="stats">
            <div v-for="stat in stats" :key="stat.label">
              <strong>{{ stat.value }}</strong>
              <span>{{ stat.label }}</span>
            </div>
          </div>

          <h2>核心问题</h2>

          <el-scrollbar class="insight-scroll">
            <div class="question-list">
              <div
                v-for="question in questions"
                :key="question.num"
                class="question"
              >
                <div class="num" :class="{ warm: question.warm }">
                  {{ question.num }}
                </div>
                <div class="q-copy">
                  <div class="q-title">{{ question.title }}</div>
                  <p>{{ question.purpose }}</p>
                  <span
                    ><component :is="locationIcon" />{{ question.note }}</span
                  >
                </div>
                <em :class="{ pending: question.status === '待追问' }">
                  {{ question.status }}
                </em>
              </div>
            </div>
          </el-scrollbar>
        </aside>

        <article class="report-card">
          <el-scrollbar class="report-scroll">
            <!-- 访谈报告 -->
            <div
              v-if="activeTab === 'report'"
              class="report-content"
              v-html="renderedReport"
            />
            <!-- 转录 -->
            <div v-else-if="activeTab === 'transcript'" class="transcript-list">
              <article
                v-for="(item, index) in transcriptEntries"
                :key="`${item.role}-${item.time}-${index}`"
                class="transcript-item"
              >
                <div class="speaker-badge" :class="item.tone">
                  {{ item.role === "说话人1" ? "1" : "2" }}
                </div>
                <div class="transcript-content">
                  <div class="transcript-meta">
                    <strong>{{ item.role }}</strong>
                    <span>{{ item.time }}</span>
                  </div>
                  <p>{{ item.text }}</p>
                </div>
              </article>
            </div>
            <!-- 笔记 -->
            <div v-else class="note-image" />
          </el-scrollbar>
        </article>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.record-page {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  height: calc(100vh - 18px);
  padding: 38px 16px 6px;
  margin: 0 !important;
  color: #15213a;
  overflow: hidden;
}

.record-page * {
  box-sizing: border-box;
}

.record-page {
  .record-header {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: center;
    justify-content: space-between;
    background: transparent;
  }

  .header-left {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .header-title {
    margin: 0;
    font-size: 28px;
    font-weight: 600;
    color: #1a1a1a;
    letter-spacing: 0;
  }

  .header-subtitle {
    margin: 0;
    font-size: 14px;
    color: #666;
  }

  .header-actions {
    display: flex;
    gap: 12px;
    align-items: center;
  }

  .header-actions button {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    cursor: pointer;
    background: rgb(255 255 255 / 68%);
    border: 1px solid rgb(223 231 240 / 90%);
    border-radius: 50%;
    box-shadow:
      0 8px 20px rgb(107 126 154 / 12%),
      inset 0 1px 0 rgb(255 255 255 / 90%);
  }

  .header-actions img {
    width: 22px;
  }

  .record-body {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
  }

  .tab-bar {
    position: relative;
    z-index: 1;
  }

  .tab-bar :deep(.pure-segmented) {
    position: relative;
    padding: 4px;
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 22px;
    box-shadow: 0 4px 20px rgb(0 0 0 / 8%);
    backdrop-filter: blur(4px);
  }

  .tab-bar :deep(.pure-segmented-item) {
    border-radius: 18px;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .tab-bar :deep(.pure-segmented-item > div) {
    min-height: 34px;
    padding: 0 20px;
    font-size: 14px;
    font-weight: 500;
    line-height: 34px;
    color: rgb(31 35 41 / 60%);
    transition: color 0.25s;
  }

  .tab-bar :deep(.pure-segmented-item:hover) {
    background: rgb(255 255 255 / 35%);
    border-radius: 18px;
  }

  .tab-bar :deep(.pure-segmented-item:hover > div) {
    color: rgb(31 35 41 / 85%);
  }

  .tab-bar :deep(.pure-segmented-item-selected > div) {
    color: rgb(31 35 41 / 95%);
  }

  .tab-bar :deep(.pure-segmented-item-selected) {
    background: rgb(255 255 255 / 65%);
    border: 1px solid rgb(255 255 255 / 65%);
    border-radius: 18px;
    box-shadow:
      0 2px 6px rgb(31 35 41 / 8%),
      0 4px 12px rgb(31 35 41 / 6%);
    backdrop-filter: blur(4px);
  }

  .tab-bar :deep(.pure-segmented-group) {
    gap: 6px;
  }

  .content-grid {
    position: relative;
    z-index: 1;
    display: grid;
    flex: 1;
    grid-template-columns: 398px minmax(0, 1fr);
    gap: 16px;
    min-height: 0;
    padding: 19px 0 0;
    align-items: stretch;
  }

  .report-card,
  .insight-card {
    display: flex;
    flex-direction: column;
    min-height: 0;
    padding: 16px 0;
    background: rgb(255 255 255 / 68%);
    border: 1px solid rgb(255 255 255 / 72%);
    border-radius: 16px;
    box-shadow: 0 0 10px rgb(31 47 86 / 10%);
    backdrop-filter: blur(10px);
  }

  .report-scroll,
  .insight-scroll {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
  }

  .report-content {
    padding: 0 16px;
  }

  .report-content :deep(h1) {
    margin: 0 0 19px;
    font-size: 22px;
    font-weight: 850;
    line-height: 1.15;
    color: #23376c;
  }

  .report-content :deep(h2) {
    margin: 24px 0 12px;
    font-size: 16px;
    font-weight: 850;
    line-height: 1.2;
    color: #2258b8;
  }

  .report-content :deep(h3) {
    margin: 16px 0 8px;
    font-size: 13px;
    font-weight: 850;
    line-height: 1.2;
    color: #3c73c7;
  }

  .report-content :deep(p) {
    margin: 0 0 12px;
    font-size: 11px;
    font-weight: 650;
    line-height: 1.72;
    color: #52617a;
  }

  .report-content :deep(ul),
  .report-content :deep(ol) {
    margin: 0 0 12px;
    padding-left: 0;
    list-style: none;
  }

  .report-content :deep(li) {
    position: relative;
    margin-bottom: 6px;
    padding-left: 13px;
    font-size: 12px;
    font-weight: 650;
    line-height: 1.72;
    color: #52617a;
  }

  .report-content :deep(li::before) {
    position: absolute;
    top: 7px;
    left: 1px;
    width: 5px;
    height: 5px;
    content: "";
    background: #356cff;
    border-radius: 50%;
  }

  .report-content :deep(strong) {
    font-weight: 850;
  }

  .report-content :deep(em) {
    font-style: normal;
  }

  .report-content :deep(.chips) {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
  }

  .report-content :deep(.chips span) {
    display: inline-flex;
    align-items: center;
    height: 20px;
    padding: 0 10px;
    font-size: 11px;
    font-weight: 750;
    color: #5071b0;
    background: rgb(227 236 255 / 95%);
    border-radius: 10px;
  }

  /* 转录列表样式 */
  .transcript-list {
    padding: 8px 12px 12px 6px;
  }

  .transcript-item {
    display: grid;
    grid-template-columns: 40px minmax(0, 1fr);
    gap: 14px;
    padding: 18px 12px;
    border-bottom: 1px solid rgb(221 226 236 / 84%);
  }

  .transcript-item:last-child {
    border-bottom: 0;
  }

  .speaker-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    font-size: 14px;
    font-weight: 700;
    color: #fff;
    border-radius: 999px;
  }

  .speaker-badge.blue {
    background: linear-gradient(135deg, #2f6fed 0%, #2458d9 100%);
  }

  .speaker-badge.green {
    background: linear-gradient(135deg, #16b981 0%, #0ea76a 100%);
  }

  .transcript-content {
    min-width: 0;
  }

  .transcript-meta {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
  }

  .transcript-meta strong {
    font-size: 14px;
    font-weight: 700;
    color: #334155;
  }

  .transcript-meta span {
    font-size: 13px;
    font-weight: 600;
    color: #94a3b8;
  }

  .transcript-content p {
    margin: 0;
    font-size: 14px;
    line-height: 1.8;
    color: #334155;
  }

  /* 笔记图片样式 */
  .note-image {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }

  .note-image img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgb(31 47 86 / 12%);
  }

  .stats {
    padding: 0 16px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    flex: 0 0 auto;
    height: 68px;
    text-align: center;
    border-bottom: 1px solid rgb(196 207 223 / 82%);
  }

  .stats strong {
    display: block;
    font-size: 18px;
    font-weight: 850;
    line-height: 1;
    color: #7898ff;
  }

  .stats span {
    display: block;
    margin-top: 16px;
    font-size: 13px;
    font-weight: 760;
    color: #8290a6;
  }

  .insight-card h2 {
    padding: 0 16px;
    margin: 21px 0 10px;
    font-size: 18px;
    font-weight: 850;
    color: #1f315e;
  }

  .question-list {
    padding: 0 16px 10px;
    display: grid;
    gap: 10px;
  }

  .question {
    position: relative;
    display: grid;
    grid-template-columns: 30px 1fr auto;
    gap: 8px;
    min-height: 91px;
    padding: 13px 10px 11px;
    background: rgb(255 255 255 / 46%);
    border: 1px solid rgb(218 228 243 / 90%);
    border-radius: 16px;
  }

  .num {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    font-size: 11px;
    font-weight: 850;
    color: #557bff;
    background: #e6ecff;
    border-radius: 50%;
  }

  .num.warm {
    color: #df6a6a;
    background: #ffe9e7;
  }

  .q-title {
    margin: 1px 0 7px;
    font-size: 14px;
    font-weight: 850;
    line-height: 1.15;
    color: #253865;
  }

  .q-copy p {
    margin: 0 0 8px;
    font-size: 12px;
    font-weight: 650;
    line-height: 1.1;
    color: #a0aabe;
  }

  .q-copy span {
    display: flex;
    gap: 4px;
    align-items: center;
    font-size: 12px;
    font-weight: 650;
    line-height: 1;
    color: #8e9ab0;
  }

  .q-copy img {
    width: 13px;
  }

  .question em {
    align-self: start;
    font-size: 12px;
    font-style: normal;
    font-weight: 700;
    color: #6f7a90;
  }

  .question em.pending {
    color: #e27272;
  }
}

@media (max-width: 1180px) {
  .record-page .content-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .record-page {
    padding: 20px 12px 16px;
  }

  .record-page .record-header {
    padding: 0 12px 4px;
  }

  .record-page .record-body {
    padding: 0 12px;
  }

  .record-page .tab-bar {
    width: 100%;
  }
}
</style>
