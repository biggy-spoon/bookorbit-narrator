FROM python:3.12-slim

# calibre is only needed for its `ebook-convert` CLI, to turn AZW3/MOBI into EPUB
# before narration (they already have proper chapter/TOC structure, same as EPUB -
# this just normalizes the container format so src/epub.py can parse them unchanged).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg calibre \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENV STATE_DB_PATH=/data/state.db
VOLUME ["/data"]

CMD ["python", "-u", "src/main.py"]
