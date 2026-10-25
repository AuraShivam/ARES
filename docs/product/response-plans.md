# ARES disruption response plans

Response plans turn a disruption assessment into owned, reviewable work. Each plan belongs to a disruption, has an accountable owner and optional target date, and contains one or more action items with owners and optional dates. Plan and action changes write before/after snapshots to ARES audit history.

## Workflow

```text
Draft → Pending approval → Approved → In progress → Completed
          └→ Rejected → edit and resubmit
Any non-terminal state → Cancelled with a reason
```

- Plans are created as drafts. They need at least one action item before submission.
- The authenticated reviewer identity and decision are recorded for approval or rejection. Only staff accounts or members of the `ares_approvers` group can approve or reject. Rejected plans can be edited and resubmitted.
- Work cannot start before approval. Action items can only be updated after the plan starts.
- Completed action items require an outcome. A plan can be completed only after each action is completed or cancelled and an overall outcome is recorded.
- Plans can be cancelled from any non-terminal state with a reason. Completed and cancelled plans are retained.
- Editing plan details or replacing its action list is limited to drafts and rejected plans. Once approved, task titles, owners, and dates are locked; active action status and outcome remain editable.
- Submitting a plan queues email to active `ares_approvers`/staff with an email address and the plan creator. Decisions and action updates queue email to the plan creator and configured operations recipients; an action owner is also notified when the owner field contains a valid email address. Risk alert open, escalation, and clear events use the same outbox. `GET /api/notifications/` lets a recipient or approver inspect delivery state.
- The email outbox is idempotent per event and recipient, retries transient errors with backoff, and records sent, failed, or unroutable results. SMTP/provider delivery is disabled by default; the worker command only sends when `ARES_EMAIL_DELIVERY_ENABLED=true` and sender/provider settings are configured. Email delivery is at least once if a worker stops after a provider accepts a message but before the database records success.
- Action items default to a manual adapter. A draft may instead select the configured webhook adapter and a JSON payload. Dry-run records what would be sent without side effects. A live webhook call requires an active (approved and started) plan, a separate approver execution request, `ARES_ACTION_EXECUTION_ENABLED=true`, an HTTPS endpoint whose hostname is allowlisted, and a caller-provided idempotency key. Redirects are blocked, payload/response sizes are bounded, and the webhook receives the idempotency key so the receiving system can deduplicate retries.
- Each action execution has an audited, idempotent record with mode, approver, result summary, and status. A successful live execution is allowed only once per action. A failed or stale running call can be retried up to three attempts with the same idempotency key; the receiving webhook should deduplicate that key because a network timeout can leave the external result uncertain.

## API

- `GET /api/response-plans/` lists plans with disruption and action details.
- `POST /api/response-plans/` creates a draft. Example:

```json
{
  "disruption": "<disruption-uuid>",
  "title": "Protect critical component supply",
  "objective": "Keep production supplied while the route is disrupted.",
  "owner": "Supply chain lead",
  "due_date": "2026-11-15",
  "actions": [
    { "title": "Confirm alternate supplier capacity", "owner": "Procurement", "due_date": "2026-10-12" },
    { "title": "Review inventory allocation", "owner": "Operations" }
  ]
}
```

- `GET /api/response-plans/<plan-uuid>/` returns the current plan, decisions, outcome, and action items.
- `PATCH /api/response-plans/<plan-uuid>/` edits plan fields and can replace the action list while the plan is a draft or rejected.
- `POST /api/response-plans/<plan-uuid>/submit/` submits a draft for review.
- `POST /api/response-plans/<plan-uuid>/approve/` accepts optional `review_notes`; the authenticated reviewer is recorded automatically.
- `POST /api/response-plans/<plan-uuid>/reject/` expects a required `review_notes` reason; the authenticated reviewer is recorded automatically.
- `POST /api/response-plans/<plan-uuid>/start/` starts an approved plan.
- `POST /api/response-plans/<plan-uuid>/complete/` expects a required overall `outcome` after all action items are completed or cancelled.
- `POST /api/response-plans/<plan-uuid>/cancel/` expects a required `reason`.
- `GET /api/response-actions/` and `GET/PATCH /api/response-actions/<action-uuid>/` list or update action items. Active plans accept status/outcome changes; valid action statuses are pending, in progress, blocked, completed, and cancelled.
- `POST /api/response-actions/<action-uuid>/execute/` requires an `Idempotency-Key` header and accepts `{ "dry_run": true }` (default). Set `dry_run` to `false` only for an approver-authorized live webhook execution. Reuse the same key for retries of the same request (up to three total attempts); a key cannot be reused for different action data.
- `GET /api/notifications/` lists delivery records for the signed-in recipient; staff and approvers can inspect the outbox.

To deliver queued email, configure SMTP/provider environment variables and recipients in the backend environment, enable `ARES_EMAIL_DELIVERY_ENABLED=true`, then run `python manage.py dispatch_notifications`. The command is suitable for a scheduled worker; hosted scheduling and monitoring remain Phase 8 deployment work.

For a live webhook, configure `ARES_ACTION_WEBHOOK_URL`, `ARES_ACTION_WEBHOOK_ALLOWED_HOSTS`, and optionally `ARES_ACTION_WEBHOOK_TOKEN`, then explicitly enable `ARES_ACTION_EXECUTION_ENABLED=true`. Keep the token only in the ignored local `.env` or deployment secret store. Never put credentials in the action JSON payload.

## Current boundary

The dashboard accepts owner names as entered, but review decisions use the signed-in account identity. Authentication and approver authorization are enforced for the API. Live execution is limited to an explicitly configured webhook; ARES does not automatically execute procurement or logistics decisions. The audit log records decisions but is not a tamper-proof compliance ledger. Email/webhook endpoints, recipient ownership, and scheduled worker execution must be configured for an environment before external delivery can occur.
