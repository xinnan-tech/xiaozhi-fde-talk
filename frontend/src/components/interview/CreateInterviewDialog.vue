<script setup lang="ts">
import {
  computed,
  nextTick,
  reactive,
  ref,
  watch,
  watchEffect,
  markRaw
} from "vue";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import type { FormInstance, FormRules } from "element-plus/es/components/form";
import { ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";
import { message } from "@/utils/message";
import { extractBackendError } from "@/utils/error";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import { AVMedia } from "vue-audio-visual";
import { useAsrRecorder } from "@/composables/useAsrRecorder";
import { useCameraCapture, blobToBase64 } from "@/composables/useCameraCapture";
import { useAbortableRequests } from "@/composables/useAbortableRequests";
import ImageCropDialog from "./ImageCropDialog.vue";
import {
  extractInterviewFieldsApi,
  getInterviewsTemplatesApi,
  getInterviewTemplateDetailApi,
  ocrInterviewImageApi,
  type CreateInterviewForm,
  type TemplateBaseField,
  type TemplateItem
} from "@/api/interview";

dayjs.extend(customParseFormat);

// 与后端 OCR 路由 magic bytes 白名单对齐：jpg / jpeg / jpe / png / bmp。
const ALLOWED_IMAGE_EXTS = ["jpg", "jpeg", "jpe", "png", "bmp"] as const;

defineOptions({
  name: "CreateInterviewDialog"
});

const props = defineProps<{
  modelValue: boolean;
  submitting?: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
  (event: "submit", value: CreateInterviewForm): void;
}>();

const { t } = useI18n();

// 弹窗宽度：桌面端 900px 让模板 4 字段一行放下（1600px 视口下不再 3+1 折行）；
// 92vw 保证窄屏不会超出视口；移动端 @media 里有 !important 兜底到 100%-24px
const dialogWidth = "min(900px, 92vw)";

const userIcon = markRaw(useRenderIcon("tabler:user"));
const calendarIcon = markRaw(useRenderIcon("tabler:calendar"));
const microphoneIcon = markRaw(useRenderIcon("tabler:microphone"));
const cameraIcon = markRaw(useRenderIcon("tabler:camera"));
const clipboardIcon = markRaw(useRenderIcon("tabler:clipboard-text"));

const formRef = ref<FormInstance>();
const selectedInputMethod = ref("");
type ActivePanel = "" | "clipboard" | "voice" | "camera" | "cropPreview";
const activePanel = ref<ActivePanel>("");
const goalError = ref("");
const interviewTemplates = ref<TemplateItem[]>([]);
const interviewTemplatesLoading = ref(false);
const templateFields = ref<TemplateBaseField[]>([]);
const templateFieldsTemplateId = ref("");
const clipboardText = ref("");
const clipboardExtracting = ref(false);
const voiceExtracting = ref(false);
const cameraRecognizing = ref(false);
const cameraFrozen = ref(false);
const cameraVideoRef = ref<HTMLVideoElement>();
const fileInputRef = ref<HTMLInputElement>();
const frozenImageSrc = ref("");
const showCropDialog = ref(false);
const pendingImageBase64 = ref("");
const cropPreviewSrc = ref("");
const createDefaultForm = (): CreateInterviewForm => ({
  // base_info 的键由所选模板的 base_fields 决定（applyTemplateDefaults
  // 加载时逐字段初始化兜底值），这里不再预置固定键
  base_info: {},
  goal: "",
  template_id: ""
});
const form = reactive<CreateInterviewForm>(createDefaultForm());
const {
  createSignal,
  finish: finishRequest,
  cancel: cancelRequest,
  isCanceled
} = useAbortableRequests();

// 语音转写录音：/ws/v1/asr 专用 WS + 麦克风（区别于访谈会话 WS）
const {
  mediaStream: asrMediaStream,
  state: asrState,
  transcript: asrTranscript,
  elapsedSeconds: asrElapsedSeconds,
  stopReason: asrStopReason,
  everRecorded: asrEverRecorded,
  error: asrError,
  start: startAsrRecording,
  stop: stopAsrRecording,
  cancel: cancelAsrRecording
} = useAsrRecorder();

// 拍照名片 OCR：取流 + 截帧，预览 <video> 挂在面板模板里
const {
  stream: cameraStream,
  open: openCamera,
  close: closeCamera,
  snap: snapCamera
} = useCameraCapture();

// 显示名/占位：模板 label 优先；canonical 键（历史模板没配 label 时）
// 回退全局文案，其余回退 key 本身
const canonicalLabel = (key: string): string =>
  ({
    project: t("create.dialog.project"),
    interviewee: t("create.dialog.interviewee"),
    start_time: t("create.dialog.start_time"),
    duration: t("create.dialog.duration")
  })[key] ?? key;
const canonicalPlaceholder = (key: string): string =>
  ({
    project: t("create.dialog.project_placeholder"),
    interviewee: t("create.dialog.interviewee_placeholder"),
    start_time: t("create.dialog.start_time_placeholder"),
    duration: t("create.dialog.duration_placeholder")
  })[key] ?? "";
const fieldLabelOf = (field: TemplateBaseField) =>
  field.label?.trim() || canonicalLabel(field.key);
const fieldPlaceholderOf = (field: TemplateBaseField) =>
  templateHints.value[field.key] ||
  canonicalPlaceholder(field.key) ||
  (field.type === "duration" || field.type === "datetime"
    ? t("create.dialog.field_select_ph", { label: fieldLabelOf(field) })
    : t("create.dialog.field_input_ph", { label: fieldLabelOf(field) }));

const rules = computed<FormRules>(() => {
  const result: FormRules = {
    "base_info.title": [
      {
        required: true,
        message: t("create.dialog.name_required"),
        trigger: "blur"
      }
    ],
    template_id: [
      {
        required: true,
        message: t("create.dialog.template_required"),
        trigger: "change"
      }
    ],
    goal: [
      {
        required: true,
        trigger: "blur",
        validator: (_rule, value, callback) => {
          if (!value?.trim()) {
            goalError.value = t("create.dialog.goal_required");
            callback(new Error(t("create.dialog.goal_required")));
            return;
          }
          goalError.value = "";
          callback();
        }
      }
    ]
  };
  // 业务字段的必填规则跟着模板走（BaseField.required），trigger 按控件类型定
  for (const field of templateFields.value) {
    if (!field.required) continue;
    result[`base_info.${field.key}`] = [
      {
        required: true,
        message: t("create.dialog.field_required", {
          label: fieldLabelOf(field)
        }),
        trigger: field.type === "text" || !field.type ? "blur" : "change"
      }
    ];
  }
  return result;
});

const inputMethods = computed(() => [
  {
    key: "voice",
    title: t("create.dialog.voice_title"),
    description: t("create.dialog.voice_description"),
    icon: microphoneIcon,
    color: "#4a90e2",
    background: "rgba(74, 144, 226, 0.12)"
  },
  {
    key: "camera",
    title: t("create.dialog.camera_title"),
    description: t("create.dialog.camera_description"),
    icon: cameraIcon,
    color: "#52c41a",
    background: "rgba(82, 196, 26, 0.12)"
  },
  {
    key: "clipboard",
    title: t("create.dialog.clipboard_title"),
    description: t("create.dialog.clipboard_description"),
    icon: clipboardIcon,
    color: "#722ed1",
    background: "rgba(114, 46, 209, 0.12)"
  }
]);

const durationOptions = computed(() => [
  { label: t("create.dialog.duration_30"), value: "30" },
  { label: t("create.dialog.duration_45"), value: "45" },
  { label: t("create.dialog.duration_60"), value: "60" },
  { label: t("create.dialog.duration_120"), value: "120" }
]);

const resetForm = async () => {
  // 兜底释放录音/摄像头（正常路径由 destroy-on-close 卸载时清理）
  cancelRequest("extract");
  cancelAsrRecording();
  closeCamera();
  formRef.value?.resetFields();
  Object.assign(form, createDefaultForm());
  // 兜底值记录随表单一起清空：模板默认值只取代兜底值，不取代用户改动
  for (const key of Object.keys(autoValues)) delete autoValues[key];
  templateHints.value = {};
  form.template_id = interviewTemplates.value[0]?.id ?? "";
  selectedInputMethod.value = "";
  activePanel.value = "";
  clipboardText.value = "";
  clipboardExtracting.value = false;
  voiceExtracting.value = false;
  cameraRecognizing.value = false;
  cameraFrozen.value = false;
  frozenImageSrc.value = "";
  cropPreviewSrc.value = "";
  goalError.value = "";
  await nextTick();
  formRef.value?.clearValidate();
};

const closeActivePanel = () => {
  selectedInputMethod.value = "";
  activePanel.value = "";
  cameraFrozen.value = false;
  frozenImageSrc.value = "";
  cropPreviewSrc.value = "";
  closeCamera();
};

const showMicrophonePermissionGuide = () => {
  // flags 指引只适用于 HTTP + 局域网 IP
  if (asrError.value?.message !== "mic_unavailable_insecure_origin") {
    message(t("interview.runtime.mic_permission"), { type: "error" });
    return;
  }

  void ElMessageBox.alert(
    t("interview.runtime.mic_permission_guide", {
      origin: window.location.origin
    }),
    t("interview.runtime.mic_permission_title"),
    {
      type: "warning",
      confirmButtonText: t("interview.runtime.mic_permission_confirm"),
      customStyle: { maxWidth: "588px" },
      closeOnClickModal: true
    }
  ).catch(() => undefined);
};

const selectInputMethod = async (methodKey: string) => {
  // 录音进行中不允许切换入口，先停止识别
  if (asrState.value !== "idle") return;
  if (
    methodKey !== "voice" &&
    methodKey !== "camera" &&
    methodKey !== "clipboard"
  ) {
    return;
  }
  selectedInputMethod.value = methodKey;
  activePanel.value = methodKey;

  if (methodKey === "voice") {
    const started = await startAsrRecording();
    if (!started) {
      showMicrophonePermissionGuide();
      closeActivePanel();
    }
  } else if (methodKey === "camera") {
    const opened = await openCamera();
    if (!opened) {
      message(t("create.dialog.camera_unavailable"), { type: "error" });
      closeActivePanel();
    }
  }
};

const loadTemplateFields = async (templateId: string) => {
  if (!templateId || templateFieldsTemplateId.value === templateId) {
    return templateFields.value;
  }

  const template = await getInterviewTemplateDetailApi(templateId);
  templateFields.value = template.session?.base_fields ?? [];
  templateSession.value = template.session ?? {};
  templateFieldsTemplateId.value = templateId;
  return templateFields.value;
};

// 模板字段的兜底初值/默认值与占位提示
// - 兜底初值按类型：datetime=此刻（访谈多为马上开始）、duration=45、其余空串，
//   加载模板时只补缺失的键
// - 模板默认值（default）只取代兜底值或空值，用户改过的不动——预填永远
//   不覆盖人的输入；访谈名称/访谈目标是固定伪字段，默认值在
//   session.title_default / goal_default
// - 占位提示：模板配了就替代全局文案；重置时清空回退
const templateHints = ref<Record<string, string>>({});
const templateSession = ref<{
  title_default?: string;
  goal_default?: string;
}>({});
// 各字段「未经用户手」的兜底值：模板 default 只取代兜底值
const autoValues: Record<string, string> = {};

const fallbackForType = (type: string): string => {
  if (type === "datetime") return dayjs().format("YYYY-MM-DD HH:mm:ss");
  if (type === "duration") return "45";
  return "";
};

const applyTemplateDefaults = async (templateId: string) => {
  if (!templateId) return;
  const fields = await loadTemplateFields(templateId);
  const baseInfo = form.base_info as Record<string, string>;
  const hints: Record<string, string> = {};

  // 切模板时清理残留：上一模板的 default + 用户输入可能让 base_info 留下
  // 不属于当前模板 base_fields 的键（孤儿数据：报告占位符用不到、用户
  // 在表单里也看不到，但会随提交一起落库）。保留 title（伪字段）和
  // end_time（提交时根据 datetime+duration 重算）；goal 是 form 顶层字段，
  // 不在 base_info 里，留给后续 goal_default 逻辑处理
  const validKeys = new Set<string>([
    ...fields.map(f => f.key),
    "title",
    "end_time",
  ]);
  for (const key of Object.keys(baseInfo)) {
    if (!validKeys.has(key)) delete baseInfo[key];
  }
  for (const key of Object.keys(autoValues)) {
    if (!validKeys.has(key)) delete autoValues[key];
  }

  // 先补兜底初值（只补缺失的键，已有值不动）
  for (const field of fields) {
    if (!(field.key in baseInfo)) {
      const fallback = fallbackForType(field.type || "text");
      baseInfo[field.key] = fallback;
      autoValues[field.key] = fallback;
    }
  }

  const titlePreset = templateSession.value.title_default?.trim();
  if (titlePreset && !baseInfo.title?.trim()) baseInfo.title = titlePreset;
  const goalPreset = templateSession.value.goal_default?.trim();
  if (goalPreset && !form.goal.trim()) form.goal = goalPreset;

  for (const field of fields) {
    const preset = field.default?.trim();
    if (preset) {
      const current = baseInfo[field.key] ?? "";
      // 当前值既非空也非兜底值 = 用户已动过，不覆盖
      if (current && current !== autoValues[field.key]) continue;
      const value = normalizeByType(field.type || "text", preset);
      if (value) baseInfo[field.key] = value;
    }
    if (field.placeholder?.trim()) {
      hints[field.key] = field.placeholder.trim();
    }
  }
  templateHints.value = hints;
  // 默认值填好后清掉 el-form 已挂上的错误态（rules computed 重新绑定 prop
  // 时偶尔会让「name」这种 required 字段带着 stale error 出现，视觉上像
  // 「已经填好却报错」——#12）。nextTick 等 prop/render 同步完再清
  await nextTick();
  formRef.value?.clearValidate();
};

watch(
  () => form.template_id,
  id => {
    if (!id || !props.modelValue) return;
    // 拉取失败不阻塞建访谈，占位/默认值退回全局兜底
    applyTemplateDefaults(id).catch(() => undefined);
  }
);

// 按字段类型规整提取/预填值：duration 吸附到最近档位，datetime 补全秒位，
// 其余原样返回。类型来自模板 base_fields（text/datetime/duration）
const normalizeByType = (type: string, value: string) => {
  if (type === "duration") {
    const source = Number.parseInt(value, 10);
    if (!Number.isFinite(source)) return "";
    return durationOptions.value.reduce((closest, option) => {
      return Math.abs(Number(option.value) - source) <
        Math.abs(Number(closest) - source)
        ? option.value
        : closest;
    }, durationOptions.value[0]?.value ?? "");
  }

  if (type === "datetime") {
    const parsed = dayjs(value, "YYYY-MM-DDTHH:mm", true);
    if (parsed.isValid()) {
      return parsed.format("YYYY-MM-DD HH:mm:ss");
    }
  }

  return value;
};

/** 公共提取流程：与文本来源无关（粘贴/录音转写/拍照 OCR 共用），返回成功回填的字段数。 */
const runExtractAndFill = async (transcript: string) => {
  // 模板详情提供字段名称和字段类型
  const fields = await loadTemplateFields(form.template_id);
  const fieldLabels: Record<string, string> = {};
  const fieldTypes: Record<string, string> = {};
  const fieldKeys = fields.map(field => {
    fieldLabels[field.key] = field.label || field.key;
    fieldTypes[field.key] = field.type || "text";
    return field.key;
  });

  // 访谈名称和目标不属于模板基础字段
  fieldKeys.push("title", "goal");
  fieldLabels.title = t("create.dialog.interview_name");
  fieldLabels.goal = t("create.dialog.goal");

  // 已填写的值会作为上下文传给后端
  const currentValues: Record<string, string> = {};
  const baseInfo = form.base_info as Record<string, string>;
  for (const key of fieldKeys) {
    const value =
      key === "title"
        ? form.base_info.title
        : key === "goal"
          ? form.goal
          : baseInfo[key];
    if (value) currentValues[key] = String(value);
  }

  // 创建extract的controller.signal
  const signal = createSignal("extract");
  try {
    // 后端根据文本和字段定义返回提取结果
    const response = await extractInterviewFieldsApi(
      {
        transcript,
        template_id: form.template_id,
        fields: fieldKeys,
        field_labels: fieldLabels,
        field_types: fieldTypes,
        current_values: currentValues
      },
      signal
    );

    // 请求返回前已取消时，不再回填表单或显示结果消息
    if (signal.aborted) return null;

    // 将提取结果写回表单控件；只回填模板字段/名称/目标（后端不会返回
    // 之外的键，这里再拦一道），值与当前一致的回显不计入 filled
    const fieldKeySet = new Set(fields.map(f => f.key));
    const fieldTypeOf = (key: string) =>
      fields.find(f => f.key === key)?.type || "text";
    let filled = 0;
    for (const [key, rawValue] of Object.entries(response.values ?? {})) {
      if (!rawValue) continue;
      if (key !== "title" && key !== "goal" && !fieldKeySet.has(key)) {
        continue;
      }
      const value =
        key === "title" || key === "goal"
          ? String(rawValue)
          : normalizeByType(fieldTypeOf(key), String(rawValue));
      if (!value) continue;

      const previous =
        key === "title"
          ? form.base_info.title
          : key === "goal"
            ? form.goal
            : baseInfo[key];
      if (previous === value) continue;

      if (key === "title") {
        form.base_info.title = value;
      } else if (key === "goal") {
        form.goal = value;
        goalError.value = "";
      } else {
        baseInfo[key] = value;
      }
      filled += 1;
    }

    message(
      filled > 0
        ? t("create.dialog.clipboard_success", { count: filled })
        : t("create.dialog.clipboard_no_fields"),
      { type: filled > 0 ? "success" : "warning" }
    );
    if (filled > 0) {
      formRef.value?.clearValidate([
        "base_info.title",
        "goal",
        ...fields.map(f => `base_info.${f.key}`)
      ]);
    }
    return filled;
  } catch (error) {
    if (isCanceled(error)) return null;
    throw error;
  } finally {
    finishRequest("extract", signal);
  }
};

const extractClipboardText = async () => {
  // 只提交有实际内容的文本
  const transcript = clipboardText.value.trim();
  if (!transcript) {
    message(t("create.dialog.clipboard_empty"), { type: "warning" });
    return;
  }

  clipboardExtracting.value = true;
  try {
    const filled = await runExtractAndFill(transcript);
    if (filled === null) return;
    clipboardText.value = "";
    closeActivePanel();
  } catch (error) {
    if (!isCanceled(error)) {
      message(extractBackendError(error, t("create.dialog.clipboard_failed")), {
        type: "error"
      });
    }
  } finally {
    clipboardExtracting.value = false;
  }
};

const voiceBusy = computed(
  () => asrState.value !== "idle" || voiceExtracting.value
);

const voiceElapsedLabel = computed(() => {
  const minutes = String(Math.floor(asrElapsedSeconds.value / 60)).padStart(
    2,
    "0"
  );
  const seconds = String(asrElapsedSeconds.value % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
});

// 转写区占位文案跟随真实状态：停止/提取阶段不再误显「录音中」
const voicePlaceholder = computed(() =>
  asrState.value === "recording"
    ? t("create.dialog.voice_recording")
    : t("create.dialog.voice_stopping")
);

/** 停止录音并提取：手动点停止与服务端自动停止（60s 上限）共用。 */
const extractVoiceTranscript = async () => {
  if (voiceExtracting.value) return;
  voiceExtracting.value = true;
  try {
    const transcript = (await stopAsrRecording()).trim();
    if (!transcript) {
      // 服务端断开（ASR 服务不可用）与真没说话，给出不同的提示
      if (asrStopReason.value === "server") {
        message(t("create.dialog.voice_service_unavailable"), {
          type: "error"
        });
      } else {
        message(t("create.dialog.voice_empty"), { type: "warning" });
      }
      // 空结果没有内容可留在面板，退回入口列表，避免卡在「录音中」假状态
      closeActivePanel();
      return;
    }
    const filled = await runExtractAndFill(transcript);
    if (filled === null) return;
    closeActivePanel();
  } catch (error) {
    if (!isCanceled(error)) {
      message(extractBackendError(error, t("create.dialog.voice_failed")), {
        type: "error"
      });
    }
    // 提取失败同样退回入口列表，面板不留不可操作的僵尸态
    closeActivePanel();
  } finally {
    voiceExtracting.value = false;
  }
};

const recognizePhoto = async () => {
  const video = cameraVideoRef.value;
  // readyState >= 1 表示视频已可以进行渲染
  if (!video || cameraRecognizing.value || video.readyState < 1) return;

  // snap 内部可能因 canvas.getContext 返 null 或 canvas.toBlob 返 null 而
  // throw（readyState 不覆盖这两种），必须在 click handler 里兜住，否则
  // unhandled rejection 让按钮永久 loading+disabled。
  let imageBase64: string;
  try {
    imageBase64 = await snapCamera(video);
  } catch (error) {
    message(extractBackendError(error, t("create.dialog.camera_unavailable")), {
      type: "error"
    });
    return;
  }

  // 截取当前帧作为定格画面，同时关闭摄像头释放资源
  frozenImageSrc.value = `data:image/jpeg;base64,${imageBase64}`;
  cameraFrozen.value = true;
  closeCamera();
};

const submitRecognition = async () => {
  if (!frozenImageSrc.value || cameraRecognizing.value) return;

  cameraRecognizing.value = true;
  try {
    // frozenImageSrc 是 data:image/jpeg;base64,... 格式，需要去掉前缀
    const imageBase64 = frozenImageSrc.value.slice(
      frozenImageSrc.value.indexOf(",") + 1
    );
    const response = await ocrInterviewImageApi({
      image_base64: imageBase64
    });
    const text = (response.text ?? "").trim();
    if (!text) {
      message(t("create.dialog.ocr_empty"), { type: "warning" });
      return;
    }
    const filled = await runExtractAndFill(text);
    if (filled === null) return;
    closeActivePanel();
  } catch (error) {
    message(extractBackendError(error, t("create.dialog.ocr_failed")), {
      type: "error"
    });
    // 识别失败时保留定格画面，用户可点击"重拍"或再次点击"提交识别"重试
  } finally {
    // 成功 closeActivePanel / 空文本 early return / catch 三支都必须重置，
    // 否则重新进入拍照面板时按钮永远 loading+disabled。
    cameraRecognizing.value = false;
  }
};

const retakePhoto = async () => {
  cameraFrozen.value = false;
  frozenImageSrc.value = "";
  // 与 selectInputMethod('camera') 一致：openCamera 失败时 message +
  // closeActivePanel，否则用户卡在无画面状态只能点"返回"。
  const opened = await openCamera();
  if (!opened) {
    message(t("create.dialog.camera_unavailable"), { type: "error" });
    closeActivePanel();
  }
};

const triggerFileUpload = () => {
  fileInputRef.value?.click();
};

const handleFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    // 用户取消了文件选择，什么都不做，摄像头继续正常使用
    return;
  }

  // 客户端前置校验（与后端 10MB 阈值对齐）：<input accept="image/*"> 只是
  // 系统选择器的提示，DevTools 可改、桌面端"全部文件"能绕过；不先拒的话
  // FileReader 会把任意二进制转 base64（约 4/3 倍内存）再 POST，等服务器
  // 回 413 已浪费上行带宽与解析时间。前端先拦，错误立即可见。
  if (file.size > 10 * 1024 * 1024) {
    message(t("create.dialog.image_too_large"), { type: "error" });
    input.value = "";
    return;
  }
  if (!file.type.startsWith("image/")) {
    message(t("create.dialog.invalid_file_type"), { type: "error" });
    input.value = "";
    return;
  }
  // 扩展名白名单与后端路由 magic bytes 一致（JPG / JPEG / JPE / PNG / BMP）。
  // 部分桌面 OS 给 .jpe / .bmp 的 MIME 可能是 image/pjpeg 或空，仅靠
  // file.type 嗅不出这些格式，file.name 后缀兜底一道。
  const ext = file.name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] ?? "";
  if (!(ALLOWED_IMAGE_EXTS as readonly string[]).includes(ext)) {
    message(t("create.dialog.image_format_unsupported"), { type: "error" });
    input.value = "";
    return;
  }

  // 选择文件后打开裁切弹窗，同时关闭摄像头
  closeCamera();
  try {
    pendingImageBase64.value = await blobToBase64(file);
    showCropDialog.value = true;
  } catch (error) {
    message(extractBackendError(error, t("create.dialog.upload_failed")), {
      type: "error"
    });
  } finally {
    // 重置 input 以便下次选择同一文件
    input.value = "";
  }
};

