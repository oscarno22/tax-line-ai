import json
import os

import boto3
from botocore.config import Config

from repository import repo

BUCKET_NAME = os.environ["BUCKET_NAME"]

s3_client = boto3.client("s3", config=Config(signature_version="s3v4"))

FILE_PRESIGN_EXPIRY = 900


def handle(event):
    invoice_id = (event.get("pathParameters") or {}).get("id")
    if not invoice_id:
        return {"statusCode": 400, "body": json.dumps({"error": "missing invoice id"})}

    try:
        meta = repo.get_metadata(invoice_id)
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to read invoice"}),
        }

    if not meta:
        return {"statusCode": 404, "body": json.dumps({"error": "invoice not found"})}

    s3_key = meta.get("s3_key")
    if not s3_key:
        return {"statusCode": 404, "body": json.dumps({"error": "file not found"})}

    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": s3_key},
            ExpiresIn=FILE_PRESIGN_EXPIRY,
        )
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to generate file url"}),
        }

    return {
        "statusCode": 302,
        "headers": {"Location": url},
        "body": "",
    }
