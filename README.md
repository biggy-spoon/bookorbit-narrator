# bookorbit-narrator

A sidecar service that turns [BookOrbit](https://github.com/bookorbit/bookorbit) ebooks into narrated
`.m4b` audiobooks using a pluggable TTS backend - [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)
by default, with a provider abstraction (`TTS_PROVIDER` in `.env.example`) for swapping in a different,
more natural-sounding model later - triggered entirely by tagging a book in the BookOrbit dashboard.
Inspired by two BookOrbit feature requests -
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
3. The chapters are muxed into a single `.m4b` with embedded chapter markers and the book's cover, then
   uploaded directly to that exact book via BookOrbit's own file-upload API - no shared folder, no
   watch-and-match step, so there's no ambiguity about which book (or library) it lands in. It's always the
   same book you tagged, in the same library, every time.
4. The book is re-tagged `audiobook-ready` (or `audiobook-failed`, with the error visible in this
   service's logs and local state, if something went wrong — re-add `convert-audio` to retry).
5. If `GENERATE_READ_ALOUD=true` (the default), this service immediately kicks off BookOrbit's own native
   "Generate read-aloud books" job - a sentence-level forced-alignment step (local model, no external AI
   provider) between the new audio and the ebook text, which is what powers synced text-highlighting and
   seamless reading↔listening in BookOrbit's reader. That job takes a while to run, so this service checks
   in on it once per poll cycle rather than blocking. It stops at `awaiting_review` and waits for you to
   check the alignment report and click Publish in the dashboard, by BookOrbit's own design — set
   `AUTO_PUBLISH_READ_ALOUD=true` if you'd rather it publish itself.

   **This needs BookOrbit's own read-aloud worker deployed separately** - a different container from
   anything in this repo, part of BookOrbit itself. Without it, step 5 above does nothing (BookOrbit
   reports `workerConfigured: false` and our job-creation call is simply never eligible) - the audiobook
   from steps 1-4 still works fine either way. See BookOrbit's own
   [docs/READ_ALOUD.md](https://github.com/bookorbit/bookorbit/blob/main/docs/READ_ALOUD.md) for deploying
   it; in short, set `COMPOSE_PROFILES=read-aloud` plus a shared `READ_ALOUD_WORKER_TOKEN` in BookOrbit's
   own `.env` and bring its stack back up - the worker service is already defined in BookOrbit's
   `docker-compose.yml`, just gated behind that profile.

## Requirements

- A running BookOrbit instance (tested against v3.9.0).
- A running Kokoro-FastAPI instance (CPU or GPU image — see its own repo for setup), reachable from this
  container.
- Docker + Compose.

## Setup

1. In BookOrbit, go to **Settings → API Keys** and create a key with:
   - Access level: **write** (bulk tag updates need this; it's not a read-only key)
   - Permissions: **Library Download**, **Library Edit Metadata**, **Library Upload**, and (only if
     `GENERATE_READ_ALOUD=true`, the default) **Generate read-aloud books**
   - Admin: off — nothing this service does needs it
   - Optionally scope the key to just the library/libraries you'll tag books in, for least privilege

   Copy the key — it's only shown once.
2. Copy `.env.example` to `.env` and fill in `BOOKORBIT_API_KEY`, and adjust `BOOKORBIT_URL` / `KOKORO_URL`
   to match your setup.
3. `docker compose up -d --build`.
4. Tag a book `convert-audio` in BookOrbit and watch this service's logs
   (`docker compose logs -f`).

## Configuration

See `.env.example` for every setting (tag names, poll interval, default voice, TTS chunk size). Pick a
voice per book by tagging it `voice:<id>` (list available voices with
`curl $KOKORO_URL/audio/voices`) — otherwise `DEFAULT_VOICE` is used.

### Swapping the TTS backend

`TTS_PROVIDER` picks which backend to talk to (`src/tts_registry.py` has the full list). Kokoro is the
only one implemented today, but it's a deliberate seam: everything that actually calls the TTS backend
(`src/audiobook.py`, the GPU wake/sleep logic in `src/tts_providers.py`) is written against the
`TTSClient` interface, not against Kokoro's API specifically. Adding a different, larger model later -
once you have real GPU compute, which is also what makes a bigger model practical for book-length
narration in the first place - means implementing `TTSClient` in a new file and adding one line to
`TTS_PROVIDERS`, not restructuring the pipeline.

## Known limitations

- This project itself only produces chapter-level audio — it doesn't implement sentence/paragraph
  alignment on its own, and that's not a planned feature here. The seamless "switch between reading and
  listening at the same spot" experience instead comes from chaining into BookOrbit's own native
  read-aloud alignment worker (see "How it works" above), which is a real, working part of the default
  setup, not aspirational — confirmed end to end against a real conversion. If you set
  `GENERATE_READ_ALOUD=false` or don't deploy BookOrbit's read-aloud worker, you get chapter-level
  audiobooks only, with no sentence-level sync.
- Chapter detection relies on the EPUB's own spine order and skips documents under ~200 characters of text
  (covers, title pages, nav) — unusually structured EPUBs may need tuning in `src/epub.py`.
- One book is converted at a time. On CPU, a full novel realistically takes **1.5-2.5 hours** depending on
  your server's CPU — this is the supported, reliable path today.

## Optional: GPU offload

The code for this (`GPU_KOKORO_URL`, `GPU_WOL_MAC`, and friends in `.env.example`) is fully optional - a
no-op for everyone unless you set `GPU_KOKORO_URL`, so it costs nothing to leave in place. The idea: point
it at a second, GPU-equipped Kokoro-FastAPI instance (optionally woken via Wake-on-LAN, and optionally put
back to sleep when idle - see below) and the sidecar uses it instead of your CPU instance when reachable,
falling back to CPU automatically otherwise.

**Status: proven working end-to-end on a native Linux GPU host** - roughly 5-7x faster than CPU on a
real novel-length book (25 minutes vs. ~2.25 hours for comparably-sized books on an RTX 2080 Super).
**Not reliable on Windows + WSL2 + Docker Desktop** - we tried extensively (disabling PCIe ASPM, updating
the NVIDIA driver, capping the GPU's power limit) and each change delayed but never eliminated a hard host
crash under sustained inference, always with zero diagnostic evidence (no bugcheck, no crash dump).

The actual fix, once we moved to bare-metal Linux: **cap the GPU's power limit below its rated TDP**
(`sudo nvidia-smi -pl 180` for a 250W-rated card survived a full book with zero crashes, where the
uncapped default didn't). The crash reproduced identically on both Windows+WSL2 and bare-metal Linux with
PCIe ASPM disabled, which pointed away from virtualization/OS and toward a power-delivery issue (PSU,
cable, or the card's own power circuitry) under the bursty, spiky load TTS inference produces - lowering
the power limit is a cheap, non-destructive fix regardless of which component was actually marginal.

**The power limit does not survive a reboot** - it silently resets to the card's default on every fresh
boot (persistence mode, `nvidia-smi -pm 1`, doesn't help here; that only keeps settings across driver
reloads within a boot, not across a power cycle), which reintroduces the exact crash this is meant to fix
the next time the host restarts for any reason. `deploy/gpu-power-cap.service` reapplies it on every boot -
install it with:

```
sudo cp deploy/gpu-power-cap.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-power-cap.service
```

(edit the `-pl` value in that file to whatever's appropriate for your card).

If you want Wake-on-LAN to actually work, two things that are easy to miss:
- **The GPU host's motherboard firmware needs its own "wake on LAN" setting enabled** (often called
  something like "PCIE Devices Power On" under ACPI/Power Management in BIOS/UEFI setup) - the OS-level
  `ethtool -s <iface> wol g` setting alone does nothing if the firmware itself isn't listening for a magic
  packet while fully powered off.
- **This container needs `network_mode: host`** (already set in `docker-compose.yml`) - a WoL magic packet
  is a broadcast UDP packet, and Docker's default bridge network won't let it escape to the real LAN.
  Without host networking, the sidecar's own wake attempts silently fail and it falls back to CPU every
  time, even though a manual magic packet sent from the host itself works fine.

### Optional: put the GPU host to sleep when idle

If `GPU_SHUTDOWN_URL` is set, once the GPU backend was used and the tagged-book queue is empty, this
service asks the GPU host to power off instead of sitting awake idle until the next book - it's woken
again via WoL next time, same as always. See `deploy/gpu-shutdown-listener/` for the small service to run
on the GPU host itself, and its README for setup.

## License

MIT
