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
        book_dock_import_timeout_seconds=int(os.environ.get("BOOK_DOCK_IMPORT_TIMEOUT_SECONDS", "300")),
        read_aloud_job_timeout_seconds=int(os.environ.get("READ_ALOUD_JOB_TIMEOUT_SECONDS", "1800")),
    )