const handleCropConfirm = async (croppedBase64: string) => {
  showCropDialog.value = false;
  cropPreviewSrc.value = `data:image/jpeg;base64,${croppedBase64}`;
  selectedInputMethod.value = "cropPreview";
  activePanel.value = "cropPreview";
};

const handleCropSubmit = async () => {
  if (cameraRecognizing.value || !cropPreviewSrc.value) return;
  cameraRecognizing.value = true;
  try {
    const imageBase64 = cropPreviewSrc.value.slice(
      cropPreviewSrc.value.indexOf(",") + 1
    );
    const response = await ocrInterviewImageApi({ image_base64: imageBase64 });
    const text = (response.text ?? "").trim();
    if (!text) {
      message(t("create.dialog.ocr_empty"), { type: "warning" });
      // 关闭 panel 让用户回到方式选择可重试；否则 preview 区只剩无 srcObject
      // 的 <video>，除了"返回"没恢复手段。
      closeActivePanel();
      return;
    }
    await runExtractAndFill(text);
    closeActivePanel();
  } catch (error) {
    message(extractBackendError(error, t("create.dialog.upload_failed")), {
      type: "error"
    });
    // 识别异常也退出 panel，让用户决定重试还是换路径。
    closeActivePanel();
  } finally {
    cameraRecognizing.value = false;
    cropPreviewSrc.value = "";
  }
};

