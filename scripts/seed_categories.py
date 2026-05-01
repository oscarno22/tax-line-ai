import csv
import os
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "eranova-technical")
CSV_PATH = Path(__file__).parent.parent / "data" / "tax_rate_by_category.csv"


def _slugify(name: str) -> str:
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def main() -> None:
    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    with CSV_PATH.open() as f:
        rows = list(csv.DictReader(f))

    with table.batch_writer() as batch:
        for row in rows:
            name = row["Category"].strip()
            rate_pct = float(row["Tax Rate (%)"].strip())
            batch.put_item(
                Item={
                    "pk": "TAXCAT",
                    "sk": f"CAT#{_slugify(name)}",
                    "name": name,
                    "rate": Decimal(str(rate_pct / 100)),
                }
            )

    print(f"seeded {len(rows)} tax categories into {TABLE_NAME}")


if __name__ == "__main__":
    main()
