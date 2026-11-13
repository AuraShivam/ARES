# Agentic AI foundation

## Phase 1: readiness and contracts

Phase 1 establishes shared output contracts and a read-only data-readiness report. It does not run an agent, call an LLM, train a new model, or write operational records. That keeps an empty or incomplete dataset from being mistaken for a successful AI analysis.

## Data-readiness API

Authenticated clients can call `GET /api/ai/data-readiness/`. It returns current ARES record counts, training-data coverage, source freshness, and known data-model gaps. The report reads PostgreSQL and does not change rows.

Capability statuses have these meanings:

| Status | Meaning |
| --- | --- |
| `ready` | The current implementation's stated minimum input conditions are present. This is not a claim of production accuracy. |
| `limited` | Some inputs exist, but one or more requirements are missing. |
| `blocked` | The capability has no usable records for its stated purpose. |
| `unavailable` | A capability or dependency cannot run with the current implementation/configuration. |
| `configured` | Required provider settings and external-processing opt-in are present; this does not prove provider reachability or health. |

The report exposes separate readiness for deterministic risk assessment, dated-demand forecasting, verified shipment-delay prediction, supplier intelligence, inventory intelligence, logistics, procurement, disaster intelligence, and agent execution. Agent-runtime readiness is `unavailable` until a provider is configured and external processing is explicitly enabled; it becomes `configured` when those settings are present. This is configuration status only: the endpoint does not make a provider request. It avoids a single composite score because these capabilities have different evidence requirements.

### Current data requirements reflected by the report

- Demand forecast eligibility is counted per material using the existing model's 180-day window, minimum 60 days of history, and at least 10 distinct issue dates.
- Shipment-delay model readiness follows the existing model's minimum 40 consistent approver-verified deliveries, with at least 10 late and 10 on-time examples. Delay-duration readiness is reported separately and needs 8 late examples.
- Supplier records currently identify a preferred supplier. A qualified alternative-supplier catalog, material capability/capacity, contract constraints, and current quote data are not modeled.
- Shipment records can include endpoints and an optional source-attributed GeoJSON path. ARES does not supply a route provider, live carrier tracking, traffic feed, or route alternatives provider.
- GDACS freshness and active alert counts come from the persisted feed status. A GDACS event is contextual hazard evidence and does not prove that a named ARES facility or shipment is impacted.
- Source provenance counts records that have a non-empty `source_name`; they do not independently validate the source's truth.

The report intentionally returns unknown model fields as JSON `null`, and it identifies missing features in `data_model_gaps` rather than estimating them.

## Shared agent execution contract

`backend/supply_chain/agents/contracts.py` defines DRF serializers for references, findings, recommendations, errors, model metadata, and the common `AgentExecutionResultSerializer`. Provider-specific integrations should produce this shape and validate it before results are stored or shown.

Top-level result fields:

| Field | Purpose |
| --- | --- |
| `contract_version` | Versioned message format, currently `1.0`. |
| `agent_id` | One of the six planned specialist/coordinator identifiers. |
| `execution_id`, `status` | Correlation and lifecycle state. |
| `input_references` | ARES records or events used for the analysis. |
| `findings`, `evidence_references` | Structured observations and their source pointers. |
| `recommendations` | Proposed actions with evidence references and approval requirement. |
| `assumptions`, `confidence`, `uncertainty` | Explicitly surface assumptions and unknowns. Unknown confidence requires an uncertainty explanation. |
| `errors`, `executed_at`, `model` | Failure details, timestamp, and optional provider/model identity. |

Findings and recommendations require at least one evidence reference. Recommendations default to requiring human approval. A successful result cannot carry execution errors; partial or failed states must be used when applicable. Phase 2 uses this contract in a bounded runtime.

Example validated result:

```json
{
  "contract_version": "1.0",
  "agent_id": "inventory_intelligence",
  "execution_id": "72aaf143-f955-4fcf-b5f5-b5063c5ea3b7",
  "status": "succeeded",
  "input_references": [
    {"reference_type": "material", "reference_id": "material-uuid"}
  ],
  "findings": [
    {
      "code": "forecast_not_ready",
      "title": "Insufficient dated usage history",
      "summary": "The material does not meet the current minimum history requirement.",
      "severity": "unknown",
      "evidence_references": [
        {"reference_type": "readiness_metric", "reference_id": "demand_forecasting.materials_with_forecast_ready_history"}
      ]
    }
  ],
  "evidence_references": [],
  "recommendations": [],
  "assumptions": [],
  "confidence": null,
  "uncertainty": "A demand estimate is unavailable until sufficient dated issue history is recorded.",
  "errors": [],
  "executed_at": "2026-11-13T00:00:00Z"
}
```

