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

## Optional: offload to a second, faster machine (e.g. a GPU box)

Kokoro-82M is small enough to run on CPU, but it's genuinely slow that way - expect well over an hour for
a full-length novel on a typical server CPU. If you have a second machine with a GPU that's normally
asleep, set `GPU_KOKORO_URL` (and optionally `GPU_WOL_MAC` for Wake-on-LAN) in `.env` and run a second
Kokoro-FastAPI instance there. The sidecar will try that machine first for each book, wake it if configured
to, and transparently fall back to your regular `KOKORO_URL` if it doesn't answer in time - so this is
purely a speed optimization, never a dependency. See `.env.example` for the full variable list and an
important caveat about *how* a Wake-on-LAN packet actually has to reach the sleeping machine on your
specific network (same LAN, a router that forwards it, etc.) - that part is unavoidably your own network's
setup, not something this project can do for you.

### Troubleshooting: Windows GPU host crashes/hangs a few seconds after inference

If your GPU backend runs on Windows via Docker Desktop + WSL2 (the common setup for a spare gaming PC),
and the whole machine hangs or silently reboots **not during inference, but a handful of seconds after a
burst of GPU activity ends**, this is very likely **PCIe ASPM (Active State Power Management)**. A few
seconds of GPU idle is exactly the kind of gap that triggers the OS/motherboard to drop the GPU's PCIe
link into a low-power link state (L1/L1 substates); that transition, combined with WSL2's virtualized GPU
compute path (GPU-PV) still holding the device open, hit a real crash/hang for us twice in a row under a
sustained synthetic load test, and holding `nvidia-smi`-level utilization/temperature/power logging through
the exact failure window confirmed the timing: healthy load, healthy idle, then dead ~19 seconds into idle,
every time - not during the load itself.

Disabling ASPM for the PCIe subsystem fixed it for us (survived the identical test twice after the change,
having failed twice before it, with nothing else different). On the Windows GPU host, as Administrator:

```powershell
powercfg /setacvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ASPM 0
powercfg /setdcvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ASPM 0
powercfg /setactive SCHEME_CURRENT
```

No reboot needed. If you hit intermittent Windows GPU-host crashes with this setup and the timing looks
similar (fine during inference, dies a few seconds after it stops), try this before suspecting the GPU
driver, thermals, or power supply - in our case none of those showed any corroborating evidence (no driver
fault events, no crash dump, temperatures stayed well within normal range), which is itself a symptom of an
ASPM-class issue: it typically leaves no trace in Windows's own crash reporting.

**Update: this fix was real but not complete for us.** It survived two rounds of synthetic stress testing
(~40 back-to-back requests, ~40 seconds of continuous load each time) that had reliably crashed the host
before the change. But a real audiobook conversion - which, depending on how your EPUB is structured, can
mean *hundreds* of back-to-back requests over several continuous minutes for a single large chapter -
crashed the same host again afterward, in the same way. Our working theory now is that WSL2's GPU-PV
virtualized compute path may simply not be stable for *sustained, multi-minute* compute sessions on this
hardware/driver combination, independent of the ASPM issue, which was real but apparently not the only
problem. We don't have a confirmed fix for that deeper issue yet. If you hit this, treat GPU offload on a
Windows+WSL2 host as viable for short bursts but not yet trustworthy for long sustained jobs, and consider
a native Linux GPU host instead if one is available to you - this project's `GPU_KOKORO_URL` works with any
OpenAI-compatible Kokoro instance, Windows or not.

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
