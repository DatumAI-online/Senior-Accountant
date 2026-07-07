# datum-skill-brain

An AI accounting API — the "Skill Brain" for **Datum**. It takes a financial
transaction as input, classifies it with Claude, and returns structured JSON:

- `category`
- `confidence`
- `tax_deductible`
- `reason`

## Architecture

```
datum-skill-brain/
├── app/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── api/
│   │   └── routes.py            # HTTP routes (/health, /classify)
│   ├── services/
│   │   └── claude_service.py    # Claude API wrapper + prompt + parsing
│   ├── schemas/
│   │   └── transaction.py       # Pydantic request/response models
│   └── core/
│       └── config.py            # Environment-based settings
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

The design keeps concerns separated:

- **`schemas/`** — pure data contracts (Pydantic), no logic.
- **`services/`** — external integrations (Claude API). Nothing here knows
  about HTTP.
- **`api/`** — HTTP layer. Translates domain errors into HTTP status codes.
- **`core/`** — cross-cutting config, loaded once and cached.

## Requirements

- Python 3.10+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

## Setup

```bash
# 1. Clone / unzip the repo, then enter it
cd datum-skill-brain

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is now available at `http://localhost:8000`, with interactive docs
at `http://localhost:8000/docs`.

## API

### `GET /api/v1/health`

Liveness check.

```json
{ "status": "ok", "service": "datum-skill-brain", "version": "0.1.0" }
```

### `POST /api/v1/classify`

Classify a single transaction.

**Request body:**

```json
{
  "description": "AWS SERVICES INVOICE #4471",
  "amount": 249.99,
  "currency": "USD",
  "merchant": "Amazon Web Services",
  "transaction_date": "2026-06-15",
  "notes": "Monthly cloud hosting for production app"
}
```

**Response:**

```json
{
  "transaction": {
    "description": "AWS SERVICES INVOICE #4471",
    "amount": 249.99,
    "currency": "USD",
    "merchant": "Amazon Web Services",
    "transaction_date": "2026-06-15",
    "notes": "Monthly cloud hosting for production app"
  },
  "classification": {
    "category": "Software & Subscriptions",
    "confidence": 0.96,
    "tax_deductible": true,
    "reason": "Cloud hosting for a production application is an ordinary and necessary business expense, typically fully deductible as a software/technology cost."
  },
  "model": "claude-sonnet-4-6"
}
```

**Example curl:**

```bash
curl -X POST http://localhost:8000/api/v1/classify \
  -H "Content-Type: application/json" \
  -d '{
    "description": "UBER TRIP 04-12 SAN FRANCISCO",
    "amount": 32.50,
    "currency": "USD"
  }'
```

## Error handling

If Claude is unreachable, times out, or returns output that cannot be parsed
into the expected schema, the API responds with `502 Bad Gateway` and a
descriptive error message — it never silently fabricates a result.

## Configuration reference

| Variable              | Default              | Description                              |
|------------------------|----------------------|-------------------------------------------|
| `ANTHROPIC_API_KEY`   | *(required)*         | Your Anthropic API key                   |
| `CLAUDE_MODEL`        | `claude-sonnet-4-6`  | Model used for classification            |
| `CLAUDE_MAX_TOKENS`   | `1024`               | Max tokens for Claude's response          |
| `APP_NAME`            | `datum-skill-brain`  | Service name (shown in health check)     |
| `APP_VERSION`         | `0.1.0`              | Service version                          |
| `ENVIRONMENT`         | `development`        | Free-form environment label              |
| `CORS_ALLOW_ORIGINS`  | `*`                  | Comma-separated allowed origins, or `*`  |

## Next steps for production

- Add authentication (API key or JWT) in front of `/api/v1/classify`.
- Add request logging / observability (e.g. OpenTelemetry).
- Add a persistence layer if you need to store classification history.
- Add rate limiting to protect the Claude API budget.
- Add automated tests (`pytest` + `httpx.AsyncClient`) for the routes and a
  mocked Claude service.
"# datum-skill-brain" 
