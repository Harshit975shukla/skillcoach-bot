"""Local Mermaid rendering and the preserved 25-second Ken Burns video effect."""

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from skillcoach.clients import ExternalError

log = logging.getLogger(__name__)


def render_png(code: str, folder: Path) -> Path:
    renderer = shutil.which("mmdc")
    if not renderer:
        raise ExternalError("local_mermaid_renderer_missing", retryable=False)
    if any(s in code.lower() for s in ("http:", "https:", "click ", "%%{", "<script", "<img")):
        raise ExternalError("unsafe_diagram", retryable=False)
    source, output = folder / "diagram.mmd", folder / "diagram.png"
    source.write_text(code, encoding="utf-8")
    config = folder / "mermaid.json"
    config.write_text(json.dumps({"securityLevel": "strict", "theme": "default"}), encoding="utf-8")
    browser = folder / "puppeteer.json"
    browser.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
    try:
        result = subprocess.run(
            [
                renderer,
                "-i",
                str(source),
                "-o",
                str(output),
                "-c",
                str(config),
                "-p",
                str(browser),
                "-b",
                "white",
                "-w",
                "1280",
            ],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExternalError("diagram_render_failed") from exc
    if result.returncode or not output.exists():
        raise ExternalError("diagram_render_failed")
    return output


def animate(image: Path, folder: Path, caption: str) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("video_fallback reason=ffmpeg_missing")
        return None
    # A text file avoids ffmpeg filter injection by captions, quotes and punctuation.
    (folder / "caption.txt").write_text(caption[:150], encoding="utf-8")
    output = folder / "diagram.mp4"
    vf = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=white,"
        "zoompan=z='min(1+on*0.25/599,1.25)':d=600"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=24,"
        "fade=t=in:st=0:d=1,fade=t=out:st=23:d=2,"
        "drawtext=textfile=caption.txt:expansion=none:fontsize=28:fontcolor=white"
        ":x=(w-text_w)/2:y=h-th-25:box=1:boxcolor=black@0.6:boxborderw=10,format=yuv420p"
    )
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(image),
                "-vf",
                vf,
                "-t",
                "25",
                "-r",
                "24",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-movflags",
                "+faststart",
                str(output),
            ],
            cwd=folder,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning("video_fallback reason=ffmpeg_unavailable")
        return None
    if proc.returncode or not output.exists():
        log.warning("video_fallback reason=encoding_failed")
        return None
    return output


def deliver_media(telegram, body: dict, budget, *, before_send=None):
    with tempfile.TemporaryDirectory(prefix="skillcoach-") as tmp:
        folder = Path(tmp)
        image = render_png(body["code"], folder)
        video = animate(image, folder, body["caption"]) if body["mode"] == "video" else None
        path = video or image
        caption = body["caption"]
        if body["mode"] == "video" and not video:
            caption += "\nStatic fallback: video rendering unavailable."
        kind = "video" if video else "photo"
        if before_send is not None:
            before_send()
        with path.open("rb") as stream:
            telegram.call(
                "sendVideo" if video else "sendPhoto",
                budget,
                data={"caption": caption[:900], **({"supports_streaming": "true"} if video else {})},
                files={kind: (path.name, stream, "video/mp4" if video else "image/png")},
            )


def deliver_storyboard(telegram, body, budget, *, before_send, cached=None):
    from skillcoach.story_renderer import render_storyboard
    from skillcoach.storyboard import Storyboard

    story = Storyboard.model_validate(body["storyboard"])
    caption = body["caption"][:500]
    caption += (
        "\nReviewed authored explanation."
        if body.get("shared_reviewed")
        else "\nAI-generated explanation; verify against the lesson references."
    )
    caption += (
        "\nSynthetic offline narration + captions."
        if body.get("voice", False) and body["mode"] == "video"
        else "\nCaptioned walkthrough."
    )
    if cached:
        before_send()
        kind = cached["kind"]
        telegram.call(
            "sendVideo" if kind == "video" else "sendPhoto",
            budget,
            data={kind: cached["file_id"], "caption": caption},
        )
        return cached
    with tempfile.TemporaryDirectory(prefix="skillcoach-storyboard-") as tmp:
        path, metadata = render_storyboard(
            story,
            Path(tmp),
            budget,
            voice=body.get("voice", False),
            static=body["mode"] == "static",
            reviewed=body.get("shared_reviewed", False),
        )
        before_send()
        kind = metadata["kind"]
        with path.open("rb") as media_file:
            result = telegram.call(
                "sendVideo" if kind == "video" else "sendPhoto",
                budget,
                data={"caption": caption, **({"supports_streaming": "true"} if kind == "video" else {})},
                files={kind: (path.name, media_file, "video/mp4" if kind == "video" else "image/png")},
            )
        delivered = result.get("video") if kind == "video" else (result.get("photo") or [{}])[-1]
        if not delivered or not isinstance(delivered.get("file_id"), str):
            raise ExternalError("media_delivery_receipt_invalid")
        return {"file_id": delivered["file_id"], "kind": kind, "metadata": metadata}
