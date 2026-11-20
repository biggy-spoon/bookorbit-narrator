import subprocess
import tempfile
from pathlib import Path


def convert_to_epub(file_bytes: bytes, source_format: str) -> bytes:
    """AZW3/MOBI already have proper chapter/TOC structure, same as EPUB - this just
    normalizes the container format via Calibre's ebook-convert so epub.py can parse
    them unchanged, rather than writing a second chapter-detection path."""
    with tempfile.TemporaryDirectory() as work_dir_str:
        work_dir = Path(work_dir_str)
        source_path = work_dir / f"source.{source_format}"
        output_path = work_dir / "converted.epub"
        source_path.write_bytes(file_bytes)

        result = subprocess.run(
            ["ebook-convert", str(source_path), str(output_path)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ebook-convert failed: {result.stderr}")

        return output_path.read_bytes()
