<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

export interface HandwritingPoint {
  x: number;
  y: number;
}

export interface HandwritingStroke {
  points: HandwritingPoint[];
  color: string;
  size: number;
  tool: "pen" | "eraser";
}

const props = withDefaults(
  defineProps<{
    initialStrokes?: HandwritingStroke[];
    fill?: boolean;
  }>(),
  {
    initialStrokes: () => [],
    fill: true
  }
);

const emit = defineEmits<{
  (event: "ready"): void;
  (event: "strokeEnd"): void;
  (event: "update", payload: HandwritingPadState): void;
}>();

/**
 * 对外回传的完整笔画状态；父组件拿到后写回自己的多画板记录，
 * 用于驱动撤销/重做按钮可用性。
 */
export interface HandwritingPadState {
  strokes: HandwritingStroke[];
  redoStack: HandwritingStroke[];
}

function publishState(): void {
  emit("update", {
    strokes: strokes.value,
    redoStack: redoStack.value
  });
}

defineOptions({
  name: "HandwritingPad"
});

const canvasRef = ref<HTMLCanvasElement | null>(null);
// 离屏画布：仅在笔画真正发生变化时整张重画一次（handleEnd / undo / redo / clear / load），
// 鼠标悬停移动光标时只做一次 drawImage + 一个圆，避免每帧都 O(N) 重画所有笔画。
let strokesLayer: HTMLCanvasElement | null = null;
let strokesLayerCtx: CanvasRenderingContext2D | null = null;
// 记录当前 canvas 的 CSS 尺寸，用于在 ResizeObserver 触发的重绘里复用。
const cssWidth = ref(1);
const cssHeight = ref(1);
let ctx: CanvasRenderingContext2D | null = null;
let dpr = 1;
let resizeObserver: ResizeObserver | null = null;

// ==================== 状态 ====================
const strokes = ref<HandwritingStroke[]>([]);
const redoStack = ref<HandwritingStroke[]>([]);
const currentStroke = ref<HandwritingPoint[]>([]);
const isDrawing = ref(false);
const lastX = ref(0);
const lastY = ref(0);
const currentTool = ref<"pen" | "eraser">("pen");
const currentColor = ref("#000000");
const currentSize = ref(4);
// 鼠标悬停时的光标预览位置；落笔或离开画布时置 null，避免光标圆与笔画重叠。
const cursorPos = ref<HandwritingPoint | null>(null);

// ==================== 工具函数 ====================
function getPosition(e: MouseEvent | TouchEvent): HandwritingPoint {
  const canvas = canvasRef.value;
  if (!canvas) return { x: 0, y: 0 };
  const rect = canvas.getBoundingClientRect();
  let clientX: number;
  let clientY: number;
  if ("touches" in e && e.touches.length > 0) {
    const touch = e.touches[0];
    clientX = touch.clientX;
    clientY = touch.clientY;
  } else if ("changedTouches" in e && e.changedTouches.length > 0) {
    const touch = e.changedTouches[0];
    clientX = touch.clientX;
    clientY = touch.clientY;
  } else {
    const mouse = e as MouseEvent;
    clientX = mouse.clientX;
    clientY = mouse.clientY;
  }
  return {
    x: clientX - rect.left,
    y: clientY - rect.top
  };
}

function drawStroke(
  drawCtx: CanvasRenderingContext2D,
  points: HandwritingPoint[],
  color: string,
  size: number,
  tool: "pen" | "eraser"
): void {
  if (points.length === 0) return;
  drawCtx.save();
  drawCtx.beginPath();
  drawCtx.strokeStyle = color;
  drawCtx.fillStyle = color;
  drawCtx.lineWidth = size;
  drawCtx.lineCap = "round";
  drawCtx.lineJoin = "round";
  drawCtx.globalCompositeOperation =
    tool === "eraser" ? "destination-out" : "source-over";
  if (points.length === 1) {
    drawCtx.arc(points[0].x, points[0].y, size / 2, 0, Math.PI * 2);
    drawCtx.fill();
  } else {
    drawCtx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      drawCtx.lineTo(points[i].x, points[i].y);
    }
    drawCtx.stroke();
  }
  drawCtx.restore();
}

