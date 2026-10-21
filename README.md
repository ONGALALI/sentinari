# Sentinari

Sentinari is a local-first sovereign knowledge and research platform built around a private SQLite knowledge library, local search, and a strict constitutional firewall. The app is designed to remain operational without cloud inference, without remote API dependencies, and without silently routing work to external providers.

The project is intentionally split into two layers:

- Local runtime: the real app, the database, the gateway, the security policy, the dashboards, and the document knowledge layer
- GitHub: public project reference, docs, source code, and a safe showcase layer for interested parties

This division is part of the design. GitHub is not the live database, not the live runtime, and not the protected operational environment.

## What the app does

Sentinari indexes and serves a large local knowledge base from SQLite, including scientific and research material. The local gateway exposes endpoints for:

- health checks
- table inspection
- field discovery
- document search
- document lookup by ID
- chunk retrieval
- recent document summaries

The app is meant to be self-contained, readable, inspectable, and governed by a fail-closed local policy.

## Constitution as firewall

The project constitution is effectively the runtime firewall. It defines the rules by which the system behaves:

- local-first execution only
- fail closed on unknown or external providers
- deny or block remote AI routes by default
- keep the data layer local
- avoid cloud inference and remote telemetry by default
- require explicit governance before any external dependency can be introduced

In practical terms, the app is designed to reject Google, Gemini, Vertex, OpenAI, Microsoft, Copilot-style remote routes unless the architecture is intentionally expanded with a conscious security decision. The local gateway and provider policy are part of the enforcement layer.

## Architecture summary

- Local SQLite database: the knowledge source of truth
- Local gateway: FastAPI endpoints for health, search, documents, chunks, and recent activity
- Local dashboard: operational visibility into database state, tables, provider lock state, and search readiness
- GitHub repo: public codebase, documentation, and project reference; no private runtime data

## Local dashboard

The app includes a local dashboard that is intended to show:

- DB path and health
- table count
- provider policy status
- blocked external providers
- live search against the local library

This dashboard is local-only and should never be used as a public cloud deployment surface.

## Local quickstart

From the project root:

```powershell
python gateway_local.py
```

Then test the local API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/tables
Invoke-RestMethod "http://127.0.0.1:8000/api/search?query=climate"
```

Open the local dashboard in a browser:

```text
http://127.0.0.1:8000/dashboard
```

## Public GitHub usage

GitHub is used as a public-facing reference point for the project. It is not the operational deployment of the private runtime. Do not upload the local database, API keys, model credentials, or sensitive local configuration to the public repo.

## Design direction

The project is best understood as a sovereign local research and knowledge platform with a strict enforcement model and a transparent public-facing repo. The aim is not to become a cloud-hosted application by default. The aim is to remain under local control, governable, and secure.

## Repository overview

This repo contains the runtime, docs, and infrastructure for the local Sentinari system, including:

- gateway and local API
- knowledge database access
- local security and governance checks
- templates and dashboards
- constitution and design documentation
- experimental and training areas

## Ownership and intent

This project is a self-funded local-first architecture. The goal is to keep the real system private, operational, and controlled while using GitHub as a public, transparent layer for code and project presentation.
