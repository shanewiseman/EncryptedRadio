"""Loopback-only browser demo. All signal and cipher work uses the shared core."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import shutil
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

MAX_TEXT = 512
MAX_UPLOAD = 64 * 1024 * 1024
MAX_SECONDS = 600
STATIC = Path(__file__).with_name("static")
PORT = web.AppKey("port", object)
JOBS = web.AppKey("jobs", dict)
SESSIONS = web.AppKey("sessions", dict)
JOB_LOCK = web.AppKey("job_lock", asyncio.Lock)
TEMP_ROOT = web.AppKey("temp_root", Path)
WORKERS = web.AppKey("workers", dict)


def _cores():
    from . import audio, cipher, config, framing
    return audio, cipher, config, framing


def _options(data):
    audio, _, config, _ = _cores()
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object.")
    mode = data.get("mode", "checked")
    if mode not in ("checked", "raw", "text"):
        raise ValueError("Choose checked, raw, or text mode.")
    machine = config.Machine.from_dict(data["machine"]) if data.get("machine") else config.load_machine()
    key = config.Key.from_dict(data["key"], machine) if data.get("key") else config.load_key(machine=machine)
    sample_rate = data.get("sample_rate", 48000)
    if type(sample_rate) is not int or sample_rate not in (44100, 48000):
        raise ValueError("Browser audio must use 44100 or 48000 Hz.")
    frequency = float(data.get("frequency", 700))
    wpm = float(data.get("wpm", 20))
    if not math.isfinite(frequency) or not 400 <= frequency <= 1200:
        raise ValueError("Frequency must be between 400 and 1200 Hz.")
    if not math.isfinite(wpm) or not 8 <= wpm <= 30:
        raise ValueError("Speed must be between 8 and 30 WPM.")
    settings = audio.AudioSettings(sample_rate=sample_rate, frequency=frequency, wpm=wpm)
    rx_frequency = data.get("rx_frequency")
    rx_wpm = data.get("rx_wpm")
    for value, low, high, label in ((rx_frequency, 400, 1200, "Receiver frequency"), (rx_wpm, 8, 30, "Receiver speed")):
        if value is not None and (not math.isfinite(float(value)) or not low <= float(value) <= high):
            raise ValueError(f"{label} is outside its supported range.")
    return mode, machine, key, settings, None if rx_frequency is None else float(rx_frequency), None if rx_wpm is None else float(rx_wpm)


def _text(value):
    if not isinstance(value, str):
        raise ValueError("Text must be a string.")
    try:
        result = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("The demo accepts ASCII only.") from exc
    if len(result) > MAX_TEXT:
        raise ValueError("The browser demo accepts at most 512 ASCII bytes; use the CLI for larger input.")
    return result


def _stream_codec(mode, machine, key, *, receive=False, block_size=128):
    _, cipher, _, framing = _cores()
    if mode == "text":
        return None
    if mode == "checked":
        return framing.CheckedDecoder(machine, key) if receive else framing.CheckedEncoder(machine, key, block_size=block_size)
    return cipher.RawDecoder(machine, key) if receive else cipher.RawEncoder(machine, key)



@web.middleware
async def _guard(request, handler):
    host = request.headers.get("Host", "")
    name, sep, port = host.partition(":")
    configured_port = request.app[PORT]
    if name not in ("localhost", "127.0.0.1") or (sep and not port.isdecimal()) or (configured_port is not None and host not in (f"localhost:{configured_port}", f"127.0.0.1:{configured_port}")):
        raise web.HTTPForbidden(text="This demo is available only on its loopback origin.")
    origin = request.headers.get("Origin")
    if origin is not None and origin != f"http://{host}":
        raise web.HTTPForbidden(text="Unexpected Origin.")
    try:
        response = await handler(request)
    except (ValueError, TypeError, KeyError, OverflowError, wave.Error, json.JSONDecodeError) as exc:
        response = web.json_response({"error": str(exc)}, status=400)
    response.headers.update({
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; worker-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        "Permissions-Policy": "microphone=(self), camera=()",
    })
    return response


async def _config(request):
    _, _, config, _ = _cores()
    machine = config.load_machine()
    key = config.load_key(machine=machine)
    return web.json_response({"machine": machine.to_dict(), "key": key.to_dict(), "limits": {"text_bytes": MAX_TEXT, "audio_seconds": MAX_SECONDS, "upload_bytes": MAX_UPLOAD}})


def _new_job(app):
    now = time.monotonic()
    jobs = app[JOBS]
    expired = [identifier for identifier, entry in jobs.items() if now - entry["created"] > 3600]
    for identifier in expired:
        shutil.rmtree(jobs.pop(identifier)["directory"], ignore_errors=True)
    if len(jobs) >= 12:
        oldest = min(jobs, key=lambda identifier: jobs[identifier]["created"])
        shutil.rmtree(jobs.pop(oldest)["directory"], ignore_errors=True)
    identifier = uuid.uuid4().hex
    directory = app[TEMP_ROOT] / identifier
    directory.mkdir()
    jobs[identifier] = {"directory": directory, "created": now}
    return identifier, directory


@contextlib.asynccontextmanager
async def _job(app):
    if app[JOB_LOCK].locked():
        raise web.HTTPConflict(text="Another offline operation is active. Wait or stop it first.")
    async with app[JOB_LOCK]:
        identifier, directory = _new_job(app)
        try:
            yield identifier, directory
        except BaseException:
            app[JOBS].pop(identifier, None)
            shutil.rmtree(directory, ignore_errors=True)
            raise


async def _worker(app, function, *args, **kwargs):
    """Never remove worker files until cancellation has stopped its thread."""
    cancel_event = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(function, *args, cancel_event=cancel_event, **kwargs))
    app[WORKERS][task] = cancel_event
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel_event.set()
        with contextlib.suppress(Exception):
            await asyncio.shield(task)
        raise
    finally:
        app[WORKERS].pop(task, None)


async def _json_data(request):
    if request.content_type != "application/json":
        raise ValueError("Send settings as application/json.")
    body = bytearray()
    async for chunk in request.content.iter_chunked(8192):
        body.extend(chunk)
        if len(body) > 65536:
            raise ValueError("JSON settings are limited to 64 KiB.")
    try:
        return json.loads(body)
    except (RecursionError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid JSON settings.") from exc


def _result_links(result, identifier, directory):
    result = dict(result)
    result["job"] = identifier
    result["downloads"] = {path.name: f"/api/artifacts/{identifier}/{path.name}" for path in directory.iterdir() if path.is_file()}
    wav = result.get("wav")
    if wav:
        result["wav_url"] = f"/api/artifacts/{identifier}/{Path(wav).name}"
    return result


async def _roundtrip(request):
    from .demo import run_roundtrip
    data = await _json_data(request)
    mode, machine, key, settings, rx_frequency, rx_wpm = _options(data)
    text = _text(data.get("text", ""))
    scenario = data.get("scenario", "clean")
    if scenario not in ("clean", "noisy", "lost-block"):
        raise ValueError("Unknown demonstration scenario.")
    if scenario == "lost-block" and mode != "checked":
        raise ValueError("The lost-block recovery demonstration requires checked mode.")
    block_size = 16 if scenario == "lost-block" else 128
    async with _job(request.app) as (identifier, directory):
        result = await _worker(request.app, run_roundtrip, text, mode=mode, scenario=scenario, machine=machine, key=key, output_dir=directory, settings=settings, block_size=block_size, rx_frequency=rx_frequency, rx_wpm=rx_wpm, max_duration_s=MAX_SECONDS)
    return web.json_response(_result_links(result, identifier, directory))


def _decode_wav(path, data, *, cancel_event=None):
    audio, _, _, _ = _cores()
    mode, machine, key, settings, rx_frequency, rx_wpm = _options(data)
    symbols, plaintext = [], []
    codec = _stream_codec(mode, machine, key, receive=True)
    with wave.open(str(path), "rb") as source:
        rate, channels, width, frames = source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()
        if rate not in (44100, 48000) or channels not in (1, 2) or width != 2:
            raise ValueError("Upload a mono/stereo PCM16 WAV at 44100 or 48000 Hz.")
        duration = frames / rate
        if duration > MAX_SECONDS:
            raise ValueError("Uploaded audio exceeds ten minutes.")
        decoder = audio.MorseDecoder(sample_rate=rate, profile=mode, frequency=rx_frequency, wpm=rx_wpm)
        while raw := source.readframes(4096):
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("WAV decoding cancelled.")
            pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
            if channels == 2:
                pcm = pcm.reshape(-1, 2).mean(axis=1)
            received = decoder.feed(pcm)
            symbols.append(received)
            plaintext.append(received if codec is None else codec.feed(received).decode("ascii"))
        received = decoder.finish()
        symbols.append(received)
        plaintext.append(received if codec is None else codec.feed(received).decode("ascii"))
        if codec is not None:
            plaintext.append(codec.finish().decode("ascii"))
    errors = list(decoder.diagnostics) + list(getattr(codec, "errors", []))
    return {"mode": mode, "scenario": "upload", "input": "", "ciphertext": "", "received_symbols": "".join(symbols), "recovered": "".join(plaintext), "matched": None, "success": not errors, "errors": errors, "duration": duration, "wav": path.name}


async def _decode(request):
    async with _job(request.app) as (identifier, directory):
        path = directory / "uploaded.wav"
        data, seen_file, size = {}, False, 0
        reader = await request.multipart()
        while field := await reader.next():
            if field.name == "settings":
                raw = bytearray()
                while chunk := await field.read_chunk(8192):
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise ValueError("Settings are too large.")
                try:
                    data = json.loads(raw)
                except (RecursionError, UnicodeDecodeError) as exc:
                    raise ValueError("Invalid JSON settings.") from exc
            elif field.name == "audio" and not seen_file:
                seen_file = True
                with path.open("wb") as target:
                    while chunk := await field.read_chunk(65536):
                        size += len(chunk)
                        if size > MAX_UPLOAD:
                            raise web.HTTPRequestEntityTooLarge(max_size=MAX_UPLOAD, actual_size=size)
                        target.write(chunk)
            else:
                raise ValueError("Upload one audio file and one settings object.")
        if not seen_file:
            raise ValueError("A WAV file is required.")
        result = await _worker(request.app, _decode_wav, path, data)
    return web.json_response(_result_links(result, identifier, directory))


async def _artifact(request):
    job = request.app[JOBS].get(request.match_info["job"])
    name = request.match_info["name"]
    if not job or name not in {path.name for path in job["directory"].iterdir() if path.is_file()}:
        raise web.HTTPNotFound()
    return web.FileResponse(job["directory"] / name)


async def _live(request):
    audio, _, _, _ = _cores()
    session = request.query.get("session", "")
    try:
        uuid.UUID(session)
    except ValueError as exc:
        raise ValueError("A browser session UUID is required.") from exc
    if session in request.app[SESSIONS]:
        raise web.HTTPConflict(text="This browser session already has an active live operation.")
    ws = web.WebSocketResponse(max_msg_size=512000, heartbeat=15)
    # Reserve before await so simultaneous upgrade requests cannot both enter.
    request.app[SESSIONS][session] = ws
    producer = None
    watchdog = None
    started = time.monotonic()
    try:
        await ws.prepare(request)
        async def expire():
            await asyncio.sleep(MAX_SECONDS)
            if not ws.closed:
                await ws.send_json({"type": "error", "error": "Live session reached the ten-minute limit."})
                await ws.close()

        watchdog = asyncio.create_task(expire())
        first = await asyncio.wait_for(ws.receive_json(), 15)
        if not isinstance(first, dict):
            raise ValueError("Start settings must be an object.")
        if first.get("type") != "start" or first.get("operation") not in ("tx", "rx"):
            raise ValueError("Start with a tx or rx operation.")
        operation = first["operation"]
        mode, machine, key, settings, rx_frequency, rx_wpm = _options(first)
        rate = settings.sample_rate
        codec = _stream_codec(mode, machine, key, receive=operation == "rx")
        total_samples, total_text = 0, 0
        if operation == "rx":
            decoder = audio.MorseDecoder(sample_rate=rate, profile=mode, frequency=rx_frequency, wpm=rx_wpm)
            await ws.send_json({"type": "ready", "operation": "rx", "sample_rate": rate})
        else:
            initial = _text(first.get("text", ""))
            total_text = len(initial)
            streaming = bool(first.get("streaming", False))
            initial_symbols = initial.decode("ascii") if codec is None else codec.feed(initial)
            if codec is not None:
                initial_symbols += codec.flush() if streaming and mode == "checked" else ("" if streaming else codec.finish())
            duration = audio.estimate_duration(initial_symbols, settings, profile=mode)
            if duration > MAX_SECONDS:
                raise ValueError("Initial audio exceeds ten minutes; use the CLI.")
            await ws.send_json({"type": "ready", "operation": "tx", "duration": duration, "streaming": streaming, "symbols": initial_symbols})
            queue = asyncio.Queue(maxsize=32)
            credits = asyncio.Condition()
            pending = 0
            begin = asyncio.Event()
            ended = not streaming

            async def send_pcm(pcm):
                nonlocal pending, total_samples
                chunk = np.asarray(pcm, dtype="<f4")
                if not len(chunk):
                    return
                if len(chunk) > 2 * rate:
                    raise ValueError("Encoder chunk exceeds the two-second audio queue.")
                total_samples += len(chunk)
                if total_samples > MAX_SECONDS * rate:
                    raise ValueError("Live audio reached the ten-minute limit.")
                async with credits:
                    await asyncio.wait_for(credits.wait_for(lambda: pending + len(chunk) <= 2 * rate), 15)
                    pending += len(chunk)
                await ws.send_bytes(chunk.tobytes())

            async def transmit():
                try:
                    await asyncio.wait_for(begin.wait(), 120)
                    encoder = audio.MorseEncoder(settings, profile=mode)

                    async def emit(symbols):
                        if symbols:
                            await ws.send_json({"type": "symbols", "symbols": symbols})
                            for pcm in encoder.feed(symbols):
                                await send_pcm(pcm)

                    await emit(initial_symbols)
                    if streaming:
                        while True:
                            try:
                                text = await asyncio.wait_for(queue.get(), 5)
                            except asyncio.TimeoutError:
                                if codec is not None and mode == "checked":
                                    await emit(codec.flush())
                                if time.monotonic() - started > MAX_SECONDS:
                                    raise ValueError("Live session reached the ten-minute limit.")
                                continue
                            if text is None:
                                if codec is not None:
                                    await emit(codec.finish())
                                break
                            await emit(text.decode("ascii") if codec is None else codec.feed(text))
                    for pcm in encoder.finish():
                        await send_pcm(pcm)
                    await ws.send_json({"type": "draining"})
                    async with credits:
                        await asyncio.wait_for(credits.wait_for(lambda: pending == 0), 15)
                    await ws.send_json({"type": "complete", "success": True, "duration": total_samples / rate})
                    await ws.close()
                except (ValueError, asyncio.TimeoutError) as exc:
                    if not ws.closed:
                        await ws.send_json({"type": "error", "error": str(exc) or "Playback acknowledgements timed out."})
                        await ws.close()

            producer = asyncio.create_task(transmit())

        async for message in ws:
            if time.monotonic() - started > MAX_SECONDS:
                raise ValueError("Live session reached the ten-minute limit.")
            if message.type == WSMsgType.BINARY:
                if operation != "rx" or not message.data or len(message.data) % 4:
                    raise ValueError("Expected mono float32 microphone samples.")
                pcm = np.frombuffer(message.data, dtype="<f4")
                if len(pcm) > 2 * rate or not np.isfinite(pcm).all():
                    raise ValueError("Invalid PCM or microphone queue exceeds two seconds.")
                total_samples += len(pcm)
                if total_samples > MAX_SECONDS * rate:
                    raise ValueError("Microphone recording reached the ten-minute limit.")
                symbols = decoder.feed(pcm)
                recovered = symbols if codec is None else codec.feed(symbols).decode("ascii")
                await ws.send_json({"type": "received", "symbols": symbols, "recovered": recovered, "ack": len(pcm)})
            elif message.type == WSMsgType.TEXT:
                data = json.loads(message.data)
                if not isinstance(data, dict):
                    raise ValueError("Control messages must be objects.")
                kind = data.get("type")
                if kind == "stop":
                    break
                if operation == "tx":
                    if kind == "begin":
                        begin.set()
                    elif kind == "ack":
                        count = data.get("samples")
                        if type(count) is not int or count <= 0 or count > pending:
                            raise ValueError("Invalid playback acknowledgement.")
                        async with credits:
                            pending -= count
                            credits.notify_all()
                    elif kind == "text" and streaming and not ended:
                        text = _text(data.get("text"))
                        total_text += len(text)
                        if total_text > MAX_TEXT:
                            raise ValueError("Live text reached the 512-byte limit.")
                        try:
                            queue.put_nowait(text)
                        except asyncio.QueueFull as exc:
                            raise ValueError("Text queue is full; input was not discarded silently.") from exc
                    elif kind == "end" and streaming and not ended:
                        ended = True
                        try:
                            queue.put_nowait(None)
                        except asyncio.QueueFull as exc:
                            raise ValueError("Text queue is full; stop and retry.") from exc
                    else:
                        raise ValueError("Unexpected transmission control message.")
                elif kind == "discontinuity":
                    symbols = decoder.discontinuity("Browser microphone sample loss")
                    recovered = symbols if codec is None else codec.feed(symbols).decode("ascii")
                    await ws.send_json({"type": "received", "symbols": symbols, "recovered": recovered, "ack": 0})
                elif kind == "end":
                    symbols = decoder.finish()
                    recovered = symbols if codec is None else codec.feed(symbols).decode("ascii")
                    if codec is not None:
                        recovered += codec.finish().decode("ascii")
                    errors = list(decoder.diagnostics) + list(getattr(codec, "errors", []))
                    await ws.send_json({"type": "complete", "symbols": symbols, "recovered": recovered, "success": not errors, "errors": errors, "duration": total_samples / rate})
                    break
                else:
                    raise ValueError("Unexpected reception control message.")
            elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    except (ValueError, TypeError, KeyError, asyncio.TimeoutError) as exc:
        if ws.prepared and not ws.closed:
            await ws.send_json({"type": "error", "error": str(exc) or "Live operation timed out."})
    finally:
        if watchdog is not None:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
        if producer is not None:
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer
        request.app[SESSIONS].pop(session, None)
        if ws.prepared:
            await ws.close()
    return ws


async def _cleanup(app):
    workers = list(app[WORKERS].items())
    for _, event in workers:
        event.set()
    if workers:
        await asyncio.gather(*(task for task, _ in workers), return_exceptions=True)
    for socket in list(app[SESSIONS].values()):
        await socket.close(code=1001, message=b"Demo server stopping")
    shutil.rmtree(app[TEMP_ROOT], ignore_errors=True)


def create_app(*, port=None):
    """Create an application. A fixed port is enforced by the production launcher."""
    app = web.Application(middlewares=[_guard], client_max_size=MAX_UPLOAD + 65536)
    app[PORT] = port
    app[JOBS] = {}
    app[SESSIONS] = {}
    app[JOB_LOCK] = asyncio.Lock()
    app[TEMP_ROOT] = Path(tempfile.mkdtemp(prefix="encrypted-radio-demo-"))
    app[WORKERS] = {}
    app.router.add_get("/api/config", _config)
    app.router.add_post("/api/roundtrip", _roundtrip)
    app.router.add_post("/api/decode", _decode)
    app.router.add_get("/api/artifacts/{job}/{name}", _artifact)
    app.router.add_get("/api/live", _live)

    async def index(request):
        return web.FileResponse(STATIC / "index.html")

    app.router.add_get("/", index)
    app.router.add_static("/static", STATIC, show_index=False)
    app.on_cleanup.append(_cleanup)
    return app


def serve(host="127.0.0.1", port=8765):
    """Run a local demonstration server; remote binding is intentionally unsupported."""
    if host != "127.0.0.1":
        raise ValueError("The demo server must bind to 127.0.0.1.")
    web.run_app(create_app(port=port), host=host, port=port, access_log=None, handler_cancellation=True)
