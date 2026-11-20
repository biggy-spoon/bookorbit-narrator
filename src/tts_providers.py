"""The provider abstraction: which TTS engine/API shape to talk to, picked once via
TTS_PROVIDER in .env. Kokoro is the only one implemented today, but the GPU
wake/poll/fallback logic below is written against this interface, not against
Kokoro specifically, so adding a second provider (e.g. a larger, more natural-sounding
model once real GPU compute is available) means: implement TTSClient in a new file,
register it in TTS_PROVIDERS, done - no changes needed here or in worker.py."""

import abc
import logging
import time

import requests

from wol import send_magic_packet

logger = logging.getLogger(__name__)


class TTSClient(abc.ABC):
    """What audiobook.py actually needs from a TTS backend. health_path is the cheap
    endpoint used to check whether a (possibly sleeping) host has woken up yet."""

    health_path: str = "/"

    def __init__(self, base_url: str):
        self.base_url = base_url

    @abc.abstractmethod
    def synthesize(self, text: str, voice: str, response_format: str = "mp3") -> bytes:
        ...


def _is_reachable(provider_cls: type[TTSClient], base_url: str) -> bool:
    try:
        resp = requests.get(f"{base_url}{provider_cls.health_path}", timeout=5)
        return resp.ok
    except requests.RequestException:
        return False


def resolve_tts_client(config) -> tuple[TTSClient, bool]:
    """Picks the GPU backend for this book if one is configured and reachable
    (waking it via WoL first if a MAC is set), otherwise falls back to the default
    (CPU) backend. A no-op - returns the default client immediately - when
    GPU_KOKORO_URL isn't configured, so this is fully opt-in. The second return value
    says whether the GPU backend was actually picked, so callers can decide whether
    the GPU host needs to be put back to sleep later."""
    from tts_registry import TTS_PROVIDERS

    provider_cls = TTS_PROVIDERS[config.tts_provider]
    default = provider_cls(config.kokoro_url)
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
        if _is_reachable(provider_cls, config.gpu_kokoro_url):
            logger.info("GPU %s host at %s is reachable, using it for this book", config.tts_provider, config.gpu_kokoro_url)
            return provider_cls(config.gpu_kokoro_url), True
        time.sleep(config.gpu_wake_poll_interval_seconds)

    logger.warning(
        "GPU %s host at %s did not become reachable within %ss, falling back to %s",
        config.tts_provider, config.gpu_kokoro_url, config.gpu_wake_timeout_seconds, config.kokoro_url,
    )
    return default, False
