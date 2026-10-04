"""PortAudio adapters: callbacks never wait on stdin, stdout, or queue space."""

from collections import deque
import queue
import time

import numpy as np

from .audio import AudioError


def _sounddevice():
    try:
        import sounddevice
    except (ImportError, OSError) as error:
        raise AudioError("live audio requires the audio extra and the system PortAudio library") from error
    return sounddevice


def devices():
    """Query devices without opening or recording from them."""
    sd = _sounddevice()
    try:
        return sd.query_devices()
    except sd.PortAudioError as error:
        raise AudioError(f"cannot enumerate audio devices: {error}") from error


def transmit(chunks, sample_rate=48000, device=None):
    """Play a bounded producer stream; intentional stdin pauses play silence."""
    sd = _sounddevice()
    block = round(sample_rate * 0.020)
    pending = queue.Queue(maxsize=100)
    errors = deque(maxlen=1)
    current = np.empty(0, dtype=np.float32)
    position = 0

    def callback(outdata, frames, timing, status):
        nonlocal current, position
        del timing
        outdata.fill(0)
        if status:
            errors.append(f"audio playback discontinuity: {status}")
        written = 0
        while written < frames:
            if position == len(current):
                try:
                    current = pending.get_nowait()
                except queue.Empty:
                    break
                position = 0
            count = min(frames - written, len(current) - position)
            outdata[written:written + count, 0] = current[position:position + count]
            position += count
            written += count
            if position == len(current):
                pending.task_done()

    try:
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", blocksize=block, device=device, callback=callback) as stream:
            for chunk in chunks:
                # Bound arbitrary producers as well as MorseEncoder output.
                for start in range(0, len(chunk), block):
                    part = np.asarray(chunk[start:start + block], dtype=np.float32)
                    while True:
                        if errors:
                            raise AudioError(errors[0])
                        if not stream.active:
                            raise AudioError("audio output stopped unexpectedly")
                        try:
                            pending.put(part, timeout=0.05)
                            break
                        except queue.Full:
                            continue
            while pending.unfinished_tasks:
                if errors:
                    raise AudioError(errors[0])
                if not stream.active:
                    raise AudioError("audio output stopped before draining")
                time.sleep(0.01)
            if errors:
                raise AudioError(errors[0])
    except sd.PortAudioError as error:
        raise AudioError(f"cannot play audio: {error}") from error


def receive(sample_rate=48000, device=None):
    """Yield microphone PCM; bounded two-second queue reports sample loss."""
    sd = _sounddevice()
    pending = queue.Queue(maxsize=100)
    errors = deque(maxlen=1)

    def callback(indata, frames, timing, status):
        del frames, timing
        if status:
            errors.append(f"audio capture discontinuity: {status}")
        try:
            pending.put_nowait(indata[:, 0].copy())
        except queue.Full:
            errors.append("microphone queue overflow: downstream cannot keep up")

    try:
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32", blocksize=round(sample_rate * 0.020), device=device, callback=callback) as stream:
            while True:
                if errors:
                    raise AudioError(errors[0])
                if not stream.active:
                    raise AudioError("audio input stopped unexpectedly")
                try:
                    yield pending.get(timeout=0.1)
                except queue.Empty:
                    continue
    except sd.PortAudioError as error:
        raise AudioError(f"cannot capture audio: {error}") from error
