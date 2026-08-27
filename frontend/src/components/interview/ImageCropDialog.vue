<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

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

const imageDataUrl = computed(() => `data:image/jpeg;base64,${props.imageBase64}`);

const canvasRef = ref<HTMLCanvasElement>();
const containerRef = ref<HTMLDivElement>();

/** 图片加载后的原始尺寸 */
const originalImage = ref<HTMLImageElement | null>(null);
/** 图片在 canvas 中的显示尺寸（可能经过缩放） */
const displaySize = ref({ width: 0, height: 0 });
/** 裁切框相对于显示图片的坐标和尺寸 */
const cropRect = ref({ x: 20, y: 20, width: 60, height: 40 }); // 百分比形式 0-100
/** 是否正在拖拽 */
const isDragging = ref(false);
/** 拖拽类型：'move' | 'tl' | 'tr' | 'bl' | 'br' */
const dragType = ref<"move" | "tl" | "tr" | "bl" | "br">("move");
const dragStart = ref({ x: 0, y: 0 });
const cropStart = ref({ x: 0, y: 0, width: 0, height: 0 });

const handleConfirm = () => {
  const cropped = extractCroppedBase64();
  emit("confirm", cropped);
  emit("update:modelValue", false);
};

/** 从原始图片中提取裁切区域，返回纯 base64 */
const extractCroppedBase64 = (): string => {
  const img = originalImage.value;
  const canvas = canvasRef.value;
  if (!img || !canvas) return props.imageBase64;

  const { width: imgW, height: imgH } = img;
  const scaleX = imgW / displaySize.value.width;
  const scaleY = imgH / displaySize.value.height;

  const sx = (cropRect.value.x / 100) * imgW;
  const sy = (cropRect.value.y / 100) * imgH;
  const sw = (cropRect.value.width / 100) * imgW;
  const sh = (cropRect.value.height / 100) * imgH;

  const outCanvas = document.createElement("canvas");
  outCanvas.width = sw;
  outCanvas.height = sh;
  const ctx = outCanvas.getContext("2d");
  if (!ctx) return props.imageBase64;

  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
  const dataUrl = outCanvas.toDataURL("image/jpeg", 0.9);
  return dataUrl.slice(dataUrl.indexOf(",") + 1);
};

/** 渲染 canvas：图片 + 遮罩 + 裁切框 */
const render = () => {
  const canvas = canvasRef.value;
  const img = originalImage.value;
  if (!canvas || !img) return;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const { width, height } = displaySize.value;
  canvas.width = width;
  canvas.height = height;

  ctx.clearRect(0, 0, width, height);

  // 1. 画完整图片
  ctx.drawImage(img, 0, 0, width, height);

  const x = (cropRect.value.x / 100) * width;
  const y = (cropRect.value.y / 100) * height;
  const w = (cropRect.value.width / 100) * width;
  const h = (cropRect.value.height / 100) * height;

  // 2. 用 destination-out 画遮罩，裁切区被挖空（变透明）
  ctx.globalCompositeOperation = "destination-out";
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, 0, width, height);
  ctx.globalCompositeOperation = "source-over";

  // 3. 把裁切区的原图贴回去（露出完整图片）
  // drawImage(source) 前四个参数是原图坐标，后四个是 canvas 坐标
  const sx = (cropRect.value.x / 100) * img.width;
  const sy = (cropRect.value.y / 100) * img.height;
  const sw = (cropRect.value.width / 100) * img.width;
  const sh = (cropRect.value.height / 100) * img.height;
  ctx.drawImage(img, sx, sy, sw, sh, x, y, w, h);

  // 4. 画裁切框边框
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(x, y, w, h);

  // 四角把手
  const handleSize = 8;
  ctx.fillStyle = "#ffffff";
  const corners = [
    [x, y],
    [x + w, y],
    [x, y + h],
    [x + w, y + h]
  ];
  for (const [cx, cy] of corners) {
    ctx.fillRect(cx - handleSize / 2, cy - handleSize / 2, handleSize, handleSize);
  }

  // 十字参考线
  ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
  ctx.lineWidth = 0.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x + w / 2, y);
  ctx.lineTo(x + w / 2, y + h);
  ctx.moveTo(x, y + h / 2);
  ctx.lineTo(x + w, y + h / 2);
  ctx.stroke();
  ctx.setLineDash([]);
};

/** 加载图片并计算显示尺寸 */
const loadImage = () => {
  const img = new Image();
  img.onload = () => {
    originalImage.value = img;
    // 等比缩放到 dialog 可用范围，不产生滚动
    const maxW = 540;
    const maxH = 420;
    const ratio = Math.min(maxW / img.width, maxH / img.height, 1);
    displaySize.value = {
      width: Math.round(img.width * ratio),
      height: Math.round(img.height * ratio)
    };
    // 初始化裁切框为整张图片
    cropRect.value = {
      x: 0,
      y: 0,
      width: 100,
      height: 100
    };
  };
  img.src = imageDataUrl.value;
};

watch(
  () => props.modelValue,
  val => {
    if (val) {
      loadImage();
    }
  }
);

watch([displaySize, cropRect], () => {
  requestAnimationFrame(render);
}, { deep: true });

onMounted(() => {
  if (props.modelValue) loadImage();
});