const handleCropReselect = () => {
  cropPreviewSrc.value = "";
  selectedInputMethod.value = "camera";
  activePanel.value = "camera";
  cameraFrozen.value = false;
  void openCamera();
};

// 服务端触发停止（60s 上限/连接断开）时，与手动停止走同一提取流程；
// everRecorded=false 说明 start() 未成功过（如启动即断开），按启动失败处理不提取
watch(asrState, (next, previous) => {
  if (previous !== "stopping" || next !== "idle") return;
  if (voiceExtracting.value || !asrEverRecorded.value) return;
  void extractVoiceTranscript();
});

// 裁切弹窗关闭时回到拍摄区并重新打开摄像头
watch(showCropDialog, val => {
  if (val) return;
  if (cropPreviewSrc.value) return; // 裁切确认后会走这里，跳过摄像头重置
  selectedInputMethod.value = "camera";
  activePanel.value = "camera";
  cameraFrozen.value = false;
  void openCamera();
});

// 摄像头流挂到预览 <video>（面板渲染与取流完成先后不定，post flush 兜底）
watchEffect(
  () => {
    const video = cameraVideoRef.value;
    const stream = cameraStream.value;
    if (!video) return;
    const next = stream ?? null;
    if (video.srcObject !== next) {
      video.srcObject = next;
    }
    if (stream) {
      void video.play().catch(() => undefined);
    }
  },
  { flush: "post" }
);

