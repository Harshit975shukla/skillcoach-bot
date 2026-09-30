"""Reviewed hands-on lab catalog: in-app scenarios, free code labs and optional learner-owned AWS checks.

Every lab has an in-app scenario route so no learner is forced to create a cloud account. Real AWS
routes are always optional, run in the learner's own account and are checked only through a public
URL that contains the learner's lab token. SkillCoach never asks for AWS credentials.
"""

import hashlib
import hmac
import secrets

from skillcoach.lab_models import AwsRoute, CodeRoute, Lab, LocalRoute, Step
from skillcoach.module_labs import MODULE_LABS

__all__ = ["AwsRoute", "CodeRoute", "Lab", "LocalRoute", "Step"]

LAB_CATALOG_VERSION = "2026-09-28"
REVIEWED = "2026-09-28 (checked against the linked official AWS documentation)"
WORKFLOW_PATH = ".github/workflows/skillcoach-labs.yml"
SHARED_PROTECTED = ("pytest.ini", "requirements-lab.txt", ".github/check_report.py", WORKFLOW_PATH)
TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROUTE_LABELS = {
    "scenario": "In-app scenario",
    "code": "Code lab (GitHub Actions)",
    "aws": "Your own AWS account",
    "local": "Practice locally (free, self-checked)",
}


COST = (
    "Cost and safety: use only an account you control, preferably a new account on the AWS Free plan or "
    "with credits. Create an AWS Budgets alert first. Charges depend on your account plan, Region and "
    "current pricing, so check the AWS pricing pages; SkillCoach cannot guarantee a lab is free. Never "
    "share access keys, passwords or screenshots of your console with SkillCoach or anyone else."
)

CODE_STEPS = (
    "Open github.com/{repo} and choose Use this template > Create a new repository. Make it Public so "
    "GitHub Actions minutes are free and SkillCoach can read the result. Do not fork private work into it.",
    "Open the new repository in a GitHub Codespace (free monthly quota on personal accounts) or clone it.",
    "Edit only labs/{lab}/solution.py. Run: pip install -r requirements-lab.txt && "
    "python -m pytest -c pytest.ini labs/{lab}",
    "Create .skillcoach/{lab}.token containing only your lab token: {token}",
    "Commit and push to the default branch. Wait for the SkillCoach labs workflow job lab-{lab} to pass.",
    "Submit: /submitlab {lab} https://github.com/<you>/<repository>. Tests, the workflow and pinned "
    "requirements must stay unchanged; SkillCoach checks their Git hashes and the Actions result.",
)

