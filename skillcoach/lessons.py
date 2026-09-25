"""Small authored architecture views; no external diagram service is used."""

ARCHITECTURES = {
    "ec2": """flowchart TD
    Client[Client] --> ALB[Load balancer]
    ALB --> AppA[EC2 app AZ A]
    ALB --> AppB[EC2 app AZ B]
    ASG[Auto Scaling Group] --> AppA
    ASG --> AppB
    Metrics[CloudWatch metrics] --> ASG
    AppA --> Data[Private data tier]
    AppB --> Data""",
    "s3": """flowchart LR
    Client[Authenticated request] --> Policies[Applicable policy evaluation]
    Ownership[Object Ownership disables ACLs] --> Policies
    Public[Block Public Access controls] --> Policies
    Policies --> Bucket[Private general purpose bucket]
    Bucket --> Object[Versioned encrypted object]
    Object --> Lifecycle[Configured lifecycle and retention]
    Object --> Checksums[Explicit integrity checksums]""",
    "rds": """flowchart TD
    App[Application connection pool] --> Primary[Traditional Multi AZ DB primary]
    Primary -->|synchronous replication| Standby[Standby in other AZ no reads]
    Primary -->|asynchronous replication| Replica[Optional read replica]
    App -->|explicit read routing| Replica
    Primary --> Backup[Backups and transaction logs]
    Backup --> Restore[New restored DB endpoint]""",
    "vpc": """flowchart TD
    Internet[Internet] --> ALB[Public ALB]
    ALB --> App[Private app subnet]
    App --> DB[Private data subnet]
    App -->|outbound| NAT[Zonal public NAT gateway]
    NAT --> IGW[Internet gateway]
    IGW --> Internet
    App --> Endpoint[S3 VPC endpoint]""",
    "iam": """flowchart LR
    Identity[Federated human or workload identity] --> Creds[Temporary credentials]
    Creds --> Sign[Signed service request]
    Sign --> Evaluate[Applicable policy evaluation]
    Boundaries[Boundaries SCPs and resource policies] --> Evaluate
    Evaluate --> Allow[Permitted service action]
    Evaluate --> Deny[Explicit deny or no applicable allow]""",
    "lambda": """flowchart LR
    API[Synchronous caller] --> Function[Lambda function]
    Events[Async event source] --> Queue[Lambda async queue and retry policy]
    Queue --> Function
    SQS[SQS queue visibility and redrive] --> Mapping[Event source mapping]
    Mapping --> Function
    Function --> Data[External durable state]
    Function --> Logs[Logs and metrics]
    Queue --> Failure[Configured failure destination]""",
}


def architecture(topic: str, concept: str | None = None) -> str:
    words = topic.lower().replace(":", " ").split()
    key = next((name for name in ARCHITECTURES if name in words), None)
    if key and concept is None:
        return ARCHITECTURES[key]
    # Generic generated-topic diagrams describe the exercise, not an invented system architecture.
    return """flowchart LR
    Understand[Understand the concept] --> Design[Define assumptions and constraints]
    Design --> Practice[Run a safe sandbox exercise]
    Practice --> Measure[Observe behavior and failure modes]
    Measure --> Cleanup[Clean up resources and record evidence]"""