const loadInterviewTemplates = async () => {
  // 先清模板字段缓存再拉列表：template_id 观察者可能在列表返回前就触发
  // applyTemplateDefaults，清晚了它读到旧缓存、随后又被这里清空——
  // 动态表单的字段会凭空消失。清在设 template_id 之前，观察者必然重拉。
  // 同一模板二次开 dialog 时 form.template_id 不会变化（resetForm 已经
  // 把值设成 cached id，watcher 看到新值==旧值不触发），这里在模版未
  // 变分支里手动跑一遍 applyTemplateDefaults，让 base_fields 行不变成空白
  templateFields.value = [];
  templateSession.value = {};
  templateFieldsTemplateId.value = "";
  interviewTemplatesLoading.value = true;
  try {
    const response = await getInterviewsTemplatesApi();
    interviewTemplates.value = response.items;
    const nextTemplateId = response.items[0]?.id ?? "";
    if (form.template_id !== nextTemplateId) {
      // 模板变了：观察者触发 applyTemplateDefaults
      form.template_id = nextTemplateId;
    } else if (props.modelValue) {
      // 同一模板二次开：观察者不触发，手动兜底（base_fields 行依赖
      // templateFields.value，上面已经清空过——否则 e2e 第二次建访谈
      // 会找不到「项目/对象」等字段）
      applyTemplateDefaults(nextTemplateId).catch(() => undefined);
    }
  } catch {
    interviewTemplates.value = [];
    form.template_id = "";
  } finally {
    interviewTemplatesLoading.value = false;
  }
};

