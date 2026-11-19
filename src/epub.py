import tempfile
from dataclasses import dataclass

from bs4 import BeautifulSoup
from ebooklib import epub

MIN_CHAPTER_CHARS = 200


@dataclass
class Chapter:
    title: str
    text: str


def _extract_text(html_bytes: bytes) -> str:
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _guess_title(soup_text_source: bytes, index: int) -> str:
    soup = BeautifulSoup(soup_text_source, "html.parser")
    for level in ("h1", "h2", "h3", "title"):
        tag = soup.find(level)
        if tag and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return f"Chapter {index}"


def parse_chapters(epub_bytes: bytes) -> list[Chapter]:
    """Walks the EPUB spine in reading order, skipping near-empty documents
    (covers, title pages, nav) that aren't real narration content."""
    with tempfile.NamedTemporaryFile(suffix=".epub") as tmp:
        tmp.write(epub_bytes)
        tmp.flush()
        book = epub.read_epub(tmp.name)

        chapters: list[Chapter] = []
        chapter_num = 0
        for item_id, _linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item is None:
                continue
            content = item.get_content()
            text = _extract_text(content)
            if len(text) < MIN_CHAPTER_CHARS:
                continue
            chapter_num += 1
            chapters.append(Chapter(title=_guess_title(content, chapter_num), text=text))
        return chapters
