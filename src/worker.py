import logging
import re
import tempfile
import time
from pathlib import Path

from audiobook import build_m4b, synthesize_chapter
from bookorbit_client import BookOrbitClient
from config import Config
from epub import parse_chapters
from kokoro_client import KokoroClient
from state import StateStore

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_POLL_SLEEP_SECONDS = 10
_READ_ALOUD_TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "cancelled"}


def _voice_for(tags: list[str], default_voice: str) -> str:
    for tag in tags:
        if tag.startswith("voice:"):
            return tag.split(":", 1)[1]
    return default_voice


def _epub_file_id(files: list[dict]) -> int | None:
    for f in files:
        if f.get("format", "").lower() in ("epub", "kepub"):
            return f["id"]
    return None


def _safe_filename(name: str) -> str:
    return _UNSAFE_FILENAME_CHARS.sub("_", name).strip() or "audiobook"


def _wait_for_audio_attached(book_id: int, client: BookOrbitClient, timeout_seconds: int) -> bool:
    """Book Dock import is async: the file we just wrote may take a while to be scanned
    and attached to the book. Poll the read-aloud capability check, which reports
    hasAudio once BookOrbit has joined our file to this book."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        capability = client.read_aloud_capability(book_id)
        if capability.get("hasAudio"):
            return True
        time.sleep(_POLL_SLEEP_SECONDS)
    return False


def _wait_for_job(job_id: str, client: BookOrbitClient, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = client.get_read_aloud_job(job_id)
        if job.get("status") == "awaiting_review" or job.get("status") in _READ_ALOUD_TERMINAL_STATUSES:
            return job
        time.sleep(_POLL_SLEEP_SECONDS)
    raise TimeoutError(f"read-aloud job {job_id} did not finish within {timeout_seconds}s")


def run_read_aloud(book_id: int, client: BookOrbitClient, config: Config) -> None:
    """Best-effort: the audiobook itself already succeeded by the time this runs, so a
    failure here is logged and swallowed rather than flipping the book to 'failed'."""
    if not _wait_for_audio_attached(book_id, client, config.book_dock_import_timeout_seconds):
        logger.warning("book %s: Book Dock never attached the new audio file, skipping read-aloud", book_id)
        return

    job = client.create_read_aloud_job(book_id)
    job_id = job["id"]
    logger.info("book %s: read-aloud job %s created", book_id, job_id)

    job = _wait_for_job(job_id, client, config.read_aloud_job_timeout_seconds)
    status = job.get("status")

    if status == "awaiting_review" and config.auto_publish_read_aloud:
        client.publish_read_aloud_job(job_id)
        logger.info("book %s: read-aloud job %s published automatically", book_id, job_id)
    elif status == "awaiting_review":
        logger.info("book %s: read-aloud job %s ready for review in the dashboard", book_id, job_id)
    elif status in ("completed", "completed_with_warnings"):
        logger.info("book %s: read-aloud job %s completed (%s)", book_id, job_id, status)
    else:
        logger.warning("book %s: read-aloud job %s ended with status %s", book_id, job_id, status)


def process_book(
    book: dict,
    client: BookOrbitClient,
    kokoro: KokoroClient,
    state: StateStore,
    config: Config,
) -> None:
    book_id = book["id"]
    title = book.get("title") or f"Book {book_id}"
    authors = book.get("authors") or []
    author = ", ".join(authors) if authors else "Unknown"

    logger.info("book %s (%s): starting conversion", book_id, title)
    client.bulk_update_tags([book_id], "remove", [config.trigger_tag])
    state.set_status(book_id, "processing")

    try:
        file_id = _epub_file_id(book.get("files") or [])
        if file_id is None:
            raise RuntimeError("no EPUB/KEPUB file found on this book")

        epub_bytes = client.download_file(file_id)
        chapters = parse_chapters(epub_bytes)
        if not chapters:
            raise RuntimeError("no narratable chapters found in EPUB")

        voice = _voice_for(book.get("tags") or [], config.default_voice)
        cover = client.get_cover(book_id)

        with tempfile.TemporaryDirectory() as work_dir_str:
            work_dir = Path(work_dir_str)
            rendered = [
                synthesize_chapter(ch, voice, kokoro, work_dir, i, config.max_chars_per_request)
                for i, ch in enumerate(chapters)
            ]

            output_name = _safe_filename(f"{title} - {author}") + ".m4b"
            output_path = Path(config.book_dock_path) / output_name
            build_m4b(rendered, title, author, cover, output_path)

        logger.info("book %s (%s): wrote %s", book_id, title, output_path)
        client.bulk_update_tags([book_id], "add", [config.ready_tag])
        state.set_status(book_id, "done")

        if config.generate_read_aloud:
            try:
                run_read_aloud(book_id, client, config)
            except Exception:  # noqa: BLE001 - the audiobook already succeeded; don't fail the book over this
                logger.exception("book %s (%s): read-aloud step failed", book_id, title)

    except Exception as exc:  # noqa: BLE001 - report and move on, never crash the poll loop
        logger.exception("book %s (%s): conversion failed", book_id, title)
        client.bulk_update_tags([book_id], "add", [config.failed_tag])
        state.set_status(book_id, "failed", error=str(exc))
