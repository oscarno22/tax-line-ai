import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]

dynamodb = boto3.resource("dynamodb")
# sigv4 required — sigv2 presigned urls fail with sts temporary credentials
s3_client = boto3.client("s3", config=Config(signature_version="s3v4"))
table = dynamodb.Table(TABLE_NAME)

PRESIGN_EXPIRY = 300


def handle(event):
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "invalid request body"}),
            }

    vendor = body.get("vendor")
    content_type = body.get("content_type")
    if not content_type:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "content_type is required"}),
        }

    invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
    s3_key = f"uploads/{invoice_id}"
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "pk": f"INVOICE#{invoice_id}",
        "sk": "METADATA",
        "status": "pending",
        "s3_key": s3_key,
        "content_type": content_type,
        "created_at": now,
        "updated_at": now,
    }

    if vendor:
        item["vendor"] = vendor

    try:
        table.put_item(Item=item)
    except Exception:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "failed to create invoice record"}),
        }

    try:
        upload_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET_NAME, "Key": s3_key, "ContentType": content_type},
            ExpiresIn=PRESIGN_EXPIRY,
        )
    except Exception:
        # clean up record if presign fails
        table.delete_item(Key={"pk": f"INVOICE#{invoice_id}", "sk": "METADATA"})
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
