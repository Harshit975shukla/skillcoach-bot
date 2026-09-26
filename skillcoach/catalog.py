"""Versioned Cloud/DevOps syllabus, not a claim of exhaustive vendor-product coverage."""

import re
from dataclasses import dataclass

CATALOG_VERSION = "2026-09-26"


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    reference: str
    topics: tuple[str, ...]


MODULES = (
    Module(
        "foundations",
        "Cloud foundations",
        "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
        (
            "Cloud service models and shared responsibility",
            "Regions availability zones and fault domains",
            "Virtualization and hypervisors",
            "Compute storage and network trade-offs",
            "Distributed systems fundamentals",
            "Capacity planning and performance baselines",
            "Cloud account organization and landing zones",
        ),
    ),
    Module(
        "linux",
        "Linux administration",
        "https://www.kernel.org/doc/html/latest/",
        (
            "Linux shell pipelines and text processing",
            "Linux filesystems permissions and ACLs",
            "Linux processes signals and systemd",
            "Linux memory CPU and IO troubleshooting",
            "Linux packages and patch management",
            "Linux networking and socket diagnostics",
            "Linux storage LVM mounts and filesystems",
            "Linux hardening SSH and audit logs",
        ),
    ),
    Module(
        "networking",
        "Networking and protocols",
        "https://www.rfc-editor.org/rfc/",
        (
            "TCP UDP and connection lifecycle",
            "DNS resolution caching and troubleshooting",
            "HTTP HTTPS TLS and certificates",
            "CIDR subnetting routing and NAT",
            "Load balancing proxies and health checks",
            "Firewalls security groups and network ACLs",
            "VPN private connectivity and hybrid networks",
            "IPv6 dual stack and service discovery",
            "CDNs caching and edge delivery",
        ),
    ),
    Module(
        "git",
        "Git and collaboration",
        "https://git-scm.com/docs",
        (
            "Git objects commits branches and remotes",
            "Git merge rebase and conflict resolution",
            "Git pull requests code review and branch protection",
            "Git release tags semantic versioning and changelogs",
            "Git bisect revert and incident recovery",
            "Git secrets signing and repository hygiene",
        ),
    ),
    Module(
        "automation",
        "Scripting and automation",
        "https://docs.python.org/3/",
        (
            "Python CLI automation and structured logging",
            "Bash robust scripts and exit handling",
            "PowerShell objects pipelines and automation",
            "REST APIs pagination retries and rate limits",
            "JSON YAML configuration and schema validation",
            "Idempotent automation and transactional workflows",
            "Unit integration contract and end-to-end testing",
        ),
    ),
    Module(
        "aws-core",
        "AWS compute and access",
        "https://docs.aws.amazon.com/",
        (
            "AWS EC2: instance types credits and purchasing",
            "AWS EC2: Auto Scaling and High Availability",
            "AWS IAM: roles policies and permission evaluation",
            "AWS VPC: subnets routing endpoints and NAT",
            "AWS Lambda: invocation concurrency and retries",
            "AWS Elastic Load Balancing and target health",
            "AWS Organizations Control Tower and SCPs",
            "AWS Systems Manager and fleet operations",
        ),
    ),
    Module(
        "aws-data",
        "AWS storage and data",
        "https://docs.aws.amazon.com/",
        (
            "AWS S3: ownership encryption lifecycle and checksums",
            "AWS RDS: Multi-AZ replicas backup and recovery",
            "AWS Aurora architecture and failover",
            "AWS DynamoDB partitioning consistency and capacity",
            "AWS EBS EFS and storage selection",
            "AWS ElastiCache Redis caching and eviction",
            "AWS OpenSearch indexing and operations",
            "AWS data migration and database replication",
        ),
    ),
    Module(
        "aws-platform",
        "AWS platform services",
        "https://docs.aws.amazon.com/",
        (
            "AWS ECS Fargate and ECR",
            "AWS EKS cluster operations",
            "AWS Route 53 and CloudFront",
            "AWS SQS SNS EventBridge and delivery semantics",
            "AWS API Gateway and service integration",
            "AWS Step Functions orchestration",
            "AWS CloudWatch CloudTrail and Config",
            "AWS KMS Secrets Manager and certificate management",
        ),
    ),
    Module(
        "azure",
        "Microsoft Azure",
        "https://learn.microsoft.com/azure/",
        (
            "Azure subscriptions management groups and landing zones",
            "Azure VMs VM Scale Sets and availability",
            "Azure Virtual Network routing private endpoints and DNS",
            "Microsoft Entra ID Azure RBAC and managed identities",
            "Azure Blob Storage Files and data protection",
            "Azure SQL Cosmos DB and managed databases",
            "Azure AKS and container operations",
            "Azure Functions App Service and Container Apps",
            "Azure Service Bus Event Hubs and Event Grid",
            "Azure Monitor Log Analytics and Application Insights",
            "Azure Key Vault and policy governance",
            "Azure Bicep ARM and deployment operations",
        ),
    ),
    Module(
        "gcp",
        "Google Cloud",
        "https://cloud.google.com/docs",
        (
            "Google Cloud organizations folders projects and billing",
            "Google Compute Engine and managed instance groups",
            "Google Cloud VPC firewall rules load balancing and DNS",
            "Google Cloud IAM service accounts and workload identity",
            "Google Cloud Storage lifecycle and access",
            "Google Cloud SQL Spanner and Firestore",
            "Google Kubernetes Engine operations",
            "Google Cloud Run and event-driven functions",
            "Google Pub Sub delivery ordering and retries",
            "Google Cloud Logging Monitoring and Trace",
            "Google Cloud KMS Secret Manager and organization policy",
        ),
    ),
    Module(
        "containers",
        "Containers",
        "https://docs.docker.com/",
        (
            "Docker images layers build cache and multi-stage builds",
            "Container runtime namespaces cgroups and isolation",
            "Container networking DNS and port publishing",
            "Container storage volumes and data persistence",
            "Container registries image tags and provenance",
            "Container security rootless builds and scanning",
            "Docker Compose local integration environments",
            "Container debugging resource limits and health checks",
        ),
    ),
    Module(
        "kubernetes",
        "Kubernetes",
        "https://kubernetes.io/docs/",
        (
            "Kubernetes control plane scheduling and reconciliation",
            "Kubernetes pods deployments and replica sets",
            "Kubernetes readiness liveness and startup probes",
            "Kubernetes services endpoints ingress and Gateway API",
            "Kubernetes CNI network policies and DNS",
            "Kubernetes persistent volumes CSI and StatefulSets",
            "Kubernetes ConfigMaps Secrets and workload configuration",
            "Kubernetes RBAC service accounts and workload identity",
            "Kubernetes requests limits QoS and eviction",
            "Kubernetes HPA VPA and cluster autoscaling",
            "Kubernetes affinity taints tolerations and topology spread",
            "Kubernetes disruption budgets draining and upgrades",
            "Kubernetes jobs CronJobs and operators",
            "Kubernetes troubleshooting events logs and ephemeral containers",
            "Kubernetes multi-cluster backup and disaster recovery",
        ),
    ),
    Module(
        "iac",
        "Infrastructure as code",
        "https://developer.hashicorp.com/terraform/docs",
        (
            "Terraform providers resources data sources and modules",
            "Terraform state locking backends and drift",
            "Terraform plans lifecycle dependencies and imports",
            "Terraform testing policy and sensitive outputs",
            "OpenTofu infrastructure workflows and compatibility",
            "Pulumi infrastructure programming and state",
            "Ansible inventory roles playbooks and idempotency",
            "Configuration drift patching and immutable infrastructure",
            "Infrastructure promotion environment isolation and rollback",
        ),
    ),
    Module(
        "delivery",
        "Continuous integration and delivery",
        "https://docs.github.com/actions",
        (
            "CI pipeline design stages artifacts and caching",
            "GitHub Actions permissions OIDC secrets and runners",
            "GitLab CI pipelines environments and deployment controls",
            "Jenkins pipelines agents credentials and shared libraries",
            "Build reproducibility dependency pinning and provenance",
            "Automated test strategy and flaky-test management",
            "Deployment blue-green canary and rolling strategies",
            "Database migrations backward compatibility and rollout",
            "Feature flags progressive delivery and rollback",
            "Release approvals change management and audit trails",
        ),
    ),
    Module(
        "gitops",
        "GitOps and package management",
        "https://argo-cd.readthedocs.io/en/stable/",
        (
            "GitOps reconciliation pull-based deployment and drift",
            "Argo CD applications sync waves and health",
            "Flux sources reconciliation and image automation",
            "Helm charts values releases and rollback",
            "Kustomize overlays patches and environment differences",
            "Secrets in GitOps external secrets and encryption",
            "Policy as code admission and deployment guardrails",
        ),
    ),
    Module(
        "observability",
        "Observability",
        "https://opentelemetry.io/docs/",
        (
            "Metrics logs traces and useful telemetry",
            "Prometheus scraping labels cardinality and PromQL",
            "Grafana dashboards alerts and operational context",
            "OpenTelemetry instrumentation propagation and collectors",
            "Centralized logging parsing retention and privacy",
            "Distributed tracing sampling and latency analysis",
            "Alert design routing deduplication and on-call noise",
            "Synthetic monitoring real-user monitoring and profiling",
            "Telemetry pipelines capacity security and cost",
        ),
    ),
    Module(
        "sre",
        "Site reliability engineering",
        "https://sre.google/books/",
        (
            "SLIs SLOs error budgets and reliability targets",
            "Incident command triage communication and escalation",
            "Blameless postmortems and corrective actions",
            "Reliability patterns timeouts retries jitter and circuit breakers",
            "Load shedding backpressure bulkheads and graceful degradation",
            "Capacity planning load tests and bottleneck analysis",
            "Disaster recovery RPO RTO backups and restore drills",
            "Chaos engineering hypothesis and blast-radius control",
            "Toil reduction runbooks and production readiness",
            "Availability design and dependency failure",
        ),
    ),
    Module(
        "security",
        "DevSecOps and supply-chain security",
        "https://owasp.org/www-project-devsecops-guideline/",
        (
            "Threat modeling trust boundaries and attack surfaces",
            "Least privilege identity federation and access reviews",
            "Secret management rotation and incident response",
            "SAST DAST SCA and container vulnerability scanning",
            "SBOM signed artifacts provenance and supply-chain controls",
            "Network segmentation zero trust and service authorization",
            "Encryption key management TLS and certificate rotation",
            "Compliance evidence policy enforcement and auditability",
            "Kubernetes workload security admission and runtime protection",
            "Secure software development and dependency updates",
        ),
    ),
    Module(
        "platform",
        "Platform engineering",
        "https://backstage.io/docs/",
        (
            "Internal developer platforms golden paths and self service",
            "Developer portals service catalogs and ownership",
            "Platform APIs tenancy quotas and isolation",
            "Crossplane control planes and infrastructure composition",
            "Service mesh traffic security and operational trade-offs",
            "Developer experience feedback and platform adoption",
            "Multi-environment governance and infrastructure standards",
        ),
    ),
    Module(
        "data",
        "Data and distributed messaging",
        "https://kafka.apache.org/documentation/",
        (
            "Relational database transactions isolation and indexes",
            "Database replication partitioning and consistency",
            "Redis caching invalidation TTL and stampede prevention",
            "Kafka partitions consumer groups offsets and delivery",
            "Message queues dead-letter handling and idempotency",
            "Stream versus batch processing and data pipelines",
            "Schema evolution data contracts and data quality",
        ),
    ),
    Module(
        "mlops",
        "MLOps and AI operations",
        "https://mlflow.org/docs/latest/",
        (
            "ML experiment tracking reproducibility and model registries",
            "Model serving scaling batching and GPU capacity",
            "Model monitoring drift data quality and rollback",
            "Feature pipelines online offline consistency and lineage",
            "LLM inference token budgets latency and caching",
            "RAG ingestion retrieval evaluation and access control",
            "AI evaluation safety privacy and prompt injection boundaries",
            "AI deployment costs quotas and operational reliability",
        ),
    ),
    Module(
        "finops",
        "FinOps and sustainability",
        "https://www.finops.org/framework/",
        (
            "Cloud cost allocation tags budgets and anomaly detection",
            "Compute rightsizing commitments and Spot trade-offs",
            "Storage retention lifecycle and retrieval costs",
            "Network egress NAT and cross-region cost analysis",
            "Kubernetes resource efficiency and unit economics",
            "Cost-aware architecture forecasting and accountability",
            "Sustainability resource utilization and workload scheduling",
        ),
    ),
    Module(
        "architecture",
        "Architecture and interview practice",
        "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
        (
            "High-availability multi-AZ application design",
            "Multi-region recovery versus active-active trade-offs",
            "System design requirements estimation and bottlenecks",
            "Monolith microservices and event-driven trade-offs",
            "API design versioning authentication and rate limiting",
            "Migration planning strangler patterns and rollback",
            "Technical decision records and stakeholder communication",
            "Behavioral interviews using honest evidence and reflection",
        ),
    ),
)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


