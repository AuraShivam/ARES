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

## Phase 4: predictive model evaluation

Chronological model evaluation is available through `POST /api/models/evaluations/` and `python manage.py evaluate_predictive_models`. Runs compare both current predictors with transparent baselines, persist holdout metrics and a SHA-256 data fingerprint, and return an explicit insufficient-data result when evaluation thresholds are not met. See the [predictive model evaluation guide](predictive-model-evaluation.md). Provider calls remain opt-in and operational writes remain outside this evaluation workflow.

## Phase 5: disaster and geospatial exposure

The GDACS connector validates and bounds source GeoJSON before persistence, retains event identifiers, available source metrics, timestamps, source URL, and active/cancelled/expired lifecycle, and preserves operator control of linked ARES disruptions and response plans. Current maps show validated GDACS point/polygon geometry and optional source-attributed shipment `LineString`/`MultiLineString` paths. Endpoint-only connectors are shown separately and are never treated as routes.

The digital-twin impact API adds structured `evidence` and canonical `exposure_classification` values: `confirmed_operational_disruption` (explicit ARES link), `confirmed_geographical_intersection` (entity coordinates inside a source polygon or supplied shipment path intersects it), `potential_geographical_exposure` (configured proximity buffer), `indirect_supply_chain_dependency` (stored graph path), `unaffected`, and `unknown_insufficient_data`. Point-event buffers are always potential. Country/region matching is disabled. Original `classification`/`counts` values remain for compatibility. This is a local code implementation; apply the new shipment-route migration and verify a live feed against the configured PostgreSQL runtime before demoing it. ARES does not invent coordinates, routes, event metrics, or operational impact.

## Phase 6: recovery strategy simulation

`POST /api/digital-twin/simulations/` now accepts up to 10 explicit recovery options and optional `ranking_weights`. Supplier alternatives are grounded in approver-verified delivered shipment history; operator options can model inventory redistribution, emergency procurement, and a source-attributed route alternative. Entries with the same `combination_name` are evaluated as one bounded combination, with supplied quantities and limits applied to an isolated scenario projection. The resulting comparison is saved with the simulation and displayed on the Digital Twin page.

This phase is deterministic and advisory. ARES does not infer supplier capacity, current quotes, warehouse demand/capacity, or alternate routes, and it does not execute proposed actions. Missing metrics lower score coverage or remain unavailable. See the [digital twin guide](digital-twin.md#recovery-strategy-comparison) for request fields, scoring policy, evidence rules, and assumptions. Source code is implemented locally; the frontend production build and Python syntax checks pass. Authenticated database-backed runtime verification remains pending in the configured PostgreSQL environment.
