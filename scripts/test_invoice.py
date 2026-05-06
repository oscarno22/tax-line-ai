import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("API_BASE_URL", "").rstrip("/")
POLL_INTERVAL = 5
MAX_POLLS = 24  # 2 minutes

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
}


def main() -> None:
    default_file = os.environ.get("TEST_INVOICE_PATH")

    # allows for easily testing of different files/vendors
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "file",
        type=Path,
        nargs="?",
        default=default_file,
        help="path to invoice file (default: TEST_INVOICE_PATH from .env)",
    )
    parser.add_argument(
        "--vendor", default="Test Vendor", help="vendor name (default: 'Test Vendor')"
    )
    args = parser.parse_args()

    if not BASE:
        sys.exit("error: API_BASE_URL not set in .env")

    if not args.file:
        sys.exit("error: no file specified and TEST_INVOICE_PATH not set in .env")

    file: Path = args.file
    if not file.exists():
        sys.exit(f"error: file not found: {file}")

    content_type = CONTENT_TYPES.get(file.suffix.lower())
    if not content_type:
        sys.exit(
            f"error: unsupported extension '{file.suffix}' — supported: {', '.join(CONTENT_TYPES)}"  # noqa: E501
        )

    print(f"file:         {file}")
    print(f"content-type: {content_type}")
    print()

    # 1. create invoice record + get presigned url
    print("--- POST /invoice")
    resp = requests.post(
        f"{BASE}/invoice",
        json={"content_type": content_type, "vendor": args.vendor},
    )
    resp.raise_for_status()
    data = resp.json()
    print_json(data)

    invoice_id = data["invoice_id"]
    upload_url = data["upload_url"]

    # 2. upload file directly to s3
    print(f"\n--- PUT {upload_url[:60]}...")
    with file.open("rb") as f:
        upload_resp = requests.put(
            upload_url, data=f, headers={"Content-Type": content_type}
        )
    upload_resp.raise_for_status()
    print("upload complete")

    # 3. poll until done
    print(f"\n--- GET /invoice/{invoice_id} (polling every {POLL_INTERVAL}s)")
    for i in range(1, MAX_POLLS + 1):
        result = requests.get(f"{BASE}/invoice/{invoice_id}")
        result.raise_for_status()
        body = result.json()
        status = body.get("status")
        print(f"[{i}] status: {status}")

        if status in ("complete", "failed"):
            print("\n--- result")
            print_json(body)
            return

        time.sleep(POLL_INTERVAL)

    sys.exit("timed out waiting for result")


def print_json(data: dict) -> None:
    import json

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
