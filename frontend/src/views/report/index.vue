<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import MarkdownIt from "markdown-it";
import ReSegmented from "@/components/ReSegmented";
import { extractBackendError } from "@/utils/error";
import { ElMessage, ElMessageBox } from "element-plus";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import {
  deleteInterviewApi,
  exportInterviewReportApi,
  getInterviewDetailApi,
  getInterviewReportApi,
  InterviewDetailItem,
  type InterviewDetailType
} from "@/api/interview";

defineOptions({
  name: "Report"
});

const route = useRoute();
const router = useRouter();
const { locale, t } = useI18n();

const shareIcon = useRenderIcon("quill:share");
const moreIcon = useRenderIcon("quill:meatballs-h");
const downloadIcon = useRenderIcon("ep:download");
const deleteIcon = useRenderIcon("ep:delete");
const refreshIcon = useRenderIcon("ep:refresh");

// 初始化 markdown-it
// html:false 关闭原始 HTML 直通——LLM 报告里若被注入 <script> 或 <img onerror=…>，
// markdown-it 默认会把 HTML 实体转义而不是放行，作为 v-html 渲染前的第一道闸。
// markdown 自身的语法（**bold** / 列表 / 代码块）不需要 html:true，关闭无功能损失。
const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true
});

// 渲染 markdown 内容
const reportMarkdown = ref("");
const reportLoading = ref(true);
const reportError = ref(false);

const renderedReport = computed(() => md.render(reportMarkdown.value));
const canExportReport = computed(
  () =>
    !reportLoading.value && !reportError.value && Boolean(reportMarkdown.value)
);

const tabOptions = computed(() => [
  { key: "report", label: t("report.tab.report") },
  { key: "transcript", label: t("report.tab.transcript") },
  { key: "note", label: t("report.tab.note"), disabled: true }
]);

const tabValue = ref(0);
const interviewDetail = ref<InterviewDetailType>();
const suggestions = ref<InterviewDetailItem[]>([]);

// 派生报告页左上 3 块指标。
// 不走新接口——interviewDetail 里已经带了 transcript + items 完整数据，
// 现算成本 < 1ms。后端列表接口 _session_summary 用的「done 且 coverage 非空」
// 覆盖率口径（backend/app/transport/http/routes/interviews.py:67-73），前端
// 复用同一规则，保证两处显示一致。
// 转录文本字数：优先 corrected_text（最终改后）> text（ASR 原稿），同
// backend/app/services/reports/generator.py:232-235 的口径。
const stats = computed(() => {
  const detail = interviewDetail.value;
  const items = detail?.items ?? [];
  const transcript = detail?.transcript ?? [];
  const coverage = (detail?.coverage ?? {}) as Record<string, unknown>;

  const covered = items.filter(
    it =>
      it.status === "done" &&
      Array.isArray(coverage[it.id]) &&
      (coverage[it.id] as unknown[]).length > 0
  ).length;
  const coveragePct =
    items.length === 0
      ? 0
      : Math.round((covered / items.length) * 100);

  const transcriptChars = transcript.reduce(
    (sum, seg) =>
      sum + (seg.corrected_text?.length || seg.text?.length || 0),
    0
  );

  return [
    { value: String(coveragePct), unit: "%", label: t("report.stats.coverage") },
    {
      value: String(transcriptChars),
      unit: t("report.stats.characters_unit"),
      label: t("report.stats.transcript")
    },
    {
      value: String(transcript.length),
      unit: t("report.stats.turns_unit"),
      label: t("report.stats.conversations")
    }
  ];
});

const activeTab = computed(() => tabOptions.value[tabValue.value].key);

const transcriptList = computed(() => {
  return [...(interviewDetail.value?.transcript ?? [])].reverse().map(item => ({
    ...item
  }));
});

/** 格式化访谈记录时间 */
const formatTranscriptTime = (startMs: number | null = null) => {
  if (startMs !== null && Number.isFinite(startMs) && startMs >= 0) {
    const totalSeconds = Math.floor(startMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds]
      .map(value => String(value).padStart(2, "0"))
      .join(":");
  }
  return new Date().toLocaleTimeString(locale.value, { hour12: false });
};

