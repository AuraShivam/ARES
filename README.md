<div align="center">

ARES

Autonomous Resilient Enterprise Supply Chain

Making supply-chain risks visible, explainable, and actionable.

A full-stack supply-chain risk intelligence platform for monitoring operations, identifying potential disruptions, assessing risk, and coordinating response plans.

<br>
</div>

⸻

Overview

Modern supply chains face challenges such as supplier delays, inventory shortages, transportation disruptions, and unexpected external events.

ARES (Autonomous Resilient Enterprise Supply Chain) is a full-stack application that brings supply-chain operations and disruption-related information into a centralized dashboard.

The platform combines operational data, external disaster alerts, explainable risk assessments, and response-management workflows to help users understand potential vulnerabilities and make informed decisions.

Project status: MVP. Risk assessments use deterministic rules and available operational data. Scores and recommendations are advisory, not guaranteed predictions.

Key Features

Supply-Chain Management

* Manage suppliers, materials, warehouses, and inventory.
* Track purchase orders and shipments.
* Record inventory receipts, issues, and adjustments.
* Monitor operational records through a centralized dashboard.
* Search, sort, and export supported tables to CSV.
* Maintain audit history for supported operations.

Risk Intelligence

* Assess potential disruptions using rule-based scoring.
* Generate risk scores from 0 to 100.
* Display contributing factors and supporting evidence.
* Identify missing or outdated information affecting assessments.
* Monitor disruption alerts and assessment history.
* Integrate global disaster alerts through the GDACS feed.
* Record incident outcomes and review descriptive calibration reports.

Response Management

* Create response plans for identified risks.
* Define and assign response actions.
* Submit plans for review.
* Support controlled approval workflows.
* Track response-plan and action status.
* Maintain audit records for supported workflow decisions.
* Queue email notifications for configured events.

Data Import

* Import operational data through supported CSV workflows.
* Preview and validate files before importing.
* Review row-level validation errors.
* Handle duplicate records according to import rules.
* Revalidate eligible imports before committing changes.

⸻

System Architecture

flowchart TD
    U[User] --> FE[React + Vite Dashboard]
    FE -->|HTTP API| BE[Django REST Framework]
    FE <-->|WebSocket Events| ASGI[Django ASGI]
    BE --> DB[(PostgreSQL)]
    BE --> R[Risk Assessment Engine]
    BE --> RP[Response Plan Workflows]
    BE --> AUD[Audit History]
    GDACS[GDACS Disaster Alerts] --> ING[GDACS Ingestion]
    ING --> DB
    ING --> R
    R --> DB
    RP --> DB
    AUD --> DB
    BE --> OUT[Notification Outbox]
    OUT --> DB
    ASGI <--> REDIS[(Redis, when configured)]

Technology Stack

Component	Technology	Purpose
Frontend	React	User interface and dashboard
Build Tool	Vite	Frontend development and builds
Backend	Python, Django	Application logic
REST API	Django REST Framework	API endpoints and validation
Database	PostgreSQL	Persistent application data
Live Communication	Django ASGI/WebSockets	Event delivery where configured
Message Layer	Redis, when configured	Shared channel communication
External Integration	GDACS	Global disaster alerts
Operations	Docker Compose	Local runtime and deployment workflows

⸻

How Risk Assessment Works

ARES uses deterministic rules to evaluate potential supply-chain risks.

Depending on the assessment and available data, the rules can consider:

* Disruption severity and reported confidence.
* Supplier status and lead time.
* Shipment status and delivery delays.
* Open or delayed purchase orders.
* Material criticality and inventory levels.
* Reorder thresholds.
* Regional relationships between disruptions and operational entities.
* Data freshness and missing evidence.

An assessment can include a risk score, risk category, contributing factors, evidence coverage, data-quality warnings, and advisory recommendations.

Risk Categories

Score	Category
0–34	Low
35–59	Moderate
60–79	High
80–100	Critical

These categories represent the application’s current scoring rules. They are not independently validated probability estimates.

Important limitations:

* A high risk score does not guarantee a disruption will occur.
* A global disaster alert does not prove that a specific supplier or shipment is affected.
* Results depend on the quality and freshness of available data.
* Calibration reports are descriptive and do not automatically train a machine-learning model.

See the Risk Intelligence Guide for details.

⸻

Repository Structure

ARES/
├── backend/
│   ├── config/
│   ├── supply_chain/
│   ├── manage.py
│   ├── requirements.txt
│   └── README.md
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── config/
│   │   ├── features/
│   │   └── lib/
│   ├── package.json
│   └── pnpm-lock.yaml
│
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   ├── risk-intelligence.md
│   ├── response-plans.md
│   ├── data-imports.md
│   ├── security-quality.md
│   └── roadmap.md
│
├── ops/
├── compose.demo.yaml
├── compose.production.yaml
└── README.md

The exact contents may change as development progresses.

⸻

Getting Started

Prerequisites

Install the following tools:

* Git
* Python 3
* Node.js
* pnpm
* PostgreSQL 14 or newer

Redis may be required for shared WebSocket event delivery in multi-process deployments.

1. Clone the Repository

git clone https://github.com/AuraShivam/ARES.git
cd ARES

