import os
from datetime import datetime, timezone

import boto3

import agent

TABLE_NAME = os.environ["TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
table = dynamodb.Table(TABLE_NAME)


def _fail(invoice_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"pk": f"INVOICE#{invoice_id}", "sk": "METADATA"},
        UpdateExpression="SET #s = :s, #e = :e, updated_at = :t",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": "failed", ":e": error, ":t": now},
    )


def lambda_handler(event, context):
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        parts = key.split("/", 1)
        if len(parts) != 2 or parts[0] != "uploads" or not parts[1]:
            raise ValueError(f"unexpected S3 key format: {key!r}")
        invoice_id = parts[1]

        try:
            resp = s3_client.get_object(Bucket=bucket, Key=key)
            file_bytes = resp["Body"].read()
            meta = table.get_item(
                Key={"pk": f"INVOICE#{invoice_id}", "sk": "METADATA"}
            ).get("Item", {})
            content_type = meta.get("content_type") or resp.get(
                "ContentType", "application/octet-stream"
            )
        except Exception as exc:
            _fail(invoice_id, f"failed to read uploaded file: {exc}")
            continue

        try:
            agent.run(invoice_id, file_bytes, content_type)
        except Exception as exc:
            _fail(invoice_id, str(exc))
