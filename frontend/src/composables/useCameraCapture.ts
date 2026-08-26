import { onBeforeUnmount, ref, shallowRef } from "vue";

export const blobToBase64 = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result ?? "");
      // 后端要求纯 base64，去掉 data:image/jpeg;base64, 前缀
      resolve(dataUrl.slice(dataUrl.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error("read_failed"));
    reader.readAsDataURL(blob);
  });

/** 拍照名片 OCR：只管取流与截帧，预览 <video> 元素留在组件模板里。 */
export function useCameraCapture() {
  const stream = shallowRef<MediaStream | null>(null);
  const error = ref<Error | null>(null);

  const close = () => {
    stream.value?.getTracks().forEach(track => track.stop());
    stream.value = null;
  };

  const open = async () => {
    if (stream.value) return true;

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      error.value = new Error("getUserMedia unsupported");
      console.error("[useCameraCapture] 浏览器不支持 getUserMedia");
      return false;
    }

    try {
      stream.value = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: false
      });
      error.value = null;
      return true;
    } catch (cause) {
      close();
      error.value =
        cause instanceof Error ? cause : new Error("camera_unavailable");
      console.error("[useCameraCapture] 摄像头开启失败", error.value);
      return false;
    }
  };

  /** 截取当前帧 → JPEG base64（无 data: 前缀）。 */
  const snap = async (video: HTMLVideoElement) => {
    if (!video.videoWidth || !video.videoHeight) {
      throw new Error("camera_not_ready");
    }

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("canvas_unsupported");

    context.drawImage(video, 0, 0);

    const blob = await new Promise<Blob | null>(resolve =>
      canvas.toBlob(resolve, "image/jpeg", 0.9)
    );
    if (!blob) throw new Error("image_encode_failed");

    return blobToBase64(blob);
  };

  onBeforeUnmount(close);

  return { stream, error, open, close, snap };
}