/** 获取鼠标在 canvas 上的百分比坐标 */
const getCanvasPercent = (e: MouseEvent) => {
  const canvas = canvasRef.value;
  if (!canvas) return { x: 0, y: 0 };
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((e.clientX - rect.left) / rect.width) * 100,
    y: ((e.clientY - rect.top) / rect.height) * 100
  };
};

/** 判断点击位置是否在裁切框边缘（用于调整大小） */
const hitTest = (px: number, py: number): "move" | "tl" | "tr" | "bl" | "br" | null => {
  const { x, y, width, height } = cropRect.value;
  const margin = 8; // 吸附距离（百分比）

  // 检查四个角
  if (px >= x - margin && px <= x + margin && py >= y - margin && py <= y + margin) return "tl";
  if (px >= x + width - margin && px <= x + width + margin && py >= y - margin && py <= y + margin) return "tr";
  if (px >= x - margin && px <= x + margin && py >= y + height - margin && py <= y + height + margin) return "bl";
  if (px >= x + width - margin && px <= x + width + margin && py >= y + height - margin && py <= y + height + margin) return "br";

  // 检查是否在框内（移动）
  if (px >= x && px <= x + width && py >= y && py <= y + height) return "move";

  return null;
};

const handleMouseDown = (e: MouseEvent) => {
  const pos = getCanvasPercent(e);
  const type = hitTest(pos.x, pos.y);
  if (!type) return;

  isDragging.value = true;
  dragType.value = type;
  dragStart.value = { x: e.clientX, y: e.clientY };
  cropStart.value = { ...cropRect.value };
  e.preventDefault();
};

const handleMouseMove = (e: MouseEvent) => {
  if (!isDragging.value) {
    // 更新鼠标样式
    const pos = getCanvasPercent(e);
    const hit = hitTest(pos.x, pos.y);
    const canvas = canvasRef.value;
    if (canvas) {
      if (hit === "move") canvas.style.cursor = "move";
      else if (hit) canvas.style.cursor = "nwse-resize";
      else canvas.style.cursor = "default";
    }
    return;
  }

  const dx = e.clientX - dragStart.value.x;
  const dy = e.clientY - dragStart.value.y;
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const deltaX = (dx / rect.width) * 100;
  const deltaY = (dy / rect.height) * 100;

  let { x, y, width, height } = cropStart.value;

  if (dragType.value === "move") {
    x = Math.max(0, Math.min(100 - width, x + deltaX));
    y = Math.max(0, Math.min(100 - height, y + deltaY));
  } else if (dragType.value === "tl") {
    const newX = Math.max(0, Math.min(x + width - 10, x + deltaX));
    const newY = Math.max(0, Math.min(y + height - 10, y + deltaY));
    width = cropStart.value.width - (newX - cropStart.value.x);
    height = cropStart.value.height - (newY - cropStart.value.y);
    x = newX;
    y = newY;
  } else if (dragType.value === "tr") {
    const newY = Math.max(0, Math.min(y + height - 10, y + deltaY));
    width = Math.max(10, Math.min(100 - x, width + deltaX));
    height = cropStart.value.height - (newY - cropStart.value.y);
    y = newY;
  } else if (dragType.value === "bl") {
    const newX = Math.max(0, Math.min(x + width - 10, x + deltaX));
    width = cropStart.value.width - (newX - cropStart.value.x);
    height = Math.max(10, Math.min(100 - y, height + deltaY));
    x = newX;
  } else if (dragType.value === "br") {
    width = Math.max(10, Math.min(100 - x, width + deltaX));
    height = Math.max(10, Math.min(100 - y, height + deltaY));
  }

  cropRect.value = { x, y, width, height };
};

const handleMouseUp = () => {
  isDragging.value = false;
};

const handleWheel = (e: WheelEvent) => {
  e.preventDefault();
  const delta = e.deltaY > 0 ? -2 : 2;
  const { x, y, width, height } = cropRect.value;
  const newW = Math.max(10, Math.min(100 - x, width + delta));
  const newH = Math.max(10, Math.min(100 - y, height + delta));
  // 以裁切框中心为基准缩放
  const cx = x + width / 2;
  const cy = y + height / 2;
  const newX = cx - newW / 2;
  const newY = cy - newH / 2;
  cropRect.value = {
    x: Math.max(0, newX),
    y: Math.max(0, newY),
    width: newW,
    height: newH
  };
};
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="580px"
    align-center
    destroy-on-close
    class="image-crop-dialog"
    :title="t('create.dialog.crop_title')"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div ref="containerRef" class="crop-container">
      <canvas
        ref="canvasRef"
        class="crop-canvas"
        @mousedown="handleMouseDown"
        @mousemove="handleMouseMove"
        @mouseup="handleMouseUp"
        @mouseleave="handleMouseUp"
        @wheel.prevent="handleWheel"
      />
      <div class="crop-hint">{{ t("create.dialog.crop_hint") }}</div>
    </div>
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

  .crop-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
  }

  .crop-canvas {
    display: block;
    border-radius: 8px;
    cursor: default;
    user-select: none;
  }

  .crop-hint {
    font-size: 12px;
    color: #a0a6ae;
    text-align: center;
  }
}
</style>
