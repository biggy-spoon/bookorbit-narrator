import re

import requests

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
