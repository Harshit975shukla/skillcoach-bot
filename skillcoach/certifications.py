"""Certification-prep tracks mapped to official exam domains.

Domains, weights and formats were checked against the vendors' official exam guides and curriculum
pages on 2026-09-30. Practice questions are original and exam-style, never real exam content.
Readiness summarizes evidence from this app only; it is not a prediction of an exam result.
"""

from dataclasses import dataclass

VERIFIED = "2026-09-30"
SESSION_SIZE = 5
MIN_ANSWERS = 5
DISCLAIMER = (
    "Readiness reflects your practice in SkillCoach only. It is not affiliated with or endorsed by the "
    "exam provider and does not predict your exam result. Check the official exam guide before booking."
)


@dataclass(frozen=True)
class Domain:
    name: str
    weight: int | None
    topics: tuple[str, ...]


@dataclass(frozen=True)
class Track:
    id: str
    name: str
    code: str
    format: str
    source: str
    hands_on: bool
    labs: tuple[str, ...]
    domains: tuple[Domain, ...]


TRACKS = {
    track.id: track
    for track in (
        Track(
            id="aws-ccp",
            name="AWS Certified Cloud Practitioner",
            code="CLF-C02",
            format="65 multiple-choice and multiple-response questions (50 scored). Passing score 700 of 1000.",
            source="https://d1.awsstatic.com/training-and-certification/docs-cloud-practitioner/"
            "AWS-Certified-Cloud-Practitioner_Exam-Guide.pdf",
            hands_on=False,
            labs=(
                "s3-private-presigned",
                "iam-least-privilege",
                "fault-domain-calculator",
                "cost-allocation-tags",
            ),
            domains=(
                Domain(
                    "Cloud Concepts",
                    24,
                    (
                        "foundations/cloud-service-models-and-shared-responsibility",
                        "foundations/regions-availability-zones-and-fault-domains",
                        "foundations/compute-storage-and-network-trade-offs",
                        "architecture/high-availability-multi-az-application-design",
                        "architecture/migration-planning-strangler-patterns-and-rollback",
                    ),
                ),
                Domain(
                    "Security and Compliance",
                    30,
                    (
                        "foundations/cloud-service-models-and-shared-responsibility",
                        "aws-core/aws-iam-roles-policies-and-permission-evaluation",
                        "aws-core/aws-organizations-control-tower-and-scps",
                        "aws-platform/aws-kms-secrets-manager-and-certificate-management",
                        "aws-platform/aws-cloudwatch-cloudtrail-and-config",
                        "networking/firewalls-security-groups-and-network-acls",
                        "security/compliance-evidence-policy-enforcement-and-auditability",
                    ),
                ),
                Domain(
                    "Cloud Technology and Services",
                    34,
                    (
                        "aws-core/aws-ec2-instance-types-credits-and-purchasing",
                        "aws-core/aws-lambda-invocation-concurrency-and-retries",
                        "aws-core/aws-vpc-subnets-routing-endpoints-and-nat",
                        "aws-core/aws-elastic-load-balancing-and-target-health",
                        "aws-data/aws-s3-ownership-encryption-lifecycle-and-checksums",
                        "aws-data/aws-rds-multi-az-replicas-backup-and-recovery",
                        "aws-data/aws-dynamodb-partitioning-consistency-and-capacity",
                        "aws-platform/aws-route-53-and-cloudfront",
                        "aws-platform/aws-ecs-fargate-and-ecr",
                        "aws-platform/aws-sqs-sns-eventbridge-and-delivery-semantics",
                    ),
                ),
                Domain(
                    "Billing, Pricing, and Support",
                    12,
                    (
                        "finops/cloud-cost-allocation-tags-budgets-and-anomaly-detection",
                        "finops/compute-rightsizing-commitments-and-spot-trade-offs",
                        "aws-core/aws-ec2-instance-types-credits-and-purchasing",
                        "aws-core/aws-organizations-control-tower-and-scps",
                    ),
                ),
            ),
        ),
        Track(
            id="aws-saa",
            name="AWS Certified Solutions Architect – Associate",
            code="SAA-C03",
            format="65 multiple-choice and multiple-response questions (50 scored). Passing score 720 of 1000.",
            source="https://d1.awsstatic.com/training-and-certification/docs-sa-assoc/"
            "AWS-Certified-Solutions-Architect-Associate_Exam-Guide.pdf",
            hands_on=False,
            labs=(
                "vpc-subnet-routing",
                "iam-least-privilege",
                "s3-private-presigned",
                "cloudfront-private-origin",
                "sqs-idempotent-consumer",
                "dynamodb-idempotent-write",
            ),
            domains=(
                Domain(
                    "Design Secure Architectures",
                    30,
                    (
                        "aws-core/aws-iam-roles-policies-and-permission-evaluation",
                        "aws-core/aws-organizations-control-tower-and-scps",
                        "aws-core/aws-vpc-subnets-routing-endpoints-and-nat",
                        "networking/firewalls-security-groups-and-network-acls",
                        "aws-platform/aws-kms-secrets-manager-and-certificate-management",
                        "aws-data/aws-s3-ownership-encryption-lifecycle-and-checksums",
                        "security/least-privilege-identity-federation-and-access-reviews",
                    ),
                ),
                Domain(
                    "Design Resilient Architectures",
                    26,
                    (
                        "aws-core/aws-ec2-auto-scaling-and-high-availability",
                        "aws-core/aws-elastic-load-balancing-and-target-health",
                        "aws-data/aws-rds-multi-az-replicas-backup-and-recovery",
                        "aws-data/aws-aurora-architecture-and-failover",
                        "aws-platform/aws-sqs-sns-eventbridge-and-delivery-semantics",
                        "architecture/multi-region-recovery-versus-active-active-trade-offs",
                        "sre/disaster-recovery-rpo-rto-backups-and-restore-drills",
                        "architecture/monolith-microservices-and-event-driven-trade-offs",
                    ),
                ),
                Domain(
                    "Design High-Performing Architectures",
                    24,
                    (
                        "aws-data/aws-elasticache-redis-caching-and-eviction",
                        "aws-data/aws-dynamodb-partitioning-consistency-and-capacity",
                        "aws-data/aws-ebs-efs-and-storage-selection",
                        "aws-platform/aws-route-53-and-cloudfront",
                        "aws-core/aws-lambda-invocation-concurrency-and-retries",
                        "aws-core/aws-ec2-instance-types-credits-and-purchasing",
                        "networking/cdns-caching-and-edge-delivery",
                    ),
                ),
                Domain(
                    "Design Cost-Optimized Architectures",
                    20,
                    (
                        "finops/compute-rightsizing-commitments-and-spot-trade-offs",
                        "finops/storage-retention-lifecycle-and-retrieval-costs",
                        "finops/network-egress-nat-and-cross-region-cost-analysis",
                        "finops/cost-aware-architecture-forecasting-and-accountability",
                        "aws-core/aws-ec2-instance-types-credits-and-purchasing",
                    ),
                ),
            ),
        ),
        Track(
            id="cka",
            name="Certified Kubernetes Administrator",
            code="CKA (curriculum v1.35)",
            format="Online, performance-based command-line tasks in 2 hours. Passing score 66%.",
            source="https://training.linuxfoundation.org/certification/certified-kubernetes-administrator-cka/",
            hands_on=True,
            labs=("probe-failing-pod", "process-signal-triage"),
            domains=(
                Domain("Storage", 10, ("kubernetes/kubernetes-persistent-volumes-csi-and-statefulsets",)),
                Domain(
                    "Troubleshooting",
                    30,
                    (
                        "kubernetes/kubernetes-troubleshooting-events-logs-and-ephemeral-containers",
                        "kubernetes/kubernetes-readiness-liveness-and-startup-probes",
                        "kubernetes/kubernetes-requests-limits-qos-and-eviction",
                        "linux/linux-networking-and-socket-diagnostics",
                    ),
                ),
                Domain(
                    "Workloads & Scheduling",
                    15,
                    (
                        "kubernetes/kubernetes-pods-deployments-and-replica-sets",
                        "kubernetes/kubernetes-configmaps-secrets-and-workload-configuration",
                        "kubernetes/kubernetes-affinity-taints-tolerations-and-topology-spread",
                        "kubernetes/kubernetes-hpa-vpa-and-cluster-autoscaling",
                        "kubernetes/kubernetes-jobs-cronjobs-and-operators",
                    ),
                ),
                Domain(
                    "Cluster Architecture, Installation & Configuration",
                    25,
                    (
                        "kubernetes/kubernetes-control-plane-scheduling-and-reconciliation",
                        "kubernetes/kubernetes-rbac-service-accounts-and-workload-identity",
                        "kubernetes/kubernetes-disruption-budgets-draining-and-upgrades",
                        "kubernetes/kubernetes-multi-cluster-backup-and-disaster-recovery",
                    ),
                ),
                Domain(
                    "Services & Networking",
                    20,
                    (
                        "kubernetes/kubernetes-services-endpoints-ingress-and-gateway-api",
                        "kubernetes/kubernetes-cni-network-policies-and-dns",
                    ),
                ),
            ),
        ),
        Track(
            id="ckad",
            name="Certified Kubernetes Application Developer",
            code="CKAD (curriculum v1.35)",
            format="Online, performance-based command-line tasks in 2 hours. Passing score 66%.",
            source="https://training.linuxfoundation.org/certification/"
            "certified-kubernetes-application-developer-ckad/",
            hands_on=True,
            labs=("probe-failing-pod", "multistage-image-volume", "helm-template-values"),
            domains=(
                Domain(
                    "Application Design and Build",
                    20,
                    (
                        "containers/docker-images-layers-build-cache-and-multi-stage-builds",
                        "kubernetes/kubernetes-jobs-cronjobs-and-operators",
                        "kubernetes/kubernetes-persistent-volumes-csi-and-statefulsets",
                        "kubernetes/kubernetes-pods-deployments-and-replica-sets",
                    ),
                ),
                Domain(
                    "Application Deployment",
                    20,
                    (
                        "kubernetes/kubernetes-pods-deployments-and-replica-sets",
                        "delivery/deployment-blue-green-canary-and-rolling-strategies",
                        "gitops/helm-charts-values-releases-and-rollback",
                        "gitops/kustomize-overlays-patches-and-environment-differences",
                    ),
                ),
                Domain(
                    "Application Observability and Maintenance",
                    15,
                    (
                        "kubernetes/kubernetes-readiness-liveness-and-startup-probes",
                        "kubernetes/kubernetes-troubleshooting-events-logs-and-ephemeral-containers",
                        "observability/metrics-logs-traces-and-useful-telemetry",
                    ),
                ),
                Domain(
                    "Application Environment, Configuration and Security",
                    25,
                    (
                        "kubernetes/kubernetes-configmaps-secrets-and-workload-configuration",
                        "kubernetes/kubernetes-rbac-service-accounts-and-workload-identity",
                        "kubernetes/kubernetes-requests-limits-qos-and-eviction",
                        "security/kubernetes-workload-security-admission-and-runtime-protection",
                    ),
                ),
                Domain(
                    "Services and Networking",
                    20,
                    (
                        "kubernetes/kubernetes-services-endpoints-ingress-and-gateway-api",
                        "kubernetes/kubernetes-cni-network-policies-and-dns",
                    ),
                ),
            ),
        ),
        Track(
            id="terraform",
            name="HashiCorp Certified: Terraform Associate",
            code="004 (tests Terraform 1.12)",
            format="Online multiple-choice exam in 1 hour. HashiCorp publishes no domain weights.",
            source="https://developer.hashicorp.com/certifications/infrastructure-automation",
            hands_on=False,
            labs=("tofu-local-drift",),
            domains=(
                Domain(
                    "Infrastructure as Code (IaC) with Terraform",
                    None,
                    (
                        "iac/configuration-drift-patching-and-immutable-infrastructure",
                        "iac/infrastructure-promotion-environment-isolation-and-rollback",
                    ),
                ),
                Domain(
                    "Terraform fundamentals",
                    None,
                    ("iac/terraform-providers-resources-data-sources-and-modules",),
                ),
                Domain(
                    "Core Terraform workflow",
                    None,
                    ("iac/terraform-plans-lifecycle-dependencies-and-imports",),
                ),
                Domain(
                    "Terraform configuration",
                    None,
                    (
                        "iac/terraform-providers-resources-data-sources-and-modules",
                        "iac/terraform-testing-policy-and-sensitive-outputs",
                    ),
                ),
                Domain(
                    "Terraform modules", None, ("iac/terraform-providers-resources-data-sources-and-modules",)
                ),
                Domain(
                    "Terraform state management", None, ("iac/terraform-state-locking-backends-and-drift",)
                ),
                Domain(
                    "Maintain infrastructure with Terraform",
                    None,
                    (
                        "iac/terraform-plans-lifecycle-dependencies-and-imports",
                        "iac/configuration-drift-patching-and-immutable-infrastructure",
                    ),
                ),
                Domain(
                    "HCP Terraform",
                    None,
                    (
                        "iac/terraform-state-locking-backends-and-drift",
                        "iac/terraform-testing-policy-and-sensitive-outputs",
                    ),
                ),
            ),
        ),
        Track(
            id="lfcs",
            name="Linux Foundation Certified System Administrator",
            code="LFCS",
            format="Online, 17-20 performance-based command-line tasks in 2 hours. Passing score 67%.",
            source="https://training.linuxfoundation.org/certification/linux-foundation-certified-sysadmin-lfcs/",
            hands_on=True,
            labs=("process-signal-triage", "bisect-broken-script"),
            domains=(
                Domain(
                    "Operations Deployment",
                    25,
                    (
                        "linux/linux-processes-signals-and-systemd",
                        "linux/linux-packages-and-patch-management",
                        "linux/linux-memory-cpu-and-io-troubleshooting",
                        "containers/container-runtime-namespaces-cgroups-and-isolation",
                    ),
                ),
                Domain(
                    "Networking",
                    25,
                    (
                        "linux/linux-networking-and-socket-diagnostics",
                        "networking/dns-resolution-caching-and-troubleshooting",
                        "networking/firewalls-security-groups-and-network-acls",
                        "networking/tcp-udp-and-connection-lifecycle",
                    ),
                ),
                Domain(
                    "Storage",
                    20,
                    (
                        "linux/linux-storage-lvm-mounts-and-filesystems",
                        "linux/linux-filesystems-permissions-and-acls",
                    ),
                ),
                Domain(
                    "Essential Commands",
                    20,
                    (
                        "linux/linux-shell-pipelines-and-text-processing",
                        "automation/bash-robust-scripts-and-exit-handling",
                        "git/git-objects-commits-branches-and-remotes",
                    ),
                ),
                Domain(
                    "Users and Groups",
                    10,
                    (
                        "linux/linux-filesystems-permissions-and-acls",
                        "linux/linux-hardening-ssh-and-audit-logs",
                    ),
                ),
            ),
        ),
    )
}