// end_time = 第一个 datetime 字段 + 第一个 duration 字段（模板没配则空）
const calculateEndTime = () => {
  const fields = templateFields.value;
  const datetimeKey =
    fields.find(f => f.type === "datetime")?.key ?? "start_time";
  const durationKey =
    fields.find(f => f.type === "duration")?.key ?? "duration";
  const startRaw = form.base_info[datetimeKey];
  const durationRaw = form.base_info[durationKey];
  if (!startRaw || !durationRaw) return "";

  const startTime = dayjs(
    startRaw,
    ["YYYY-MM-DD HH:mm:ss", "YYYY-MM-DDTHH:mm:ss"],
    true
  );
  const minutes = Number(durationRaw);
  if (!startTime.isValid() || !Number.isFinite(minutes)) return "";

  return startTime.add(minutes, "minute").format("YYYY-MM-DD HH:mm:ss");
};

const handleModelValueChange = (value: boolean) => {
  if (!value) {
    cancelRequest("extract");
    cancelAsrRecording();
    // 关闭对话框时也要释放摄像头，与 handleClose 保持一致
    cameraFrozen.value = false;
    frozenImageSrc.value = "";
    closeCamera();
  }
  emit("update:modelValue", value);
};

const handleClose = () => {
  cameraFrozen.value = false;
  frozenImageSrc.value = "";
  closeCamera();
  // 取消extract请求
  cancelRequest("extract");
  // 取消asr录音,释放ws连接
  cancelAsrRecording();
  emit("update:modelValue", false);
};

const handleSubmit = async () => {
  if (props.submitting) return;
  if (!formRef.value) return;

  if ((form.goal?.length || 0) > 100) {
    message(t("create.dialog.goal_too_long"), { type: "error" });
    return;
  }

  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) {
    // 表单比一屏长（名称/时间/模板/目标），出错的字段常在滚动区外：
    // scroll-to-error 负责滚过去标红，这里再 toast 一条兜底，避免「点了没反应」
    message(t("create.dialog.form_invalid"), { type: "warning" });
    return;
  }

  form.base_info.end_time = calculateEndTime();

  emit("submit", {
    ...form,
    base_info: { ...form.base_info }
  });
};

