import { markRaw, nextTick, type Ref } from "vue";

export type SignatureStroke = unknown;

export interface SignatureHistoryState {
  /** 当前画板中实际保留的笔画，顺序就是绘制顺序。 */
  strokes: SignatureStroke[];
  /** 撤销后暂存的笔画，重做时会从这里取回最后一笔。 */
  redoStrokes: SignatureStroke[];
  /** 接口返回的原始图片地址；没有笔画数据时用它恢复画布。 */
  dataUrl?: string;
  /** 每个已完成笔画之前的画布快照，用于快速撤销。 */
  snapshots?: ImageData[];
  /** 撤销后的画布快照，用于快速重做。 */
  redoSnapshots?: ImageData[];
}

interface SignatureInstance {
  save?: (format?: string) => string;
  toData?: () => SignatureStroke[];
  fromData?: (
    strokes: SignatureStroke[],
    options?: { clear?: boolean }
  ) => void;
  fromDataURL?: (
    dataUrl: string,
    options?: { clear?: boolean }
  ) => Promise<void>;
  undo?: () => void;
  isEmpty?: () => boolean;
  clear?: () => void;
  getInstance?: () => { canvas?: HTMLCanvasElement };
}

export function useSignatureHistory(
  signatureRef: Ref<SignatureInstance | undefined>
) {
  const snapshotLimit = 20;
  // 组件 ref 在手写板尚未挂载时可能为空，所以所有操作都通过这个方法取实例。
  const getSignature = () => signatureRef.value;
  const getCanvas = () => getSignature()?.getInstance?.().canvas;

  const captureCanvas = () => {
    const canvas = getCanvas();
    const context = canvas?.getContext("2d");
    if (!canvas || !context || canvas.width === 0 || canvas.height === 0) {
      return null;
    }
    return markRaw(context.getImageData(0, 0, canvas.width, canvas.height));
  };

  const restoreCanvas = (imageData: ImageData) => {
    const canvas = getCanvas();
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return false;
    context.putImageData(imageData, 0, 0);
    return true;
  };

  // 从插件读取当前画布的原始笔画数据，而不是读取已经绘制好的图片。
  const readStrokes = () => getSignature()?.toData?.() ?? [];

  /** 将指定画板的笔画重新绘制到当前签名组件中。 */
  const restore = async (state: SignatureHistoryState) => {
    await nextTick();
    const signature = getSignature();
    if (!signature) return;
    signature.clear?.();
    if (state.strokes.length > 0) {
      if (!state.snapshots?.length) {
        state.snapshots = [];
        state.redoSnapshots = [];
        const snapshotStart = Math.max(state.strokes.length - snapshotLimit, 0);
        state.strokes.forEach((stroke, index) => {
          if (index >= snapshotStart) {
            const snapshot = captureCanvas();
            if (snapshot) state.snapshots?.push(snapshot);
          }
          signature.fromData?.([stroke], { clear: false });
        });
      } else {
        signature.fromData?.([...state.strokes], { clear: true });
      }
      return;
    }
    if (state.dataUrl) {
      await signature.fromDataURL?.(state.dataUrl, { clear: true });
    }
  };

  /** 在切换画板或打开画板列表前，把当前画布状态保存回画板对象。 */
  const sync = (state: SignatureHistoryState) => {
    const signature = getSignature();
    if (!signature) return "";

    const strokes = readStrokes();
    state.strokes = [...strokes];
    state.redoStrokes = [];
    return signature.save?.("image/png") ?? "";
  };

  const captureSnapshot = (state: SignatureHistoryState) => {
    const snapshot = captureCanvas();
    if (!snapshot) return;
    state.snapshots ??= [];
    state.redoSnapshots = [];
    state.snapshots.push(snapshot);
  };

  /** 撤销最近一笔，并把这笔数据放入重做列表。 */
  const undo = async (state: SignatureHistoryState) => {
    const signature = getSignature();
    if (!signature || state.strokes.length === 0) return state.dataUrl ?? "";

    const lastStroke = state.strokes.at(-1);
    if (!lastStroke) return "";

    const currentSnapshot = captureCanvas();
    const previousSnapshot = state.snapshots?.pop();
    if (
      currentSnapshot &&
      previousSnapshot &&
      restoreCanvas(previousSnapshot)
    ) {
      state.redoSnapshots ??= [];
      state.redoSnapshots.push(currentSnapshot);
      state.redoStrokes.push(lastStroke);
      state.strokes = state.strokes.slice(0, -1);
      return state.dataUrl ?? "";
    }

    state.redoStrokes.push(lastStroke);
    state.strokes = state.strokes.slice(0, -1);
    signature.fromData?.([...state.strokes], { clear: true });
    return state.dataUrl ?? "";
  };

  /** 恢复最近一次撤销的笔画，并重新绘制当前画布。 */
  const redo = async (state: SignatureHistoryState) => {
    const signature = getSignature();
    const nextStroke = state.redoStrokes.pop();
    if (!signature || !nextStroke) return state.dataUrl ?? "";

    const redoSnapshot = state.redoSnapshots?.pop();
    const currentSnapshot = captureCanvas();
    if (redoSnapshot && currentSnapshot && restoreCanvas(redoSnapshot)) {
      state.snapshots ??= [];
      state.snapshots.push(currentSnapshot);
      state.strokes = [...state.strokes, nextStroke];
      return state.dataUrl ?? "";
    }

    const strokes = [...state.strokes, nextStroke];
    signature.fromData?.(strokes, { clear: true });
    state.strokes = strokes;
    return state.dataUrl ?? "";
  };

  /** 清空画布，同时清空该画板的撤销和重做记录。 */
  const clear = (state: SignatureHistoryState) => {
    getSignature()?.clear?.();
    state.strokes = [];
    state.redoStrokes = [];
    state.snapshots = [];
    state.redoSnapshots = [];
  };

  return {
    clear,
    readStrokes,
    redo,
    captureSnapshot,
    restore,
    sync,
    undo
  };
}