LABS = {
    lab.id: lab
    for lab in (
        Lab(
            id="s3-private-presigned",
            title="Private S3 object shared with a presigned URL",
            topics=("AWS S3: ownership encryption lifecycle and checksums",),
            minutes=30,
            goal="Keep a bucket private, then grant time-limited access to one object without making it public.",
            references=(
                "https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html",
                "https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html",
                "https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html",
                "https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-encryption-faq.html",
            ),
            scenario=(
                Step(
                    'A teammate saves a bucket policy granting s3:GetObject to Principal "*" on a bucket '
                    "where Block Public Access BlockPublicPolicy is enabled. What happens?",
                    (
                        "S3 rejects the PutBucketPolicy request because the policy would allow public access.",
                        "The policy is saved and every object becomes public.",
                        "The policy is saved but applies only to objects uploaded later.",
                        "S3 converts the policy into public object ACLs.",
                    ),
                    "BlockPublicPolicy makes S3 reject bucket-policy updates that would grant public access. "
                    "Keep all four Block Public Access settings on unless a reviewed design needs otherwise.",
                ),
                Step(
                    "Object Ownership is set to Bucket owner enforced (the default for new buckets). What is true?",
                    (
                        "ACLs are disabled; the bucket owner owns every object and policies control access.",
                        "Uploaders keep ownership of their objects through object ACLs.",
                        "ACLs are evaluated before bucket policies.",
                        "Public ACLs are automatically converted into bucket policy statements.",
                    ),
                    "With Bucket owner enforced, ACLs no longer affect permissions. Object Ownership is separate "
                    "from Block Public Access: one controls ACLs and ownership, the other blocks public grants.",
                ),
                Step(
                    "A partner must download one private object for one hour. What is the safest option?",
                    (
                        "Generate a presigned GET URL that expires after 3600 seconds.",
                        "Make the object public, then make it private again after an hour.",
                        "Send the partner your access keys and rotate them later.",
                        "Turn off Block Public Access for the bucket temporarily.",
                    ),
                    "A presigned URL uses the signer's permissions for a limited time. It stops working when it "
                    "expires, or earlier if the signing credentials expire or lose permission.",
                ),
                Step(
                    "An object is uploaded without encryption headers to a bucket with default settings. "
                    "How is it stored at rest?",
                    (
                        "Encrypted with SSE-S3, the default base level of encryption for new uploads.",
                        "Unencrypted unless you enable default encryption manually.",
                        "Encrypted with a customer managed KMS key that S3 creates for you.",
                        "The upload is rejected until an encryption header is added.",
                    ),
                    "Since January 2023, S3 applies SSE-S3 to all new object uploads by default at no additional "
                    "cost. Choose SSE-KMS when you need KMS key policies, auditing or key control.",
                ),
            ),
            aws=AwsRoute(
                kind="s3-presigned",
                steps=(
                    "Create a general purpose bucket with a name that contains no dots. Keep Block Public Access "
                    "fully enabled and Object Ownership as Bucket owner enforced.",
                    "Create a text file named skillcoach-token.txt containing only your lab token: {token}",
                    "Upload it: aws s3 cp skillcoach-token.txt s3://<bucket>/skillcoach-token.txt",
                    "Create a one-hour link: aws s3 presign s3://<bucket>/skillcoach-token.txt "
                    "--expires-in 3600 --region <region>",
                ),
                cleanup=(
                    "aws s3 rm s3://<bucket>/skillcoach-token.txt",
                    "aws s3 rb s3://<bucket>",
                    "Confirm with /labcleanup s3-private-presigned <the same presigned URL>.",
                ),
                submit="/submitlab s3-private-presigned <presigned URL>. SkillCoach checks that the signed "
                "link returns your token and that the same object is denied without a signature.",
            ),
            code=CodeRoute(CODE_STEPS),
        ),
        Lab(
            id="lambda-function-url",
            title="Lambda handler behind a Function URL",
            topics=("AWS Lambda: invocation concurrency and retries",),
            minutes=30,
            goal="Return correct HTTP responses from a Lambda Function URL handler and understand its public exposure.",
            references=(
                "https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html",
                "https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html",
                "https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html",
                "https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html",
            ),
            scenario=(
                Step(
                    "An S3 event invokes your function asynchronously and your code raises an error every time. "
                    "What does Lambda do by default?",
                    (
                        "It runs the function two more times, then discards the event unless a failure "
                        "destination or dead-letter queue is configured.",
                        "It never retries asynchronous events.",
                        "It retries forever until the function succeeds.",
                        "It asks S3 to resend the event every minute.",
                    ),
                    "By default Lambda retries function errors twice for asynchronous invocations (waiting one "
                    "then two minutes). Capture failures with an on-failure destination or a DLQ.",
                ),
                Step(
                    "Reserved concurrency is 5 and 20 synchronous requests arrive at the same moment. "
                    "What happens to requests beyond the available concurrency?",
                    (
                        "They are throttled with a 429 TooManyRequestsException, so callers should retry.",
                        "Lambda queues them internally until an instance is free.",
                        "Lambda temporarily raises the reserved concurrency.",
                        "They run in another Region automatically.",
                    ),
                    "Reserved concurrency is also a maximum. Synchronous callers receive throttling errors "
                    "and must retry with backoff; asynchronous events are retried by Lambda's queue.",
                ),
                Step(
                    "A Function URL uses auth type NONE with a resource policy that allows public invocation. "
                    "Who can call it?",
                    (
                        "Anyone who knows the URL, because Lambda performs no authentication.",
                        "Only IAM users in the same account.",
                        "Only callers inside your VPC.",
                        "Nobody until you create API keys.",
                    ),
                    "NONE is public access controlled only by the resource-based policy. Never return secrets, "
                    "add your own authorization if needed, and delete lab URLs after verification.",
                ),
                Step(
                    "Your Function URL handler returns a JSON object without statusCode. What does the client get?",
                    (
                        "HTTP 200 with the object as a JSON body; Lambda infers the response format.",
                        "HTTP 502, because statusCode is mandatory.",
                        "HTTP 204 with an empty body.",
                        "The invocation is retried twice.",
                    ),
                    "For Function URLs, valid JSON without statusCode becomes 200, application/json and the "
                    "returned value as the body. Return explicit status codes for errors such as 404 or 405.",
                ),
            ),
            aws=AwsRoute(
                kind="lambda-url",
                steps=(
                    "Create a Python Lambda function. Replace the code with a handler that returns "
                    '{{"status": "ok", "token": "{token}"}} and deploy it.',
                    "Configuration > Function URL > Create. Choose auth type NONE only for this short check; the "
                    "console adds the resource-based policy for public invocation.",
                    "Open the URL once in a browser to confirm it returns your token.",
                ),
                cleanup=(
                    "Delete the Function URL, then delete the function and its CloudWatch log group.",
                    "Confirm with /labcleanup lambda-function-url <the same URL>.",
                ),
                submit="/submitlab lambda-function-url https://<id>.lambda-url.<region>.on.aws/",
            ),
            code=CodeRoute(CODE_STEPS),
        ),
        Lab(
            id="iam-least-privilege",
            title="Evaluate IAM policies like AWS does",
            topics=(
                "AWS IAM: roles policies and permission evaluation",
                "Least privilege identity federation and access reviews",
            ),
            minutes=35,
            goal="Apply explicit deny, implicit deny and wildcard matching, then write a least-privilege policy.",
            references=(
                "https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html",
                "https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html",
                "https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html",
            ),
            scenario=(
                Step(
                    "An identity policy allows s3:* on a bucket, but the bucket policy explicitly denies "
                    "s3:DeleteObject for that user. Can the user delete objects?",
                    (
                        "No. An explicit deny in any applicable policy overrides every allow.",
                        "Yes, identity policies are evaluated after bucket policies.",
                        "Yes, because s3:* is broader than s3:DeleteObject.",
                        "Only if the objects were uploaded by the same user.",
                    ),
                    "Evaluation starts with explicit denies. A single applicable Deny wins over any Allow.",
                ),
                Step(
                    "In one account, a user's identity policy allows s3:GetObject on an object and the bucket "
                    "policy does not mention the user. No deny, SCP or boundary applies. Result?",
                    (
                        "Allowed: within one account, an allow in either the identity or resource policy is enough.",
                        "Denied, because the bucket policy must also allow the user.",
                        "Allowed only if the object is public.",
                        "Denied, because resource policies deny by default.",
                    ),
                    "Same-account access needs an allow from an identity-based or resource-based policy and no "
                    "explicit deny. Cross-account access needs both sides to allow it.",
                ),
                Step(
                    "An SCP allows only ec2:* in a member account. A role there has AdministratorAccess. "
                    "Can it call s3:ListBucket?",
                    (
                        "No. SCPs set the maximum available permissions and never grant permissions themselves.",
                        "Yes, AdministratorAccess overrides SCPs.",
                        "Yes, SCPs apply only to IAM users, not roles.",
                        "Only in the us-east-1 Region.",
                    ),
                    "SCPs limit principals in member accounts (not the management account). Identity policies "
                    "still have to grant access inside that limit.",
                ),
                Step(
                    "An application on EC2 must read one S3 prefix. What is the best credential approach?",
                    (
                        "Attach an IAM role through an instance profile scoped to that prefix.",
                        "Create an IAM user and store its access keys in the AMI.",
                        "Use the root user's keys as environment variables.",
                        "Grant AdministratorAccess to avoid permission errors.",
                    ),
                    "Roles provide temporary credentials that rotate automatically. Scope actions and resources "
                    "to what the workload needs and review access regularly.",
                ),
            ),
            code=CodeRoute(CODE_STEPS),
        ),
        Lab(
            id="api-gateway-health",
            title="HTTP API health route with Lambda",
            topics=("AWS API Gateway and service integration",),
            minutes=35,
            goal="Expose a Lambda-backed GET /health route through an HTTP API and understand API Gateway errors.",
            references=(
                "https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html",
                "https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html",
                "https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html",
                "https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-request-throttling.html",
            ),
            scenario=(
                Step(
                    "You need per-customer API keys and usage plans. Which API Gateway API type fits?",
                    (
                        "A REST API; HTTP APIs do not support API keys or usage plans.",
                        "An HTTP API, which is the only type with usage plans.",
                        "A WebSocket API, because it meters each message.",
                        "Any type; usage plans are configured on Lambda.",
                    ),
                    "HTTP APIs are simpler and cheaper for many proxies, but API keys and usage plans are "
                    "REST API features. Compare features before choosing.",
                ),
                Step(
                    "A REST API Lambda proxy integration returns a plain string instead of statusCode, headers "
                    "and body. What does the client receive?",
                    (
                        "502 Bad Gateway, because the Lambda proxy response is malformed.",
                        "200 with the string as the body.",
                        "404 Not Found.",
                        "The request is retried by API Gateway until it succeeds.",
                    ),
                    "REST API proxy integrations require the documented response shape. Malformed output is "
                    "reported to clients as a 502 and logged as a malformed Lambda proxy response.",
                ),
                Step(
                    "A browser app on another origin calls your HTTP API and fails with a CORS error. Where do "
                    "you fix it?",
                    (
                        "Configure CORS on the HTTP API; API Gateway then answers preflight OPTIONS requests.",
                        "Disable HTTPS on the API.",
                        "Add the browser's IP address to the Lambda resource policy.",
                        "Increase the Lambda timeout.",
                    ),
                    "With CORS configured on an HTTP API, API Gateway responds to preflight requests and adds "
                    "the configured headers. Allow only the origins, methods and headers you need.",
                ),
                Step(
                    "During a spike, clients receive 429 Too Many Requests from API Gateway. What does it mean?",
                    (
                        "Requests exceeded throttling limits; clients should retry with backoff.",
                        "The Lambda function has a syntax error.",
                        "The TLS certificate expired.",
                        "The route does not exist.",
                    ),
                    "API Gateway applies account, stage and route throttling. Use retries with jitter and set "
                    "limits that protect your backend.",
                ),
            ),
            aws=AwsRoute(
                kind="api-health",
                steps=(
                    'Create a Python Lambda function returning {{"status": "ok", "token": "{token}"}}.',
                    "API Gateway > Create API > HTTP API. Add a Lambda integration for that function.",
                    "Create route GET /health using the integration and keep the $default stage with auto-deploy.",
                    "Open https://<api-id>.execute-api.<region>.amazonaws.com/health and confirm your token.",
                ),
                cleanup=(
                    "Delete the HTTP API, the Lambda function and its CloudWatch log group.",
                    "Confirm with /labcleanup api-gateway-health <the same /health URL>.",
                ),
                submit="/submitlab api-gateway-health https://<api-id>.execute-api.<region>.amazonaws.com/health",
            ),
        ),
        Lab(
            id="cloudfront-private-origin",
            title="CloudFront in front of a private S3 origin",
            topics=("AWS Route 53 and CloudFront", "CDNs caching and edge delivery"),
            minutes=45,
            goal="Serve a private S3 object through CloudFront with origin access control and reason about caching.",
            references=(
                "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html",
                "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Invalidation.html",
                "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/ConfiguringCaching.html",
            ),
            scenario=(
                Step(
                    "You want CloudFront to serve content from an S3 bucket that stays private. What is recommended?",
                    (
                        "Origin access control (OAC) plus a bucket policy allowing only that distribution.",
                        "Make the bucket public and keep the S3 URL secret.",
                        "Use an S3 website endpoint with OAC.",
                        "Give CloudFront an IAM user's access keys.",
                    ),
                    "OAC signs origin requests; the bucket policy allows the CloudFront service principal with "
                    "the distribution ARN as a condition, so direct public access remains blocked.",
                ),
                Step(
                    "You replaced style.css in S3, but users still receive the old file through CloudFront. Why?",
                    (
                        "Edge caches serve the cached copy until it expires; invalidate the path or version file names.",
                        "S3 is still replicating the old object to all Regions.",
                        "CloudFront never caches CSS files.",
                        "The bucket policy blocks updated objects.",
                    ),
                    "Invalidations remove cached objects before expiry; versioned names such as style.v2.css "
                    "avoid invalidation cost and stale mixes.",
                ),
                Step(
                    "A response contains the header X-Cache: Hit from cloudfront. What happened?",
                    (
                        "The edge location served the object from its cache without contacting the origin.",
                        "The origin returned an error.",
                        "The object was fetched from S3 for this request.",
                        "The request bypassed CloudFront.",
                    ),
                    "Miss means CloudFront fetched from the origin; Hit means the cached copy served the request.",
                ),
                Step(
                    "Can OAC protect an S3 static website endpoint origin?",
                    (
                        "No. Website endpoints are custom origins; use the bucket's REST endpoint with OAC.",
                        "Yes, OAC works with every S3 endpoint.",
                        "Yes, but only in us-east-1.",
                        "Only if the website endpoint is public.",
                    ),
                    "Use the regular bucket endpoint as the origin for OAC. Website endpoints do not support it.",
                ),
            ),
            aws=AwsRoute(
                kind="cloudfront",
                steps=(
                    "Create a private bucket (Block Public Access on) and upload skillcoach-token.txt containing "
                    "only your token: {token}",
                    "CloudFront > Create distribution. Choose the bucket as the origin (not the website endpoint) "
                    "and create origin access control. Apply the bucket policy the console provides.",
                    "When deployment finishes, open https://<distribution>.cloudfront.net/skillcoach-token.txt.",
                ),
                cleanup=(
                    "Disable the distribution, wait until it is deployed, then delete it and its OAC.",
                    "Empty and delete the bucket.",
                    "Confirm with /labcleanup cloudfront-private-origin <the same CloudFront URL>.",
                ),
                submit="/submitlab cloudfront-private-origin https://<distribution>.cloudfront.net/skillcoach-token.txt",
            ),
        ),
        Lab(
            id="dynamodb-idempotent-write",
            title="Idempotent DynamoDB writes with conditions",
            topics=("AWS DynamoDB partitioning consistency and capacity",),
            minutes=35,
            goal="Record each payment once with a conditional write, even when a client retries.",
            references=(
                "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html",
                "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html",
                "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html",
                "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html",
            ),
            scenario=(
                Step(
                    "PutItem uses ConditionExpression attribute_not_exists(pk) and the key already exists. Result?",
                    (
                        "The write fails with ConditionalCheckFailedException and the item is unchanged.",
                        "The item is overwritten silently.",
                        "DynamoDB creates a second item with the same key.",
                        "The write waits until the old item expires.",
                    ),
                    "Conditional writes make retries safe: treat ConditionalCheckFailedException as "
                    "'already recorded' when the key represents the same business operation.",
                ),
                Step(
                    "You write an item, then immediately query a global secondary index for it. What can happen?",
                    (
                        "It may not appear yet; GSIs support only eventually consistent reads.",
                        "Use ConsistentRead=true on the GSI to see it immediately.",
                        "The write fails until the GSI is updated.",
                        "GSIs are updated before the base table.",
                    ),
                    "Global secondary indexes are updated asynchronously. Read the base table with a strongly "
                    "consistent read when you need your own latest write.",
                ),
                Step(
                    "All writes use today's date as the partition key, and writes are throttled. What helps?",
                    (
                        "Spread writes across more partition key values, for example with a shard suffix.",
                        "Add more sort key attributes.",
                        "Switch reads to strongly consistent.",
                        "Create a local secondary index.",
                    ),
                    "A single hot key concentrates traffic. Design keys with high cardinality or shard them.",
                ),
                Step(
                    "Traffic is spiky and unpredictable, and you do not want to manage capacity. Which mode?",
                    (
                        "On-demand capacity mode, billed per request.",
                        "Provisioned mode with fixed capacity and no auto scaling.",
                        "Local secondary indexes.",
                        "DynamoDB Streams.",
                    ),
                    "On-demand removes capacity planning for variable workloads; table and account quotas still "
                    "apply. Provisioned capacity can cost less for steady, predictable traffic.",
                ),
            ),
            code=CodeRoute(CODE_STEPS),
        ),
        Lab(
            id="sqs-idempotent-consumer",
            title="Idempotent SQS consumer with a dead-letter queue",
            topics=(
                "AWS SQS SNS EventBridge and delivery semantics",
                "Message queues dead-letter handling and idempotency",
            ),
            minutes=40,
            goal="Process at-least-once messages safely, keep failures for retry and route poison messages to a DLQ.",
            references=(
                "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html",
                "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html",
                "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html",
                "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/using-messagededuplicationid-property.html",
            ),
            scenario=(
                Step(
                    "A standard queue consumer occasionally receives the same message twice. Why, and what should "
                    "you do?",
                    (
                        "Standard queues deliver at least once; make processing idempotent.",
                        "It is a bug; standard queues deliver exactly once.",
                        "Enable long polling to prevent duplicates.",
                        "Increase the message retention period.",
                    ),
                    "Record processed business keys or use conditional writes so a duplicate does not repeat "
                    "side effects such as charging a card.",
                ),
                Step(
                    "Processing takes 90 seconds but the visibility timeout is 30 seconds. What happens?",
                    (
                        "The message becomes visible again and another consumer may process it concurrently.",
                        "SQS deletes the message after 30 seconds.",
                        "SQS pauses the consumer until processing ends.",
                        "The message moves to the dead-letter queue immediately.",
                    ),
                    "Set the visibility timeout above normal processing time or extend it with "
                    "ChangeMessageVisibility while work continues.",
                ),
                Step(
                    "The redrive policy has maxReceiveCount 3 and a message keeps failing. What happens?",
                    (
                        "After it has been received three times without deletion, SQS moves it to the DLQ.",
                        "SQS deletes it after the first failure.",
                        "It stays in the source queue forever.",
                        "SQS retries it three times per second.",
                    ),
                    "When the receive count exceeds maxReceiveCount, SQS moves the message to the dead-letter "
                    "queue for inspection and redrive.",
                ),
                Step(
                    "A FIFO queue receives two sends with the same MessageDeduplicationId within five minutes. Result?",
                    (
                        "Both sends succeed, but the duplicate is not delivered again.",
                        "The second send fails with an error.",
                        "Both messages are delivered in order.",
                        "The first message is replaced by the second.",
                    ),
                    "FIFO deduplication accepts duplicate sends during the five-minute interval without "
                    "delivering them. Consumers still need idempotent side effects.",
                ),
            ),
            code=CodeRoute(CODE_STEPS),
        ),
        Lab(
            id="vpc-subnet-routing",
            title="VPC subnet sizing and route selection",
            topics=("AWS VPC: subnets routing endpoints and NAT", "CIDR subnetting routing and NAT"),
            minutes=35,
            goal="Size subnets with AWS reserved addresses, choose routes by longest prefix and identify public subnets.",
            references=(
                "https://docs.aws.amazon.com/vpc/latest/userguide/subnet-sizing.html",
                "https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Route_Tables.html",
                "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html",
                "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html",
            ),
            scenario=(
                Step(
                    "What makes a subnet public in a VPC?",
                    (
                        "Its route table has a route, usually 0.0.0.0/0, to an internet gateway.",
                        "Its name contains 'public'.",
                        "It has more than 256 addresses.",
                        "Its network ACL allows all traffic.",
                    ),
                    "Instances also need public IP addresses, but the internet gateway route is what makes the "
                    "subnet public.",
                ),
                Step(
                    "Instances in a private subnet need outbound internet access for updates but no inbound access. "
                    "What do you add?",
                    (
                        "A route 0.0.0.0/0 to a NAT gateway placed in a public subnet.",
                        "A route 0.0.0.0/0 directly to the internet gateway from the private subnet.",
                        "Public IP addresses on every instance.",
                        "A security group rule allowing all inbound traffic.",
                    ),
                    "A NAT gateway lets private instances start outbound connections while unsolicited inbound "
                    "connections are not allowed. NAT gateways are billed hourly and per GB.",
                ),
                Step(
                    "A security group allows inbound 443. The network ACL allows inbound 443 but denies all "
                    "outbound traffic. Do HTTPS responses reach clients?",
                    (
                        "No. Network ACLs are stateless, so outbound ephemeral ports must be allowed too.",
                        "Yes. Network ACLs remember allowed inbound connections.",
                        "Yes. Security groups override network ACLs.",
                        "Only for IPv6 clients.",
                    ),
                    "Security groups are stateful; network ACLs evaluate each direction separately.",
                ),
                Step(
                    "How many IPv4 addresses can you assign to instances in a /28 subnet?",
                    (
                        "11, because AWS reserves 5 of the 16 addresses in every subnet.",
                        "16.",
                        "14, as in traditional networks.",
                        "12.",
                    ),
                    "AWS reserves the first four addresses and the last address of each subnet CIDR block.",
                ),
            ),
            code=CodeRoute(CODE_STEPS),
        ),
    )
}