watch(
  () => props.modelValue,
  async value => {
    if (value) {
      resetForm();
      await loadInterviewTemplates();
    }
  }
);
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :width="dialogWidth"
    align-center
    destroy-on-close
    class="create-interview-dialog"
    @update:model-value="handleModelValueChange"
    @closed="formRef?.clearValidate()"
  >
    <template #header>
      <div class="text-[18px] font-semibold text-[#1f2329]">
        {{ $t("create.dialog.title") }}
      </div>
    </template>

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      require-asterisk-position="right"
      scroll-to-error
      class="create-interview-form"
    >
      <section class="form-section">
        <div class="section-title">
          <h3>{{ $t("create.dialog.basic_info") }}</h3>
        </div>
        <div class="form-grid">
          <div class="secondary-fields-row">
            <el-form-item prop="base_info.title">
              <template #label>
                <span class="form-label-content">
                  <span class="required-prefix">*</span>
                  {{ $t("create.dialog.interview_name") }}
                </span>
              </template>
              <el-input
                v-model="form.base_info.title"
                :placeholder="$t('create.dialog.name_placeholder')"
              />
            </el-form-item>
          </div>

          <!-- 访谈模板提到访谈名称之后：先告诉系统这条访谈是什么，
               下面的 base_fields 才会按所选模板渲染对应的字段 -->
          <el-form-item prop="template_id" class="template-field">
            <template #label>
              <span class="form-label-content">
                <span class="required-prefix">*</span>
                {{ $t("create.dialog.template") }}
              </span>
            </template>
            <el-select
              v-model="form.template_id"
              :placeholder="$t('create.dialog.template_placeholder')"
              :loading="interviewTemplatesLoading"
              :disabled="interviewTemplatesLoading"
            >
              <el-option
                v-for="template in interviewTemplates"
                :key="template.id"
                :label="template.name"
                :value="template.id"
              />
            </el-select>
          </el-form-item>

          <!-- 业务字段按模板 base_fields 渲染（label=显示名，控件跟类型走）：
               text→输入框 datetime→时间选择 duration→档位下拉 -->
          <div class="basic-fields-row">
            <el-form-item
              v-for="f in templateFields"
              :key="f.key"
              :class="{ 'is-duration': f.type === 'duration' }"
              :prop="`base_info.${f.key}`"
            >
              <template #label>
                <span class="form-label-content">
                  <!-- Element Plus 在 label-position=top 下不会渲染 .el-form-item__required 红星（#15），
                       这里手动拼红字「* 」绕开；模板字段级 required:true 才显示 -->
                  <span v-if="f.required" class="required-prefix">*</span>
                  {{ fieldLabelOf(f) }}
                </span>
              </template>
              <el-date-picker
                v-if="f.type === 'datetime'"
                v-model="form.base_info[f.key]"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                format="YYYY-MM-DD HH:mm:ss"
                :placeholder="fieldPlaceholderOf(f)"
                class="field-control"
              >
                <template #suffix>
                  <component :is="calendarIcon" />
                </template>
              </el-date-picker>

              <el-select
                v-else-if="f.type === 'duration'"
                v-model="form.base_info[f.key]"
                :placeholder="fieldPlaceholderOf(f)"
              >
                <el-option
                  v-for="option in durationOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>

              <el-input
                v-else
                v-model="form.base_info[f.key]"
                :placeholder="fieldPlaceholderOf(f)"
              >
                <template v-if="f.key === 'interviewee'" #suffix>
                  <component :is="userIcon" />
                </template>
              </el-input>
            </el-form-item>
          </div>

          <el-form-item prop="goal" class="goal-field" :show-message="false">
            <template #label>
              <span class="form-label-content">
                <span class="required-prefix">*</span>
                {{ $t("create.dialog.goal") }}
              </span>
            </template>
            <div class="goal-field-stack">
              <el-input
                v-model="form.goal"
                type="textarea"
                :rows="3"
                :placeholder="$t('create.dialog.goal_placeholder')"
                @input="goalError = ''"
              />
              <div class="goal-count" :class="{ overlimit: (form.goal?.length || 0) > 100 }">
                {{ form.goal?.length || 0 }} / 100
              </div>
              <p class="goal-error" :class="{ visible: !!goalError }">
                {{ goalError || " " }}
              </p>
            </div>
          </el-form-item>
        </div>
      </section>

      <section class="form-section quick-input-section">
        <div class="section-title">
          <h3>{{ $t("create.dialog.quick_input") }}</h3>
        </div>
        <div class="quick-input-stage">
          <Transition name="quick-input-panel" mode="out-in">
            <div
              v-if="activePanel === 'clipboard'"
              key="clipboard"
              class="clipboard-input-panel"
            >
              <el-input
                v-model="clipboardText"
                type="textarea"
                :rows="3"
                :disabled="clipboardExtracting"
                :placeholder="$t('create.dialog.clipboard_placeholder')"
              />
              <div class="panel-actions">
                <el-button
                  type="primary"
                  :loading="clipboardExtracting"
                  :disabled="clipboardExtracting"
                  @click="extractClipboardText"
                >
                  {{ $t("create.dialog.clipboard_extract") }}
                </el-button>
                <el-button
                  plain
                  :disabled="clipboardExtracting"
                  @click="closeActivePanel"
                >
                  {{ $t("create.dialog.back") }}
                </el-button>
              </div>
            </div>

            <div
              v-else-if="activePanel === 'voice'"
              key="voice"
              class="voice-input-panel"
            >
              <div class="voice-body">
                <div class="voice-transcript">
                  {{ asrTranscript || voicePlaceholder }}
                </div>
                <div class="voice-meta">
                  <AVMedia
                    v-if="asrState === 'recording' && asrMediaStream"
                    :media="asrMediaStream"
                    class="voice-voiceprint"
                    type="frequ"
                    frequ-direction="mo"
                    :canv-width="72"
                    :canv-height="16"
                    :frequ-lnum="24"
                    :line-width="1"
                    frequ-line-cap
                    line-color="#409eff"
                  />
                  <span class="voice-duration">{{ voiceElapsedLabel }}</span>
                </div>
              </div>
              <div class="panel-actions">
                <el-button
                  type="primary"
                  :loading="voiceExtracting"
                  :disabled="asrState === 'idle' && !voiceExtracting"
                  @click="extractVoiceTranscript"
                >
                  {{ $t("create.dialog.voice_stop") }}
                </el-button>
              </div>
            </div>

            <div
              v-else-if="activePanel === 'camera'"
              key="camera"
              class="camera-input-panel"
            >
              <div class="camera-preview">
                <video
                  v-show="!cameraFrozen"
                  ref="cameraVideoRef"
                  autoplay
                  playsinline
                  muted
                />
                <img
                  v-if="cameraFrozen"
                  :src="frozenImageSrc"
                  class="frozen-preview"
                />
              </div>
              <div class="panel-actions">
                <template v-if="!cameraFrozen">
                  <el-button
                    type="primary"
                    :loading="cameraRecognizing"
                    :disabled="cameraRecognizing"
                    @click="recognizePhoto"
                  >
                    {{ $t("create.dialog.camera_snap") }}
                  </el-button>
                  <el-button
                    plain
                    :disabled="cameraRecognizing"
                    @click="triggerFileUpload"
                  >
                    {{ $t("create.dialog.upload_image") }}
                  </el-button>
                </template>
                <template v-else>
                  <el-button
                    type="primary"
                    :loading="cameraRecognizing"
                    :disabled="cameraRecognizing"
                    @click="submitRecognition"
                  >
                    {{ $t("create.dialog.camera_submit") }}
                  </el-button>
                  <el-button
                    plain
                    :disabled="cameraRecognizing"
                    @click="retakePhoto"
                  >
                    {{ $t("create.dialog.camera_retake") }}
                  </el-button>
                </template>
                <el-button
                  plain
                  :disabled="cameraRecognizing"
                  @click="closeActivePanel"
                >
                  {{ $t("create.dialog.back") }}
                </el-button>
              </div>
              <input
                ref="fileInputRef"
                type="file"
                accept=".jpg,.jpeg,.jpe,.png,.bmp"
                class="hidden-file-input"
                @change="handleFileChange"
              />
            </div>

            <div
              v-else-if="activePanel === 'cropPreview'"
              key="cropPreview"
              class="crop-preview-panel"
            >
              <div class="crop-preview-image">
                <img :src="cropPreviewSrc" alt="crop preview" />
              </div>
              <div class="panel-actions">
                <el-button
                  type="primary"
                  :loading="cameraRecognizing"
                  :disabled="cameraRecognizing"
                  @click="handleCropSubmit"
                >
                  {{ $t("create.dialog.crop_submit") }}
                </el-button>
                <el-button
                  plain
                  :disabled="cameraRecognizing"
                  @click="handleCropReselect"
                >
                  {{ $t("create.dialog.crop_reselect") }}
                </el-button>
              </div>
            </div>

            <div v-else key="methods" class="input-method-list">
              <button
                v-for="method in inputMethods"
                :key="method.key"
                type="button"
                class="input-method"
                :class="{ selected: selectedInputMethod === method.key }"
                @click="selectInputMethod(method.key)"
              >
                <span
                  class="method-icon"
                  :style="{
                    color: method.color,
                    background: method.background
                  }"
                >
                  <component :is="method.icon" />
                </span>
                <span class="method-copy">
                  <strong>{{ method.title }}</strong>
                  <small>{{ method.description }}</small>
                </span>
                <span class="method-arrow">→</span>
              </button>
            </div>
          </Transition>
        </div>
      </section>
    </el-form>

    <template #footer>
      <el-button
        style="border-radius: 8px"
        plain
        :disabled="submitting"
        @click="handleClose"
        >{{ $t("create.dialog.cancel") }}</el-button
      >
      <el-button
        style="border-radius: 8px"
        type="primary"
        :loading="submitting"
        @click="handleSubmit"
        >{{ $t("create.dialog.submit") }}</el-button
      >
    </template>
  </el-dialog>

  <ImageCropDialog
    v-model="showCropDialog"
    :image-base64="pendingImageBase64"
    @confirm="handleCropConfirm"
  />
