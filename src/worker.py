import logging
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from audiobook import build_m4b, synthesize_chapter
from bookorbit_client import BookOrbitClient
from config import Config
from ebook_convert import convert_to_epub
from epub import parse_chapters
from tts_providers import resolve_tts_client
from state import StateStore

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_READ_ALOUD_TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "cancelled"}


def _voice_for(tags: list[str], default_voice: str) -> str:
    for tag in tags:
        if tag.startswith("voice:"):
            return tag.split(":", 1)[1]
    return default_voice


_CONVERTIBLE_FORMATS = ("azw3", "mobi")


def _narratable_file(files: list[dict]) -> tuple[int, str] | None:
    """Prefers EPUB/KEPUB (no conversion needed) over AZW3/MOBI if a book somehow has
    both. Returns (file_id, format)."""
    by_format = {f.get("format", "").lower(): f["id"] for f in files}
    for fmt in ("epub", "kepub", *_CONVERTIBLE_FORMATS):
        if fmt in by_format:
            return by_format[fmt], fmt
    return None


def _safe_filename(name: str) -> str:
    return _UNSAFE_FILENAME_CHARS.sub("_", name).strip() or "audiobook"


def _seconds_since(started_at: str) -> float:
    started = datetime.fromisoformat(started_at)
    return (datetime.now(timezone.utc) - started).total_seconds()


def advance_read_aloud(
    book_id: int,
    job_id: str,
    started_at: str,
    client: BookOrbitClient,
    config: Config,
    state: StateStore,
) -> None:
    """One non-blocking check per poll cycle, for one book's read-aloud alignment job -
    BookOrbit's own forced-alignment step takes a while, so this checks in once per
    cycle rather than blocking the main poll loop on it."""
    try:
        job = client.get_read_aloud_job(job_id)
        status = job.get("status")
        if status == "awaiting_review" or status in _READ_ALOUD_TERMINAL_STATUSES:
            if status == "awaiting_review" and config.auto_publish_read_aloud:
                client.publish_read_aloud_job(job_id)
                logger.info("book %s: read-aloud job %s published automatically", book_id, job_id)
            elif status == "awaiting_review":
                logger.info("book %s: read-aloud job %s ready for review in the dashboard", book_id, job_id)
            elif status in ("completed", "completed_with_warnings"):
                logger.info("book %s: read-aloud job %s completed (%s)", book_id, job_id, status)
            else:
                logger.warning("book %s: read-aloud job %s ended with status %s", book_id, job_id, status)
            state.clear_read_aloud_tracking(book_id)
            return
        if _seconds_since(started_at) > config.read_aloud_job_timeout_seconds:
            logger.warning(
                "book %s: read-aloud job %s did not finish within %ss, giving up on tracking it "
                "(it may still finish on its own - check the dashboard)",
                book_id, job_id, config.read_aloud_job_timeout_seconds,
            )
            state.clear_read_aloud_tracking(book_id)
    except Exception:  # noqa: BLE001 - this book's audiobook already succeeded; never crash the poll loop over it
        logger.exception("book %s: read-aloud tracking check failed", book_id)


def process_book(
    book: dict,
    client: BookOrbitClient,
    state: StateStore,
    config: Config,
) -> bool:
    """Returns whether the GPU backend was used for this book, so the poll loop
    can decide whether the GPU host needs to be put back to sleep afterward."""
    book_id = book["id"]
    title = book.get("title") or f"Book {book_id}"
    authors = book.get("authors") or []
    author = ", ".join(authors) if authors else "Unknown"

    logger.info("book %s (%s): starting conversion", book_id, title)
    client.bulk_update_tags([book_id], "remove", [config.trigger_tag])
    state.set_status(book_id, "processing")
    kokoro, used_gpu = resolve_tts_client(config)

    try:
        found = _narratable_file(book.get("files") or [])
        if found is None:
            raise RuntimeError("no EPUB/KEPUB/AZW3/MOBI file found on this book")
        file_id, file_format = found

        source_bytes = client.download_file(file_id)
        if file_format in _CONVERTIBLE_FORMATS:
            logger.info("book %s (%s): converting %s to EPUB", book_id, title, file_format)
            epub_bytes = convert_to_epub(source_bytes, file_format)
        else:
            epub_bytes = source_bytes
        chapters = parse_chapters(epub_bytes)
        if not chapters:
            raise RuntimeError("no narratable chapters found in EPUB")
        total_chars = sum(len(ch.text) for ch in chapters)
        logger.info(
            "book %s (%s): %d chapters, %d characters to narrate",
            book_id, title, len(chapters), total_chars,
        )

        voice = _voice_for(book.get("tags") or [], config.default_voice)
        cover = client.get_cover(book_id)

        with tempfile.TemporaryDirectory() as work_dir_str:
            work_dir = Path(work_dir_str)
            rendered = []
            for i, ch in enumerate(chapters, start=1):
                started = time.monotonic()
                rendered.append(
                    synthesize_chapter(ch, voice, kokoro, work_dir, i, config.max_chars_per_request)
                )
                logger.info(
                    "book %s (%s): chapter %d/%d '%s' narrated in %.0fs",
                    book_id, title, i, len(chapters), ch.title, time.monotonic() - started,
                )

            output_name = _safe_filename(f"{title} - {author}") + ".m4b"
            output_path = work_dir / output_name
            build_m4b(rendered, title, author, cover, output_path)

            client.upload_book_file(book_id, output_name, output_path.read_bytes())

        logger.info("book %s (%s): uploaded %s directly to the book", book_id, title, output_name)
        client.bulk_update_tags([book_id], "add", [config.ready_tag])
        state.set_status(book_id, "done")

        if config.generate_read_aloud:
            job = client.create_read_aloud_job(book_id)
            state.track_read_aloud_job(book_id, job["id"])
            logger.info("book %s: read-aloud job %s created", book_id, job["id"])

        return used_gpu

    except Exception as exc:  # noqa: BLE001 - report and move on, never crash the poll loop
        logger.exception("book %s (%s): conversion failed", book_id, title)
        client.bulk_update_tags([book_id], "add", [config.failed_tag])
        state.set_status(book_id, "failed", error=str(exc))
        return used_gpu