// 用白色背景铺底，保证从透明区域导出 PNG 时不会变成黑色。
function fillBackground(
  target: CanvasRenderingContext2D,
  w: number,
  h: number
) {
  target.save();
  target.fillStyle = "#ffffff";
  target.fillRect(0, 0, w, h);
  target.restore();
}

/**
 * 确保离屏画布存在且跟当前可见画布尺寸一致；
 * 仅在 resize 或初始化时调用一次，同尺寸下是空操作。
 */
function ensureStrokesLayer(): void {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const targetWidth = canvas.width;
  const targetHeight = canvas.height;
  if (!strokesLayer) {
    strokesLayer = document.createElement("canvas");
    strokesLayerCtx = strokesLayer.getContext("2d");
  }
  if (
    !strokesLayerCtx ||
    strokesLayer.width !== targetWidth ||
    strokesLayer.height !== targetHeight
  ) {
    strokesLayer.width = targetWidth;
    strokesLayer.height = targetHeight;
  }
}

/**
 * 把当前所有笔画重新绘制到离屏画布：白底 + 笔画。
 * 笔画数据没变就不需要调，每一帧重画所有笔画是肉眼延迟的元凶。
 */
function paintStrokesLayer(): void {
  ensureStrokesLayer();
  const lctx = strokesLayerCtx;
  const layer = strokesLayer;
  if (!lctx || !layer) return;
  lctx.save();
  lctx.setTransform(1, 0, 0, 1, 0, 0);
  lctx.clearRect(0, 0, layer.width, layer.height);
  lctx.fillStyle = "#ffffff";
  lctx.fillRect(0, 0, layer.width, layer.height);
  lctx.scale(dpr, dpr);
  for (const stroke of strokes.value) {
    drawStroke(lctx, stroke.points, stroke.color, stroke.size, stroke.tool);
  }
  lctx.restore();
}

/**
 * 在可见画布左上角画光标圆；沿用 dpr 的坐标系变换。
 */
function drawCursorCircleOn(target: CanvasRenderingContext2D): void {
  if (!cursorPos.value) return;
  const { x, y } = cursorPos.value;
  const radius = Math.max(currentSize.value / 2, 1);
  target.save();
  target.scale(dpr, dpr);
  target.lineWidth = 1;
  if (currentTool.value === "eraser") {
    target.setLineDash([4, 4]);
    target.strokeStyle = "#888888";
  } else {
    target.setLineDash([]);
    target.strokeStyle = currentColor.value;
  }
  target.beginPath();
  target.arc(x, y, radius, 0, Math.PI * 2);
  target.stroke();
  target.restore();
}

/**
 * 把离屏笔画层整张 blit 到可见画布，再在顶层叠一个光标圆。
 * 这是鼠标悬停 / 工具色变更路径的主入口，O(1) 一次 drawImage + 一个 arc。
 *
 * 注意：setTransform 会冲掉之前留下来的 dpr 缩放，用 save/restore 包起来保证调用后
 * 可见 ctx 的"持久变换"仍是 dpr-scaled，后续调 drawStroke 落点正确。
 */
function renderVisibleFromLayer(): void {
  if (!ctx || !canvasRef.value || !strokesLayer) return;
  const canvas = canvasRef.value;
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(strokesLayer, 0, 0);
  ctx.restore();
  // drawCursorCircleOn 内部 save/restore，会自行退回 ctx 之前的状态。
  drawCursorCircleOn(ctx);
}

/**
 * 笔画数据真发生了变化时用：先重画离屏层，再 blit 到可见画布。
 */
function redrawCanvas(): void {
  paintStrokesLayer();
  renderVisibleFromLayer();
}

/** 光标移动时专用：只走 blit + 圆，不重画笔画。 */
function drawCursor(): void {
  renderVisibleFromLayer();
}

// 按当前 cssWidth/cssHeight 重新初始化 canvas 像素分辨率，触发坐标变换与白底。
function resizeCanvas(): void {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const nextWidth = Math.max(1, Math.floor(rect.width));
  const nextHeight = Math.max(1, Math.floor(rect.height));
  if (nextWidth === cssWidth.value && nextHeight === cssHeight.value) {
    return;
  }
  cssWidth.value = nextWidth;
  cssHeight.value = nextHeight;
  dpr = window.devicePixelRatio || 1;
  canvas.width = nextWidth * dpr;
  canvas.height = nextHeight * dpr;
  ctx = canvas.getContext("2d");
  if (!ctx) return;
  // 设置 canvas.width/height 会把 ctx 状态全部清零，这里重新挂上 dpr 缩放，
  // 否则后续直接调 drawStroke 落到内部 1:1 像素上，移动端 dpr>1 时笔迹会偏。
  ctx.scale(dpr, dpr);
  redrawCanvas();
}

