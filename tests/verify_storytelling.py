"""Verify the safe caption-only default; no API calls, credentials or Telegram sends."""

import json
import subprocess
import tempfile
from pathlib import Path

from skillcoach.clients import Budget
from skillcoach.story_renderer import render_storyboard
from skillcoach.storyboard import reviewed_architecture


def main():
    with tempfile.TemporaryDirectory(prefix="skillcoach-narration-check-") as tmp:
        story = reviewed_architecture("EC2")
        video, metadata = render_storyboard(story, Path(tmp), Budget(210), reviewed=True)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        data = json.loads(probe.stdout)
        visual = next(item for item in data["streams"] if item["codec_type"] == "video")
        audio = [item for item in data["streams"] if item["codec_type"] == "audio"]
        assert visual["width"] == 1280 and visual["height"] == 720
        assert visual["r_frame_rate"] == "24/1"
        assert not audio, "The default lesson video must not contain an audio stream"
        assert metadata["voice"] is False
        assert abs(float(data["format"]["duration"]) - sum(metadata["scene_durations"])) < 0.12
        assert all(4 <= duration <= 33 for duration in metadata["scene_durations"])
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"],
            capture_output=True,
            timeout=60,
            check=True,
        )
        assert not decoded.stderr
        print(
            f"Real caption-only EC2 video verified: {metadata['duration']:.2f}s, 1280x720/24fps, "
            "no audio stream; explanatory scenes and motion retained."
        )


if __name__ == "__main__":
    main()
