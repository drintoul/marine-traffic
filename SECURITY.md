# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

This project runs a local, self-hosted stack (Redis, FastAPI, Ollama) and ingests
public AIS data. If you discover a security issue — especially anything exposing
the Redis instance, dashboard, or API to untrusted networks — please report it
privately rather than opening a public issue.

- **Preferred:** use GitHub's private vulnerability reporting ("Report a vulnerability"
  under the Security tab), or
- **Email:** drintoul@gmail.com

Please include steps to reproduce, the affected service (ais-ingest, ml-engine,
agent-worker, redis), and any relevant logs. You can expect an acknowledgement
within a few days.

## Notes for Operators

- Never commit `.env` — it contains your aisstream.io API key. `.env.example`
  documents the required variables without secrets.
- Redis is bound to a host port by default; restrict it to localhost
  (`127.0.0.1:${REDIS_PORT}:6379`) if the host is multi-user or shared.
- The dashboard has no authentication — treat the exposed port accordingly.
