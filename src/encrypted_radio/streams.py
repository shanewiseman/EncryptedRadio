"""Shared Linux pipe reads for both cipher command-line adapters."""
from __future__ import annotations

import os
import select
from typing import BinaryIO, Iterator


def iter_chunks(stream: BinaryIO, idle_seconds: float | None = None) -> Iterator[bytes | None]:
    """Yield available bytes, or None after an idle interval; never wait to fill a chunk."""
    descriptor = stream.fileno()
    while True:
        ready, _, _ = select.select([descriptor], [], [], idle_seconds)
        if not ready:
            yield None
            continue
        data = os.read(descriptor, 4096)
        if not data:
            return
        yield data
