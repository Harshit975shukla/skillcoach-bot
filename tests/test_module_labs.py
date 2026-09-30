from urllib.parse import urlparse

from skillcoach.catalog import MODULES
from skillcoach.module_labs import MODULE_LABS, MODULE_OF

MODULE_IDS = (
    "foundations",
    "linux",
    "git",
    "automation",
    "azure",
    "gcp",
    "containers",
    "kubernetes",
    "iac",
    "delivery",
    "gitops",
    "observability",
    "sre",
    "platform",
    "mlops",
    "finops",
    "architecture",
)
EXISTING_IDS = {
    "s3-private-presigned",
    "lambda-function-url",
    "iam-least-privilege",
    "api-gateway-health",
    "cloudfront-private-origin",
    "dynamodb-idempotent-write",
    "sqs-idempotent-consumer",
    "vpc-subnet-routing",
}
ALLOWED_HOSTS = {
    "kernel.org",
    "man7.org",
    "www.gnu.org",
    "git-scm.com",
    "docs.python.org",
    "docs.docker.com",
    "kubernetes.io",
    "kind.sigs.k8s.io",
    "developer.hashicorp.com",
    "opentofu.org",
    "docs.github.com",
    "argo-cd.readthedocs.io",
    "helm.sh",
    "opentelemetry.io",
    "prometheus.io",
    "grafana.com",
    "sre.google",
    "learn.microsoft.com",
    "cloud.google.com",
    "docs.aws.amazon.com",
    "backstage.io",
    "mlflow.org",
    "www.finops.org",
    "owasp.org",
}


def test_module_lab_ids_and_mapping():
    assert len(MODULE_LABS) == 17
    ids = [lab.id for lab in MODULE_LABS]
    assert len(ids) == len(set(ids))
    assert not set(ids) & EXISTING_IDS
    assert set(MODULE_OF.values()) == set(MODULE_IDS)
    assert set(MODULE_OF) == set(ids)
    assert all(3 <= len(lab_id) <= 40 for lab_id in ids)
    assert all(lab_id == lab_id.lower() for lab_id in ids)
    assert all(all(part.isalnum() for part in lab_id.split("-")) for lab_id in ids)
    assert all("--" not in lab_id and lab_id.strip("-") == lab_id for lab_id in ids)

    by_module = {}
    for lab_id, module_id in MODULE_OF.items():
        by_module.setdefault(module_id, []).append(lab_id)
    assert sorted(by_module) == sorted(MODULE_IDS)
    assert all(len(lab_ids) == 1 for lab_ids in by_module.values())


def test_topics_are_exact_for_own_module():
    modules = {module.id: module for module in MODULES}
    for lab in MODULE_LABS:
        module = modules[MODULE_OF[lab.id]]
        assert 1 <= len(lab.topics) <= 2
        for topic in lab.topics:
            assert topic in module.topics


def test_reference_hosts_are_allowed_https():
    for lab in MODULE_LABS:
        assert 2 <= len(lab.references) <= 4
        for reference in lab.references:
            parsed = urlparse(reference)
            assert parsed.scheme == "https"
            assert parsed.hostname in ALLOWED_HOSTS


def test_scenario_steps_are_well_formed():
    for lab in MODULE_LABS:
        assert len(lab.scenario) == 4
        correct_is_longest = []
        for step in lab.scenario:
            assert 0 < len(step.prompt) <= 300
            assert len(step.options) == 4
            assert len(set(step.options)) == 4
            assert all(0 < len(option) <= 160 for option in step.options)
            assert 0 < len(step.explanation) <= 350
            correct_is_longest.append(len(step.options[0]) == max(len(option) for option in step.options))
        assert not all(correct_is_longest)


def test_local_route_and_lab_limits():
    for lab in MODULE_LABS:
        assert lab.routes == ("scenario", "local")
        assert 20 <= lab.minutes <= 45
        assert 0 < len(lab.title) <= 80
        assert 0 < len(lab.goal) <= 200
        assert lab.local is not None
        assert 0 < len(lab.local.tools) <= 160
        assert 4 <= len(lab.local.steps) <= 8
        assert all(0 < len(step) <= 400 for step in lab.local.steps)
        assert 1 <= len(lab.local.cleanup) <= 4
        assert all(0 < len(step) <= 400 for step in lab.local.cleanup)