/** 状态标签 */
const suggestionStatusLabel = (status: InterviewDetailItem["status"]) => {
  switch (status) {
    case "todo":
      return t("report.status.todo");
    case "new":
      return t("report.status.new");
    case "ignored":
      return t("report.status.ignored");
    case "done":
      return t("report.status.done");
    case "skipped":
      return t("report.status.skipped");
    default:
      return status;
  }
};

/** 获取访谈报告 */
const getInterviewReport = async () => {
  const id = route.params.id as string;
  if (!id) {
    reportLoading.value = false;
    reportError.value = true;
    return;
  }

  reportLoading.value = true;
  reportError.value = false;

  try {
    const res = await getInterviewReportApi(id);
    reportMarkdown.value = res?.content_md ?? "";
    reportError.value = !reportMarkdown.value;
  } catch {
    reportError.value = true;
  } finally {
    reportLoading.value = false;
  }
};

/** 获取访谈详情 */
const getInterviewDetail = async () => {
  const id = route.params.id as string;
  if (!id) return;
  const res = await getInterviewDetailApi(id);
  interviewDetail.value = res;
  suggestions.value = res?.items.map(item => item);
};

const getInterviewId = () => route.params.id as string;

/** 导出访谈报告 */
const handleExportReport = async (
  format: "md" | "html" | "word",
  extension: "md" | "html" | "docx"
) => {
  const id = getInterviewId();
  if (!id || !canExportReport.value) return;

  try {
    const report = await exportInterviewReportApi(id, format);
    const title =
      interviewDetail.value?.base_info?.title || t("report.default_title");
    const filename = `${title.replace(/[\\/:*?"<>|]/g, "_")}.${extension}`;
    const url = URL.createObjectURL(report);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  } catch (e: unknown) {
    ElMessage.error(
      extractBackendError(
        e,
        t("report.export_failed", { extension: extension.toUpperCase() })
      )
    );
  }
};

/** 删除访谈 */
const handleDeleteInterview = async () => {
  const id = getInterviewId();
  if (!id) return;

  try {
    await ElMessageBox.confirm(
      t("confirm.delete_one", {
        name: interviewDetail.value?.base_info?.title || ""
      }),
      t("report.delete_title"),
      {
        confirmButtonText: t("report.delete_confirm"),
        cancelButtonText: t("home.cancel"),
        type: "warning"
      }
    );
    await deleteInterviewApi(id);
    ElMessage.success(t("report.delete_success"));
    await router.push("/home");
  } catch (error) {
    if (error !== "cancel" && error !== "close") {
      ElMessage.error(extractBackendError(error, t("report.delete_failed")));
    }
  }
};

onMounted(async () => {
  await getInterviewDetail();
  await getInterviewReport();
});
</script>

