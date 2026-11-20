import logging

import requests

logger = logging.getLogger(__name__)


def request_gpu_sleep(config) -> None:
    """Asks the GPU host to shut itself down via its shutdown-listener service, so it
    doesn't sit awake burning power until the next book needs it (it's woken again via
    WoL next time, same as any other use of the GPU backend). A no-op - and never
    raises - if GPU_SHUTDOWN_URL isn't configured; this is best-effort and never worth
    failing a conversion over."""
    if not config.gpu_shutdown_url:
        return
    try:
        resp = requests.post(
            config.gpu_shutdown_url,
            headers={"Authorization": f"Bearer {config.gpu_shutdown_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("asked GPU host at %s to power off", config.gpu_shutdown_url)
    except Exception:  # noqa: BLE001 - best-effort; the GPU host staying awake an extra cycle is harmless
        logger.exception("failed to ask GPU host to power off")
