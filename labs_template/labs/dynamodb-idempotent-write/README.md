# Lab: idempotent DynamoDB writes with conditions

Goal: record each payment exactly once, even when a client retries the same request.
Runs locally against [moto](https://docs.getmoto.org/) — no AWS account, no credentials, no cost.

Edit only `solution.py`:

1. `create_table(dynamodb, name)` creates a table with string partition key `pk` using on-demand
   capacity (`PAY_PER_REQUEST`) and waits until it exists.
2. `record_payment(dynamodb, table, payment_id, amount_cents)`:
   - rejects anything but a positive `int` amount with `ValueError`;
   - writes `pk = "payment#<payment_id>"` and `amount_cents` (a number) only if the key does not exist,
     using a condition expression (no read-then-write race);
   - returns `True` when written and `False` when the payment was already recorded (unchanged);
   - lets every other error propagate — never hide a missing table or throttling as "duplicate".

Run: `python -m pytest -c pytest.ini labs/dynamodb-idempotent-write`

Official references:

- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html
