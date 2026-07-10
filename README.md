# radio-feed-watch

Multi-source radio transcription, incident classification/geocoding, clip storage, and waypoint alerts for Home Assistant.

**City-agnostic core** — locale packs hold feeds, bbox, and vocabulary. Austin is the first example locale / public demo config, not hard-wired into the engine.

## Features (v0.1 scaffold)

- Multi-source config (`broadcastify` **listen stream** via Basic auth by default; optional Calls API; `rtlsdr` stubbed for later)
- Pluggable STT: **local** `faster-whisper` (default) or **Deepgram** (optional)
- Clip storage with rolling retention + pin-to-keep
- Keyword incident-type classification + address extraction + Nominatim geocode
- Waypoint proximity alerts
- Optional MQTT publish for Home Assistant (`radio/{source_id}/transcript|incident|alert`)
- Example HA YAML under [`ha/`](ha/)

Dashboard (ops/demo) is served automatically when you run the service — open the URL printed at startup (default `http://0.0.0.0:8080/`, or whatever `dashboard.port` is in your config).

## Quick start

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

# ffmpeg required for stream decode/VAD
# macOS: brew install ffmpeg

radio-feed-watch --check-config
radio-feed-watch -c config.yaml
```

Locale packs live in [`config/locales/`](config/locales/). Start from `austin.example.yaml`.

### Broadcastify auth

**Default (`mode: stream`):** only your Broadcastify username/password. Audio from `https://audio.broadcastify.com/{feed_id}.mp3` with HTTP Basic auth. No developer API approval.

**Optional (`mode: calls`):** Broadcastify Calls API (per-call MP3s). Needs an approved developer app + API keys. Most users should skip this.

## Config sketch

```yaml
locale: config/locales/austin.example.yaml
stt:
  provider: local   # or deepgram
clips:
  retention_days: 7
mqtt:
  enabled: false
waypoints: []
```

## Architecture

```
Broadcastify / (later RTL-SDR)
        → clips + STT
        → classify / extract / geocode
        → waypoint check
        → MQTT + (soon) web dashboard
```

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for upstream references.

## License

MIT
