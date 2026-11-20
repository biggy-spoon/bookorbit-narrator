"""The one place that lists every TTS provider this sidecar knows how to talk to.
Add a new provider by implementing tts_providers.TTSClient in its own module and
adding it here - TTS_PROVIDER in .env then just names the key."""

from kokoro_client import KokoroClient

TTS_PROVIDERS = {
    "kokoro": KokoroClient,
}
