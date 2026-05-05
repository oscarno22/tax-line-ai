import json

import file
import presign
import query


def lambda_handler(event, context):
    # routekey contains HTTP method and path
    route = event.get("routeKey", "")

    # simple health check
    if route == "GET /health":
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "ok"}),
        }

    # handle invoice creation
    if route == "POST /invoice":
        return presign.handle(event)

    # handle invoice file retrieval
    if route == "GET /invoice/{id}/file":
        return file.handle(event)

    # handle invoice result retrieval
    if route == "GET /invoice/{id}":
        return query.handle(event)

    return {"statusCode": 404, "body": json.dumps({"error": "not found"})}
