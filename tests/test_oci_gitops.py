"""Offline checks for the OCI image publishing and Argo CD learning manifests."""

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/publish-oci-images.yml")
APP = Path("deploy-oci/argocd/skillcoach.yaml")
VALUES = Path("deploy-oci/helm/skillcoach/values-oci.yaml")


def test_image_publication_is_manual_and_requires_an_explicit_yes():
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    expected_paths = [
        "deploy-oci/**",
        "tests/test_helm_chart.py",
        "tests/test_container_image.py",
        "tests/test_oci_gitops.py",
        ".github/workflows/publish-oci-images.yml",
    ]
    assert triggers["push"]["branches"] == ["oci-learning"]
    assert triggers["push"]["paths"] == expected_paths
    assert triggers["pull_request"]["paths"] == expected_paths
    choice = triggers["workflow_dispatch"]["inputs"]["publish_images"]
    assert choice["required"] == "true"
    assert choice["default"] == "no"
    assert choice["options"] == ["no", "yes"]
    publish = workflow["jobs"]["publish"]
    assert "github.event_name == 'workflow_dispatch'" in publish["if"]
    assert "inputs.publish_images == 'yes'" in publish["if"]
    assert "github.ref == 'refs/heads/oci-learning'" in publish["if"]


def test_publisher_builds_both_arm_images_with_sha_tags_and_limited_permissions():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    permissions = workflow["jobs"]["publish"]["permissions"]
    assert permissions == {"contents": "write", "packages": "write"}
    assert "packages: write" not in workflow.get("permissions", {})
    assert "contents: write" not in workflow.get("permissions", {})
    assert "linux/arm64" in text
    assert "ghcr.io/harshit975shukla/skillcoach-bot:${{ github.sha }}" in text
    assert "ghcr.io/harshit975shukla/skillcoach-bot-media:${{ github.sha }}" in text
    assert "Refuse to overwrite an existing commit-SHA tag" in text
    assert "github.sha" in text and "set-by-publish-workflow" in text
    assert "git push origin HEAD:oci-learning" in text


def test_argocd_tracks_the_learning_branch_and_preserves_stateful_resources():
    app = yaml.safe_load(APP.read_text(encoding="utf-8"))
    spec = app["spec"]
    assert spec["source"]["repoURL"] == "https://github.com/Harshit975shukla/skillcoach-bot.git"
    assert spec["source"]["targetRevision"] == "oci-learning"
    assert spec["source"]["path"] == "deploy-oci/helm/skillcoach"
    assert spec["source"]["helm"]["valueFiles"] == ["values.yaml", "values-oci.yaml"]
    assert spec["destination"]["namespace"] == "skillcoach"
    assert spec["syncPolicy"]["automated"] == {"prune": False, "selfHeal": True}


def test_oci_values_use_the_same_immutable_tag_for_both_ghcr_packages():
    values = yaml.safe_load(VALUES.read_text(encoding="utf-8"))
    assert values["image"]["repository"] == "ghcr.io/harshit975shukla/skillcoach-bot"
    assert values["image"]["tag"] == "set-by-publish-workflow"
    assert values["media"]["repository"] == "ghcr.io/harshit975shukla/skillcoach-bot-media"
    assert values["imagePullSecrets"] == [{"name": "ghcr-pull-secret"}]
    assert "password" not in VALUES.read_text(encoding="utf-8").lower()


def test_learning_docs_explain_visibility_and_do_not_apply_the_application():
    readme = Path("deploy-oci/README.md").read_text(encoding="utf-8").lower()
    assert "private" in readme and "never put a token" in readme
    assert "not a command to apply yet" in readme
    assert "not changed" in readme


def test_learning_diagrams_match_the_selected_github_and_traefik_design():
    import re

    for name in ("bot-app-architecture", "cicd-pipeline"):
        source = Path(f"docs/diagrams/{name}.mmd").read_text(encoding="utf-8").strip()
        html = Path(f"docs/diagrams/{name}.html").read_text(encoding="utf-8")
        embedded = re.search(r'<pre class="mermaid" id="diagram">\s*(.*?)\s*</pre>', html, re.S)
        assert embedded and embedded.group(1).strip() == source
        assert "not live" in html.lower()

    architecture = Path("docs/diagrams/bot-app-architecture.mmd").read_text(encoding="utf-8")
    pipeline = Path("docs/diagrams/cicd-pipeline.mmd").read_text(encoding="utf-8")
    assert "Traefik ingress + HTTPS" in architecture
    assert "free capacity must be verified" in architecture
    assert "GitHub Actions" in pipeline and "Argo CD" in pipeline and "GHCR" in pipeline
    assert "GitLab" not in pipeline and "NGINX" not in architecture
