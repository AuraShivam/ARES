# ARES

Autonomous Resilient Enterprise Supply Chain is a standalone supply-chain visibility and disruption-response application. The current MVP uses Django REST Framework, PostgreSQL, and a React dashboard.

ARES accepts data through its authenticated APIs, dashboard forms, and validated CSV imports for supply-chain records. A scheduled, credential-free GDACS connector brings global recent disaster alerts into the disruption workflow; additional supplier and carrier feeds remain future integrations.

## Repository map

```text
.
├── backend/
│   ├── config/               # Django settings, routes, WSGI, and ASGI
│   ├── supply_chain/         # Domain models, APIs, migrations, and risk rules
│   ├── manage.py
│   ├── requirements.txt
│   └── README.md             # Backend setup and API reference
├── frontend/                 # React + Vite dashboard
│   └── src/
│       ├── app/              # Dashboard shell and orchestration
│       ├── config/           # Navigation and record column definitions
│       ├── features/         # Overview, record tables, and action dialogs
│       └── lib/              # API client and shared display helpers
└── docs/
    ├── architecture.md      # Runtime layout and data flow
    └── roadmap.md           # Phases, status, and remaining work
```

Start with the [architecture guide](docs/architecture.md), [roadmap](docs/roadmap.md), [security and quality guide](docs/security-quality.md), [risk intelligence guide](docs/risk-intelligence.md), [response-plan guide](docs/response-plans.md), and [backend setup/API guide](backend/README.md).
