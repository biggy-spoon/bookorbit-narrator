import logging
import re
import tempfile
from pathlib import Path

from audiobook import build_m4b, synthesize_chapter
from bookorbit_client import BookOrbitClient
from config import Config
from epub import parse_chapters
from kokoro_client import KokoroClient
from state import StateStore

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


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


def process_book(
    book: dict,
    client: BookOrbitClient,
    kokoro: KokoroClient,
    state: StateStore,
    config: Config,
) -> None:
    book_id = book["bookId"]
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

    except Exception as exc:  # noqa: BLE001 - report and move on, never crash the poll loop
        logger.exception("book %s (%s): conversion failed", book_id, title)
        client.bulk_update_tags([book_id], "add", [config.failed_tag])
        state.set_status(book_id, "failed", error=str(exc))
