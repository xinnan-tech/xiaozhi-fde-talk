import { onBeforeUnmount, ref, shallowRef } from "vue";

export interface UseAudioRecorderOptions {
  audio?: MediaTrackConstraints;
  onAudioData?: (audio: Blob) => void;
}

/** 管理浏览器麦克风权限和音频流。 */
export function useAudioRecorder(options: UseAudioRecorderOptions = {}) {
  const mediaStream = shallowRef<MediaStream | null>(null);
  const mediaRecorder = shallowRef<MediaRecorder | null>(null);
  const isRecording = ref(false);
  const error = ref<Error | DOMException | null>(null);

  const acquireStream = async () => {
    if (mediaStream.value) return true;
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      error.value = new Error("当前浏览器不支持 getUserMedia");
      console.error(
        "[useAudioRecorder] 浏览器不支持 getUserMedia",
        error.value
      );
      return false;
    }

    try {
      mediaStream.value = await navigator.mediaDevices.getUserMedia({
        audio: options.audio ?? true,
        video: false
      });
      error.value = null;
      return true;
    } catch (cause) {
      mediaStream.value?.getTracks().forEach(track => track.stop());
      mediaStream.value = null;
      const recorderError =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法开启麦克风");
      error.value = recorderError;
      console.error("[useAudioRecorder] 麦克风开启失败", recorderError);
      return false;
    }
  };

  const startRecording = async () => {
    if (mediaRecorder.value) return true;

    if (!(await acquireStream())) return false;

    try {
      if (typeof MediaRecorder === "undefined") {
        throw new Error("当前浏览器不支持 MediaRecorder");
      }

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : undefined;
      mediaRecorder.value = new MediaRecorder(
        mediaStream.value,
        mimeType ? { mimeType } : undefined
      );
      mediaRecorder.value.ondataavailable = event => {
        if (!event.data.size) return;

        console.info("[useAudioRecorder] 收到音频片段", {
          size: event.data.size,
          type: event.data.type
        });
        options.onAudioData?.(event.data);
      };
      mediaRecorder.value.start(200);
      error.value = null;
      isRecording.value = true;
      console.info("[useAudioRecorder] 麦克风已开启", {
        stream: mediaStream.value,
        tracks: mediaStream.value.getAudioTracks().map(track => ({
          id: track.id,
          label: track.label,
          enabled: track.enabled,
          readyState: track.readyState
        }))
      });
      return true;
    } catch (cause) {
      mediaRecorder.value = null;
      mediaStream.value?.getTracks().forEach(track => track.stop());
      mediaStream.value = null;
      const recorderError =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法开启麦克风");
      error.value = recorderError;
      console.error("[useAudioRecorder] 麦克风开启失败", recorderError);
      return false;
    }
  };

  const stopRecording = () => {
    if (mediaRecorder.value?.state === "recording") {
      mediaRecorder.value.stop();
    }
    mediaRecorder.value = null;
    mediaStream.value?.getTracks().forEach(track => track.stop());
    mediaStream.value = null;
    if (isRecording.value) {
      console.info("[useAudioRecorder] 麦克风已关闭");
    }
    isRecording.value = false;
  };

  onBeforeUnmount(stopRecording);

  return {
    mediaStream,
    isRecording,
    error,
    acquireStream,
    startRecording,
    stopRecording
  };
}
