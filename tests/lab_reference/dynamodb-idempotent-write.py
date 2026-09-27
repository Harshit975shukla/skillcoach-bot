"""Private reference solution for the dynamodb-idempotent-write code lab. Never publish."""


def create_table(dynamodb, name: str) -> None:
    dynamodb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.get_waiter("table_exists").wait(TableName=name)


def record_payment(dynamodb, table: str, payment_id: str, amount_cents: int) -> bool:
    if type(amount_cents) is not int or amount_cents <= 0:
        raise ValueError("amount_cents must be a positive integer")
    try:
        dynamodb.put_item(
            TableName=table,
            Item={"pk": {"S": f"payment#{payment_id}"}, "amount_cents": {"N": str(amount_cents)}},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except dynamodb.exceptions.ConditionalCheckFailedException:
        return False
    return True