## Phase 2: bounded agent runtime

Phase 2 adds an optional provider adapter, configuration/status handling, user-scoped execution records, and restricted read-only tools. The only live adapter currently implemented is the OpenAI Responses API. It uses function calling and strict JSON-schema output; see the [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create) and [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).

### Endpoints

All routes below require an authenticated ARES user.

| Method and path | Purpose |
| --- | --- |
| `GET /api/ai/status/` | Provider configuration state, available roles, read-only access mode, and execution limits. Does not probe the provider. |
| `GET /api/ai/tools/` | Public descriptions of the registered read-only tools. |
| `GET /api/ai/data-readiness/` | Current operational-data and model-input coverage. |
| `GET /api/ai/executions/` | The current user's latest 50 execution records. |
| `POST /api/ai/executions/` | Start one bounded specialist analysis or coordinator workflow. Requires an `Idempotency-Key` request header. |
| `GET /api/ai/executions/<uuid>/` | Read one execution owned by the current user. |
| `GET /api/ai/disruption-workflows/` | List the current user's recent disruption-specific coordinator workflows. |
| `POST /api/ai/disruption-workflows/` | Analyze one disruption against an exact saved risk-assessment snapshot. Requires an `Idempotency-Key` request header. |
| `POST /api/ai/disruption-workflows/<uuid>/handoff/` | Create an audited response-plan draft from a human-selected recommendation. |

The execution POST body is `{ "agent_id": "risk_intelligence", "question": "..." }`. The agent ID must be one of the six role IDs in the shared contract. For a coordinated workflow, send `agent_id: "coordinator"` and optionally a `specialists` list containing one or more supported specialist IDs. Omitting the list selects all five when the deployment caps allow it; otherwise, send an explicit subset. A repeated key and identical request returns the original result; reusing a key for a different question or specialist selection returns HTTP 409. Each user is limited to five POST attempts per hour. A direct specialist request can make at most four read-tool calls by default (configurable from one to eight). A coordinated workflow uses one shared timeout (30 seconds by default) and a shared total tool-call budget (12 by default, configurable up to 40), with a maximum of five specialists. The coordinator synthesis stage has no tools. Provider retries and output tokens are also bounded.

### Tools, data handling, and limits

The registered tools only read ARES data: data readiness, supplier, material, current inventory, shipment, purchase order, disruption, and the latest stored risk assessment. Role-specific allowlists narrow access further. Tool arguments are validated, results are bounded, and generated evidence references must exactly match references returned by those tools. The runtime rejects unsupported tools, invalid output, and unverified citations. It never changes operational records; every generated recommendation is forced to require human approval.

| Role | Focus and boundary |
| --- | --- |
| `risk_intelligence` | Summarize recorded disruption and stored deterministic risk evidence; does not recalculate risk scores. |
| `supplier_intelligence` | Review supplier records and verified delivery history; qualified alternatives, capacity, and current quotes are not available. |
| `inventory_intelligence` | Review current balances, purchase-order context, and demand-data readiness; does not infer a forecast from balances alone. |
| `logistics_intelligence` | Review shipments and linked disruptions; does not invent carrier tracking, routes, traffic, or alternate ETAs. |
| `procurement_intelligence` | Review purchase orders, suppliers, materials, and stock; cannot create or approve procurement actions. |
| `coordinator` | Run the selected specialists in order and combine their verified reports; synthesis has no direct tools. |

The coordinator runs selected specialists sequentially under one shared time and tool budget, then asks a tool-free synthesis stage to combine their structured findings, recommendations, assumptions, and evidence. A specialist failure stops the workflow and is recorded with its completed and failed stages. Each stage is stored as an `AgentExecutionStep` beneath the user-scoped parent execution and is returned in execution history/detail. The coordinator cannot use evidence beyond the exact references in specialist outputs.

