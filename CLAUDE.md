# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make format        # ruff format .
make lint          # ruff check --fix .
make test-retailco # smoke-test against live API using sample_invoices/RetailCo_Invoice.pdf
make test-alpha    # smoke-test using sample_invoices/AlphaImportInvoice.pdf
make test-scan     # smoke-test using sample_invoices/Invoice_Scan.pdf
make test-invoice FILE=path/to/invoice.pdf  # smoke-test with any file
make layer         # rebuild layer/python from pyproject.toml (run after dep changes)
make bootstrap     # deploy bootstrap.yaml once to create artifacts bucket + GitHub OIDC role
```

Smoke tests require `API_BASE_URL` in `.env`. They run the full POST → PUT → poll cycle against the deployed API.

**Deploy:**
```bash
make bootstrap     # once — creates S3 artifacts bucket and GitHub OIDC role
make layer         # after any dep changes
sam package --s3-bucket <artifacts-bucket> --output-template-file packaged.yaml
sam deploy --template-file packaged.yaml --stack-name tax-line-ai \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides OpenAIApiKey=<key> NotificationEmail=<email>
uv run python scripts/seed_categories.py  # first deploy only
```

**Web frontend** (`web/index.html`) deploys to the S3 WebsiteBucket and is served via CloudFront:
```bash
aws s3 sync web/ s3://tax-line-ai-<account>-website/
```

## Architecture

Two Lambda functions behind API Gateway HTTP API (v2):

**`tax-line-ai` (ApiLambda)** — handles all HTTP routes. `handler.py` dispatches on `routeKey`:
- `POST /invoice` → `presign.py`: validates `content_type`, writes `INVOICE#{id}` METADATA record (status `pending`), returns presigned S3 PUT URL (5 min expiry). Invoice ID format: `inv_{12 hex chars}`.
- `GET /invoice/{id}` → `query.py`: reads METADATA + RESULT records, builds response
- `GET /invoice/{id}/file` → `file.py`: generates a fresh presigned GET URL, returns 302
- `GET /health` → returns 200

Supported upload types: `application/pdf`, `image/*`, `text/csv`, `application/json`, `text/plain`.

**`tax-line-ai-process` (ProcessLambda)** — triggered by S3 `ObjectCreated` on `uploads/` prefix. `process.py` orchestrates:
1. Read file bytes from S3
2. `agent.run()` — three-step agent pipeline (extract → classify → save)
3. `agent.run_critic()` — reviews and corrects the saved result (non-fatal if it fails)
4. SNS notification email (non-fatal if it fails)

**Agent pipeline** (`agent.py`) — all agents use `gpt-5`, max 20 turns each (`AGENT_MAX_TURNS`):
- **Extract**: `client.responses.parse()` with `ExtractedInvoice` schema — base64 vision for images, OpenAI Files API for PDFs, plain text for CSV/JSON. Checks `is_invoice` flag; raises `ValueError` if false.
- **Classify**: OpenAI Agents SDK `Runner.run_sync()` with two tools: `get_tax_categories` (reads DynamoDB) and `save_invoice_result` (closure capturing `invoice_id`, writes RESULT + updates METADATA status).
- **Critic**: Second agent loop with `get_tax_categories` + `correct_invoice_result` tool. Corrects misclassifications and recovers `unclassified` items. Writes a CORRECTIONS audit record.

**DynamoDB** — single table `tax-line-ai`, PK/SK design:

| PK | SK | Purpose |
|---|---|---|
| `TAXCAT` | `CAT#{id}` | Tax category with `name` and `rate` |
| `INVOICE#{id}` | `METADATA` | Status, s3_key, content_type, vendor, timestamps |
| `INVOICE#{id}` | `RESULT` | line_items, subtotal, total_tax, total |
| `INVOICE#{id}` | `CORRECTIONS` | Critic audit trail |

**Invoice status lifecycle**: `pending` → `complete` | `partial` | `failed`. Status is `partial` if any line items are excluded, `complete` otherwise. The critic can upgrade `partial` → `complete` if it recovers all excluded items.

**Exclusion rule**: a line item is `excluded: true` (and omitted from totals) if `tax_category == "unclassified"` or any of `quantity`, `unit_price`, `subtotal` is null.

## Key Patterns

**Decimal handling**: boto3 requires `Decimal` for all DynamoDB numeric writes. `repository.py` uses `_to_decimal()` before writes and `to_float()` before passing data to the critic agent (which needs JSON-serialisable floats).

**`invoice_id` closure**: `save_invoice_result` and `correct_invoice_result` tools are defined as closures inside `run()` and `run_critic()` respectively, capturing `invoice_id` so it doesn't need to be passed via the agent prompt.

**PDF cleanup**: uploaded PDFs are sent to OpenAI Files API and always deleted in a `finally` block — OpenAI charges for storage.

**Lambda layer**: runtime dependencies live in `layer/python/`. After changing `pyproject.toml` deps, run `make layer` before deploying.