<template>
  <div class="record-page">
    <header class="record-header">
      <div class="header-left">
        <h1 class="header-title">{{ interviewDetail?.base_info?.title }}</h1>
        <p class="header-subtitle">
          {{ interviewDetail?.base_info?.interviewee }} ·
          {{ interviewDetail?.base_info?.start_time }} ·
          {{ interviewDetail?.base_info?.duration }}{{ t("report.minutes") }}
        </p>
      </div>
      <div class="header-actions">
        <button
          style="cursor: not-allowed"
          type="button"
          :aria-label="t('report.share')"
          :title="t('report.share')"
        >
          <component :is="shareIcon" />
        </button>
        <div class="more-action">
          <button
            type="button"
            :aria-label="t('report.more')"
            :title="t('report.more')"
          >
            <component :is="moreIcon" />
          </button>
          <div class="more-menu" role="menu">
            <button
              type="button"
              role="menuitem"
              :disabled="!canExportReport"
              @click="handleExportReport('md', 'md')"
            >
              <component :is="downloadIcon" />
              <span>{{ t("report.export", { extension: "md" }) }}</span>
            </button>
            <button
              type="button"
              role="menuitem"
              :disabled="!canExportReport"
              @click="handleExportReport('html', 'html')"
            >
              <component :is="downloadIcon" />
              <span>{{ t("report.export", { extension: "html" }) }}</span>
            </button>
            <button
              type="button"
              role="menuitem"
              :disabled="!canExportReport"
              @click="handleExportReport('word', 'docx')"
            >
              <component :is="downloadIcon" />
              <span>{{ t("report.export", { extension: "docx" }) }}</span>
            </button>
            <button
              type="button"
              role="menuitem"
              class="danger"
              @click="handleDeleteInterview"
            >
              <component :is="deleteIcon" />
              <span>{{ t("report.delete") }}</span>
            </button>
          </div>
        </div>
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
              <strong>{{ stat.value }}{{ stat.unit }}</strong>
              <span>{{ stat.label }}</span>
            </div>
          </div>

          <h2>{{ t("report.core_questions") }}</h2>

          <el-scrollbar class="insight-scroll">
            <div class="suggestion-list">
              <div
                v-for="suggestion in suggestions"
                :key="suggestion.id"
                class="suggestion"
              >
                <div class="suggestion-copy">
                  <div
                    class="suggestion-title"
                    :class="{ 'not-mb': !suggestion.reason }"
                  >
                    {{ suggestion.text }}
                  </div>
                  <p v-if="suggestion.reason" class="suggestion-goal">
                    <strong>{{ t("report.follow_up_goal") }}</strong>
                    <span>{{ suggestion.reason }}</span>
                  </p>
                </div>
                <div class="suggestion-tag" :class="suggestion.status">
                  {{ suggestionStatusLabel(suggestion.status) }}
                </div>
              </div>
            </div>
          </el-scrollbar>
        </aside>

        <article class="report-card">
          <el-scrollbar class="report-scroll">
            <!-- Report -->
            <template v-if="activeTab === 'report'">
              <div
                v-if="reportLoading"
                class="report-loading"
                aria-live="polite"
              >
                <div class="loading-spinner" aria-hidden="true">
                  <span>{{ t("report.ai") }}</span>
                </div>
                <div class="loading-copy">
                  <h2>{{ t("report.loading_title") }}</h2>
                  <p>{{ t("report.loading_description") }}</p>
                </div>
              </div>
              <div v-else-if="reportError" class="report-error">
                <div class="error-mark">!</div>
                <h2>{{ t("report.error_title") }}</h2>
                <p>{{ t("report.error_description") }}</p>
                <el-button
                  type="primary"
                  class="report-retry-button"
                  :icon="refreshIcon"
                  :title="t('report.reload')"
                  @click="getInterviewReport"
                >
                  {{ t("report.reload") }}
                </el-button>
              </div>
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div v-else class="report-content" v-html="renderedReport" />
              <!-- v-html 是必需的：渲染 markdown-it 的产物为富文本。安全前提见同文件 md 配置注释（html:false + markdown-it 实体转义双层防护）。 -->
            </template>
            <!-- Transcript -->
            <div v-else-if="activeTab === 'transcript'" class="transcript-list">
              <article
                v-for="item in transcriptList"
                :key="item.seg_id"
                class="transcript-item"
              >
                <div class="transcript-content">
                  <div class="transcript-meta">
                    <span class="seg-id">{{ item.seg_id }}</span>
                  </div>
                  <p>{{ item.text }}</p>
                </div>
              </article>
            </div>
            <!-- Notes -->
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

  .more-action {
    position: relative;
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

  .more-menu {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 10;
    display: grid;
    width: 156px;
    padding: 6px;
    visibility: hidden;
    background: rgb(255 255 255 / 96%);
    border: 1px solid rgb(223 231 240 / 90%);
    border-radius: 10px;
    box-shadow: 0 10px 24px rgb(31 47 86 / 16%);
    opacity: 0;
    transform: translateY(-4px);
    transition:
      opacity 0.16s ease,
      transform 0.16s ease,
      visibility 0.16s ease;
  }

  .more-action:hover .more-menu,
  .more-action:focus-within .more-menu {
    visibility: visible;
    opacity: 1;
    transform: translateY(0);
  }

  .more-menu button {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 100%;
    height: 36px;
    padding: 0 10px;
    font-size: 13px;
    color: #334155;
    background: transparent;
    border: 0;
    border-radius: 6px;
    box-shadow: none;
  }

  .more-menu button:hover,
  .more-menu button:focus-visible {
    background: #f1f5f9;
    outline: none;
  }

  .more-menu button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .more-menu button:disabled:hover {
    background: transparent;
  }

  .more-menu button :deep(svg) {
    width: 16px;
    margin-right: 8px;
  }

  .more-menu button.danger {
    color: #e05252;
  }

  .more-menu button.danger:hover,
  .more-menu button.danger:focus-visible {
    background: #fff1f1;
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

  .tab-bar :deep(.pure-segmented-item-disabled) {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .tab-bar :deep(.pure-segmented-item-disabled:hover) {
    background: transparent;
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

  .report-loading,
  .report-error {
    display: flex;
    flex: 1;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 360px;
    padding: 32px 24px;
    text-align: center;
  }

  .loading-spinner {
    position: relative;
    display: grid;
    place-items: center;
    width: 58px;
    height: 58px;
    margin-bottom: 18px;
    border: 3px solid rgb(53 108 255 / 16%);
    border-top-color: #356cff;
    border-radius: 50%;
    animation: loading-spin 1s linear infinite;
  }

  .loading-spinner span {
    width: 48px;
    height: 48px;
    display: grid;
    place-items: center;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: #fff;
    background: #356cff;
    border-radius: 50%;
    box-shadow: 0 10px 24px rgb(53 108 255 / 28%);
    animation: loading-spin 1s linear infinite reverse;
  }

  .loading-copy {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .loading-copy h2,
  .report-error h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 800;
    color: #23376c;
  }

  .loading-copy p,
  .report-error p {
    margin: 10px 0 0;
    font-size: 12px;
    line-height: 1.6;
    color: #8995aa;
  }

  .report-error .error-mark {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    margin-bottom: 16px;
    font-size: 24px;
    font-weight: 800;
    color: #e2786f;
    background: rgb(239 121 108 / 12%);
    border: 1px solid rgb(239 121 108 / 24%);
    border-radius: 50%;
  }

  .report-retry-button {
    margin-top: 20px;
    border-radius: 8px;
  }

  @keyframes loading-spin {
    from {
      transform: rotate(0deg);
    }

    to {
      transform: rotate(360deg);
    }
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
    padding: 0 12px;
  }

  .transcript-item {
    display: block;
    padding: 14px 16px;
    border-bottom: 1px solid rgb(221 226 236 / 84%);
  }

  .transcript-item:last-child {
    border-bottom: 0;
  }

  .transcript-content {
    min-width: 0;
  }

  .transcript-meta {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
  }

  .transcript-meta .seg-id {
    font-size: 13px;
    font-weight: 600;
    color: #94a3b8;
  }

  .transcript-content p {
    margin: 0;
    font-size: 14px;
    line-height: 1.75;
    color: #334155;
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

  .suggestion-list {
    padding: 0 16px 10px;
    display: grid;
    gap: 10px;
  }

  .suggestion {
    position: relative;
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 12px 14px;
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

  .suggestion-title {
    margin-bottom: 8px;
    font-size: 14px;
    font-weight: 700;
    line-height: 1.5;
    color: #24324a;
    overflow-wrap: anywhere;

    &.not-mb {
      margin-bottom: 0;
    }
  }

  .suggestion-copy p {
    font-size: 12px;
    color: #a0aabe;
  }

  .suggestion-copy span {
    font-size: 12px;
    color: #8e9ab0;
  }

  .suggestion-tag {
    align-self: flex-start;
    white-space: nowrap;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    border-radius: 14px;
  }

  .suggestion-tag.todo {
    color: #d97706;
    background: rgb(245 158 11 / 14%);
  }

  .suggestion-tag.new {
    color: #dc2626;
    background: rgb(224 38 38 / 14%);
  }

  .suggestion-tag.done {
    color: #0f9d63;
    background: rgb(16 185 129 / 14%);
  }

  .suggestion-tag.ignored {
    color: #64748b;
    background: rgb(148 163 184 / 16%);
  }

  .suggestion-tag.skipped {
    color: #64748b;
    background: rgb(148 163 184 / 16%);
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
