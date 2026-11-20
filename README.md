# bookorbit-kokoro-audiobook

A sidecar service that turns [BookOrbit](https://github.com/bookorbit/bookorbit) ebooks into narrated
`.m4b` audiobooks using [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI), triggered entirely by
tagging a book in the BookOrbit dashboard. Inspired by two BookOrbit feature requests -
[#1019](https://github.com/bookorbit/bookorbit/issues/1019) (chapter-level EPUB → audiobook conversion)
and [#1589](https://github.com/bookorbit/bookorbit/issues/1589) (generating TTS audio ahead of time
instead of live during reading) - both great ideas, both unassigned feature requests with no BookOrbit
source access available to build against, so this does the same job as an external sidecar instead of a
core-app PR. It also chains into BookOrbit's own native read-aloud alignment once the audiobook lands,
which gets most of the way to what #1589 is after: audio that's already generated and aligned by the time
you want to listen, not produced live.

## How it works

1. Tag a book `convert-audio` in BookOrbit.
2. This service polls BookOrbit's API, finds the tag, downloads the book's EPUB, splits it into chapters,
   and sends each chapter to your Kokoro-FastAPI instance for narration.
3. The chapters are muxed into a single `.m4b` with embedded chapter markers and the book's cover, and
   dropped into BookOrbit's Book Dock folder.
4. BookOrbit's own Book Dock import picks it up and attaches it to the existing book (not a duplicate).
5. The book is re-tagged `audiobook-ready` (or `audiobook-failed`, with the error visible in this
   service's logs and local state, if something went wrong — re-add `convert-audio` to retry).
6. If `GENERATE_READ_ALOUD=true` (the default), this service then watches for BookOrbit's Book Dock to
   actually attach the new file to the book - which in our own testing took anywhere from a few seconds to
   **several hours**, so this is a non-blocking check on every poll cycle, never a long wait that would
   stall other books. Once attached, it kicks off BookOrbit's own native "Generate read-aloud books" job -
   a sentence-level forced-alignment step (local model, no external AI provider) between the new audio and
   the ebook text, which is what powers synced text-highlighting and seamless reading↔listening in
   BookOrbit's reader. That job stops at `awaiting_review` and waits for you to check the alignment report
   and click Publish in the dashboard, by BookOrbit's own design — set `AUTO_PUBLISH_READ_ALOUD=true` if
   you'd rather it publish itself.

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
- One book is converted at a time. On CPU, a full novel realistically takes **1.5-2.5 hours** depending on
  your server's CPU — this is the supported, reliable path today.

## Future feature: GPU offload (experimental, not recommended yet)

The code for this already exists (`GPU_KOKORO_URL`, `GPU_WOL_MAC`, and friends in `.env.example`) and is
fully optional - it's a no-op for everyone unless you set `GPU_KOKORO_URL`, so it costs nothing to leave in
place. The idea: point it at a second, GPU-equipped Kokoro-FastAPI instance (optionally woken via
Wake-on-LAN) and the sidecar uses it instead of your CPU instance when reachable, falling back to CPU
automatically otherwise.

**Status: works great on a native Linux GPU host. Not yet reliable on Windows + WSL2 + Docker Desktop**,
which is the common "spare gaming PC" setup. We tried this extensively - disabling PCIe ASPM (genuinely
fixed one real, confirmed failure mode), updating the NVIDIA driver, and capping the GPU's power limit.
Each change meaningfully *delayed* the crash (from ~2-3 minutes of sustained inference to 20+ minutes and
68%+ through a real conversion), but a real multi-chapter book eventually crashed the Windows host every
time we tried it end to end, across five attempts with every mitigation in place - always the same
signature (no bugcheck, no driver fault event, no crash dump - a true unexplained hard hang characteristic
of a GPU-PV virtualization bug, not something a config change on our end can fully resolve).

If you want to pick this up: a native Linux GPU host (no virtualization layer between the container and
the driver) should sidestep this entirely and is the path we'd actually recommend if you have one available.
If you're on Windows and want to help debug the deeper issue, the `nvidia-smi`-polling + `docker logs`
technique we used to characterize the failures (see the commit history) is the place to start - we ran out
of configuration-level ideas, not patience.

## License

MIT
