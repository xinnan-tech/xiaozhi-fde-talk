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
  base_info: {
    title: "欣南科技公司售前业务洽谈助手",
    project: "欣南科技售前",
    interviewee: "彭经理",
    start_time: "",
    duration: "45",
    end_time: ""
  },
  goal: "了解欣南售前工作流程，业务洽谈工具的需求，使用场景，部署方式之类",
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

const rules = computed<FormRules>(() => ({
  "base_info.title": [
    {
      required: true,
      message: t("create.dialog.name_required"),
      trigger: "blur"
    }
  ],
  "base_info.interviewee": [
    {
      required: true,
      message: t("create.dialog.interviewee_required"),
      trigger: "blur"
    }
  ],
  "base_info.start_time": [
    {
      required: true,
      message: t("create.dialog.start_time_required"),
      trigger: "change"
    }
  ],
  "base_info.duration": [
    {
      required: true,
      message: t("create.dialog.duration_required"),
      trigger: "change"
    }
  ],
  template_id: [
    {
      required: true,
      message: t("create.dialog.template_required"),
      trigger: "change"
    }
  ],
  "base_info.project": [
    {
      required: true,
      message: t("create.dialog.project_required"),
      trigger: "blur"
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
}));

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
      message(t("create.dialog.voice_failed"), { type: "error" });
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
  templateFieldsTemplateId.value = templateId;
  return templateFields.value;
};

const normalizeExtractedValue = (key: string, value: string) => {
  if (key === "duration") {
    const source = Number.parseInt(value, 10);
    if (!Number.isFinite(source)) return "";
    return durationOptions.value.reduce((closest, option) => {
      return Math.abs(Number(option.value) - source) <
        Math.abs(Number(closest) - source)
        ? option.value
        : closest;
    }, durationOptions.value[0]?.value ?? "");
  }

  if (key === "start_time") {
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

    // 将提取结果写回表单控件；值与当前一致的回显不计入 filled，filled表示更新字段数
    let filled = 0;
    for (const [key, rawValue] of Object.entries(response.values ?? {})) {
      if (!rawValue) continue;
      const value = normalizeExtractedValue(key, String(rawValue));
      if (!value) continue;
      if (key !== "title" && key !== "goal" && !(key in form.base_info)) {
        continue;
      }

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
        "base_info.project",
        "base_info.interviewee",
        "base_info.start_time",
        "base_info.duration",
        "goal"
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
  interviewTemplatesLoading.value = true;
  try {
    const response = await getInterviewsTemplatesApi();
    interviewTemplates.value = response.items;
    form.template_id = response.items[0]?.id ?? "";
    templateFields.value = [];
    templateFieldsTemplateId.value = "";
  } catch {
    interviewTemplates.value = [];
    form.template_id = "";
  } finally {
    interviewTemplatesLoading.value = false;
  }
};

const calculateEndTime = () => {
  const startTime = dayjs(
    form.base_info.start_time,
    ["YYYY-MM-DD HH:mm:ss", "YYYY-MM-DDTHH:mm:ss"],
    true
  );
  if (!startTime.isValid()) return "";

  return startTime
    .add(Number(form.base_info.duration), "minute")
    .format("YYYY-MM-DD HH:mm:ss");
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
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;

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
    width="660px"
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
      class="create-interview-form"
    >
      <section class="form-section">
        <div class="section-title">
          <h3>{{ $t("create.dialog.basic_info") }}</h3>
        </div>
        <div class="form-grid">
          <div class="secondary-fields-row">
            <el-form-item
              :label="$t('create.dialog.interview_name')"
              prop="base_info.title"
            >
              <el-input
                v-model="form.base_info.title"
                :placeholder="$t('create.dialog.name_placeholder')"
              />
            </el-form-item>

            <el-form-item
              :label="$t('create.dialog.project')"
              prop="base_info.project"
            >
              <el-input
                v-model="form.base_info.project"
                :placeholder="$t('create.dialog.project_placeholder')"
              />
            </el-form-item>
          </div>

          <div class="basic-fields-row">
            <el-form-item
              :label="$t('create.dialog.interviewee')"
              prop="base_info.interviewee"
            >
              <el-input
                v-model="form.base_info.interviewee"
                :placeholder="$t('create.dialog.interviewee_placeholder')"
              >
                <template #suffix>
                  <component :is="userIcon" />
                </template>
              </el-input>
            </el-form-item>

            <el-form-item
              :label="$t('create.dialog.start_time')"
              prop="base_info.start_time"
            >
              <el-date-picker
                v-model="form.base_info.start_time"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                format="YYYY-MM-DD HH:mm:ss"
                :placeholder="$t('create.dialog.start_time_placeholder')"
                class="field-control"
              >
                <template #suffix>
                  <component :is="calendarIcon" />
                </template>
              </el-date-picker>
            </el-form-item>

            <el-form-item
              :label="$t('create.dialog.duration')"
              prop="base_info.duration"
            >
              <el-select
                v-model="form.base_info.duration"
                :placeholder="$t('create.dialog.duration_placeholder')"
              >
                <el-option
                  v-for="option in durationOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </el-form-item>
          </div>

          <el-form-item
            :label="$t('create.dialog.template')"
            prop="template_id"
            class="template-field"
          >
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

          <el-form-item
            :label="$t('create.dialog.goal')"
            prop="goal"
            class="goal-field"
            :show-message="false"
          >
            <div class="goal-field-stack">
              <el-input
                v-model="form.goal"
                type="textarea"
                :rows="3"
                maxlength="100"
                show-word-limit
                :placeholder="$t('create.dialog.goal_placeholder')"
                @input="goalError = ''"
              />
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
                accept="image/*"
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
      gap: 14px;
      align-items: flex-start;
    }

    .secondary-fields-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .template-field {
      width: 100%;
    }

    .basic-fields-row {
      .el-form-item {
        flex: 1 1 0;
        min-width: 0;

        &:nth-child(3) {
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