The runtime is disabled by default. To enable external processing, an operator must set `ARES_AGENT_PROVIDER=openai_responses`, configure `ARES_AGENT_MODEL`, `ARES_AGENT_API_KEY`, and `ARES_AGENT_API_BASE_URL`, and explicitly set `ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=true`. Remote endpoints must use HTTPS; HTTP is accepted only for localhost development. Configuration examples use blank provider fields, and no credentials are included in the repository. The status endpoint does not expose the key or endpoint URL. When enabled, the user's question and selected read-only ARES tool results are sent to the configured external model provider. Execution records store a hash of the idempotency key and request, the validated result, usage metadata, and safe error details; they do not store the raw question.

`configured` means the settings are complete, not that the provider is reachable, the model is available, or the account has quota. No live provider request is made by default. The workflow is synchronous and sequential; it does not run specialists in parallel and does not provide cancellation or background execution. Write tools and automated actions remain later work.

### Optional local provider configuration

The standard demo does not require an AI provider. Only configure one when a live agent call is part of the demonstration and the data owner has approved sending the selected question and ARES evidence to that provider. The repository currently implements the `openai_responses` adapter only.

Edit the ignored root `.env.demo` file in a local editor and set the provider-issued model and API key without putting the key in shell history or source control:

```dotenv
ARES_AGENT_PROVIDER=openai_responses
ARES_AGENT_MODEL=<provider-issued-model-id>
ARES_AGENT_API_KEY=<provider-issued-secret>
ARES_AGENT_API_BASE_URL=https://api.openai.com/v1
ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=true
```

Replace the placeholder values; do not copy them literally. Keep the key private and use only approved demo data. Then recreate the API container so Compose loads the updated environment:

```sh
docker compose --env-file .env.demo -f compose.demo.yaml up -d --force-recreate api
```

Check **AI control center** and read the external-processing notice before submitting anything. A `configured` status is not a reachability check; one intentionally submitted bounded analysis is required to verify the connection. Provider calls can incur charges. Afterward, set `ARES_AGENT_PROVIDER=disabled`, clear the model/key/base URL values, set `ARES_AGENT_EXTERNAL_PROCESSING_ENABLED=false`, and recreate the API if the provider should no longer be available.

## Phase 4: predictive model evaluation

Chronological model evaluation is available through `POST /api/models/evaluations/` and `python manage.py evaluate_predictive_models`. Runs compare both current predictors with transparent baselines, persist holdout metrics and a SHA-256 data fingerprint, and return an explicit insufficient-data result when evaluation thresholds are not met. See the [predictive model evaluation guide](predictive-model-evaluation.md). Provider calls remain opt-in and operational writes remain outside this evaluation workflow.

## Phase 5: disaster and geospatial exposure

The GDACS connector validates and bounds source GeoJSON before persistence, retains event identifiers, available source metrics, timestamps, source URL, and active/cancelled/expired lifecycle, and preserves operator control of linked ARES disruptions and response plans. Current maps show validated GDACS point/polygon geometry and optional source-attributed shipment `LineString`/`MultiLineString` paths. Endpoint-only connectors are shown separately and are never treated as routes.

The digital-twin impact API adds structured `evidence` and canonical `exposure_classification` values: `confirmed_operational_disruption` (explicit ARES link), `confirmed_geographical_intersection` (entity coordinates inside a source polygon or supplied shipment path intersects it), `potential_geographical_exposure` (configured proximity buffer), `indirect_supply_chain_dependency` (stored graph path), `unaffected`, and `unknown_insufficient_data`. Point-event buffers are always potential. Country/region matching is disabled. Original `classification`/`counts` values remain for compatibility. This is a local code implementation; apply the new shipment-route migration and verify a live feed against the configured PostgreSQL runtime before demoing it. ARES does not invent coordinates, routes, event metrics, or operational impact.

## Phase 6: recovery strategy simulation

`POST /api/digital-twin/simulations/` now accepts up to 10 explicit recovery options and optional `ranking_weights`. Supplier alternatives are grounded in approver-verified delivered shipment history; operator options can model inventory redistribution, emergency procurement, and a source-attributed route alternative. Entries with the same `combination_name` are evaluated as one bounded combination, with supplied quantities and limits applied to an isolated scenario projection. The resulting comparison is saved with the simulation and displayed on the Digital Twin page.