TOPICS = {f"{module.id}/{slug(title)}": (module, title) for module in MODULES for title in module.topics}


def find_topic(value: str):
    normalized = value.strip().casefold()
    if normalized in TOPICS:
        return normalized, *TOPICS[normalized]
    for ident, (module, title) in TOPICS.items():
        if normalized == title.casefold():
            return ident, module, title
    return None


def catalog_text(module_id=""):
    if not module_id:
        return (
            f"Cloud/DevOps syllabus {CATALOG_VERSION}: {len(TOPICS)} topic entries.\n"
            "This is a versioned syllabus, not every vendor product/version.\n\n"
            + "\n".join(f"{module.id}: {module.title} ({len(module.topics)})" for module in MODULES)
            + "\n\nUse /topics <module_id>, then /learn <topic_id>."
        )
    module = next((module for module in MODULES if module.id == module_id.casefold()), None)
    if module is None:
        return "Unknown module. Use /topics for the module list."
    return (
        module.title
        + "\n\n"
        + "\n".join(f"{ident}\n{title}" for ident, (owner, title) in TOPICS.items() if owner.id == module.id)
        + "\n\nOfficial starting reference: "
        + module.reference
    )


def planning_catalog():
    return "\n".join(f"{module.title}: {', '.join(module.topics)}" for module in MODULES)
