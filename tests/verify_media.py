"""Optional real local renderer/ffmpeg check; never sends media externally."""

import json
import subprocess
import tempfile
from pathlib import Path

from lesson_content import CONCEPT_DIAGRAMS
from skillcoach.lessons import ARCHITECTURES
from skillcoach.media import animate, render_png


def main():
    diagrams = [d for items in CONCEPT_DIAGRAMS.values() for d in items] + list(ARCHITECTURES.values())
    with tempfile.TemporaryDirectory(prefix="skillcoach-render-check-") as tmp:
        folder = Path(tmp)
        for index, diagram in enumerate(diagrams):
            image = render_png(diagram, folder)
            assert image.stat().st_size > 100
            if index == 0:
                video = animate(image, folder, "Concept: CPU credits")
                assert video is not None, (
                    "Animated video failed (static fallback is not sufficient for this check)"
                )
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                )
                info = json.loads(result.stdout)
                stream = info["streams"][0]
                assert stream["width"] == 1280 and stream["height"] == 720
                assert stream["r_frame_rate"] == "24/1"
                assert 24.9 <= float(info["format"]["duration"]) <= 25.1
    print(f"Rendered {len(diagrams)} diagrams; verified 25-second 1280x720 24fps MP4.")


if __name__ == "__main__":
    main()
