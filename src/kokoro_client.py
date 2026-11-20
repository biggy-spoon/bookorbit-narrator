import logging
import re
import time

import requests

from wol import send_magic_packet

logger = logging.getLogger(__name__)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Splits on sentence boundaries, packing sentences up to max_chars per chunk.
    A single sentence longer than max_chars is hard-split as a last resort."""
    sentences = [s for s in _SENTENCE_BOUNDARY.split(text.strip()) if s]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i : i + max_chars])
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class KokoroClient:
    def __init__(self, base_url: str, model: str = "kokoro"):
        self.base_url = base_url
        self.model = model

    def synthesize(self, text: str, voice: str, response_format: str = "mp3") -> bytes:
        resp = requests.post(
            f"{self.base_url}/audio/speech",
            json={
                "model": self.model,
                "input": text,
                "voice": voice,
                "response_format": response_format,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content


def _is_reachable(base_url: str) -> bool:
    try:
        resp = requests.get(f"{base_url}/audio/voices", timeout=5)
        return resp.ok
    except requests.RequestException:
        return False


def resolve_kokoro_client(config) -> tuple[KokoroClient, bool]:
    """Picks the GPU backend for this book if one is configured and reachable
    (waking it via WoL first if a MAC is set), otherwise falls back to the
    default (CPU) backend. A no-op - returns the default client immediately -
    when GPU_KOKORO_URL isn't configured, so this is fully opt-in. The second
    return value says whether the GPU backend was actually picked, so callers
    can decide whether the GPU host needs to be put back to sleep later."""
    default = KokoroClient(config.kokoro_url)
    if not config.gpu_kokoro_url:
        return default, False

    if config.gpu_wol_mac:
        try:
            send_magic_packet(config.gpu_wol_mac, config.gpu_wol_broadcast_address, config.gpu_wol_port)
            logger.info("sent WoL packet for GPU host to %s:%d", config.gpu_wol_broadcast_address, config.gpu_wol_port)
        except Exception:  # noqa: BLE001 - WoL is best-effort; the reachability poll below is authoritative
            logger.exception("failed to send WoL packet, will still try polling the GPU host")

    deadline = time.monotonic() + config.gpu_wake_timeout_seconds
    while time.monotonic() < deadline:
        if _is_reachable(config.gpu_kokoro_url):
            logger.info("GPU Kokoro host at %s is reachable, using it for this book", config.gpu_kokoro_url)
            return KokoroClient(config.gpu_kokoro_url), True
        time.sleep(config.gpu_wake_poll_interval_seconds)

    logger.warning(
        "GPU Kokoro host at %s did not become reachable within %ss, falling back to %s",
        config.gpu_kokoro_url, config.gpu_wake_timeout_seconds, config.kokoro_url,
    )
    return default, False
