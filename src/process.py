import logging
import os

import boto3
from botocore.exceptions import ClientError

import agent
from repository import repo

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")
API_BASE_URL = os.environ.get("API_BASE_URL")

s3_client = boto3.client("s3")
sns_client = boto3.client("sns")


def lambda_handler(event, _):
    for record in event.get("Records", []):
        # parse bucket and key from s3 event record
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        # parse invoice_id from key - uploads/{invoice_id}
        parts = key.split("/")
        if len(parts) != 2 or parts[0] != "uploads" or not parts[1]:
            raise ValueError(f"unexpected S3 key format: {key!r}")
        invoice_id = parts[1]

        logger.info("invoice_id=%s processing started key=%s", invoice_id, key)

        try:
            # read file bytes from s3
            resp = s3_client.get_object(Bucket=bucket, Key=key)
            file_bytes = resp["Body"].read()
            # get content type from metadata or s3 response header
            meta = repo.get_metadata(invoice_id) or {}
            content_type = meta.get("content_type") or resp.get(
                "ContentType", "application/octet-stream"
            )
            logger.info(
                "invoice_id=%s file loaded content_type=%s size=%d bytes",
                invoice_id,
                content_type,
                len(file_bytes),
            )
        except Exception as exc:
            # set invoice status to "failed" + email result
            _fail(invoice_id, f"failed to read uploaded file: {exc}")
            continue

        try:
            # run agent on file - updates invoice record with results and status
            extracted_vendor = agent.run(invoice_id, file_bytes, content_type)
            if extracted_vendor:
                try:
                    repo.set_vendor_if_missing(invoice_id, extracted_vendor)
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        logger.warning(
                            "invoice_id=%s failed to set vendor: %s", invoice_id, e
                        )
        except Exception as exc:
            # set invoice status to "failed" + email result
            _fail(invoice_id, str(exc))
            continue

        try:
            # run critic on results - updates invoice record with final status
            agent.run_critic(invoice_id)
        except Exception as exc:
            # don't fail invoice even if critic fails
            logger.warning("invoice_id=%s critic failed: %s", invoice_id, exc)

        try:
            # get final invoice metadata and results
            meta = repo.get_metadata(invoice_id) or {}
            result = repo.get_result(invoice_id)
            # send notification email with results
            _notify(
                invoice_id,
                meta.get("status", "complete"),
                vendor=meta.get("vendor"),
                result=result,
            )
        except Exception as exc:
            # don't fail invoice if notification fails
            logger.warning("invoice_id=%s post-processing failed: %s", invoice_id, exc)


def _notify(
    invoice_id: str,
    status: str,
    vendor: str | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    if not SNS_TOPIC_ARN:
        return

    # build email body
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

    # lambda path that generates a presigned url for uploaded file
    if API_BASE_URL:
        body += f"\n\nDocument: {API_BASE_URL}/invoice/{invoice_id}/file"

    try:
        # publish notification to sns topic - sends email
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Invoice {invoice_id} - {status}",
            Message=body,
        )
        logger.info("invoice_id=%s notification sent status=%s", invoice_id, status)
    except Exception as exc:
        logger.warning("invoice_id=%s notification failed: %s", invoice_id, exc)


def _fail(invoice_id: str, error: str) -> None:
    logger.error("invoice_id=%s failed: %s", invoice_id, error)
    repo.set_failed(invoice_id, error)
    _notify(invoice_id, "failed", error=error)