</template>

<style lang="scss">
.create-interview-dialog {
  --el-dialog-border-radius: 24px;

  overflow: hidden;
  background: rgb(255 255 255 / 98%);
  border: 1px solid rgb(255 255 255 / 90%);
  box-shadow: 0 22px 70px rgb(31 41 55 / 24%);
  border-radius: 16px !important;

  .el-dialog__header {
    padding: 14px 24px 16px;
    margin-right: 0;
  }

  .el-dialog__body {
    padding: 0 24px;
  }

  .el-dialog__footer {
    padding: 16px 24px 20px;
  }

  .el-dialog__headerbtn {
    top: 16px;
    right: 18px;
  }

  .create-interview-form {
    .form-section + .form-section {
      margin-top: 12px;
    }

    .section-title {
      display: flex;
      gap: 8px;
      align-items: center;
      margin-bottom: 14px;
    }

    .section-title {
      h3 {
        margin: 0;
        font-size: 15px;
        font-weight: 700;
        color: #343a40;
      }
    }

    .section-hint {
      font-size: 12px;
      color: #a0a6ae;
    }

    .form-grid {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .basic-fields-row {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: flex-start;
    }

    // 改单列：早期设计里这一行放两个固定字段，现只剩「访谈名称」一个，
    // 2 列布局导致它被压成半宽。整行只有 1 项时让输入框撑满容器
    .secondary-fields-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 14px;
    }

    .template-field {
      width: 100%;
    }

    .basic-fields-row {
      .el-form-item {
        flex: 1 1 180px;
        min-width: 0;

        // 时长是固定档位下拉，窄列即可（字段数随模板变，不再按位置写死）
        &.is-duration {
          flex: 0 0 128px;
        }
      }
    }

    .el-form-item {
      display: flex;
      flex-direction: column;
      align-self: start;
      margin-bottom: 0;
    }

    .el-form-item__label {
      height: auto;
      margin-bottom: 6px;
      font-size: 13px;
      line-height: 1.2;
      color: #6d737c;
    }

    // 必填红字前缀：label-top 模式下 Element Plus 不渲染红星（#15），
    // 手动加在 label 文字前。
    // 但「required」规则会触发 EP 自动在 ::after 加一个 *（右侧红星），
    // 跟我们的 * 前缀撞车，必须显式关掉
    .el-form-item.is-required .el-form-item__label::after {
      content: none !important;
    }

    .form-label-content {
      display: inline-flex;
      align-items: center;
    }

    .required-prefix {
      margin-right: 2px;
      color: #f56c6c;
    }

    .el-form-item__content {
      display: flex;
      flex-direction: column;
      align-items: stretch;
      width: 100%;
    }

    .el-input__wrapper,
    .el-select__wrapper {
      min-height: 36px;
      border-radius: 9px;
      box-shadow: 0 0 0 1px #e4e8ed inset;
    }

    .el-input__wrapper,
    .el-select__wrapper {
      &:hover {
        box-shadow: 0 0 0 1px #b9c0c9 inset;
      }
    }

    .el-input__inner::placeholder,
    .el-textarea__inner::placeholder {
      color: #b0b5bd;
    }

    .el-input__suffix-inner svg,
    .el-date-editor .el-input__suffix svg {
      width: 17px;
      height: 17px;
      color: #a8adb5;
    }

    .field-control,
    .el-select {
      width: 100%;
    }

    .field-control {
      height: 36px;
    }

    .el-textarea__inner {
      padding: 10px 12px;
      resize: vertical;
      border: 0;
      border-radius: 8px;
      box-shadow: 0 0 0 1px #e4e8ed inset;
    }

    .el-textarea {
      .el-input__count {
        right: 12px;
        bottom: 6px;
      }
    }

    .goal-field {
      width: 100%;
    }

    .goal-field-stack {
      display: flex;
      flex-direction: column;
      width: 100%;
    }

    .goal-error {
      visibility: hidden;
      min-height: 14px;
      margin: 4px 0 0;
      font-size: 12px;
      line-height: 14px;
      color: #f56c6c;
    }

    .goal-error {
      &.visible {
        visibility: visible;
      }
    }

    .goal-count {
      align-self: flex-end;
      margin-top: 4px;
      font-size: 12px;
      line-height: 14px;
      color: #909399;

      &.overlimit {
        color: #f56c6c;
      }
    }

    .el-form-item__error {
      position: static !important;
      display: block;
      padding-top: 0;
      margin-top: 4px;
      line-height: 1.2;
      white-space: normal;
    }

    .quick-input-section {
      width: 100%;
      padding-bottom: 10px;
    }

    .quick-input-stage {
      position: relative;
      display: block;
      width: 100%;
      min-height: 112px;
    }

    // out-in 切换：离场元素脱离文档流，进场面板撑起实际高度
    .quick-input-panel-leave-active {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      transition:
        transform 0.28s ease,
        opacity 0.28s ease;
    }

    .quick-input-panel-enter-active {
      transition:
        transform 0.28s ease,
        opacity 0.28s ease;
    }

    .quick-input-panel-enter-from.clipboard-input-panel,
    .quick-input-panel-enter-from.voice-input-panel,
    .quick-input-panel-enter-from.camera-input-panel,
    .quick-input-panel-leave-to.clipboard-input-panel,
    .quick-input-panel-leave-to.voice-input-panel,
    .quick-input-panel-leave-to.camera-input-panel {
      opacity: 0;
      transform: translateX(100%);
    }

    .quick-input-panel-enter-from.input-method-list,
    .quick-input-panel-leave-to.input-method-list {
      opacity: 0;
      transform: translateX(-100%);
    }

    .clipboard-input-panel,
    .voice-input-panel,
    .camera-input-panel {
      display: flex;
      gap: 10px;
      align-items: stretch;
      width: 100%;
    }

    .clipboard-input-panel,
    .voice-input-panel {
      height: 112px;
    }

    .camera-input-panel {
      height: 216px;
    }

    .clipboard-input-panel {
      .el-textarea {
        flex: 1;
        min-width: 0;
      }

      .el-textarea__inner {
        height: 100%;
        resize: none;
      }
    }

    .voice-body {
      display: flex;
      flex: 1;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }

    .voice-transcript {
      flex: 1;
      padding: 8px 10px;
      overflow-y: auto;
      font-size: 13px;
      line-height: 1.5;
      color: #343a40;
      background: #f7f8fa;
      border-radius: 8px;
    }

    .voice-meta {
      display: flex;
      flex-shrink: 0;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      min-height: 16px;
    }

    .voice-voiceprint {
      canvas {
        display: block;
      }
    }

    .voice-duration {
      font-size: 12px;
      color: #a0a6ae;
      font-variant-numeric: tabular-nums;
    }

    .camera-preview {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      background: #000;
      border-radius: 8px;

      video {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
      }

      .frozen-preview {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
    }

    .crop-preview-panel {
      display: flex;
      gap: 10px;
      align-items: stretch;
      width: 100%;
      height: 216px;
    }

    .crop-preview-image {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      background: #000;
      border-radius: 8px;

      img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
    }

    .hidden-file-input {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    .panel-actions {
      display: flex;
      flex: 0 0 90px;
      flex-direction: column;
      gap: 8px;
      justify-content: center;

      .el-button {
        width: 100%;
        height: 32px;
        margin: 0;
        border-radius: 8px;
      }
    }

    .input-method-list {
      position: relative;
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
      grid-template-rows: repeat(2, minmax(52px, auto));
      gap: 8px;
    }

    .input-method {
      display: flex;
      gap: 9px;
      align-items: center;
      min-width: 0;
      padding: 10px;
      color: #303133;
      text-align: left;
      cursor: pointer;
      background: #fff;
      border: 1px solid #edf0f4;
      border-radius: 9px;
      transition:
        border-color 0.2s,
        background 0.2s,
        transform 0.2s;
    }

    .input-method {
      &:hover,
      &.selected {
        background: #f7fbff;
        border-color: #9cc5f2;
        transform: translateY(-1px);
      }

      &:first-child {
        grid-row: span 2;
        flex-direction: column;
        justify-content: center;
        gap: 8px;
        padding: 14px 18px;
        text-align: center;
        background: linear-gradient(135deg, #f2edff 0%, #e8f5ff 100%);
        border-color: #dbe4fb;

        .method-icon {
          width: 52px;
          height: 52px;
          background: #5c9df5 !important;
          border-radius: 50%;
          box-shadow: 0 8px 18px rgb(92 157 245 / 28%);

          svg {
            width: 25px;
            height: 25px;
            color: #fff;
          }
        }

        .method-copy {
          flex: 0 0 auto;
          align-items: center;

          strong {
            color: #735de0;
          }
        }

        .method-arrow {
          display: none;
        }
      }

      &:not(:first-child) {
        padding: 9px 12px;
      }
    }

    .method-icon {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 9px;
    }

    .method-icon {
      svg {
        width: 18px;
        height: 18px;
      }
    }

    .method-copy {
      display: flex;
      flex: 1;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }

    .method-copy {
      strong,
      small {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      strong {
        font-size: 14px;
        font-weight: 600;
        color: #343a40;
      }

      small {
        font-size: 10px;
        color: #a0a6ae;
      }
    }

    .method-arrow {
      flex-shrink: 0;
      font-size: 18px;
      color: #a0a6ae;
    }

    .create-dialog-footer {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
    }

    .dialog-footer-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 32px;
      padding: 0 16px;
      font-size: 14px;
      font-weight: 500;
      line-height: 32px;
      color: inherit;
      cursor: pointer;
      appearance: none;
      -webkit-appearance: none;
      outline: none;
      border-radius: 8px;
      box-sizing: border-box;
      transition:
        opacity 0.2s,
        transform 0.2s;
    }

    .dialog-footer-btn {
      &:hover {
        transform: translateY(-1px);
      }

      &--ghost {
        color: #4a90e2;
        background: rgb(74 144 226 / 10%);
        border: 1px solid rgb(74 144 226 / 18%);

        &:hover {
          color: #3a7bc8;
          background: rgb(74 144 226 / 14%);
          border-color: rgb(74 144 226 / 26%);
          opacity: 0.96;
        }
      }

      &--primary {
        color: #fff;
        background: linear-gradient(135deg, #4a90e2 0%, #3a7bc8 100%);
        border: none;

        &:hover {
          opacity: 0.92;
        }
      }
    }
  }
}

@media (width <= 680px) {
  .create-interview-dialog {
    width: calc(100% - 24px) !important;

    .el-dialog__header,
    .el-dialog__body,
    .el-dialog__footer {
      padding-right: 16px;
      padding-left: 16px;
    }

    .create-interview-form {
      .basic-fields-row {
        flex-direction: column;

        .el-form-item {
          flex-basis: auto;
          width: 100%;
        }
      }

      .secondary-fields-row {
        grid-template-columns: 1fr;
      }

      .input-method-list {
        min-height: 172px;
        grid-template-columns: 1fr;
        grid-template-rows: none;
      }

      .quick-input-stage {
        min-height: 172px;
      }

      .clipboard-input-panel,
      .voice-input-panel {
        height: 132px;
      }

      .camera-input-panel {
        height: 260px;
      }

      .panel-actions {
        flex-basis: 88px;
      }

      .input-method:first-child {
        grid-row: auto;
      }

      .goal-field {
        width: 100%;
      }

      .el-form-item__error {
        margin-top: 4px;
      }
    }
  }
}
</style>
