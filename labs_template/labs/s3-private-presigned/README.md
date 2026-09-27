# Lab: private S3 object shared with a presigned URL

Goal: keep a bucket private, then grant time-limited access to one object without making it public.
Runs locally against [moto](https://docs.getmoto.org/) — no AWS account, no credentials, no cost.

Edit only `solution.py`:

1. `create_private_bucket(s3, name)` creates the bucket in the client's Region (outside `us-east-1`,
   S3 requires a `LocationConstraint`), turns on all four Block Public Access settings and sets Object
   Ownership to `BucketOwnerEnforced`.
2. `upload_token(s3, bucket, key, token)` stores the token as `text/plain` with SSE-S3 (`AES256`).
3. `share_link(s3, bucket, key, seconds)` returns a presigned GET URL. Reject expiry outside
   1–604800 seconds (7 days, the SigV4 maximum) with `ValueError`.

Run: `python -m pytest -c pytest.ini labs/s3-private-presigned`

Official references:

- https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html
