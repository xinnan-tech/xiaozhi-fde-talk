<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import Cropper from "cropperjs";
import "cropperjs/dist/cropper.css";

defineOptions({ name: "ImageCropDialog" });

const props = defineProps<{
  modelValue: boolean;
  /** 纯 base64，不带 data:image/... 前缀 */
  imageBase64: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "confirm", croppedBase64: string): void;
}>();

const { t } = useI18n();

const imageSrc = computed(() => `data:image/jpeg;base64,${props.imageBase64}`);

const imgRef = ref<HTMLImageElement | null>(null);
let cropper: Cropper | null = null;

const initCropper = () => {
  if (!imgRef.value || cropper) return;
  cropper = new Cropper(imgRef.value, {
    autoCrop: true,
    autoCropArea: 0.8,
    center: true,
    movable: true,
    rotatable: true,
    scalable: true,
    zoomable: true,
    toggleDragModeOnDblclick: false,
    preview: [],
    checkOrientation: false
  });
};

watch(
  () => props.modelValue,
  val => {
    if (val) {
      // dialog 打开时，等图片加载完成后再初始化 cropper
      // 否则 cropper 可能拿到没有尺寸的 img 元素而失败
      cropper?.destroy();
      cropper = null;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          initCropper();
        });
      });
    } else {
      cropper?.destroy();
      cropper = null;
    }
  },
  { immediate: true }
);

onUnmounted(() => {
  cropper?.destroy();
  cropper = null;
});

const handleConfirm = () => {
  if (!cropper) return;
  const canvas = cropper.getCroppedCanvas({
    maxWidth: 4096,
    maxHeight: 4096,
    imageSmoothingEnabled: true,
    imageSmoothingQuality: "high"
  });
  canvas.toBlob(
    blob => {
      if (!blob) return;
      const reader = new FileReader();
      reader.onload = () => {
        const base64 = (reader.result as string).split(",")[1];
        emit("confirm", base64);
        emit("update:modelValue", false);
      };
      reader.readAsDataURL(blob);
    },
    "image/jpeg",
    0.9
  );
};

const rotateLeft = () => cropper?.rotate(-90);
const rotateRight = () => cropper?.rotate(90);
// checkOrientation: false 时 cropperjs 不会初始化 imageData.scaleX/scaleY，
// 首次读取是 undefined（取负得 NaN 会被 scale() 静默丢弃），需兜底为 1
const flipHorizontal = () => cropper?.scaleX(-(cropper?.getImageData().scaleX ?? 1));
const flipVertical = () => cropper?.scaleY(-(cropper?.getImageData().scaleY ?? 1));
const reset = () => cropper?.reset();
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="620px"
    align-center
    destroy-on-close
    class="image-crop-dialog"
    :title="t('create.dialog.crop_title')"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="crop-area">
      <img
        ref="imgRef"
        :src="imageSrc"
        class="crop-image"
        crossorigin="anonymous"
      />
    </div>

    <!-- 操作按钮 -->
    <div class="toolbar">
      <el-tooltip :content="t('crop.rotate_left')" placement="top">
        <el-button text @click="rotateLeft">
          <span class="toolbar-icon">↺</span>
        </el-button>
      </el-tooltip>
      <el-tooltip :content="t('crop.rotate_right')" placement="top">
        <el-button text @click="rotateRight">
          <span class="toolbar-icon">↻</span>
        </el-button>
      </el-tooltip>
      <el-tooltip :content="t('crop.flip_h')" placement="top">
        <el-button text @click="flipHorizontal">
          <span class="toolbar-icon">⇿</span>
        </el-button>
      </el-tooltip>
      <el-tooltip :content="t('crop.flip_v')" placement="top">
        <el-button text @click="flipVertical">
          <span class="toolbar-icon">⇅</span>
        </el-button>
      </el-tooltip>
      <el-tooltip :content="t('crop.reset')" placement="top">
        <el-button text @click="reset">
          <span class="toolbar-icon">⟳</span>
        </el-button>
      </el-tooltip>
    </div>

    <div class="crop-hint">{{ t("create.dialog.crop_hint") }}</div>

    <template #footer>
      <el-button type="primary" @click="handleConfirm">
        {{ t("create.dialog.crop_confirm") }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style lang="scss">
.image-crop-dialog {
  --el-dialog-border-radius: 16px;

  .el-dialog__header {
    padding: 14px 24px 16px;
    margin-right: 0;
  }

  .el-dialog__body {
    padding: 0 24px 8px;
  }

  .el-dialog__footer {
    padding: 12px 24px 20px;
  }

  .crop-area {
    width: 100%;
    height: 400px;
    background: #000;
    border-radius: 8px;
    overflow: hidden;

    .crop-image {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
  }

  .crop-hint {
    font-size: 12px;
    color: #a0a6ae;
    text-align: center;
    margin-top: 4px;
  }

  .toolbar {
    display: flex;
    justify-content: center;
    gap: 4px;
    padding: 8px 0 4px;

    .el-button {
      padding: 6px 10px;
      font-size: 18px;
      color: #606266;
      border-radius: 6px;

      &:hover {
        background: #f0f0f0;
        color: #409eff;
      }
    }

    .toolbar-icon {
      font-size: 20px;
      line-height: 1;
    }
  }
}
</style>
