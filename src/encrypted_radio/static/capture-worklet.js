// Audio capture only. Morse and cipher decoding always run in the Python core.
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
    this.pending = 0;
    this.limit = 2 * sampleRate;
    this.closed = false;
    this.port.onmessage = ({ data }) => {
      if (this.closed) return;
      if (data === 'flush') {
        if (this.offset) {
          const tail = this.buffer.slice(0, this.offset);
          this.pending += tail.length;
          this.port.postMessage(tail, [tail.buffer]);
        }
        this.offset = 0;
        this.closed = true;
        this.port.postMessage({ flushed: true });
      } else if (Number.isInteger(data?.ack) && data.ack > 0 && data.ack <= this.pending) {
        this.pending -= data.ack;
      }
    };
  }
  process(inputs) {
    if (this.closed) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      // Credits are returned only after Python acknowledges the corresponding
      // samples. This bounds MessagePort backlog even if the main thread stalls.
      if (this.pending + this.offset >= this.limit) {
        this.closed = true;
        this.port.postMessage({ discontinuity: 'Microphone audio exceeded the two-second queue.' });
        return false;
      }
      let sample = 0;
      for (const channel of channels) sample += channel[i] || 0;
      this.buffer[this.offset++] = sample / channels.length;
      if (this.offset === this.buffer.length) {
        this.pending += this.buffer.length;
        this.port.postMessage(this.buffer, [this.buffer.buffer]);
        this.buffer = new Float32Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('er-capture', CaptureProcessor);