def practice_answers(state, track_id, index):
    source = f"{track_id}:{index}"
    return [
        answer
        for session in sorted(state.assessments.values(), key=lambda s: s.date)
        if session.kind == "cert" and session.source == source
        for answer in session.answers
    ]


def readiness(state, track, now):
    """Per-domain evidence: exam-style practice accuracy plus roadmap coverage of mapped topics."""
    from skillcoach.mastery import mastery_view

    states = mastery_view(state, now)["states"]
    domains, weighted, weights = [], 0.0, 0
    for index, domain in enumerate(track.domains):
        answers = practice_answers(state, track.id, index)[-20:]
        accuracy = round(100 * sum(a.correct for a in answers) / len(answers)) if answers else None
        started = [t for t in domain.topics if t in states]
        solid = [t for t in started if states[t]["state"] == "solid"]
        if not answers and not started:
            label = "Not started"
        elif len(answers) >= 10 and accuracy >= 80:
            label = "Strong in practice"
        elif len(answers) >= MIN_ANSWERS and accuracy < 60:
            label = "Needs work"
        else:
            label = "Building"
        if len(answers) >= MIN_ANSWERS:
            weight = domain.weight or 1
            weighted += accuracy * weight
            weights += weight
        domains.append(
            {
                "index": index,
                "name": domain.name,
                "weight": domain.weight,
                "practice_answers": len(answers),
                "practice_accuracy": accuracy,
                "topics_total": len(domain.topics),
                "topics_started": len(started),
                "topics_solid": len(solid),
                "label": label,
            }
        )
    return {
        "domains": domains,
        "overall": round(weighted / weights) if weights else None,
        "covered_domains": sum(d["practice_answers"] >= MIN_ANSWERS for d in domains),
    }


def weakest(state, track, now, count=2):
    items = readiness(state, track, now)["domains"]
    ranked = sorted(
        items,
        key=lambda d: (
            d["practice_accuracy"] if d["practice_accuracy"] is not None else -1,
            -(d["weight"] or 0),
        ),
    )
    return [d["name"] for d in ranked[:count]]


def cert_view(state, now):
    from skillcoach.labs import LABS

    selected = TRACKS.get(state.cert_track or "")
    view = {
        "selected": selected.id if selected else None,
        "tracks": [
            {"id": t.id, "name": t.name, "code": t.code, "hands_on": t.hands_on} for t in TRACKS.values()
        ],
        "verified": VERIFIED,
        "disclaimer": DISCLAIMER,
        "track": None,
    }
    if selected:
        view["track"] = {
            "id": selected.id,
            "name": selected.name,
            "code": selected.code,
            "format": selected.format,
            "source": selected.source,
            "hands_on": selected.hands_on,
            "labs": [{"id": lab, "title": LABS[lab].title} for lab in selected.labs if lab in LABS],
            **readiness(state, selected, now),
        }
    return view
