"""Lab: Lambda Function URL handler (payload format 2.0). Edit only this file."""


def handler(event, context):
    """Route GET /health, reject other methods with 405 and unknown paths with 404."""
    raise NotImplementedError("Read event['requestContext']['http'] and return a response dict")