// ==================== 事件处理 ====================
function handleStart(e: MouseEvent | TouchEvent): void {
  e.preventDefault();
  if (!ctx) return;
  isDrawing.value = true;
  const pos = getPosition(e);
  lastX.value = pos.x;
  lastY.value = pos.y;
  currentStroke.value = [{ x: pos.x, y: pos.y }];
  const size = currentSize.value;
  drawStroke(
    ctx,
    currentStroke.value,
    currentColor.value,
    size,
    currentTool.value
  );
}

function handleMove(e: MouseEvent | TouchEvent): void {
  if (!ctx) return;
  const pos = getPosition(e);
  if (isDrawing.value) {
    e.preventDefault();
    // 正在落笔时悬浮圆必须让位，避免压笔尖位置出现鬼影；先清一次再补一笔。
    if (cursorPos.value) {
      cursorPos.value = null;
      renderVisibleFromLayer();
    }
    const size = currentSize.value;
    drawStroke(
      ctx,
      [
        { x: lastX.value, y: lastY.value },
        { x: pos.x, y: pos.y }
      ],
      currentColor.value,
      size,
      currentTool.value
    );
    currentStroke.value.push({ x: pos.x, y: pos.y });
    lastX.value = pos.x;
    lastY.value = pos.y;
    return;
  }
  // 鼠标悬停：画一个随 currentSize 变化的圆作光标预览。
  cursorPos.value = pos;
  drawCursor();
}

function handleCanvasLeave(): void {
  // 落笔中离开：保留原"拖出 canvas 也能提交"的语义，先 commit 那一笔。
  if (isDrawing.value) {
    handleEnd();
    return;
  }
  // 纯悬停离开：清掉光标预览，恢复纯笔画画面。
  if (cursorPos.value) {
    cursorPos.value = null;
    renderVisibleFromLayer();
  }
}

function handleEnd(): void {
  if (!isDrawing.value) return;
  isDrawing.value = false;
  if (currentStroke.value.length > 0) {
    const size = currentSize.value;
    strokes.value.push({
      points: [...currentStroke.value],
      color: currentColor.value,
      size,
      tool: currentTool.value
    });
    redoStack.value = [];
    publishState();
    // 落笔期间笔画是直接画到可见 canvas 的，离屏层这会儿是旧的，
    // 同步一次让下次光标移动不会出现该笔丢失的鬼影。
    paintStrokesLayer();
    renderVisibleFromLayer();
  }
  currentStroke.value = [];
  emit("strokeEnd");
}

function undo(): void {
  if (strokes.value.length === 0) return;
  const last = strokes.value.pop();
  if (last) redoStack.value.push(last);
  redrawCanvas();
  publishState();
}

function redo(): void {
  if (redoStack.value.length === 0) return;
  const stroke = redoStack.value.pop();
  if (!stroke) return;
  strokes.value.push(stroke);
  redrawCanvas();
  publishState();
}

function clear(): void {
  strokes.value = [];
  redoStack.value = [];
  redrawCanvas();
  publishState();
}

function setTool(tool: "pen" | "eraser"): void {
  currentTool.value = tool;
}

function setPenColor(color: string): void {
  currentColor.value = color;
}

function setPenSize(size: number): void {
  currentSize.value = Math.max(1, size);
}

function getStrokes(): HandwritingStroke[] {
  return strokes.value.map(stroke => ({
    points: stroke.points.map(p => ({ x: p.x, y: p.y })),
    color: stroke.color,
    size: stroke.size,
    tool: stroke.tool
  }));
}

