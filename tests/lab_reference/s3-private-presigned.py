"""Private reference solution for the s3-private-presigned code lab. Never publish."""


def create_private_bucket(s3, name: str) -> None:
    region = s3.meta.region_name
    options = {} if region == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": region}}
    s3.create_bucket(Bucket=name, **options)
    s3.put_public_access_block(
        Bucket=name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_ownership_controls(
        Bucket=name, OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
    )


def upload_token(s3, bucket: str, key: str, token: str) -> None:
    s3.put_object(
        Bucket=bucket, Key=key, Body=token.encode(), ContentType="text/plain", ServerSideEncryption="AES256"
    )


def share_link(s3, bucket: str, key: str, seconds: int) -> str:
    if type(seconds) is not int or not 1 <= seconds <= 604800:
        raise ValueError("Presigned URL expiry must be 1-604800 seconds")
    return s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=seconds)
