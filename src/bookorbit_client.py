from typing import Iterator

import requests

PAGE_SIZE = 200


class BookOrbitClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def iter_books(self) -> Iterator[dict]:
        """Yields every book's summary row (includes tags and files[]), paginated."""
        page = 0
        while True:
            resp = self.session.post(
                f"{self.base_url}/api/v1/books/query",
                json={"pagination": {"page": page, "size": PAGE_SIZE}},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("items", data.get("books", data if isinstance(data, list) else []))
            if not rows:
                return
            for row in rows:
                yield row
            if len(rows) < PAGE_SIZE:
                return
            page += 1

    def bulk_update_tags(self, book_ids: list[int], mode: str, tags: list[str]) -> None:
        resp = self.session.post(
            f"{self.base_url}/api/v1/books/bulk-update-tags",
            json={"bookIds": book_ids, "mode": mode, "tags": tags},
            timeout=30,
        )
        resp.raise_for_status()

    def download_file(self, file_id: int) -> bytes:
        resp = self.session.get(
            f"{self.base_url}/api/v1/books/files/{file_id}/download", timeout=120
        )
        resp.raise_for_status()
        return resp.content

    def upload_book_file(self, book_id: int, filename: str, file_bytes: bytes) -> dict:
        """Attaches a file directly to a specific, already-known book - bypassing Book
        Dock's folder-watch-and-match entirely, so there's no ambiguity about which
        book (or which of its duplicates) the file ends up on."""
        resp = self.session.post(
            f"{self.base_url}/api/v1/books/{book_id}/files",
            files={"file": (filename, file_bytes)},
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()

    def get_cover(self, book_id: int) -> bytes | None:
        resp = self.session.get(
            f"{self.base_url}/api/v1/books/{book_id}/cover", timeout=30
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    def read_aloud_capability(self, book_id: int) -> dict:
        resp = self.session.get(
            f"{self.base_url}/api/v1/books/{book_id}/read-aloud", timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def create_read_aloud_job(self, book_id: int) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/v1/books/{book_id}/read-aloud-jobs", json={}, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def get_read_aloud_job(self, job_id: str) -> dict:
        resp = self.session.get(
            f"{self.base_url}/api/v1/read-aloud-jobs/{job_id}", timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def publish_read_aloud_job(self, job_id: str) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/v1/read-aloud-jobs/{job_id}/publish", timeout=30
        )
        resp.raise_for_status()
        return resp.json()
