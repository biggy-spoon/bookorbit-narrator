import logging
import time

import config as config_module
from bookorbit_client import BookOrbitClient
from gpu_sleep import request_gpu_sleep
from state import StateStore
from worker import advance_read_aloud, process_book

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def run_once(client: BookOrbitClient, state: StateStore, cfg) -> None:
    used_gpu_this_cycle = False
    queued_books = [b for b in client.iter_books() if cfg.trigger_tag in (b.get("tags") or [])]
    for book in queued_books:
        if state.get_status(book["id"]) == "processing":
            # A previous run died mid-conversion without updating state; let it retry.
            logger.warning("book %s stuck in 'processing' from a prior run, retrying", book["id"])
        if process_book(book, client, state, cfg):
            used_gpu_this_cycle = True

    # Books with a read-aloud job still in progress - checked once per cycle, never
    # blocking the loop above.
    for book_id, job_id, started_at in state.pending_read_aloud():
        advance_read_aloud(book_id, job_id, started_at, client, cfg, state)

    # The GPU host was used this cycle and the queue it was working through is now
    # empty - no point keeping it awake until the next book shows up, it's woken via
    # WoL again whenever one does.
    if used_gpu_this_cycle and queued_books:
        remaining = [b for b in client.iter_books() if cfg.trigger_tag in (b.get("tags") or [])]
        if not remaining:
            request_gpu_sleep(cfg)


def main() -> None:
    cfg = config_module.load()
    client = BookOrbitClient(cfg.bookorbit_url, cfg.bookorbit_api_key)
    state = StateStore(cfg.state_db_path)

    logger.info(
        "watching %s for tag '%s' every %ss",
        cfg.bookorbit_url, cfg.trigger_tag, cfg.poll_interval_seconds,
    )
    while True:
        try:
            run_once(client, state, cfg)
        except Exception:  # noqa: BLE001 - keep the poll loop alive across transient errors
            logger.exception("poll cycle failed")
        time.sleep(cfg.poll_interval_seconds)


if __name__ == "__main__":
    main()
