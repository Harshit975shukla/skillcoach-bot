"""Lab: private S3 bucket with a presigned download link. Edit only this file."""


def create_private_bucket(s3, name: str) -> None:
    """Create a private bucket: all Block Public Access settings on, ACLs disabled (BucketOwnerEnforced)."""
    raise NotImplementedError("Create the bucket, then configure Block Public Access and Object Ownership")


def upload_token(s3, bucket: str, key: str, token: str) -> None:
    """Upload the token as text/plain, encrypted with SSE-S3 (AES256)."""
    raise NotImplementedError("Upload the token object")


def share_link(s3, bucket: str, key: str, seconds: int) -> str:
    """Return a presigned GET URL valid for `seconds` (1-604800), otherwise raise ValueError."""
    raise NotImplementedError("Generate a presigned URL")
