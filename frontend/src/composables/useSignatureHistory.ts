import { nextTick, type Ref } from "vue";

export type SignatureStroke = unknown;

export interface SignatureHistoryState {
  /** 当前画板中实际保留的笔画，顺序就是绘制顺序。 */
  strokes: SignatureStroke[];
  /** 撤销后暂存的笔画，重做时会从这里取回最后一笔。 */
  redoStrokes: SignatureStroke[];
  /** 接口返回的原始图片地址；没有笔画数据时用它恢复画布。 */
  dataUrl?: string;
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
}

export function useSignatureHistory(
  signatureRef: Ref<SignatureInstance | undefined>
) {
  // 组件 ref 在手写板尚未挂载时可能为空，所以所有操作都通过这个方法取实例。
  const getSignature = () => signatureRef.value;

  // 从插件读取当前画布的原始笔画数据，而不是读取已经绘制好的图片。
  const readStrokes = () => getSignature()?.toData?.() ?? [];

  /** 将指定画板的笔画重新绘制到当前签名组件中。 */
  const restore = async (state: SignatureHistoryState) => {
    await nextTick();
    const signature = getSignature();
    if (!signature) return;
    signature.clear?.();
    if (state.strokes.length > 0) {
      signature.fromData?.([...state.strokes], { clear: true });
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

  /** 撤销最近一笔，并把这笔数据放入重做列表。 */
  const undo = async (state: SignatureHistoryState) => {
    const signature = getSignature();
    if (!signature || signature.isEmpty?.()) return "";

    const strokesBeforeUndo = readStrokes();
    const lastStroke = strokesBeforeUndo.at(-1);
    if (!lastStroke) return "";

    // 使用插件提供的原生 undo，让当前画布立即撤销上一笔。
    signature.undo?.();
    await nextTick();

    state.redoStrokes.push(lastStroke);
    state.strokes = readStrokes();
    return signature.save?.("image/png") ?? "";
  };

  /** 恢复最近一次撤销的笔画，并重新绘制当前画布。 */
  const redo = async (state: SignatureHistoryState) => {
    const signature = getSignature();
    const nextStroke = state.redoStrokes.pop();
    if (!signature || !nextStroke) return "";

    const strokes = [...readStrokes(), nextStroke];
    signature.fromData?.(strokes, { clear: true });
    state.strokes = strokes;
    return signature.save?.("image/png") ?? "";
  };

  /** 清空画布，同时清空该画板的撤销和重做记录。 */
  const clear = (state: SignatureHistoryState) => {
    getSignature()?.clear?.();
    state.strokes = [];
    state.redoStrokes = [];
  };

  return {
    clear,
    readStrokes,
    redo,
    restore,
    sync,
    undo
  };
}
