# ARES test guide

Run these checks from the repository root after configuring the backend environment and starting PostgreSQL.

## Backend

```sh
cd backend
python manage.py test supply_chain.tests
```

Django creates and removes an isolated PostgreSQL test database. The configured database role needs permission to create databases. The feed tests mock upstream responses, and notification tests mock the mail provider; the suite does not send real email or call GDACS.

The backend suite covers token login/expiry/logout, authentication and approver permissions, response-plan transitions, inventory validation, risk outcome auditing, notification recipient privacy and dispatch, action dry-run idempotency, safe API errors, and GDACS sync retry/idempotency. Agent tests cover disabled-provider status, secret non-disclosure, read-only tool registration and role allowlists, idempotent provider execution, bounded specialist coordination, and failure-stage recording using fake providers. These tests do not call a live AI provider. The digital-twin tests in `backend/supply_chain/tests/test_digital_twin.py` cover database-derived relationships, missing coordinates, point/polygon exposure, exact warehouse-to-shipment propagation, filtered graph pagination, coordinate validation, simulation isolation and warehouse matching, demand-history readiness, sync-feed status, and ordered change recovery.

## Frontend

```sh
cd frontend
pnpm test
pnpm build
```

The frontend tests cover API error formatting and visible-tab dashboard polling behavior. Polling pauses while the browser tab is hidden and refreshes immediately when the tab becomes visible again. `pnpm build` also compiles the digital-twin page; the current frontend suite does not render React components in a browser or DOM test environment.

## Not covered by the local MVP suite

Authenticated WebSocket event delivery is implemented with Redis and a 30-second polling fallback, but socket authentication, transaction ordering, and reconnect behavior do not yet have automated regression coverage. Live GDACS availability, a live AI provider, SMTP delivery, webhook execution, off-host backups, and production monitoring require separately configured environments. The Compose walkthrough is documented separately; passing unit/API tests alone does not prove the end-to-end Docker stack or external integrations work in a particular environment.
