# radio-feed-watch

Multi-source radio transcription, incident classification/geocoding, clip storage, and waypoint alerts for Home Assistant.

**City-agnostic core** — locale packs hold feeds, bbox, and vocabulary. Austin is the first example locale / public demo config, not hard-wired into the engine.

## Features (v0.1)

- Multi-source config (`broadcastify` **listen stream** via Basic auth by default; optional Calls API; `rtlsdr` stubbed for later)
- Pluggable STT: **local** `faster-whisper` (default) or **Deepgram** (optional)
- Clip storage with rolling retention + pin-to-keep + periodic purge
- Transcript filters: min length/confidence, noise-phrase drop, near-duplicate dedupe
- Optional gated LLM correction for short/low-confidence STT (OpenAI-compatible)
- Keyword incident-type classification + address extraction + Nominatim geocode
- Waypoint proximity alerts
- Optional MQTT publish for Home Assistant (`radio/{source_id}/transcript|incident|alert`)
- Dual-mode ops/demo dashboard (SSE + clip playback)
- Example HA YAML under [`ha/`](ha/)

## Quick start (local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# optional local STT:
pip install -e ".[local-stt]"
# optional Deepgram:
pip install -e ".[deepgram]"

cp .env.example .env          # BROADCASTIFY_USERNAME + PASSWORD (+ optional Deepgram/MQTT)
cp config.example.yaml config.yaml
cp config/locales/austin.example.yaml config/locales/austin.yaml
# point config.yaml locale: at your austin.yaml and set feed_id

# ffmpeg required for stream decode/VAD
# macOS: brew install ffmpeg

radio-feed-watch --check-config
radio-feed-watch -c config.yaml
```

Open the dashboard URL printed at startup (default `http://127.0.0.1:8080/`).

### Broadcastify auth

**Default (`mode: stream`):** only your Broadcastify username/password. Audio from `https://audio.broadcastify.com/{feed_id}.mp3` with HTTP Basic auth. No developer API approval.

**Optional (`mode: calls`):** Broadcastify Calls API (per-call MP3s). Needs an approved developer app + API keys. Most users should skip this.

## Docker

Requires Docker + Compose. Keep secrets on the host (`.env`, `config.yaml`, locale pack) — they are bind-mounted, not baked into the image.

```bash
cp .env.example .env
cp config.example.yaml config.yaml
# set dashboard.port: 8080 in config.yaml for the default compose mapping
docker compose up --build -d
```

Data (clips + SQLite) lives in `./data`. Logs: `docker compose logs -f`.

For local Whisper inside Docker, build with an extra step or extend the image (`pip install -e ".[local-stt]"`) — the default image includes Deepgram support only.

## Config sketch

```yaml
locale: config/locales/austin.example.yaml
stt:
  provider: local   # or deepgram
clips:
  retention_days: 7
  purge_interval_s: 3600
filters:
  min_text_chars: 3
  min_confidence: 0.25
  dedupe_window_s: 45
mqtt:
  enabled: false
waypoints: []
```

**Do not commit** `.env`, `config.yaml`, or non-example locale packs — they may contain credentials and home waypoints. See `.gitignore`.

## Architecture

```
Broadcastify / (later RTL-SDR)
        → VAD clips + STT
        → phonetic / short-ack / radio-code decode
        → optional LLM correct (gated: short / low-conf)
        → filters (length / confidence / dedupe)
        → classify / extract / geocode
        → waypoint check
        → MQTT + dashboard
```

## STT tuning (radio)

Scanner audio is narrowband and full of codes/proper nouns. Defaults lean radio-oriented:

| Provider | Default | Why |
|----------|---------|-----|
| Deepgram | `nova-2-phonecall` + `numerals` + keyword boost | Closest stock model to compressed radio; locale `stt_vocab` is boosted |
| Local Whisper | `small.en`, `beam_size: 5`, `condition_on_previous_text: false`, higher `no_speech_threshold` | Bigger model + no cross-clip hallucination; locale vocab goes into `initial_prompt` |

Add local street/agency names under `stt_vocab:` in your locale pack. For Deepgram Nova-3, set `stt.deepgram.model: nova-3` (uses `keyterm` instead of `keywords`).

Bad STT is still the main limit on geocoding — filters drop junk, but they cannot invent the right street name.

### Optional LLM correction

Set `llm_correct.enabled: true` and `OPENAI_API_KEY` in `.env`. Only short clips, low STT confidence, or few-word utterances are sent (see `max_duration_s` / `max_confidence` / `max_words`). The model must return structured JSON and meet `min_correct_confidence` before a change is applied. Short-ack heuristic remaps skip the LLM when `skip_if_short_ack: true` (default).

Works with any OpenAI-compatible `base_url` (OpenAI, Groq, OpenRouter, local vLLM, etc.).

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for upstream references (patterns only; this is an independent implementation).

## License

MIT