2. Configure the Backend

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Create a local environment file:

cp .env.example .env

Configure the required environment variables in backend/.env, including your PostgreSQL connection details and Django secret key.

Export the variables into your current terminal session:

set -a
source .env
set +a

Django does not automatically load a .env file unless the project explicitly configures an environment loader.

Never commit your .env file or real credentials to GitHub.

3. Prepare the Database

Create a PostgreSQL database and configure its connection details.

Run the migrations:

python manage.py migrate

Create an administrator account:

python manage.py createsuperuser

If the demo-data command exists in your current version, load sample records:

python manage.py seed_demo

4. Start the Backend

From the backend/ directory:

python manage.py runserver

The development API should be available at:

http://127.0.0.1:8000

5. Start the Frontend

Open another terminal from the repository root:

cd frontend
pnpm install --frozen-lockfile
pnpm run dev

Open the local URL printed by Vite.

The frontend is expected to communicate with the backend API at:

http://127.0.0.1:8000/api

If your backend runs at another address, configure VITE_API_BASE_URL according to the frontend configuration.

6. Synchronize Disaster Alerts

From the backend/ directory, with the virtual environment active:

python manage.py sync_gdacs_alerts

For continuous polling during development:

python manage.py sync_gdacs_alerts --watch

These commands depend on the connector being configured and network access being available.

For complete setup instructions, see the Deployment Guide.

⸻

API Overview

ARES exposes REST API endpoints under /api/.

The following table summarizes major API areas. Refer to the backend documentation for exact request formats, authentication requirements, and supported operations.

Area	Example Endpoint
Authentication	/api/auth/login/
Current User	/api/auth/me/
Logout	/api/auth/logout/
Health	/api/health/
Dashboard Overview	/api/overview/
Suppliers	/api/suppliers/
Materials	/api/materials/
Warehouses	/api/warehouses/
Inventory	/api/inventory/
Purchase Orders	/api/purchase-orders/
Shipments	/api/shipments/
Disruptions	/api/disruptions/
Risk Assessment	/api/risk/assess/
Risk Assessments	/api/risk/assessments/
Risk Alerts	/api/risk/alerts/
Response Plans	/api/response-plans/
Response Actions	/api/response-actions/
Import Templates	/api/imports/templates/
Feed Status	/api/feeds/status/
Audit Events	/api/audit-events/

For more information, see the Backend README.

⸻

Testing

Run backend tests from the backend/ directory:

python manage.py test supply_chain.tests

Before deployment, verify that:

* Database migrations complete successfully.
* Authentication and authorization work as expected.
* Risk-assessment rules produce expected results.
* Import validation handles invalid and duplicate rows correctly.
* Response-plan approval restrictions are enforced.
* External-feed failures are handled safely.

Only report passing tests after running them successfully.

⸻

Security Considerations

Before exposing ARES to an external network:

* Disable Django debug mode.
* Generate a strong, unique Django secret key.
* Configure allowed hosts and trusted frontend origins.
* Use HTTPS for production traffic.
* Store credentials in environment variables or a secret manager.
* Never commit passwords, tokens, or private operational data.
* Configure appropriate database permissions.
* Review authorization checks for sensitive API operations.
* Keep external-action execution disabled unless explicitly required and reviewed.
* Configure database backups, monitoring, and restoration procedures.
* Review production deployment settings before accepting real operational data.

Application-level safeguards do not automatically make a deployment production-ready.

See the Security and Quality Guide.

⸻

Current Limitations

ARES is an evolving MVP. Current limitations include:

* Risk scoring is rule-based rather than generated by a trained AI model.
* Risk assessments depend on the quality and availability of operational data.
* GDACS alerts are global disaster signals, not direct supplier or carrier telemetry.
* Regional matching based on text may not identify every geographical relationship.
* Calibration reports require reliable, reviewed incident outcomes.
* Additional integrations may be needed for real-time supplier and logistics information.
* Production deployment requires appropriate security, scheduling, monitoring, and infrastructure configuration.

⸻

Roadmap

Potential areas for future development include:

* Additional supplier and logistics data integrations.
* Improved geographical matching.
* Better risk evaluation using verified historical outcomes.
* Expanded automated testing.
* Improved monitoring and operational observability.
* Enhanced dashboards and reporting.
* More comprehensive deployment documentation.
* Carefully evaluated predictive models when suitable training data becomes available.

For current implementation status, see the Project Roadmap.

⸻

Documentation

Explore the technical documentation:

* Architecture
* Deployment and Operations
* Risk Intelligence
* Response Plans
* Data Imports
* Security and Quality
* Roadmap
* Backend Setup and API Reference

⸻

Contributing

Contributions and constructive feedback are welcome.

1. Review the architecture and roadmap.
2. Reproduce the issue or behavior locally.
3. Keep changes focused and maintainable.
4. Add tests for behavior changes where practical.
5. Document new configuration variables and API changes.
6. Never commit secrets or private operational data.

⸻

License

Check the repository for a LICENSE file before reusing or redistributing this project.

If no license is present, do not assume that the code is available for unrestricted reuse.

⸻

<div align="center">

ARES

Building more visible, explainable, and resilient supply-chain operations.

</div>
