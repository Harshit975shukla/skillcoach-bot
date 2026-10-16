"""Render the learning Helm chart with the local helm binary and check what Kubernetes would receive."""

import functools
import shutil
import subprocess
from pathlib import Path

import pytest

from skillcoach.scheduler import SLOTS

CHART = Path("deploy-oci/helm/skillcoach")
HELM = shutil.which("helm")
pytestmark = pytest.mark.skipif(not HELM, reason="helm is not installed")
# Python weekday() numbers (Monday=0) to cron day-of-week numbers (Sunday=0).
CRON_DAY = {0: "1", 1: "2", 2: "3", 3: "4", 4: "5", 5: "6", 6: "0"}


@functools.lru_cache(maxsize=None)
def render(*args):
    result = subprocess.run(
        [HELM, "template", "sc", str(CHART), *args], capture_output=True, text=True, timeout=60, check=False
    )
    return result


def documents(text):
    import yaml

    return [doc for doc in yaml.safe_load_all(text) if doc]


def cronjobs(text):
    return {
        doc["metadata"]["name"].removeprefix("skillcoach-"): doc
        for doc in documents(text)
        if doc["kind"] == "CronJob" and doc["metadata"]["labels"]["app.kubernetes.io/component"].startswith("cron-")
    }


def cron_days(days):
    numbers = sorted(int(CRON_DAY[d]) for d in days)
    if numbers == list(range(numbers[0], numbers[-1] + 1)) and len(numbers) > 1:
        return f"{numbers[0]}-{numbers[-1]}"
    return ",".join(str(n) for n in numbers)


def test_chart_lints():
    result = subprocess.run([HELM, "lint", str(CHART)], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_slot_cronjobs_run_at_the_products_india_times():
    jobs = cronjobs(render().stdout)
    for kind, slot in SLOTS.items():
        spec = jobs[kind]["spec"]
        assert spec["timeZone"] == "Asia/Kolkata"
        assert spec["schedule"] == f"{slot.at.minute} {slot.at.hour} * * {cron_days(slot.weekdays)}"
    assert jobs["recovery"]["spec"]["schedule"] == "*/5 * * * *"


def test_a_missing_time_zone_fails_instead_of_running_in_utc():
    result = render("--set", "cron.timeZone=")
    assert result.returncode != 0 and "cron.timeZone is required" in result.stderr


def wave(doc):
    return int((doc["metadata"].get("annotations") or {}).get("argocd.argoproj.io/sync-wave", "0"))


def test_migration_job_runs_after_the_database_and_before_the_app():
    docs = documents(render().stdout)
    job = next(d for d in docs if d["kind"] == "Job" and d["metadata"]["name"].endswith("-migrate"))
    notes = job["metadata"]["annotations"]
    assert notes["argocd.argoproj.io/hook"] == "Sync"
    assert notes["argocd.argoproj.io/hook-delete-policy"] == "BeforeHookCreation"
    assert notes["helm.sh/hook"] == "post-install,pre-upgrade"
    pod = job["spec"]["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["containers"][0]["command"] == ["python", "-m", "skillcoach.cli", "migrate"]
    assert "pg_isready" in pod["initContainers"][0]["command"][-1]

    before = [d for d in docs if d["kind"] in ("Secret", "ConfigMap", "StatefulSet")]
    before += [d for d in docs if d["kind"] == "Service" and d["metadata"]["name"].endswith("-postgresql")]
    after = [d for d in docs if d["kind"] in ("Deployment", "CronJob")]
    assert len(before) == 5 and len(after) == 7  # 2 Secrets; web, 5 slot CronJobs, backup
    assert all(wave(d) < wave(job) for d in before)
    assert all(wave(d) > wave(job) for d in after)


def test_migration_uses_the_same_database_address_as_the_app():
    docs = documents(render().stdout)
    env = {
        d["metadata"]["name"]: {
            e["name"]: e.get("value") for e in d["spec"]["template"]["spec"]["containers"][0]["env"]
        }
        for d in docs
        if d["kind"] in ("Job", "Deployment")
    }
    job = env["skillcoach-migrate"]
    assert job["DATABASE_URL"] == env["skillcoach-web"]["DATABASE_URL"]
    assert "$(POSTGRES_PASSWORD)" in job["DATABASE_URL"]
    assert list(job) == ["POSTGRES_PASSWORD", "DATABASE_URL"]  # the password must be defined first


def test_migration_can_be_switched_off():
    assert not any(d["kind"] == "Job" for d in documents(render("--set", "migration.enabled=false").stdout))


class Parsed(Exception):
    pass


def test_slim_cronjobs_pass_the_apps_real_no_media_flag(monkeypatch):
    import argparse

    from skillcoach import cli

    original = argparse.ArgumentParser.parse_args

    def parse_only(self, args=None, namespace=None):
        original(self, args, namespace)
        raise Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_only)
    for name, job in cronjobs(render().stdout).items():
        container = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        assert container["command"] == ["python", "-m", "skillcoach.cli"]
        media = name in ("lesson", "recovery")
        assert ("--no-media" in container["args"]) is not media, name
        assert container["image"].startswith("REPLACE_WITH_OCIR_MEDIA_REPO:" if media else "REPLACE_WITH_OCIR_REPO:")
        assert not any(e["name"] == "SKILLCOACH_RENDER_MEDIA" for e in container["env"])
        with pytest.raises(Parsed):
            cli.main(container["args"])  # argparse exits with an error for an unknown flag

    rich = cronjobs(render("--set", "cron.renderMedia=true").stdout)
    assert all(
        "--no-media" not in j["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"]
        for j in rich.values()
    )


def test_probes_never_restart_a_pod_that_is_only_busy_with_a_slow_request():
    import re

    web = next(d for d in documents(render().stdout) if d["kind"] == "Deployment")
    container = web["spec"]["template"]["spec"]["containers"][0]
    startup, ready, live = (container[p] for p in ("startupProbe", "readinessProbe", "livenessProbe"))
    assert {p["httpGet"]["path"] for p in (startup, ready, live)} == {"/"}
    assert all(p["timeoutSeconds"] >= 5 for p in (startup, ready, live))
    gunicorn = int(re.search(r"--timeout (\d+)", Path("deploy-oci/docker/Dockerfile").read_text()).group(1))
    assert live["periodSeconds"] * live["failureThreshold"] > gunicorn
    assert startup["periodSeconds"] * startup["failureThreshold"] >= 60
    assert "secret" not in str(container["livenessProbe"]).lower()


def test_probe_path_answers_without_login_or_database():
    from skillcoach.web import create_app

    response = create_app(runtime=object()).test_client().get("/")
    assert response.status_code == 200 and response.get_json() == {"service": "skillcoach", "live": True}


def pod_specs(docs):
    for doc in docs:
        if doc["kind"] in ("Deployment", "StatefulSet", "Job"):
            yield doc["metadata"]["name"], doc["spec"]["template"]["spec"]
        elif doc["kind"] == "CronJob":
            yield doc["metadata"]["name"], doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]


