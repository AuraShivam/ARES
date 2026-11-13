# ARES local demo walkthrough

This guide is a short, repeatable walkthrough for the local ARES dashboard at [http://localhost:8080](http://localhost:8080). It demonstrates the current application without a hosted service, SAP connection, live supplier/carrier feed, or AI provider. It is designed for a disposable local demo database.

## Before the demo

1. Install Docker Desktop and start its engine.
2. Open a terminal at the repository root. Create the local environment file only if it does not already exist, so existing local configuration is preserved:

   ```sh
   if [ ! -f .env.demo ]; then cp .env.demo.example .env.demo; fi
   chmod 600 .env.demo
   ```

3. Start the local services:

   ```sh
   docker compose --env-file .env.demo -f compose.demo.yaml up --build -d
   docker compose --env-file .env.demo -f compose.demo.yaml ps
   ```

   The `migrate` service applies database migrations, including the latest agent-governance migration, before the API and workers start. PostgreSQL and Redis are private to the Compose network; the dashboard binds to loopback on port 8080.

4. If this is a new database, create an administrator interactively. Skip this command if an administrator already exists:

   ```sh
   docker compose --env-file .env.demo -f compose.demo.yaml exec api python manage.py createsuperuser
   ```

5. Load the small, repeatable example dataset:

   ```sh
   docker compose --env-file .env.demo -f compose.demo.yaml exec api python manage.py seed_demo
   ```

   `seed_demo` upserts fixed demo codes such as `SUP-001`, `MTR-440`, `PO-2026-1043`, and `SHP-7781`. Run it only in the isolated demo database: it can update records that use those same codes. The examples are synthetic and are not verified business records. The command does not make fake historical delivery labels, dated material consumption, shipment routes, or GDACS events.

6. Check the app before presenting:

   ```sh
   curl --fail http://localhost:8080/api/health/
   docker compose --env-file .env.demo -f compose.demo.yaml logs --tail=80 api gdacs-worker web
   ```

   Open the dashboard, sign in with the administrator account you created, then check **Data onboarding** for GDACS sync status. The GDACS worker polls at its configured minimum interval (six minutes by default); the first successful sync may take a moment. A feed failure should be described as a feed issue, not as proof that the whole ARES app is down. The basemap and GDACS also need outbound internet access.

## 8-minute presenter flow

### 1. Start at Network overview (1 minute)

Point out the summary cards, open disruption queue, delayed shipment, and reorder watch. The seed includes a delayed `SHP-7781`, resin inventory below its reorder point, and a synthetic East Asia disruption. Explain that ARES joins operational records to make these signals reviewable.

### 2. Show the shipment and map (1 minute)

Open **Shipments** and find `SHP-7781`, then open **World map**. The demo has recorded coordinates for its origin and destination, so ARES can draw an endpoint connector. That connector is not an actual carrier route or live vessel track. When GDACS has synchronized events, show their source alert level, event time, geometry, and source link. A GDACS hazard is context; it does not establish impact to this shipment or supplier.

If map tiles are blocked or unavailable, use **Data onboarding** and the authenticated feed status as the source-health check. Missing basemap tiles alone do not show that the GDACS sync failed.

### 3. Assess the sample disruption (1 minute)

From **Network overview** or **Disruptions**, select **Assess** for `Port congestion in East Asia`. Open **Risk intelligence** to show the saved score, factors, evidence, and data gaps. Make clear that this seeded record is an illustrative ARES input, not a live GDACS event or verified report from a port operator.

### 4. Explore the supply-chain twin (2 minutes)

Open **Supply chain twin** and follow the links among the supplier, purchase order, material, warehouse, shipment, and disruption. Select a disruption and choose **Analyze impact** to see the recorded-link and geography evidence with its classification. If coordinates or a route are missing, ARES reports unknown or unavailable rather than estimating them from names.

For a safe what-if, choose the **Shipment delay** scenario, select `SHP-7781`, set a seven-day delay and a 30-day horizon, leave the recovery options empty, and run the scenario. Review the saved comparison and explain that it is isolated and hypothetical: it does not edit the shipment, order, or inventory.

### 5. Show what the models and AI know (2 minutes)

Open **AI control center** and review **Data readiness**. The seeded database intentionally lacks enough verified deliveries and dated issue movements for the predictive models to claim reliable training history. Show `insufficient data` or unavailable results as an honest system response; do not present invented delay probabilities or demand forecasts.

If time permits, open **Model evaluation** and run one evaluation. With the demo seed it should report insufficient history; the saved evaluation is a local evaluation record and does not train or change the live prediction model.

On **Agent control center**, show that the provider is disabled by default, the read-only boundary, and the current limits. Do not promise a generated agent analysis while the provider is unavailable. Enabling a provider sends the submitted question and selected ARES records outside the local app. Configure that only with an approved provider and demo data, following the [agentic AI guide](../engineering/agentic-ai-foundation.md); provider status indicates configuration, not reachability.

### 6. Close on human review and traceability (1 minute)

In **Response plans**, choose **New response plan**, link it to the synthetic disruption, assign yourself as owner, and add one manual action. Creating a draft writes to the local demo database and its change appears in **Audit history**. Stop at the draft or submit it for review; approval and any separately enabled external action remain explicit. Email and live action execution are disabled by default.

## What this demo proves—and does not prove

- It demonstrates the local dashboard, PostgreSQL-backed records, risk assessment workflow, evidence-aware digital-twin impact view, and isolated scenario history when the Compose services are healthy.
- It can show current GDACS events only after a successful upstream sync. GDACS supplies disaster alerts, not supplier, carrier, or facility telemetry.
- It does not establish predictive model accuracy. Production-grade training requires enough verified shipment outcomes and dated material consumption history.
- It does not establish a real supplier impact, true shipment route, alternate supplier capacity, quote, or operational recovery result.
- It does not verify a live AI provider unless an operator explicitly configures one and completes a separate bounded provider call. No provider credential is included in the repository.
- A localhost demonstration is not a hosted deployment, external backup, monitoring, or disaster-recovery exercise.

## Stop the demo safely

Stop services while preserving the local database and backup volumes:

```sh
docker compose --env-file .env.demo -f compose.demo.yaml down
```

Do not add `-v` unless you intentionally want to delete those volumes. See the [deployment and operations guide](deployment.md) for logs, backups, restore procedures, and the production boundary.
