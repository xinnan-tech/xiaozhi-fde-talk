class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs, _outputs, _parameters) {
    const channel = inputs[0]?.[0];
    if (channel && channel.length) {
      this.port.postMessage(channel.slice());
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