function loadStrokes(
  next: HandwritingStroke[],
  backgroundDataUrl?: string
): void {
  strokes.value = next.map(stroke => ({
    points: stroke.points.map(p => ({ x: p.x, y: p.y })),
    color: stroke.color,
    size: stroke.size,
    tool: stroke.tool
  }));
  redoStack.value = [];
  // 把 PNG 当作背景叠到当前 canvas，保证视觉与历史结果一致，再让新笔画覆盖。
  if (backgroundDataUrl) {
    ensureStrokesLayer();
    const layer = strokesLayer;
    const lctx = strokesLayerCtx;
    if (!layer || !lctx) return;
    const tempImg = new Image();
    tempImg.onload = () => {
      lctx.setTransform(1, 0, 0, 1, 0, 0);
      lctx.clearRect(0, 0, layer.width, layer.height);
      lctx.drawImage(tempImg, 0, 0, layer.width, layer.height);
      lctx.scale(dpr, dpr);
      for (const stroke of strokes.value) {
        drawStroke(lctx, stroke.points, stroke.color, stroke.size, stroke.tool);
      }
      renderVisibleFromLayer();
      publishState();
    };
    tempImg.onerror = () => {
      redrawCanvas();
      publishState();
    };
    tempImg.src = backgroundDataUrl;
    return;
  }
  paintStrokesLayer();
  renderVisibleFromLayer();
  publishState();
}

// 将透明区域铺白后导出 PNG dataURL，供父组件上传后端。
function saveImage(): string {
  const canvas = canvasRef.value;
  if (!canvas) return "";
  const exportCanvas = document.createElement("canvas");
  exportCanvas.width = canvas.width;
  exportCanvas.height = canvas.height;
  const exportCtx = exportCanvas.getContext("2d");
  if (!exportCtx) return "";
  fillBackground(exportCtx, exportCanvas.width, exportCanvas.height);
  exportCtx.drawImage(canvas, 0, 0);
  return exportCanvas.toDataURL("image/png");
}

onMounted(() => {
  if (!canvasRef.value) return;
  dpr = window.devicePixelRatio || 1;
  ctx = canvasRef.value.getContext("2d");
  // 首次挂载后用客户端读取的 initialStrokes 还原画板；
  // 后续由父组件通过 loadStrokes 驱动，不要再读取 props.initialStrokes。
  const initial = props.initialStrokes;
  if (Array.isArray(initial) && initial.length > 0) {
    loadStrokes(initial);
  }
  if (props.fill) {
    resizeCanvas();
    const target = canvasRef.value.parentElement;
    if (target && typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => resizeCanvas());
      resizeObserver.observe(target);
    }
  } else {
    const canvas = canvasRef.value;
    canvas.width = 1 * dpr;
    canvas.height = 1 * dpr;
    fillBackground(ctx!, canvas.width / dpr, canvas.height / dpr);
  }
  emit("ready");
});

// 工具或粗细变化：刷新光标圆 + 在画布顶部弹出"画笔 / 橡皮擦粗细"提示。
watch(
  [currentSize, currentTool],
  () => {
    if (cursorPos.value) drawCursor();
  },
  { immediate: false }
);

// 当父组件把 props.initialStrokes 整个替换时（例如页面已经加载到后端数据），刷新画板。
// 笔画细粒度修改由 loadStrokes 接管，这里只对"初次出现且非空"做兜底还原。
watch(
  () => props.initialStrokes,
  next => {
    if (!Array.isArray(next) || next.length === 0) return;
    if (strokes.value.length === 0) {
      loadStrokes(next);
    }
  },
  { deep: false }
);

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});

defineExpose({
  getStrokes,
  loadStrokes,
  saveImage,
  clear,
  undo,
  redo,
  setTool,
  setPenColor,
  setPenSize
});
</script>

<template>
  <div class="handwriting-pad-shell">
    <div class="canvas-container" :class="{ fill: fill }">
      <canvas
        ref="canvasRef"
        class="handwriting-pad-canvas"
        @mousedown="handleStart"
        @mousemove="handleMove"
        @mouseup="handleEnd"
        @mouseleave="handleCanvasLeave"
        @touchstart.prevent="handleStart"
        @touchmove.prevent="handleMove"
        @touchend.prevent="handleEnd"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.handwriting-pad-shell {
  display: flex;
  width: 100%;
  height: 100%;
}

.canvas-container {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 8%);

  .handwriting-pad-canvas {
    display: block;
    width: 100%;
    height: 100%;
    cursor: none;
    background: #fff;
    border-radius: 8px;
    touch-action: none;
  }
}
</style>
