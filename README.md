# BC Maritime & Port Operations Disruption Copilot

An event-driven, containerized enterprise AI architecture that simulates, analyzes, and autonomously responds to real-time maritime traffic disruptions in coastal British Columbia (Strait of Georgia and Fraser River corridor). 

The system couples unsupervised machine learning for high-frequency anomaly detection with a local Large Language Model (Ollama) agent, streamed in real time to an interactive Leaflet.js map via WebSockets, and exposed securely through a containerized Cloudflare Tunnel.

---

## Business Value Proposition

Maritime supply chains face massive financial friction from unexpected navigational delays, channel bottlenecks, and coordination lag between vessels, pilots, and port authorities:

*   **Eliminating Demurrage Costs:** Real-time anomaly detection flags unplanned stops or fairway drift instantly, preventing cascading berth scheduling conflicts that cost thousands of dollars per hour.
*   **Proactive Exception Handling:** Shifting operations from reactive firefighting to autonomous event-driven triage via local LLM agents that draft immediate port advisories and safety broadcasts.
*   **Data Sovereignty & Edge Privacy:** Fully self-hosted architecture operating securely within local infrastructure, avoiding third-party cloud data exposure.
*   **Satellite Bandwidth Optimization:** Event-driven WebSocket communication patterns minimize data overhead, mirroring real-world maritime network constraints.

---

## Dashboard Preview

![BC Maritime Copilot Dashboard](docs/dashboard-screenshot.png)

---

## System Architecture

```mermaid
graph TD
    subgraph Simulation Layer
        A[AIS Simulator] -->|Telemetry JSON| B[(Redis Streams)]
    end

    subgraph Intelligence & Web Layer
        B -->|Read Stream| C[ML Engine & FastAPI]
        C -->|WebSocket Push| D[Leaflet.js Map UI]
        C -->|Anomaly Event| E[(Redis Anomaly Stream)]
    end

    subgraph Generative Agent Layer
        E -->|Consumer Worker| F[Ollama Local LLM Qwen 2.5]
        F -->|Console / Webhook| G[Port Ops Advisory]
    end

    subgraph Edge Security
        H[Cloudflare Tunnel] -->|Secure Edge Route| C
    end