This phase is deterministic and advisory. ARES does not infer supplier capacity, current quotes, warehouse demand/capacity, or alternate routes, and it does not execute proposed actions. Missing metrics lower score coverage or remain unavailable. See the [digital twin guide](digital-twin.md#recovery-strategy-comparison) for request fields, scoring policy, evidence rules, and assumptions. Source code is implemented locally; the frontend production build and Python syntax checks pass. Authenticated database-backed runtime verification remains pending in the configured PostgreSQL environment.

## Phase 7: outcome tracking and calibration

Phase 7 preserves the evidence needed to compare a prediction or response with what was later verified. It does not claim causal impact, automatically tune thresholds, or recalibrate production probabilities.

### Shipment prediction snapshots

The dashboard's **Track this prediction** action calls `POST /api/risk/predictive/snapshots/` with a shipment UUID. A snapshot stores the promised ETA, model version and training cutoff, predicted late probability, confidence, conditional delay range, point-in-time features, explanation factors, and shortage outlook. An identical prediction for the same shipment is deduplicated by a content fingerprint so refreshes do not overweight calibration, and a creation event is added to audit history. Changed predictions can create a new snapshot. Authenticated users can capture predictions (limited to 30 captures per hour); approvers can read the latest 100 snapshots using `GET /api/risk/predictive/snapshots/` and optionally filter by `shipment_id`.

The label is read from the shipment's current approver-verified delivery record. Delivery verification requires evidence notes and an explicit intervention attribution (`none`, `ares_plan`, `external`, or `unknown`). Selecting `ares_plan` also requires a linked active or completed plan explicitly connected to the shipment through its disruption. Changing model inputs invalidates the delivery verification, so those labels stop contributing until reviewed again. The original promise saved in the prediction snapshot is used even if the current ETA later changes.

### Reviewed disruption outcomes

`POST /api/risk/outcomes/` accepts `disruption_id`, `outcome`, evidence notes, `assessment_snapshot_id`, and intervention attribution; `response_plan_id` is required when attribution is `ares_plan`. The exact risk assessment must belong to that disruption. The dashboard requires an exact snapshot selection, while API clients that omit it are linked to the latest assessment at write time when one exists. Corrections remain auditable. Legacy labels without a linked snapshot remain visible but are not substituted against a later assessment.

### Response-plan effectiveness

When a response plan is completed, an ARES approver can submit `POST /api/response-plans/<plan-uuid>/review-effectiveness/` with an `effectiveness` value (`prevented_impact`, `reduced_impact`, `no_measurable_effect`, `worsened_impact`, or `unknown`) and required evidence notes. The review records the authenticated reviewer, timestamp, linked verified outcome for the same plan (if one exists), the pre-response assessment score reference, and a snapshot of action statuses/outcomes. Reviews are append-only through the API and corrections create a new review. The response-plan view returns the latest review and up to five reviews of history.

### Reports and interpretation

`GET /api/risk/calibration/` now includes the existing rule-threshold report, shipment prediction outcome summary, and response-effectiveness summary. Shipment metrics include Brier score for all verified tracked outcomes, a separately reported no-intervention Brier score, probability bands and observed late rates for the no-intervention subset, delay-range MAE where available, intervention counts, and pending-label counts. Disruption threshold metrics use only exact-linked labels explicitly marked `none`; intervened, unknown, and legacy-unlinked labels are counted but excluded. The plan report counts each completed plan's latest reviewer entry and action status coverage.

These reports are descriptive summaries of the captured and reviewer-selected data. Small samples, selective capture, missing outcomes, and confounding may skew them. “No intervention” is an explicit reviewer assertion, not an independently observed fact. An approver's effectiveness label is evidence-backed but does not prove the plan caused the result. No model or threshold is automatically adjusted. Phase 7 is implemented in source with additive migration `0017_outcome_tracking`; database-backed verification remains pending until that migration is applied to the configured local PostgreSQL environment.

## Phase 8: human-reviewed disruption response

The Risk Intelligence page connects one saved disruption assessment to the existing sequential coordinator and response-plan approval workflow. `POST /api/ai/disruption-workflows/` accepts a `disruption_id`, an `assessment_snapshot_id` belonging to that disruption, and an optional bounded specialist list. The risk-intelligence specialist is required so the exact selected assessment is read; specialists retain their role-scoped read-only tools, timeout, and tool-call limits. An `Idempotency-Key` is required.

Successful runs preserve the exact disruption and assessment snapshot on the `AgentExecution`. The dashboard displays findings, recommendations, assumptions, uncertainty, and evidence references for human review. `POST /api/ai/disruption-workflows/<execution-uuid>/handoff/` accepts a selected recommendation plus editable plan/action titles, owners, description, and optional due date. The transaction creates an audited `ResponsePlan` in `draft` status with one manual `ResponseAction`, and records the source execution, recommendation index, exact assessment, recommendation content, and evidence provenance. Repeating the same handoff returns the existing plan. The standard response-plan submission and approver decision endpoints remain the only way to submit, approve, start, or execute follow-up work; this workflow does not perform those actions.

The workflow panel reports provider readiness and makes external processing visible. Provider calls remain disabled unless an operator explicitly configures and enables one. The implementation is present locally with additive migration `0018_human_reviewed_workflows`; apply migrations and verify the authenticated API, configured-provider analysis, idempotent handoff, and approval boundary in PostgreSQL before treating the full runtime path as verified. No provider call or operational action is triggered automatically.

For the local Compose demo, `docker compose --env-file .env.demo -f compose.demo.yaml up --build -d` rebuilds the API and runs the migration service before starting the API. The workflow remains unavailable for new analyses until an operator supplies their own provider configuration in the ignored local environment file and explicitly opts into external processing.

## Phase 9: agent and predictive control center

The dashboard's **AI control center** reads `/api/ai/status/`, `/api/ai/data-readiness/`, `/api/ai/executions/`, and `/api/models/evaluations/`. Its readiness cards show entity coverage, capability status, sampled evidence, and known limitations. The agent console can run a selected specialist or the bounded sequential coordinator, inspect the current account's saved runs and stage outputs, and review cited evidence, assumptions, and uncertainty. The UI displays the provider/model and external-processing boundary; it does not collect or expose provider credentials. New agent starts remain disabled unless the provider is fully configured and external processing is explicitly enabled.

The Model Evaluation tab can start and review persisted chronological evaluations for shipment delay or material demand through the existing `POST/GET /api/models/evaluations/` API. It surfaces holdout windows, sample counts, fingerprints, shipment classification and delay metrics against baselines, or 7/30/90-day demand metrics against the seasonal-naive baseline. The UI displays insufficient-data results and the evaluation throttling limit; these historical metrics do not automatically calibrate or change live predictions.

The Digital Twin scenario area now fetches the signed-in account's saved simulations from `GET /api/digital-twin/simulations/`, supports paging through history, and reopens each complete persisted comparison. Simulation outputs remain hypothetical and do not mutate operational records. This phase adds no schema migration. The frontend is implemented locally; authenticated API, persisted history, and database-backed evaluation behavior still need runtime verification in the configured PostgreSQL environment.

## Phase 10: integrated reliability and governance

All `/api/ai/` status, readiness, tool, execution, workflow, and handoff endpoints explicitly require an authenticated account. Agent roles retain separate read-only tool allowlists, result evidence is checked against tool-returned references, execution history is scoped to its requesting account, and handoff remains a separate human-reviewed response-planning action. Provider use remains disabled by default and the status response continues to disclose the external-processing boundary without returning credentials or endpoint URLs.

Agent executions now retain a policy version and the prompt version selected for the root agent; each coordinator stage retains its own specialist or coordinator prompt version. Increment the corresponding version constant whenever its prompt or policy changes. The configured provider/model identifier is retained with the execution, and the provider-reported model identifier is stored when the response includes one. A blank model version means the provider omitted it; ARES does not fabricate a version. The `/api/ai/status/` response publishes the active prompt and policy versions.

Execution start and terminal success/failure transitions create `AuditEvent` records. These events contain the actor, execution identifier, agent, status, prompt/policy/provider/model metadata, bounded call counts, duration, and error code. They do not contain the user question, prompt text, idempotency key, provider API key, or provider response. Audit events are read-only through both the API and Django admin interfaces. The `AgentExecution` record separately retains the validated agent result and cited ARES evidence for the requesting account's history. Existing retries are bounded to one retry for retryable provider errors within the shared timeout; response size, question length, specialist count, and tool calls remain capped.

This implementation adds migration `0019_agent_governance_metadata`. Apply it to the configured PostgreSQL database before using the new metadata fields. Existing focused backend coverage is present for authentication defaults, disabled-provider behavior, tool allowlists, idempotency, orchestration, and response workflow boundaries. No tests or live-provider calls were run as part of this phase; apply the migration and run the repository's documented verification workflow before treating the full configured-provider path as runtime-verified. Provider credentials must remain in an ignored local environment file or deployment secret store.
