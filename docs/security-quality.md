# ARES security and quality

## API access

- All `/api/` endpoints require authentication except `GET /api/health/` and `POST /api/auth/login/`.
- Login accepts a Django username and password and returns a token. The React dashboard sends it as `Authorization: Token <token>` and keeps it in the current tab's session storage.
- A new login rotates the account's existing token. Tokens expire after eight hours by default (`ARES_API_TOKEN_TTL_HOURS`) and `/api/auth/logout/` revokes the active token.
- Login attempts are rate limited to 10 per hour per client address.
- There is no public account registration. Bootstrap an administrator with `python manage.py createsuperuser`; add normal accounts in Django Admin.
- Only staff/superuser accounts or members of the Django group named `ares_approvers` can approve or reject response plans. A decision stores the signed-in identity and audit actor.

## Error behavior

| Condition | HTTP response |
| --- | --- |
| Missing or expired credentials | `401` with an authentication detail |
| Authenticated user lacks approval rights | `403` |
| Invalid input | `400` with field-level validation details |
| Database uniqueness/integrity conflict | `409` with a safe retry message |
| Database unavailable | `503` with a safe retry message |
| Unknown API endpoint | `404` JSON detail |
| Unexpected API error | `500` generic JSON detail; traceback remains in server logs |

The dashboard converts nested field errors into readable messages. Unexpected server details and SQL errors are not returned to the browser.

## Local and deployed settings

`.env.example` is configured for a local development run. Before deployment, set `DJANGO_DEBUG=false`, a strong unique `DJANGO_SECRET_KEY`, exact `DJANGO_ALLOWED_HOSTS`, and exact `CORS_ALLOWED_ORIGINS`. Serve over HTTPS. Set `DJANGO_SECURE_SSL_REDIRECT=true` and a positive `DJANGO_SECURE_HSTS_SECONDS` only once the HTTPS endpoint and proxy behavior are verified. Keep credentials and secret keys in deployment secret storage; never commit `.env`.

Token authentication is an MVP mechanism. A public deployment should review token storage, TLS termination, rate limits, user lifecycle, backups, monitoring, and incident response before launch.

## Automated backend coverage

The Django API tests cover authentication and token revocation/expiry, approver authorization and reviewer identity, the response-plan lifecycle, inventory movement atomicity, and risk-assessment validation. The frontend's dependency-free Node tests cover nested API error formatting. Run from `backend/` after installing dependencies and configuring a PostgreSQL test database:

```sh
python manage.py test supply_chain.tests
```

UI-level automated tests and a production security review remain future work.

Run the frontend utility tests from `frontend/` with:

```sh
node --test
```
