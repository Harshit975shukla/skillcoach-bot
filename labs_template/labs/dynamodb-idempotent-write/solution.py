"""Lab: idempotent DynamoDB payment writes. Edit only this file."""


def create_table(dynamodb, name: str) -> None:
    """Create an on-demand table keyed by string attribute pk and wait until it exists."""
    raise NotImplementedError("Create the table")


def record_payment(dynamodb, table: str, payment_id: str, amount_cents: int) -> bool:
    """Write once with a condition. True if written, False if already recorded."""
    raise NotImplementedError("Use a conditional PutItem")