# One or more labs for every catalog module: the per-module labs add free local practice routes.
LABS.update({lab.id: lab for lab in MODULE_LABS})


def labs_for_topic(title):
    return [lab for lab in LABS.values() if title in lab.topics]


def new_token():
    groups = ("".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4)) for _ in range(2))
    return "SC-" + "-".join(groups)


def required_quota(minutes):
    return 1 if minutes <= 30 else 2


def url_digest(token, value):
    # Salted with the random per-assignment token so the verified link itself is never stored.
    return hmac.new(("skillcoach-lab-link:" + token).encode(), value.encode(), hashlib.sha256).hexdigest()


def blob_sha(data: bytes):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def token_blob_shas(token):
    return {blob_sha(token.encode() + suffix) for suffix in (b"", b"\n", b"\r\n")}


CODE_LABS = (
    "s3-private-presigned",
    "lambda-function-url",
    "iam-least-privilege",
    "dynamodb-idempotent-write",
    "sqs-idempotent-consumer",
    "vpc-subnet-routing",
)
# Git blob SHAs of the protected template files (LF endings). tests/test_labs.py recomputes them.
SHARED_BLOBS = {
    "pytest.ini": "71ca9e4f58dce22daf9d6665b869dcd20d1742ea",
    "requirements-lab.txt": "87f01171a05f495fb27ba9223627eab261b28fb4",
    ".github/check_report.py": "d9a9a19a1f740cd610cd02a2282a8f20233ec5fc",
    WORKFLOW_PATH: "3e3a8c421efed64bd722257ba63120fd03afb944",
}
LAB_TEST_BLOBS = {
    "s3-private-presigned": "9321686acb0f64212a21b5b1322aca31922aa70d",
    "lambda-function-url": "65793993f99b4b8593a3203c51d5172127c1bccd",
    "iam-least-privilege": "948050428dec9b0b0ff5c7447816392c9afa68a7",
    "dynamodb-idempotent-write": "ed0c6d68a616f5891589742d8795271a2f6d51fa",
    "sqs-idempotent-consumer": "ce70f55f78358f8025cc95078cc3ccd389618bf2",
    "vpc-subnet-routing": "7a0c95b4a7d0646da1aaa7f0b03cd53b0ddf8470",
}
TEMPLATE_BLOBS = {lab: {**SHARED_BLOBS, f"labs/{lab}/test_lab.py": LAB_TEST_BLOBS[lab]} for lab in CODE_LABS}


def lab_steps(lab, route, token, repo):
    if route == "aws" and lab.aws:
        return [s.format(token=token) for s in lab.aws.steps], list(lab.aws.cleanup), lab.aws.submit
    if route == "code" and lab.code:
        steps = [s.format(repo=repo, lab=lab.id, token=token) for s in lab.code.steps]
        return steps, [], f"/submitlab {lab.id} https://github.com/<you>/<repository>"
    if route == "local" and lab.local:
        return ["Free tools: " + lab.local.tools, *lab.local.steps], list(lab.local.cleanup), ""
    return [], [], ""
