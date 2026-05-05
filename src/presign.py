import json
import os
import uuid
from datetime import datetime, timezone
from json import JSONDecodeError

import boto3
from botocore.config import Config

from repository import repo

BUCKET_NAME = os.environ["BUCKET_NAME"]

# sigv2 presigned urls fail with sts temporary credentials
s3_client = boto3.client("s3", config=Config(signature_version="s3v4"))
# s3 presigned url expiry time on initial upload
PRESIGN_EXPIRY = 300


def handle(event):
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except JSONDecodeError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "invalid request body"}),
            }

    # vendor name input - optional
    vendor = body.get("vendor", None)
    # content type of uploaded file
    content_type = body.get("content_type")
    if not content_type:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "content_type is required"}),
        }

    invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
    s3_key = f"uploads/{invoice_id}"
    now = datetime.now(timezone.utc).isoformat()

    try:
        # create initial invoice record in dynamo - status "pending"
        repo.create_invoice(invoice_id, s3_key, content_type, vendor, now)
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to create invoice record"}),
        }

    try:
        # upload file to s3 on presigned url - triggers ProcessLambda
        upload_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET_NAME, "Key": s3_key, "ContentType": content_type},
            ExpiresIn=PRESIGN_EXPIRY,
        )
    except Exception:
        # clean up dynamo record if presign fails
        repo.delete_invoice(invoice_id)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to generate upload url"}),
        }

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "invoice_id": invoice_id,
                "upload_url": upload_url,
                "expires_in": PRESIGN_EXPIRY,
            }
        ),
    }
