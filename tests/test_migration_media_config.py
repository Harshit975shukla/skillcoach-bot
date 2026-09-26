import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from skillcoach.cli import main
from skillcoach.media import animate, render_png
from skillcoach.migration import dry_run, import_snapshot, load_snapshot
from skillcoach.models import State


def snapshot():
    done = {
        "id": "task_001",
        "title": "Actual private task",
        "skill": "IAM",
        "assigned_date": "2026-09-24",
        "completed_at": "2026-09-25T17:00:00+05:30",
        "estimated_time": "20 min",
    }
    return {
        "open_tasks": [],
        "completed_tasks": [done],
        "recent_done": [dict(done)],
        "statistics": {"completed_tasks": 500, "streak": 999},
        "weekly_scores": {"week_1": 50},
        "curriculum": {
            "daily_lessons": {"2026-09-24": "IAM"},
            "week_plan": {f"2026-09-{day}": "IAM" for day in range(21, 27)},
        },
    }


def test_legacy_original_shape_preserves_done_and_quarantines_scores(tmp_path, capsys):
    raw = snapshot()
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(raw))
    data, digest = load_snapshot(path)
    report = dry_run(data, digest)
    assert report["tasks"] == 1 and report["usable_plans"] == 1
    state = import_snapshot(State(), data, digest)
    assert next(iter(state.tasks.values())).status == "done"
    assert len(state.activity) == 1
    assert len(state.lessons) == 1
    assert not state.assessments and state.profile is None
    assert state.legacy_archive["snapshot"]["weekly_scores"]["week_1"] == 50
    assert main(["import-legacy", str(path)]) == 0
    assert '"writes": false' in capsys.readouterr().out
    assert main(["import-legacy", str(path), "--apply"]) == 1
    assert import_snapshot(state, data, digest) == state
    with pytest.raises(ValueError, match="empty private state"):
        import_snapshot(state, data, "different-digest")


def test_legacy_conflicts_and_dashboard_snapshots_rejected():
    raw = snapshot()
    raw["recent_done"][0]["title"] = "Conflicting update"
    with pytest.raises(ValueError, match="Conflicting"):
        dry_run(raw, "hash")
    with pytest.raises(ValueError, match="public dashboard"):
        dry_run({"schema_version": 1, "profile": {}, "stats": {}, "activity": []}, "hash")
    raw = snapshot()
    raw["completed_tasks"][0]["completed_at"] = "2026-09-25T17:00:00"
    raw.pop("recent_done")
    with pytest.raises(ValueError, match="timezone"):
        dry_run(raw, "hash")


def test_optional_static_and_preserved_video_filter(tmp_path, monkeypatch):
    captured = {}
    image = tmp_path / "diagram.png"
    image.write_bytes(b"fake-png")
    monkeypatch.setattr(shutil, "which", lambda name: "fake-ffmpeg" if name == "ffmpeg" else None)

    def process(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        Path(args[-1]).write_bytes(b"fake-video")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", process)
    assert animate(image, tmp_path, "Caption: [x] 'quoted'") == tmp_path / "diagram.mp4"
    args = captured["args"]
    assert args[args.index("-t") + 1] == "25"
    assert args[args.index("-r") + 1] == "24"
    vf = args[args.index("-vf") + 1]
    assert "1.25" in vf and "fade=t=out:st=23:d=2" in vf
    assert "textfile=caption.txt" in vf and "expansion=none" in vf
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert animate(image, tmp_path, "Caption") is None
    with pytest.raises(Exception, match="local_mermaid_renderer_missing"):
        render_png("flowchart LR\nA-->B", tmp_path)


def test_dependency_python_workflow_and_help_consistency():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    requirements = set(Path("requirements.txt").read_text().splitlines())
    assert requirements == set(project["project"]["dependencies"])
    assert Path(".python-version").read_text().strip() == "3.12"
    worker = Path(".github/workflows/coach-job.yml").read_text()
    assert 'python-version: "3.12"' in worker
    assert "skillcoach-private-worker-${{ inputs.kind }}" in worker
    assert "GITHUB_TOKEN: ${{ secrets.GH_PAT }}" in worker
    assert "OWNER_ID: ${{ secrets.OWNER_ID || secrets.CHAT_ID }}" in worker
    assert "if: steps.media.outputs.needed == 'true'" in worker
    assert "*/5 * * * *" in Path(".github/workflows/recovery.yml").read_text()
    assert not Path(".github/workflows/daily_reminder.yml").exists()
    assert '"30 3 * * 1-5"' in Path(".github/workflows/morning_lesson.yml").read_text()
    assert '"30 12 * * 1-5"' in Path(".github/workflows/evening_quiz.yml").read_text()
    weekend = Path(".github/workflows/weekend.yml").read_text()
    assert "inputs.kind == 'weekly'" in weekend and "inputs.kind == 'review'" in weekend
    assert "DAY=$(date" not in weekend
    ci = Path(".github/workflows/tests.yml").read_text()
    assert "runs-on: ubuntu-latest" in ci and "workflow_dispatch:" in ci
    assert "upload-artifact" not in ci and "cache:" not in ci
    assert "cache:" not in worker
    assert json.loads(Path("vercel.json").read_text())["git"]["deploymentEnabled"] is False
    assert "rewrites" not in json.loads(Path("vercel.json").read_text())
    assert project["tool"]["vercel"]["entrypoint"] == "api.webhook:app"
    assert "needs: test" in ci and "vars.SKILLCOACH_BOOTSTRAP_SHA == github.sha" in ci
    assert "github.event_name == 'workflow_dispatch' && vars.SKILLCOACH_UPGRADE_SHA == github.sha" in ci
    assert "upgrade-schema --writers-stopped" in ci
    assert "VERIFY_MEDIA: ${{ inputs.verify_media }}" in worker
    assert "run: python tests/verify_storytelling.py" in worker
    assert "PYTHONPATH: ${{ github.workspace }}" in worker
    assert (
        "verify_media: ${{ inputs.verify_media || false }}"
        in Path(".github/workflows/recovery.yml").read_text()
    )
    for caller in ("morning_lesson.yml", "evening_quiz.yml", "weekend.yml", "recovery.yml"):
        workflow = Path(".github", "workflows", caller).read_text()
        assert "contents: read" in workflow and "actions: read" in workflow
