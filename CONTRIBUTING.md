# Contributing

Thanks for your interest! This is a small project — contributions of any size
are welcome, from typo fixes to new detection logic.

## Getting started

1. Fork the repo and clone your fork.
2. Copy `.env.example` to `.env` and fill in:
   - `AISSTREAM_API_KEY` — free key from https://aisstream.io (required for live data)
   - `OLLAMA_HOST` — point at your Ollama instance (defaults to the Docker host)
3. Start the stack:

   ```bash
   docker compose up -d --build
   ```

   Dashboard: http://localhost:8090

   To run the built-in fake-fleet simulator instead of live AIS:
   `docker compose --profile sim up -d`

## Project layout

```
services/
  ais-ingest/    live AIS feed -> maritime_telemetry_stream (Redis)
  ml-engine/     FastAPI + Isolation Forest detection, WebSocket dashboard
  agent-worker/  anomaly stream -> Ollama LLM -> maritime_advisory_stream
  simulator/     fake-fleet fallback (compose profile: sim)
shared/          pydantic schemas
docs/            screenshots and assets
```

Redis streams: `maritime_telemetry_stream` -> `maritime_anomaly_stream` ->
`maritime_advisory_stream`. Vessel state lives in `vessel_state:*`,
tracks in `vessel_track:*`, trained models in `ml:model*`.

## Making changes

- Keep the event-driven boundaries: services talk through Redis streams, not
  direct calls (ML_ENGINE_URL is the exception for the dashboard API).
- Static files are baked into images at build time — rebuild after changing
  `server.py`, `index.html`, or `train.py`:
  `docker compose up -d --build ml-engine`
- Match existing style: plain Python, no framework ceremony, `PYTHONUNBUFFERED=1`
  for log visibility.
- Test end-to-end before opening a PR: vessel dots moving, alert fires on a
  forced anomaly, advisory appears in the Alerts panel.

## Pull requests

- One change per PR with a clear description of *why*, not just *what*.
- Update `README.md` / `.env.example` if you add config or change behavior.
- Don't commit `.env` or anything under `data/` (both git-ignored).
