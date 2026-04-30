AWS_REGION      ?= us-east-1
BOOTSTRAP_STACK := eranova-bootstrap

.PHONY: layer bootstrap delete-secret

layer:
	uv export --no-dev --no-hashes -o layer/requirements.txt
	uv pip install \
		-r layer/requirements.txt \
		-t layer/python \
		--python-version 3.12

bootstrap:
	aws cloudformation deploy \
		--template-file bootstrap.yaml \
		--stack-name $(BOOTSTRAP_STACK) \
		--capabilities CAPABILITY_NAMED_IAM \
		--region $(AWS_REGION)

delete-secret:
	aws secretsmanager delete-secret \
		--secret-id eranova/openai-api-key \
		--force-delete-without-recovery \
		--region $(AWS_REGION)
