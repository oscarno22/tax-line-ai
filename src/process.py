import os
from datetime import datetime, timezone

import boto3

import agent

TABLE_NAME = os.environ["TABLE_NAME"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
sns_client = boto3.client("sns")
table = dynamodb.Table(TABLE_NAME)


def _notify(
    invoice_id: str,
    status: str,
    vendor: str | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    if not SNS_TOPIC_ARN:
        return

    subject = f"Invoice {invoice_id} - {status}"

    if status == "failed":
        body = f"Invoice {invoice_id} failed to process.\n\nError: {error}"
    else:
        lines = [f"Invoice {invoice_id} processed ({status})."]
        if vendor:
            lines.append(f"Vendor: {vendor}")
        if result:
            lines.append(f"Subtotal: ${float(result.get('subtotal', 0)):.2f}")
            lines.append(f"Total tax: ${float(result.get('total_tax', 0)):.2f}")
            lines.append(f"Total: ${float(result.get('total', 0)):.2f}")
        body = "\n".join(lines)

    try:
        sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=body)
    except Exception:
        pass


def _fail(invoice_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"pk": f"INVOICE#{invoice_id}", "sk": "METADATA"},
        UpdateExpression="SET #s = :s, #e = :e, updated_at = :t",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": "failed", ":e": error, ":t": now},
    )
    _notify(invoice_id, "failed", error=error)


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
            continue

        try:
            meta = table.get_item(
                Key={"pk": f"INVOICE#{invoice_id}", "sk": "METADATA"}
            ).get("Item", {})
            result = table.get_item(
                Key={"pk": f"INVOICE#{invoice_id}", "sk": "RESULT"}
            ).get("Item", {})
            _notify(
                invoice_id,
                meta.get("status", "complete"),
                vendor=meta.get("vendor"),
                result=result,
            )
        except Exception:
            pass
