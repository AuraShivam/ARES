# ARES deployment and operations

The primary Phase 8 demo target is localhost. The repository also includes a provider-neutral production Compose package for a future hosted deployment. No cloud account, domain, database, or secret is provisioned by this repository.

## Run the local demonstration

Install Docker Desktop (including Compose) on the demo machine, then from the repository root:

```sh
umask 077
cp .env.demo.example .env.demo
chmod 600 .env.demo
docker compose --env-file .env.demo -f compose.demo.yaml up --build -d
docker compose --env-file .env.demo -f compose.demo.yaml ps
docker compose --env-file .env.demo -f compose.demo.yaml logs --tail=100 api gdacs-worker backup-worker web
```

Open [http://localhost:8080](http://localhost:8080). The first startup builds the React bundle and Django image, starts isolated PostgreSQL and Redis containers, applies migrations, and then starts the API, dashboard, and GDACS poller. PostgreSQL and Redis are on a private Compose network and are not published to the host; the web port binds only to `127.0.0.1`. Django debug mode and the demo credentials in `.env.demo.example` are intentionally local-only; use them only for this loopback demo.

Create an administrator interactively:

```sh
docker compose --env-file .env.demo -f compose.demo.yaml exec api python manage.py createsuperuser
```

To add realistic sample records after creating the admin account, run `docker compose --env-file .env.demo -f compose.demo.yaml exec api python manage.py seed_demo`.

Then sign in, check the overview and supply-chain records, and review the GDACS feed status. The first backup worker cycle creates a PostgreSQL archive in a local named volume; allow up to 10 minutes for its health check. Email and external action execution remain disabled. To stop the demo while preserving its database and backup volumes, run `docker compose --env-file .env.demo -f compose.demo.yaml down`. **Do not use `down -v` unless you intend to erase the local demo database and backups.**

GitHub is appropriate for the repository, collaboration, and build automation. GitHub Pages serves static files and cannot run the Django API, background workers, or PostgreSQL needed for a live ARES demo. A static UI preview there would not be a working application.

## Runtime layout

- `web` serves the built React dashboard through Caddy, obtains/renews TLS certificates, adds browser security headers, and proxies API, Django Admin, and static-file requests to the API service.
- `api` runs Django REST Framework and the ASGI WebSocket endpoint under Daphne. Its readiness check calls `/api/health/`, which returns unhealthy when PostgreSQL is unavailable.
- Authenticated WebSocket invalidation events carry only resource/action metadata and publish after database commit. The browser reloads current data through the authenticated API. Redis carries event groups across API and worker processes; the existing 30-second dashboard polling remains as a fallback.
- `migrate` applies Django migrations before the API and workers start.
- `gdacs-worker` continuously polls GDACS using the configured interval.
- `notification-worker` is opt-in under the `notifications` Compose profile. It exits without modifying queued notifications while email delivery is disabled.
- `backup-worker` uses PostgreSQL's custom archive format, validates each dump, rotates local copies, and reports unhealthy when no recent dump exists.
- In production, PostgreSQL and Redis are external managed/private services. The local demo includes both as isolated Compose services.

## Provision before deployment

1. Choose a host/provider, a DNS name, a managed PostgreSQL service, and a private Redis service in a compatible network region. Restrict both services to the application host, use a dedicated least-privilege ARES database role, and require TLS for hosted PostgreSQL and Redis. Enable provider PostgreSQL backup/PITR options where available.
2. Point the DNS name at the host. Permit inbound TCP 80 and 443 (and UDP 443 for HTTP/3 if desired). Caddy needs outbound access to its certificate authority and the app host needs outbound HTTPS for GDACS.
3. Obtain PostgreSQL host, database, username, password, port, TLS mode, and any required CA certificate from the provider. Do not put credentials in source control or paste them into chat.
4. Create the deployment secret file on the host from `.env.production.example`. Set permissions before editing and enter values through a trusted secret manager or local editor:

   ```sh
   umask 077
   cp .env.production.example .env.production
   chmod 600 .env.production
   ```

   Set a fresh `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, the exact domain in `ARES_DOMAIN` and `DJANGO_ALLOWED_HOSTS`, and exact HTTPS origins in `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`. Keep the configured proxy SSL header enabled when Caddy is the only trusted proxy. The Compose API health check sends the matching forwarded-protocol header for this internal readiness check. Keep optional email and external action execution disabled until each is configured and verified.
5. Set `ARES_REDIS_URL` to the provider's private `rediss://` endpoint and ensure the API and workers can reach it. URL-encode special characters in credentials. If PostgreSQL requires a private CA, copy `compose.production.ca.example.yaml` to the ignored `compose.production.ca.yaml`, place the provider CA at `secrets/postgres-ca.crt`, set `POSTGRES_SSLROOTCERT=/run/secrets/postgres-ca`, and add `-f compose.production.ca.yaml` to the Compose commands below. Use the TLS mode and CA chain required by the provider. Do not disable certificate verification to work around a trust error.

The Compose command uses `.env.production` both for variable substitution and for backend environment injection. The file is ignored by Git. Avoid printing rendered Compose configuration because it can contain credentials.

## Deploy and smoke-check

Run on the configured deployment host from the repository root:

```sh
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml up --build -d
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml logs --tail=100 api gdacs-worker backup-worker web
```

The first `up` runs the migration service before API and workers start. Confirm required services are healthy, check `https://<ARES_DOMAIN>/api/health/` returns success, load the dashboard, sign in, and exercise a read-only workflow. Create the first administrator interactively:

```sh
docker compose --env-file .env.production -f compose.production.yaml exec api python manage.py createsuperuser
```

Confirm that `/api/feeds/status/` reports successful recent feed checks for an authenticated operator. Check the initial backup archive exists and its timestamp is current. Do not enable outbound action execution until an approved target is allowlisted and the approval workflow has been rehearsed.

For email delivery, first configure SMTP credentials, sender, and operations recipients in secret storage; verify delivery using a test account; then start the opt-in worker:

```sh
docker compose --profile notifications --env-file .env.production -f compose.production.yaml up -d notification-worker
```

The notification worker is deliberately not part of the default profile. Review logs and the outbox after enabling it.

## Backups and recovery

The Compose backup worker creates a daily compressed PostgreSQL custom-format archive in the `ares_backups` named volume and removes local archives older than the retention period (14 days by default). It sets restrictive file permissions and checks the archive catalog before publishing a completed file. Its health check expects a recent archive.

**The named volume is local to the deployment host and is not an off-site disaster-recovery backup.** Before production use, configure provider-managed point-in-time recovery and/or copy validated archives to a separate encrypted object-storage account or backup service with independent credentials, retention/object-lock policy, and alerts. The upload destination and credentials are intentionally not guessed here because no provider was selected. Test that off-host copies can actually be downloaded.

For a recovery drill, provision a separate empty PostgreSQL database, copy a validated archive to a trusted admin host, and install the matching PostgreSQL client tools. For the local Compose demo, list archives with `docker compose --env-file .env.demo -f compose.demo.yaml exec backup-worker ls -l /backups`, then copy one with `docker compose --env-file .env.demo -f compose.demo.yaml cp backup-worker:/backups/<archive-name>.dump /secure/path/`. Set `RESTORE_SOURCE_DB` to the name of the source database and target connection variables in the current shell through a secret manager, then run:

```sh
ops/restore_postgres.sh /secure/path/ares-YYYYMMDDTHHMMSSZ.dump
```

The restore script refuses the configured source database and any target with existing user relations; it does not drop objects or use `pg_restore --clean`. Validate the restored schema, representative records, migrations, and application health before directing traffic. Store restore credentials in a protected environment/secret manager, not shell history. Record recovery time and data-loss point, and update recovery objectives from the exercise.

## Monitoring and maintenance

Configure provider/host alerts for:

- HTTPS availability and API readiness (`GET /api/health/`), TLS certificate renewal, CPU, memory, disk, and container restarts.
- Managed PostgreSQL availability, connection/storage limits, replication lag, and provider backup status.
- `gdacs-worker` last successful poll and feed freshness via authenticated `/api/feeds/status/`, plus repeated sync failures and ingestion lag.
- Redis availability and repeated WebSocket reconnects; dashboard polling continues while live updates are disconnected.
- Notification worker/outbox retry failures when enabled, and missing/stale local or off-host backups.
- Recovery drill completion and restoration duration.

Compose health checks provide local readiness signals; they do not send alerts or replace host/provider monitoring. Collect container logs centrally with access controls and retention. Avoid logging credentials, tokens, request authorization headers, or database payloads.

Before each release, back up PostgreSQL, build and review the new images, check migrations, deploy to staging, and verify health/workflows. Keep the previous image tag for rollback. Do not assume a code rollback reverses schema/data changes; check migration reversibility, and use a separately validated recovery target when data must be restored. Pull and review current security updates for the pinned base images and Python dependencies on a regular schedule.

## Current boundary

The repository package is ready for provider-specific configuration, but no live deployment, managed database, external backup target, alert destination, or restore drill has been performed. A public production launch remains incomplete until those external setup and verification steps are recorded.
