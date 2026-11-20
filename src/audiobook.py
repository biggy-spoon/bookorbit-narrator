import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mutagen.mp3 import MP3

from epub import Chapter
from kokoro_client import chunk_text
from tts_providers import TTSClient


@dataclass
class RenderedChapter:
    title: str
    path: Path
    duration_seconds: float


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{result.stderr}")


def synthesize_chapter(
    chapter: Chapter, voice: str, kokoro: TTSClient, work_dir: Path, index: int, max_chars: int
) -> RenderedChapter:
    chunks = chunk_text(chapter.text, max_chars)
    chunk_paths: list[Path] = []
    for i, chunk in enumerate(chunks):
        audio = kokoro.synthesize(chunk, voice=voice)
        chunk_path = work_dir / f"ch{index:03d}_part{i:03d}.mp3"
        chunk_path.write_bytes(audio)
        chunk_paths.append(chunk_path)

    chapter_path = work_dir / f"ch{index:03d}.mp3"
    if len(chunk_paths) == 1:
        chunk_paths[0].rename(chapter_path)
    else:
        _concat_mp3(chunk_paths, chapter_path, work_dir)
        for p in chunk_paths:
            p.unlink(missing_ok=True)

    duration = MP3(chapter_path).info.length
    return RenderedChapter(title=chapter.title, path=chapter_path, duration_seconds=duration)


def _concat_mp3(parts: list[Path], output: Path, work_dir: Path) -> None:
    list_file = work_dir / f"{output.stem}_list.txt"
    list_file.write_text("".join(f"file '{p}'\n" for p in parts))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)])
    list_file.unlink(missing_ok=True)


def _ffmetadata_chapters(chapters: list[RenderedChapter]) -> str:
    lines = [";FFMETADATA1"]
    start_ms = 0
    for chapter in chapters:
        end_ms = start_ms + int(chapter.duration_seconds * 1000)
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={start_ms}")
        lines.append(f"END={end_ms}")
        lines.append(f"title={chapter.title}")
        start_ms = end_ms
    return "\n".join(lines) + "\n"


def build_m4b(
    chapters: list[RenderedChapter],
    title: str,
    author: str,
    cover_bytes: bytes | None,
    output_path: Path,
) -> None:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        combined = tmp / "combined.mp3"
        _concat_mp3([c.path for c in chapters], combined, tmp)

        metadata_file = tmp / "chapters.txt"
        metadata_file.write_text(_ffmetadata_chapters(chapters))

        cmd = [
            "ffmpeg", "-y",
            "-i", str(combined),
            "-i", str(metadata_file),
        ]
        if cover_bytes:
            cover_path = tmp / "cover.jpg"
            cover_path.write_bytes(cover_bytes)
            cmd += ["-i", str(cover_path), "-map", "0:a", "-map", "2:v",
                    "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        else:
            cmd += ["-map", "0:a"]
        cmd += [
            "-map_metadata", "1",
            "-metadata", f"title={title}",
            "-metadata", f"artist={author}",
            "-c:a", "aac", "-b:a", "64k",
            "-movflags", "+faststart",
            "-f", "mp4", str(output_path),
        ]
        _run(cmd)
