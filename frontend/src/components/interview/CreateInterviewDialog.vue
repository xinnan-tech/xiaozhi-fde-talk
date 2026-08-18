<script setup lang="ts">
import { nextTick, reactive, ref, watch, markRaw } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({
  name: "CreateInterviewDialog"
});

type CreateInterviewForm = {
  interviewee: string;
  interviewTime: string;
  duration: string;
  goal: string;
};

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
  (event: "submit", value: CreateInterviewForm): void;
}>();

const noteIcon = markRaw(useRenderIcon("majesticons:note-text"));
const userIcon = markRaw(useRenderIcon("tabler:user"));
const calendarIcon = markRaw(useRenderIcon("tabler:calendar"));
const microphoneIcon = markRaw(useRenderIcon("tabler:microphone"));
const cameraIcon = markRaw(useRenderIcon("tabler:camera"));
const clipboardIcon = markRaw(useRenderIcon("tabler:clipboard-text"));

const formRef = ref<FormInstance>();
const selectedInputMethod = ref("");
const goalError = ref("");
const form = reactive<CreateInterviewForm>({
  interviewee: "",
  interviewTime: "",
  duration: "30 分钟",
  goal: ""
});

const rules: FormRules<CreateInterviewForm> = {
  interviewee: [
    { required: true, message: "请输入访谈人姓名", trigger: "blur" }
  ],
  interviewTime: [
    { required: true, message: "请选择访谈时间", trigger: "change" }
  ],
  duration: [{ required: true, message: "请选择访谈时长", trigger: "change" }],
  goal: [
    {
      trigger: "blur",
      validator: (_rule, value, callback) => {
        if (!value?.trim()) {
          goalError.value = "请输入访谈目标";
          callback(new Error("请输入访谈目标"));
          return;
        }
        goalError.value = "";
        callback();
      }
    }
  ]
};

const inputMethods = [
  {
    key: "voice",
    title: "开始录音描述",
    description: "通过语音输入访谈目标",
    icon: microphoneIcon,
    color: "#4a90e2",
    background: "rgba(74, 144, 226, 0.12)"
  },
  {
    key: "camera",
    title: "拍照识别",
    description: "拍照图片识别文字内容",
    icon: cameraIcon,
    color: "#52c41a",
    background: "rgba(82, 196, 26, 0.12)"
  },
  {
    key: "clipboard",
    title: "从粘贴板提取",
    description: "自动提取剪贴板内容",
    icon: clipboardIcon,
    color: "#722ed1",
    background: "rgba(114, 46, 209, 0.12)"
  }
];

const resetForm = async () => {
  formRef.value?.resetFields();
  form.interviewee = "";
  form.interviewTime = "";
  form.duration = "30 分钟";
  form.goal = "";
  selectedInputMethod.value = "";
  goalError.value = "";
  await nextTick();
  formRef.value?.clearValidate();
};

const handleClose = () => {
  emit("update:modelValue", false);
};

const handleSubmit = async () => {
  if (!formRef.value) return;
  const valid = await formRef.value.validate().catch(() => false);
  if (!valid) return;

  emit("submit", { ...form });
  emit("update:modelValue", false);
};

watch(
  () => props.modelValue,
  value => {
    if (value) resetForm();
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
    @update:model-value="emit('update:modelValue', $event)"
    @closed="formRef?.clearValidate()"
  >
    <template #header>
      <div class="text-[18px] font-semibold text-[#1f2329]">创建新访谈</div>
    </template>

    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      hide-required-asterisk
      class="create-interview-form"
    >
      <section class="form-section">
        <div class="section-title">
          <h3>基本信息</h3>
        </div>
        <div class="form-grid">
          <div class="basic-fields-row">
            <el-form-item label="访谈人" prop="interviewee">
              <el-input
                v-model="form.interviewee"
                placeholder="请输入受访者姓名"
              >
                <template #suffix>
                  <component :is="userIcon" />
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="访谈时间" prop="interviewTime">
              <el-date-picker
                v-model="form.interviewTime"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                format="YYYY-MM-DD HH:mm"
                placeholder="选择日期和时间"
                class="field-control"
              >
                <template #suffix>
                  <component :is="calendarIcon" />
                </template>
              </el-date-picker>
            </el-form-item>

            <el-form-item label="访谈时长" prop="duration">
              <el-select v-model="form.duration" placeholder="请选择访谈时长">
                <el-option label="15 分钟" value="15 分钟" />
                <el-option label="30 分钟" value="30 分钟" />
                <el-option label="45 分钟" value="45 分钟" />
                <el-option label="60 分钟" value="60 分钟" />
              </el-select>
            </el-form-item>
          </div>

          <el-form-item
            label="访谈目标"
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
                placeholder="请输入本次访谈的目标"
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
          <h3>便捷录入</h3>
        </div>
        <div class="input-method-list">
          <button
            v-for="method in inputMethods"
            :key="method.key"
            type="button"
            class="input-method"
            :class="{ selected: selectedInputMethod === method.key }"
            @click="selectedInputMethod = method.key"
          >
            <span
              class="method-icon"
              :style="{ color: method.color, background: method.background }"
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
      </section>
    </el-form>

    <template #footer>
      <el-button style="border-radius: 8px" plain @click="handleClose"
        >取消</el-button
      >
      <el-button style="border-radius: 8px" type="primary" @click="handleSubmit"
        >创建访谈</el-button
      >
    </template>
  </el-dialog>
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
      border-radius: 9px;
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
      padding-bottom: 10px;
    }

    .input-method-list {
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

      .input-method-list {
        grid-template-columns: 1fr;
        grid-template-rows: none;
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
