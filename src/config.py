import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bookorbit_url: str
    bookorbit_api_key: str
    kokoro_url: str
    default_voice: str
    trigger_tag: str
    ready_tag: str
    failed_tag: str
    poll_interval_seconds: int
    max_chars_per_request: int
    book_dock_path: str
    state_db_path: str
    generate_read_aloud: bool
    auto_publish_read_aloud: bool
    book_dock_import_timeout_seconds: int
    read_aloud_job_timeout_seconds: int
    gpu_kokoro_url: str | None
    gpu_wol_mac: str | None
    gpu_wol_broadcast_address: str
    gpu_wol_port: int
    gpu_wake_timeout_seconds: int
    gpu_wake_poll_interval_seconds: int
    gpu_shutdown_url: str | None
    gpu_shutdown_token: str | None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load() -> Config:
    required = ["BOOKORBIT_URL", "BOOKORBIT_API_KEY", "KOKORO_URL"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")

    return Config(
        bookorbit_url=os.environ["BOOKORBIT_URL"].rstrip("/"),
        bookorbit_api_key=os.environ["BOOKORBIT_API_KEY"],
        kokoro_url=os.environ["KOKORO_URL"].rstrip("/"),
        default_voice=os.environ.get("DEFAULT_VOICE", "af_heart"),
        trigger_tag=os.environ.get("TRIGGER_TAG", "convert-audio"),
        ready_tag=os.environ.get("READY_TAG", "audiobook-ready"),
        failed_tag=os.environ.get("FAILED_TAG", "audiobook-failed"),
        poll_interval_seconds=int(os.environ.get("POLL_INTERVAL_SECONDS", "60")),
        max_chars_per_request=int(os.environ.get("MAX_CHARS_PER_REQUEST", "1000")),
        book_dock_path=os.environ.get("BOOK_DOCK_PATH", "/book-dock"),
        state_db_path=os.environ.get("STATE_DB_PATH", "/data/state.db"),
        generate_read_aloud=_bool_env("GENERATE_READ_ALOUD", True),
        auto_publish_read_aloud=_bool_env("AUTO_PUBLISH_READ_ALOUD", False),
        book_dock_import_timeout_seconds=int(os.environ.get("BOOK_DOCK_IMPORT_TIMEOUT_SECONDS", "86400")),
        read_aloud_job_timeout_seconds=int(os.environ.get("READ_ALOUD_JOB_TIMEOUT_SECONDS", "1800")),
        gpu_kokoro_url=(os.environ.get("GPU_KOKORO_URL") or "").rstrip("/") or None,
        gpu_wol_mac=os.environ.get("GPU_WOL_MAC") or None,
        gpu_wol_broadcast_address=os.environ.get("GPU_WOL_BROADCAST_ADDRESS", "255.255.255.255"),
        gpu_wol_port=int(os.environ.get("GPU_WOL_PORT", "9")),
        gpu_wake_timeout_seconds=int(os.environ.get("GPU_WAKE_TIMEOUT_SECONDS", "120")),
        gpu_wake_poll_interval_seconds=int(os.environ.get("GPU_WAKE_POLL_INTERVAL_SECONDS", "5")),
        gpu_shutdown_url=(os.environ.get("GPU_SHUTDOWN_URL") or "").rstrip("/") or None,
        gpu_shutdown_token=os.environ.get("GPU_SHUTDOWN_TOKEN") or None,
    )
