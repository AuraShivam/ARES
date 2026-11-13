# Repository structure

ARES keeps the web application, operational tooling, and project documentation in separate top-level areas. This guide explains those boundaries and gives contributors a safe place to put future work.

## Top-level areas

| Path | Responsibility |
| --- | --- |
| `backend/` | Django REST API, PostgreSQL models and migrations, external-feed integration, risk and forecasting logic, and workers. |
| `frontend/` | React + Vite dashboard, user workflows, shared browser-side API helpers, and frontend tests. |
| `docs/engineering/` | Architecture, implementation details, security, quality, and testing guidance. |
| `docs/product/` | User-facing feature behavior, data requirements, and workflow documentation. |
| `docs/operations/` | Local demonstration, deployment, backup, recovery, and project roadmap. |
| `docs/references/` | Historical project documents. Existing reference PDFs are tracked; new PDFs are ignored by default. |
| `ops/` | PostgreSQL backup and guarded restore scripts used by operators. |
| `compose.*.yaml` | Root-level Compose entry points for the local demo and hosted runtime example. |
| `.env.*.example` | Safe configuration templates. Real credentials belong in ignored local environment files or a deployment secret manager. |

## Backend layout

`backend/config/` contains Django project configuration and root routing. `backend/supply_chain/` is the Django domain app: models, API serializers and views, authentication, workflows, and integrations share its model registry and migration history.

Capabilities with substantial internal boundaries have their own packages:

- `supply_chain/agents/` contains agent contracts, providers, tools, and runtime orchestration.
- `supply_chain/digital_twin/` contains the graph, impact, recovery, and simulation logic.
- `supply_chain/management/commands/` contains supported operator and worker commands.
- `supply_chain/migrations/` contains the ordered database schema history.
- `supply_chain/tests/` contains backend tests.

Keep Django model ownership and migrations within the existing app unless a deliberate multi-app split is designed. Moving model modules casually can alter Django's model discovery and migration behavior.

## Frontend layout

`frontend/src/app/` owns the dashboard shell and app-level orchestration. `frontend/src/config/` holds navigation and display configuration. `frontend/src/features/` holds user-facing workflows grouped by capability. `frontend/src/lib/` is for shared API, error, formatting, and polling helpers. Keep feature-only UI and state within its feature folder; promote it to `lib/` only when multiple features use it.

## Runtime files at the repository root

Compose files stay at the root so existing documented commands, relative build contexts, and local demo setup remain direct. `backend/Dockerfile` and `frontend/Dockerfile` define how each app image is built; they are kept beside the source they package. Operational backup and restore scripts stay in `ops/` because they are not app runtime entry points.

Do not commit local `.env` files, database dumps, Python or JavaScript dependencies, generated frontend bundles, or the local `.local/archive/` legacy project. The root `.gitignore` covers these local artifacts.

## Placement checklist for new work

1. Put API and domain behavior in `backend/supply_chain/`; add a migration when a model schema changes.
2. Put screens and user workflows in the matching `frontend/src/features/<capability>/` folder.
3. Put setup, deployment, backup, and recovery instructions in `docs/operations/`; put feature and data explanations in `docs/product/`.
4. Put reusable technical design and test guidance in `docs/engineering/`.
5. Keep root Compose and environment-template paths stable unless every command, build context, and linked guide is updated together.
6. Never add credentials, local database files, generated bundles, or dependency directories to the repository.