def test_every_pod_is_locked_down_and_the_app_uid_matches_the_image():
    import re

    uid = int(re.search(r"useradd .*--uid (\d+)", Path("deploy-oci/docker/Dockerfile").read_text()).group(1))
    specs = dict(pod_specs(documents(render().stdout)))
    assert len(specs) == 9  # web, 5 CronJobs, backup, migration Job, PostgreSQL
    for name, spec in specs.items():
        assert spec["automountServiceAccountToken"] is False, name
        pod = spec["securityContext"]
        assert pod["runAsNonRoot"] is True and pod["seccompProfile"]["type"] == "RuntimeDefault", name
        for container in spec["containers"] + spec.get("initContainers", []):
            rules = container["securityContext"]
            assert rules["allowPrivilegeEscalation"] is False, name
            assert rules["capabilities"]["drop"] == ["ALL"], name
        if name.endswith(("-postgresql", "-backup")):
            if name.endswith("-backup"):
                assert pod["runAsUser"] == uid
                assert all(c["securityContext"]["readOnlyRootFilesystem"] for c in spec["containers"])
                continue
            assert pod["runAsUser"] == pod["fsGroup"] == 70  # postgres user in the alpine image
            continue
        assert pod["runAsUser"] == pod["runAsGroup"] == uid, name
        for container in spec["containers"] + spec.get("initContainers", []):
            assert container["securityContext"]["readOnlyRootFilesystem"] is True, name
        app = spec["containers"][0]
        mounts, volumes = app["volumeMounts"], spec["volumes"]
        if name in ("skillcoach-lesson", "skillcoach-recovery"):  # media worker: Chromium shared memory
            assert mounts.pop() == {"name": "dshm", "mountPath": "/dev/shm"}, name
            assert volumes.pop() == {"name": "dshm", "emptyDir": {"medium": "Memory", "sizeLimit": "256Mi"}}
        assert mounts == [{"name": "tmp", "mountPath": "/tmp"}], name
        assert volumes == [{"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}}], name


def test_the_app_writes_temporary_files_only_through_tempfile():
    import re

    writers = re.compile(r"open\([^)]*['\"][wa]b?['\"]|\.write_(text|bytes)\(")
    for path in Path("skillcoach").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if writers.search(text):
            # Files are written only inside tempfile directories, which live in /tmp.
            assert "tempfile" in text or path.name == "story_renderer.py", path


def test_only_app_pods_may_reach_postgresql():
    docs = documents(render().stdout)
    policy = next(d for d in docs if d["kind"] == "NetworkPolicy")
    pods = {}
    for doc in docs:
        if doc["kind"] in ("Deployment", "StatefulSet", "Job"):
            pods[doc["metadata"]["name"]] = doc["spec"]["template"]["metadata"]["labels"]
        elif doc["kind"] == "CronJob":
            pods[doc["metadata"]["name"]] = doc["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]

    def matches(selector, labels):
        return all(labels.get(k) == v for k, v in selector["matchLabels"].items())

    protected = [name for name, labels in pods.items() if matches(policy["spec"]["podSelector"], labels)]
    assert protected == ["skillcoach-postgresql"]
    rule = policy["spec"]["ingress"][0]
    allowed = sorted(name for name, labels in pods.items() if matches(rule["from"][0]["podSelector"], labels))
    assert allowed == sorted(n for n in pods if n != "skillcoach-postgresql") and len(allowed) == 8
    assert rule["ports"] == [{"protocol": "TCP", "port": 5432}]
    assert policy["spec"]["policyTypes"] == ["Ingress"]
    off = documents(render("--set", "networkPolicy.enabled=false").stdout)
    assert not any(d["kind"] == "NetworkPolicy" for d in off)


def test_nightly_backup_dumps_then_uploads_with_its_own_write_only_link():
    docs = documents(render().stdout)
    job = next(d for d in docs if d["kind"] == "CronJob" and d["metadata"]["name"] == "skillcoach-backup")
    assert job["spec"]["timeZone"] == "Asia/Kolkata" and job["spec"]["schedule"] == "30 2 * * *"
    assert job["spec"]["concurrencyPolicy"] == "Forbid"
    pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    dump, upload = pod["initContainers"][0], pod["containers"][0]
    assert "pg_dump" in dump["command"][-1] and "-Fc -f /backup/db.dump" in dump["command"][-1]
    assert dump["image"] == "postgres:16-alpine"  # same major version as the server
    assert upload["image"] == "curlimages/curl:8.16.0"
    assert "curl --fail" in upload["command"][-1] and "exit 1" in upload["command"][-1]
    assert upload["volumeMounts"][0]["readOnly"] is True
    link = upload["env"][0]["valueFrom"]["secretKeyRef"]
    assert link == {"name": "skillcoach-backup", "key": "BACKUP_UPLOAD_URL"}

    secrets = {d["metadata"]["name"]: d["stringData"] for d in docs if d["kind"] == "Secret"}
    assert "BACKUP_UPLOAD_URL" not in secrets["skillcoach-secrets"]  # app pods load this whole Secret
    assert list(secrets["skillcoach-backup"]) == ["BACKUP_UPLOAD_URL"]
    off = documents(render("--set", "backup.enabled=false").stdout)
    assert not any(d["metadata"]["name"] in ("skillcoach-backup",) for d in off)


def test_media_jobs_render_videos_and_share_the_app_image_tag():
    jobs = cronjobs(render("--set", "image.tag=9f3c2a1").stdout)
    for name in ("lesson", "recovery"):
        pod = jobs[name]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        container = pod["containers"][0]
        assert container["image"].endswith(":9f3c2a1")
        assert {"name": "HOME", "value": "/tmp"} in container["env"]  # Chromium profile on a read-only root
        assert container["resources"]["limits"]["memory"] == "1536Mi"
    quiz = jobs["quiz"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert quiz["image"].endswith(":9f3c2a1")
