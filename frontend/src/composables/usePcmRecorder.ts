import { onBeforeUnmount, ref, shallowRef } from "vue";

export interface UsePcmRecorderOptions {
  audio?: MediaTrackConstraints;
  onAudioData?: (audio: ArrayBuffer) => void;
}

const TARGET_SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 320; // 20ms at 16kHz
const WORKLET_URL = "/pcm-processor.js";

/** Captures microphone audio as stable 16kHz mono PCM for streaming ASR. */
export function usePcmRecorder(options: UsePcmRecorderOptions = {}) {
  const mediaStream = shallowRef<MediaStream | null>(null);
  const audioContext = shallowRef<AudioContext | null>(null);
  const audioSource = shallowRef<MediaStreamAudioSourceNode | null>(null);
  const audioNode = shallowRef<AudioWorkletNode | null>(null);
  const isRecording = ref(false);
  const error = ref<Error | DOMException | null>(null);
  let resampleBuffer = new Float32Array(0);
  let resamplePosition = 0;
  let outputBuffer = new Int16Array(0);

  const acquireStream = async () => {
    if (mediaStream.value) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      error.value = new Error("mic_unavailable_insecure_origin");
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
      error.value =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法开启麦克风");
      return false;
    }
  };

  const appendOutput = (samples: Int16Array) => {
    if (!samples.length) return;
    const next = new Int16Array(outputBuffer.length + samples.length);
    next.set(outputBuffer);
    next.set(samples, outputBuffer.length);
    outputBuffer = next;
    while (outputBuffer.length >= FRAME_SAMPLES) {
      const frame = outputBuffer.slice(0, FRAME_SAMPLES);
      outputBuffer = outputBuffer.slice(FRAME_SAMPLES);
      options.onAudioData?.(frame.buffer);
    }
  };

  const appendInput = (input: Float32Array, inputRate: number) => {
    const merged = new Float32Array(resampleBuffer.length + input.length);
    merged.set(resampleBuffer);
    merged.set(input, resampleBuffer.length);
    resampleBuffer = merged;

    const step = inputRate / TARGET_SAMPLE_RATE;
    const output: number[] = [];
    while (resamplePosition + 1 < resampleBuffer.length) {
      const index = Math.floor(resamplePosition);
      const fraction = resamplePosition - index;
      output.push(
        resampleBuffer[index] * (1 - fraction) +
          resampleBuffer[index + 1] * fraction
      );
      resamplePosition += step;
    }

    const consumed = Math.floor(resamplePosition);
    if (consumed > 0) {
      resampleBuffer = resampleBuffer.slice(consumed);
      resamplePosition -= consumed;
    }

    const pcm = new Int16Array(output.length);
    for (let i = 0; i < output.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, output[i]));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    appendOutput(pcm);
  };

  const startRecording = async () => {
    if (isRecording.value) return true;
    if (!(await acquireStream())) return false;

    try {
      if (!("AudioWorkletNode" in window)) {
        throw new Error("当前浏览器不支持 AudioWorklet");
      }
      const context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      await context.audioWorklet.addModule(WORKLET_URL);
      const source = context.createMediaStreamSource(mediaStream.value!);
      const node = new AudioWorkletNode(context, "pcm-capture-processor");
      const silentGain = context.createGain();
      silentGain.gain.value = 0;
      source.connect(node).connect(silentGain).connect(context.destination);
      node.port.onmessage = event => {
        if (isRecording.value && event.data instanceof Float32Array) {
          appendInput(event.data, context.sampleRate);
        }
      };
      await context.resume();
      audioContext.value = context;
      audioSource.value = source;
      audioNode.value = node;
      resampleBuffer = new Float32Array(0);
      resamplePosition = 0;
      outputBuffer = new Int16Array(0);
      isRecording.value = true;
      error.value = null;
      return true;
    } catch (cause) {
      stopRecording();
      error.value =
        cause instanceof Error ||
        (typeof DOMException !== "undefined" && cause instanceof DOMException)
          ? cause
          : new Error("无法启动 PCM 录音");
      return false;
    }
  };

  const stopRecording = () => {
    isRecording.value = false;
    audioNode.value?.disconnect();
    audioSource.value?.disconnect();
    audioNode.value = null;
    audioSource.value = null;
    const context = audioContext.value;
    audioContext.value = null;
    if (context) void context.close();
    mediaStream.value?.getTracks().forEach(track => track.stop());
    mediaStream.value = null;
    resampleBuffer = new Float32Array(0);
    resamplePosition = 0;
    outputBuffer = new Int16Array(0);
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
