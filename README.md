# Marine Traffic & Disruption Copilot

A production-grade, containerized spatial intelligence platform engineered for real-time maritime traffic tracking, automated anomaly detection, and AI-driven operational risk assessment across coastal British Columbia.

## Architecture & Tech Stack

* **Telemetry Ingestion:** High-throughput Redis streams capturing live vessel positioning and AIS data feeds.
* **Anomaly Detection:** Statistical and machine learning-driven anomaly scoring via scikit-learn's **Isolation Forest** to flag erratic vessel behavior or unexpected loitering.
* **Edge Intelligence Agent:** Self-hosted local **Qwen 2.5 (14B)** LLM instance generating contextualized operational advisories and narrative disruption briefs.
* **Real-Time Visualization:** Interactive **Leaflet.js** map dashboard streaming updates over **WebSockets** with variable simulation speeds.
* **Secure Edge Routing:** Zero-trust origin protection configured via a containerized **Cloudflare Tunnel**.

An event-driven, containerized AI system that watches **live maritime traffic** in the
Salish Sea (Olympia / Puget Sound through the Strait of Georgia), detects anomalous
vessel behavior with machine learning, and autonomously drafts port-operations
advisories with a local LLM — all streamed in real time to an interactive
nautical-chart dashboard.

Two AI layers, no human in the loop, no cloud: an **unsupervised anomaly model**
(Isolation Forest) scores every AIS position report against each vessel's own
behavioral baseline, and an **Ollama LLM agent** (Qwen 2.5) turns each detection
into a written operational advisory and safety broadcast.

---

## Business Value Proposition

Maritime supply chains face massive financial friction from unexpected navigational
delays, channel bottlenecks, and coordination lag between vessels, pilots, and port
authorities:

* **Eliminating Demurrage Costs:** real-time anomaly detection flags unplanned stops
  or fairway drift instantly, preventing cascading berth scheduling conflicts that
  cost thousands of dollars per hour.
* **Proactive Exception Handling:** shifting operations from reactive firefighting to
  autonomous event-driven triage via a local LLM agent that drafts immediate port
  advisories and safety broadcasts.
* **Data Sovereignty & Edge Privacy:** fully self-hosted architecture — vessel data
  never leaves local infrastructure.
* **You only look when it matters:** detection filters hundreds of vessels down to
  the handful that need a human, and the first draft of the response is already written.

---

## Dashboard Preview

![BC Maritime Copilot Dashboard](docs/dashboard-screenshot.png)

*A live anomaly: OCEAN GREG (power-driven vessel towing astern) dropped to 0.3 kn
against its own baseline in the Fraser River Fairway. The ML service flagged it and
the LLM agent drafted the advisory shown in the Alerts panel — click an alert to
fly to the vessel.*

![Tug anomaly with LLM advisory](docs/ocean-greg-alert.png)

![Closeup of generated advisory](docs/advisory-closeup.png)

> **Note:** ferries, tugs, pilot boats and other vessels that start and stop by
> design can be filtered from the map and alerts panel with the
> **HIDE FERRIES & WORKBOATS** toggle — detection still runs underneath.

---

---

## System Architecture

```mermaid
graph TD
    subgraph Ingestion
        AIS[aisstream.io live AIS] -->|WebSocket| ING[ais-ingest]
        ING -->|baseline speed, zone, ship type| B[(Redis telemetry stream)]
        SIM[AIS Simulator - optional] -.->|fallback feed| B
    end

    subgraph "Detection Layer (ml-engine)"
        B -->|read stream| C[Isolation Forest + rules]
        C -->|vessel_state, tracks| B
        C -->|anomaly events - deduplicated| E[(Redis anomaly stream)]
        C -->|WebSocket push| D[Nautical chart UI - Leaflet]
    end

    subgraph "Response Layer (agent-worker)"
        E -->|consume| F[Ollama Qwen 2.5, on-premise]
        F -->|port advisory + broadcast| G[(Redis advisory stream)]
        G -->|WebSocket| D
    end
```

### Services

| Service | Role |
|---|---|
| `ais-ingest` | Subscribes to aisstream.io, enriches each report with a per-vessel rolling speed baseline, zone label, ship type and IMO, writes to `maritime_telemetry_stream` |
| `ml-engine` | FastAPI + Isolation Forest detection, serves the dashboard/WebSocket, REST API, model training (`train.py`) |
| `agent-worker` | Consumes `maritime_anomaly_stream`, prompts the local LLM, publishes advisories to `maritime_advisory_stream` |
| `redis` | Streams, vessel state (`vessel_state:*`), tracks (`vessel_track:*`), model store (`ml:model*`) — persisted via `./data/redis` bind mount |
| `simulator` | Fake-fleet telemetry fallback (compose profile `sim`) |

## How Detection Works

Each position report is scored on three features:

1. **Speed deviation** — current speed vs. the vessel's own rolling-median baseline (~40 reports). Moored/anchored vessels (baseline < 2 kn) are exempt — sitting still is normal for them.
2. **Acceleration** — abrupt braking rate in knots/minute.
3. **Dead stop** — speed < 2 kn while the vessel's baseline is ≥ 5 kn.

