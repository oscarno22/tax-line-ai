AWS_REGION      ?= us-east-1
BOOTSTRAP_STACK := eranova-bootstrap

.PHONY: layer bootstrap format lint test-invoice test-retailco test-alpha test-scan

format:
	uv run ruff format .

lint:
	uv run ruff check --fix .

layer:
	uv export --no-dev --no-hashes -o layer/requirements.txt
	uv pip install \
		-r layer/requirements.txt \
		--target layer/python \
		--python-version 3.12

bootstrap:
	aws cloudformation deploy \
		--template-file bootstrap.yaml \
		--stack-name $(BOOTSTRAP_STACK) \
		--capabilities CAPABILITY_NAMED_IAM \
		--region $(AWS_REGION)

FILE ?= sample_invoices/RetailCo_Invoice.pdf
test-invoice:
	uv run python scripts/test_invoice.py "$(FILE)"

test-retailco:
	uv run python scripts/test_invoice.py sample_invoices/RetailCo_Invoice.pdf

test-alpha:
	uv run python scripts/test_invoice.py sample_invoices/AlphaImportInvoice.pdf

test-scan:
	uv run python scripts/test_invoice.py sample_invoices/Invoice_Scan.pdf
