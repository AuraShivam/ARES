# Agentic AI foundation

## Phase 1 scope

Phase 1 establishes shared output contracts and a read-only data-readiness report. It does not run an agent, call an LLM, train a new model, or write operational records. That keeps an empty or incomplete dataset from being mistaken for a successful AI analysis.

## Data-readiness API

Authenticated clients can call `GET /api/ai/data-readiness/`. It returns current ARES record counts, training-data coverage, source freshness, and known data-model gaps. The report reads PostgreSQL and does not change rows.

Capability statuses have these meanings:

| Status | Meaning |
| --- | --- |
| `ready` | The current implementation's stated minimum input conditions are present. This is not a claim of production accuracy. |
| `limited` | Some inputs exist, but one or more requirements are missing. |
| `blocked` | The capability has no usable records for its stated purpose. |
| `not_implemented` | The execution capability belongs to a later phase and is not available yet. |

The report exposes separate readiness for deterministic risk assessment, dated-demand forecasting, verified shipment-delay prediction, supplier intelligence, inventory intelligence, logistics, procurement, disaster intelligence, and agent execution. It avoids a single composite score because these capabilities have different evidence requirements.

### Current data requirements reflected by the report

- Demand forecast eligibility is counted per material using the existing model's 180-day window, minimum 60 days of history, and at least 10 distinct issue dates.
- Shipment-delay model readiness follows the existing model's minimum 40 consistent approver-verified deliveries, with at least 10 late and 10 on-time examples. Delay-duration readiness is reported separately and needs 8 late examples.
- Supplier records currently identify a preferred supplier. A qualified alternative-supplier catalog, material capability/capacity, contract constraints, and current quote data are not modeled.
- Shipment records can include endpoint coordinates, but ARES has no verified route geometry, live carrier tracking, traffic feed, or route alternatives provider.
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

Findings and recommendations require at least one evidence reference. Recommendations default to requiring human approval. A successful result cannot carry execution errors; partial or failed states must be used when applicable. These serializers define a data contract only; they are not an agent runtime.

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

## Next phases

Phase 2 adds an optional provider abstraction, configuration/status handling, and restricted read-only tools. Phase 3 adds orchestration and specialist-agent workflows. Do not enable write-capable tools before the approval and audit controls are implemented.
