# ARES test guide

Run these checks from the repository root after configuring the backend environment and starting PostgreSQL.

## Backend

```sh
cd backend
python manage.py test supply_chain.tests
```

Django creates and removes an isolated PostgreSQL test database. The configured database role needs permission to create databases. The feed tests mock upstream responses, and notification tests mock the mail provider; the suite does not send real email or call GDACS.

The backend suite covers token login/expiry/logout, authentication and approver permissions, response-plan transitions, inventory validation, risk outcome auditing, notification recipient privacy and dispatch, action dry-run idempotency, safe API errors, and GDACS sync retry/idempotency. The digital-twin tests in `backend/supply_chain/tests/test_digital_twin.py` cover database-derived relationships, missing coordinates, point/polygon exposure, exact warehouse-to-shipment propagation, filtered graph pagination, coordinate validation, simulation isolation and warehouse matching, demand-history readiness, sync-feed status, and ordered change recovery.

## Frontend

```sh
cd frontend
pnpm test
pnpm build
```

The frontend tests cover API error formatting and visible-tab dashboard polling behavior. Polling pauses while the browser tab is hidden and refreshes immediately when the tab becomes visible again. `pnpm build` also compiles the digital-twin page; the current frontend suite does not render React components in a browser or DOM test environment.

## Not covered by the local MVP suite

Authenticated WebSocket event delivery is implemented with Redis and a 30-second polling fallback, but socket authentication, transaction ordering, and reconnect behavior do not yet have automated regression coverage. Docker/Podman is unavailable in the current development environment, so the local Compose stack and backup/restore workflow have not been run here. Real SMTP delivery, live webhook execution, off-host backups, and production monitoring require separately configured environments.
