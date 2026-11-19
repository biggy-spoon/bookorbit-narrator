# bookorbit-kokoro-audiobook

A sidecar service that turns [BookOrbit](https://github.com/bookorbit/bookorbit) ebooks into narrated
`.m4b` audiobooks using [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI), triggered entirely by
tagging a book in the BookOrbit dashboard. Built in response to
[bookorbit/bookorbit#1019](https://github.com/bookorbit/bookorbit/issues/1019) — since that's an
unassigned feature request with no BookOrbit source access, this does the same job as an external sidecar
instead of a core-app PR.

## How it works

1. Tag a book `convert-audio` in BookOrbit.
2. This service polls BookOrbit's API, finds the tag, downloads the book's EPUB, splits it into chapters,
   and sends each chapter to your Kokoro-FastAPI instance for narration.
3. The chapters are muxed into a single `.m4b` with embedded chapter markers and the book's cover, and
   dropped into BookOrbit's Book Dock folder.
4. BookOrbit's own Book Dock import picks it up and attaches it to the existing book (not a duplicate).
5. The book is re-tagged `audiobook-ready` (or `audiobook-failed`, with the error visible in this
   service's logs and local state, if something went wrong — re-add `convert-audio` to retry).
6. If `GENERATE_READ_ALOUD=true` (the default), this service then also kicks off BookOrbit's own native
   "Generate read-aloud books" job on that book — a sentence-level forced-alignment step (local model, no
   external AI provider) between the new audio and the ebook text, which is what powers synced
   text-highlighting and seamless reading↔listening in BookOrbit's reader. That job stops at
   `awaiting_review` and waits for you to check the alignment report and click Publish in the dashboard,
   by BookOrbit's own design — set `AUTO_PUBLISH_READ_ALOUD=true` if you'd rather it publish itself.

## Requirements

- A running BookOrbit instance (tested against v3.9.0).
- A running Kokoro-FastAPI instance (CPU or GPU image — see its own repo for setup), reachable from this
  container.
- Docker + Compose.

## Setup

1. In BookOrbit, go to **Settings → API Keys** and create a key with:
   - Access level: **write** (bulk tag updates need this; it's not a read-only key)
   - Permissions: **Library Download**, **Library Edit Metadata**, and **Generate read-aloud books**
     (the last one is only needed if `GENERATE_READ_ALOUD=true`, the default; it implies Upload)
   - Admin: off — nothing this service does needs it
   - Optionally scope the key to just the library/libraries you'll tag books in, for least privilege

   Copy the key — it's only shown once.
2. Copy `.env.example` to `.env` and fill in `BOOKORBIT_API_KEY`, and adjust `BOOKORBIT_URL` / `KOKORO_URL`
   to match your setup.
3. Edit `docker-compose.yml`'s volume mount so the second path (`/DATA/AppData/bookorbit/...`) points at
   **your** BookOrbit's actual Book Dock folder on the host — this must be the same folder BookOrbit's own
   Book Dock watcher is watching, shared as a bind mount into both containers.
4. `docker compose up -d --build`.
5. Tag a book `convert-audio` in BookOrbit and watch this service's logs
   (`docker compose logs -f`).

## Configuration

See `.env.example` for every setting (tag names, poll interval, default voice, TTS chunk size). Pick a
voice per book by tagging it `voice:<id>` (list available voices with
`curl $KOKORO_URL/audio/voices`) — otherwise `DEFAULT_VOICE` is used.

## Known limitations

- No "seamless switch between reading and listening at the same spot" sync — chapter-level audiobooks
  only. That's a much harder alignment problem than converting the text; a reasonable follow-up, not a v1
  feature.
- Chapter detection relies on the EPUB's own spine order and skips documents under ~200 characters of text
  (covers, title pages, nav) — unusually structured EPUBs may need tuning in `src/epub.py`.
- One book is converted at a time; a long book can take a while depending on your Kokoro instance's
  throughput (CPU vs GPU).

## License

MIT
