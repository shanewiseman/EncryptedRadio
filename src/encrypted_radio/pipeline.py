"""Select shared cipher and audio implementations without coupling either wire format."""
from __future__ import annotations

from . import cipher, config, framing, seal
from .codec import DEFAULT_TEXT_ENCODING, normalize_text_encoding

CIPHERS = ("rotorcrypt", "sealcrypt")
TRANSPORTS = ("morselink", "audiolink")


def validate_selection(cipher_name="rotorcrypt", transport="morselink"):
    if cipher_name not in CIPHERS:
        raise ValueError("Choose rotorcrypt or sealcrypt.")
    if transport not in TRANSPORTS:
        raise ValueError("Choose morselink or audiolink.")


def demo_key(cipher_name, machine, value=None):
    """Demo-only defaults: public rotor settings or a fresh ephemeral seal key."""
    validate_selection(cipher_name)
    if cipher_name == "sealcrypt":
        return seal.SealKey.from_dict(value) if value is not None else seal.generate_key()
    return config.Key.from_dict(value, machine) if value is not None else config.load_key(machine=machine)


def resolve_text_encoding(mode, text_encoding=None):
    """Keep ordinary text normalization separate from the default cipher codec."""
    if mode not in ("checked", "raw", "text"):
        raise ValueError("Choose checked, raw, or text mode.")
    if text_encoding is None:
        return "uppercase-first" if mode == "text" else DEFAULT_TEXT_ENCODING
    encoding = normalize_text_encoding(text_encoding)
    if mode == "text" and encoding != "uppercase-first":
        raise ValueError("Lowercase-first encoding requires raw or checked encryption; text mode is unencrypted.")
    return encoding


def stream_codec(mode, machine, key, *, cipher_name="rotorcrypt", receive=False, block_size=128,
                 text_encoding=None):
    validate_selection(cipher_name)
    text_encoding = resolve_text_encoding(mode, text_encoding)
    if mode == "text":
        return None
    if cipher_name == "sealcrypt":
        return (seal.SealDecoder(machine, key, mode=mode, text_encoding=text_encoding) if receive else
                seal.SealEncoder(machine, key, mode=mode, block_size=block_size, text_encoding=text_encoding))
    if mode == "checked":
        return (framing.CheckedDecoder(machine, key, text_encoding=text_encoding) if receive else
                framing.CheckedEncoder(machine, key, block_size=block_size, text_encoding=text_encoding))
    return (cipher.RawDecoder(machine, key, text_encoding=text_encoding) if receive else
            cipher.RawEncoder(machine, key, text_encoding=text_encoding))


def encrypt(data, machine, key, *, cipher_name="rotorcrypt", mode="checked", block_size=128,
            text_encoding=None):
    codec = stream_codec(mode, machine, key, cipher_name=cipher_name, block_size=block_size,
                         text_encoding=text_encoding)
    return data.decode("ascii") if codec is None else codec.feed(data) + codec.finish()


def decrypt(text, machine, key, *, cipher_name="rotorcrypt", mode="checked", text_encoding=None):
    codec = stream_codec(mode, machine, key, cipher_name=cipher_name, receive=True,
                         text_encoding=text_encoding)
    if codec is None:
        return cipher.DecodeResult(text.encode("ascii"), [], True)
    try:
        plaintext = codec.feed(text) + codec.finish()
    except ValueError as exc:
        return cipher.DecodeResult(b"", [str(exc)], False)
    return cipher.DecodeResult(plaintext, list(getattr(codec, "errors", [])), getattr(codec, "complete", True))


def transport_module(transport):
    validate_selection(transport=transport)
    if transport == "audiolink":
        from . import packet_audio
        return packet_audio
    from . import audio
    return audio


def audio_settings(transport="morselink", *, sample_rate=48000, frequency=700, wpm=20):
    module = transport_module(transport)
    if transport == "audiolink":
        return module.AFSKSettings(sample_rate=sample_rate)
    return module.AudioSettings(sample_rate=sample_rate, frequency=frequency, wpm=wpm)


def audio_encoder(transport, settings, profile):
    module = transport_module(transport)
    cls = module.AFSKEncoder if transport == "audiolink" else module.MorseEncoder
    return cls(settings, profile=profile)


def audio_decoder(transport, rate, profile, frequency=None, wpm=None):
    module = transport_module(transport)
    if transport == "audiolink":
        return module.AFSKDecoder(sample_rate=rate, profile=profile)
    return module.MorseDecoder(sample_rate=rate, profile=profile, frequency=frequency, wpm=wpm)
