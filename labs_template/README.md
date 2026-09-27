# SkillCoach code labs

Hands-on cloud practice that needs **no AWS account and no payment**. Each lab is a small Python task
checked by tests that run against [moto](https://docs.getmoto.org/), an open-source library that fakes
AWS services such as S3, DynamoDB and SQS in memory. Some labs are pure Python.

| Lab | Practises |
| --- | --- |
| `labs/s3-private-presigned` | Block Public Access, Object Ownership, SSE-S3, presigned URLs |
| `labs/lambda-function-url` | Function URL payload 2.0, status codes, configuration in environment |
| `labs/iam-least-privilege` | Explicit/implicit deny, wildcards, least-privilege policy |
| `labs/dynamodb-idempotent-write` | Conditional writes, on-demand capacity, safe retries |
| `labs/sqs-idempotent-consumer` | At-least-once delivery, visibility timeout, dead-letter queue |
| `labs/vpc-subnet-routing` | Reserved addresses, subnetting, longest-prefix routes, public subnets |

## Start

1. Choose **Use this template → Create a new repository** and make it **Public**. Standard GitHub-hosted
   runners are free for public repositories, and SkillCoach can only read public results.
2. Open it in **GitHub Codespaces** (personal accounts include a free monthly quota; stop the codespace
   when you finish) or clone it locally.
3. `pip install -r requirements-lab.txt`
4. Edit only `labs/<lab>/solution.py`, then run `python -m pytest -c pytest.ini labs/<lab>`.
5. Create `.skillcoach/<lab>.token` containing only the token SkillCoach gave you.
6. Commit and push. The **SkillCoach labs** workflow runs job `lab-<lab>`.
7. Send `/submitlab <lab> https://github.com/<you>/<repository>` to SkillCoach, or submit the link from
   the Labs section of your dashboard.

SkillCoach verifies the Git hashes of the protected files (`labs/*/test_lab.py`, `pytest.ini`,
`requirements-lab.txt`, `.github/check_report.py` and `.github/workflows/skillcoach-labs.yml`), your
token file and the result of the workflow job for that exact commit. Changing protected files fails the
check. This is a practice-integrity check, not proctoring: the point is to learn by doing.

## Rules

- Never commit AWS access keys, passwords or personal data. These labs never need real credentials.
- The token is a check code, not a secret; it only links the result to your SkillCoach lab.
- Free quotas and prices are set by GitHub and AWS and can change. Check your own account's billing
  pages if you use anything beyond this repository.

## More free practice

- [AWS Educate](https://aws.amazon.com/education/awseducate/): free self-paced AWS training and badges.
- [Killercoda](https://killercoda.com/): free browser-based Linux and Kubernetes scenarios.
- [AWS Skill Builder](https://skillbuilder.aws/): includes free digital courses.

Terraform learners can practise `terraform test` with mock providers
([docs](https://developer.hashicorp.com/terraform/language/tests/mocking)) without cloud credentials.
