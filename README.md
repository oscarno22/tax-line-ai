# Tax Line AI

This project is an agentic invoice tax classification system. A user uploads an invoice (PDF, image, CSV, JSON), an AI agent reads it, figures out what each line item is, and assigns the right tax category to it. Results come back via email and are also queryable through the API.

![Architecture](architecture.png)

## How it works

1. A `POST /invoice` request with the file's content type (and optionally the vendor name) returns an `invoice_id` and a presigned `upload_url`
2. The file is PUT directly to S3 using that URL, with a `Content-Type` header matching what was declared. The URL expires in 5 minutes. PDFs, images, CSVs, and JSON are all supported
3. The S3 upload triggers the processing agent automatically. It runs in three steps:
   - first it extracts all line items from the document (description, quantity, unit price, subtotal)
   - then it classifies each one against the tax categories stored in the database, calculating the tax owed per line
   - finally a critic agent reviews the classifications, fixes any obvious errors, and tries to recover any items that couldn't be classified
4. `GET /invoice/{id}` returns the current status - polling until it changes from `pending`
5. An email is sent when processing finishes

Status will be `complete`, `partial` (some items couldn't be classified), or `failed` (something went wrong, resubmit the invoice).

## Frontend

The `web/index.html` is a single static HTML file served from S3 + CloudFront. It implements the same POST → PUT → poll flow as the API:

1. Vendor name (optional) and invoice file are submitted via a form
2. The file is PUT directly to S3 using the presigned URL
3. The UI polls every 5 seconds and renders the result when processing finishes

## DynamoDB Schema

Single table: `eranova-technical`. PK/SK design.

| PK | SK | Attributes |
|---|---|---|
| `TAXCAT` | `CAT#fresh_produce` | `name`, `rate` |
| `INVOICE#inv_abc123` | `METADATA` | `status`, `vendor`, `s3_key`, `content_type`, `created_at`, `updated_at` |
| `INVOICE#inv_abc123` | `RESULT` | `line_items`, `subtotal`, `total_tax`, `total` |
| `INVOICE#inv_abc123` | `CORRECTIONS` | `corrections`, `corrected_at` |

Tax categories are seeded from `data/tax_rate_by_category.csv` by `scripts/seed_categories.py`, which runs automatically as a post-deploy step.