Plus rule overlays:

- **Hazard statuses** (`Aground`, `Not under command`) flag immediately — the vessel is self-reporting an emergency.
- **Workboat exemption** — tugs, towing vessels, pilot boats, port tenders and fishing boats are exempt from *speed* anomalies (they stop and start by profession) but not hazard statuses.
- **Confirmation streak** — 5+ consecutive anomalous reports required, so routine approaches to a dock don't trip alerts.
- **Deduplication** — an event (and LLM call) fires only on the normal → anomaly transition per vessel.
- **Departure exemption** — a vessel that was recently stopped (< 2 kn in recent reports) with a low baseline and is now accelerating is a normal departure, not an anomaly. Without this, every vessel leaving a mooring falsely trips the detector.

### Edge cases handled

| Case | Handling |
|---|---|
| Moored/anchored vessels | Baseline < 2 kn exempts them — sitting still is normal |
| Vessel departing after being stopped | Recently-stopped + accelerating + low baseline → suppressed |
| Routine dock approaches | 5 consecutive anomalous reports required before alerting |
| Tugs/pilots/fishing workboats | Exempt from *speed* anomalies (stop-start is their job); hazard statuses still fire |
| AIS nav-status is stale/manual (e.g. "Anchored" while moving) | Speed is treated as truth; hazard statuses only fire on the two unambiguous emergencies |
| Vessel sails out of coverage / stops reporting | Dot expires after 5 min; open alert auto-resolves within ~30 s |
| Vessel state expires mid-alert then returns normal | Alert auto-resolves — no "stuck" ANOMALY card for a healthy ship |
| Speed jump vs slowdown | Alert text is direction-aware ("up to" / "down to"); overspeed events are detected but worded correctly |

### The model

An **Isolation Forest** — unsupervised anomaly detection, no labeled examples needed.
It builds hundreds of random decision trees that split the data on random features.
Anomalies are rare and different, so they get "isolated" in a few splits near the
top of a tree; normal points take many more splits. Averaging path length across
all trees yields each report's anomaly score — short path = weird.

For example, `[0.02, 0.1, 0]` (cruising at baseline) sits deep in every tree, while
`[-0.9, -12, 1]` (moving vessel that just stopped) separates almost immediately →
flagged. The model is direction-agnostic, so speed *jumps* above baseline are
flagged too. It retrains on real accumulated telemetry via `POST /api/retrain`
or the RETRAIN ANOMALY MODEL button. A global model covers all vessels; vessels with
≥50 stored track points also get **per-vessel models** (`ml:model:{mmsi}`) that learn
their individual behavior. A synthetic-data model is used as fallback until enough
real data exists.

## The Dashboard

- Nautical chart base (Esri Ocean + reference overlay), WebSocket live updates
- Color-coded markers: green = underway, gray = moored/anchored, pulsing red = anomaly, faint trails = recent paths
- **Alerts panel**: each anomaly is a card showing the vessel, what it did, and the LLM-drafted advisory when ready; click to fly to the vessel
- Click any vessel: popup + amber history trace (last ~200 reports, `/api/vessel/{id}/history`)
- Controls: SHOW ALL SHIPS, city zooms (Vancouver/Victoria/Nanaimo/Seattle), RETRAIN ANOMALY MODEL, CLEAR ALL SHIPS & HISTORY, HIDE FERRIES & WORKBOATS filter

## Running It

```bash
cp .env.example .env   # add your aisstream.io key + Ollama host
docker compose up -d --build
```

Dashboard: http://localhost:8090 (host port set by `ML_ENGINE_PORT`)

Requires an [aisstream.io](https://aisstream.io) API key (free) and a local
[Ollama](https://ollama.com) instance with `qwen2.5:14b` pulled. The built-in
simulator works without either: `docker compose --profile sim up -d`.

### API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI |
| `WS /ws` | Live vessel updates + events |
| `POST /api/retrain` | Retrain anomaly models on accumulated real data |
| `GET /api/vessel/{id}/history` | Vessel's stored position/speed track |
| `POST /api/clear` | Erase all vessel state, tracks and metadata |
| `POST /api/speed` | Simulation speed (sim profile only) |

## Project Layout

```
marine-traffic/
├── docker-compose.yaml
├── .env / .env.example
├── services/
│   ├── ais-ingest/
│   │   ├── Dockerfile
│   │   └── main.py          # aisstream.io -> maritime_telemetry_stream
│   ├── ml-engine/
│   │   ├── Dockerfile
│   │   ├── server.py        # FastAPI + anomaly detection + WebSocket
│   │   ├── train.py         # Isolation Forest trainer (global + per-vessel)
│   │   └── static/
│   │       └── index.html   # nautical-chart dashboard
│   ├── agent-worker/
│   │   ├── Dockerfile
│   │   └── worker.py        # anomaly stream -> Ollama -> advisory stream
│   └── simulator/
│       ├── Dockerfile
│       └── main.py          # fake-fleet fallback (profile: sim)
├── shared/
│   └── schemas.py           # pydantic telemetry models
├── tests/                   # pytest + fakeredis suite
├── data/redis/              # persisted Redis (bind mount)
└── docs/                    # screenshots
```
