"""Offline, captioned scene rendering with stock eSpeak NG narration."""

import math
import os
import shutil
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from skillcoach.clients import Budget, ExternalError
from skillcoach.storyboard import Storyboard

WIDTH, HEIGHT, FPS = 1280, 720, 24


def fonts():
    system = Path(os.path.sep)
    candidates = [
        (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\segoeuib.ttf")),
        (
            system / "usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            system / "usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ]
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            return {
                (size, heavy): ImageFont.truetype(str(bold if heavy else regular), size)
                for size in (17, 18, 20, 22, 24, 28, 30)
                for heavy in (False, True)
            }
    raise ExternalError("readable_render_font_missing", retryable=False)


def _wrapped(draw, text, font, width):
    lines, current = [], ""
    for word in text.split():
        if draw.textlength(word, font=font) > width:
            raise ExternalError("storyboard_text_does_not_fit", retryable=False)
        trial = (current + " " + word).strip()
        if current and draw.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    return [*lines, current] if current else lines


def render_frame(
    story: Storyboard,
    scene_index: int,
    local_time: float,
    progress: float,
    font_set,
    *,
    reviewed=False,
    narrated=True,
):
    image = Image.new("RGB", (WIDTH, HEIGHT), "#101B2A")
    draw = ImageDraw.Draw(image)
    white, muted = "#F0F4F9", "#BDCADD"
    palette = {"request": "#60DFF4", "control": "#C5A8FA", "replication": "#F7CB76"}
    state_colors = {
        "healthy": "#7AE4BA",
        "unhealthy": "#FFADB7",
        "starting": "#F7CB76",
        "waiting": "#F7CB76",
        "complete": "#7AE4BA",
    }
    scene = story.scenes[scene_index]

    def text(x, y, value, size=20, color=white, heavy=False):
        draw.text((x, y), value, font=font_set[size, heavy], fill=color)

    lines = _wrapped(draw, story.title, font_set[30, True], 1190)
    if len(lines) > 2:
        raise ExternalError("storyboard_title_does_not_fit", retryable=False)
    for index, line in enumerate(lines):
        text(40, 18 + index * 34, line, 30, heavy=True)
    quality = (
        "Reviewed authored explanation" if reviewed else "AI-generated explanation - verify the references"
    )
    text(
        40,
        100,
        quality + (" | Synthetic offline narration" if narrated else " | Captioned, sound off"),
        17,
        muted,
    )
    draw.line((40, 133, 1240, 133), fill="#3B4C63", width=2)
    text(40, 146, f"{scene_index + 1}/{len(story.scenes)}  {scene.title}", 22, heavy=True)
    count = len(story.actors)
    centers = {}
    for index, actor in enumerate(story.actors):
        if count <= 3:
            centers[actor.id] = (WIDTH * (index + 1) / (count + 1), 345)
        else:
            centers[actor.id] = (215 + (index % 3) * 425, 265 + (index // 3) * 215)
    boxes = {name: (x - 165, y - 57, x + 165, y + 57) for name, (x, y) in centers.items()}

    def edge_path(edge):
        ax, ay = centers[edge.source]
        bx, by = centers[edge.target]
        if ay == by and abs(bx - ax) > 500:
            return [(ax, ay + 57), (ax, ay + 72), (bx, by + 72), (bx, by + 57)]
        dx, dy = bx - ax, by - ay
        ratio = min(165 / abs(dx) if dx else math.inf, 57 / abs(dy) if dy else math.inf)
        return [(ax + dx * ratio, ay + dy * ratio), (bx - dx * ratio, by - dy * ratio)]

    for edge in story.edges:
        points = edge_path(edge)
        active = edge.id in scene.active_edges
        color = palette[edge.kind] if active else "#46566B"
        draw.line(points, fill=color, width=4 if active else 2)
        (ax, ay), (bx, by) = points[-2:]
        angle = math.atan2(by - ay, bx - ax)
        draw.polygon(
            [
                (bx, by),
                (bx - 12 * math.cos(angle - 0.4), by - 12 * math.sin(angle - 0.4)),
                (bx - 12 * math.cos(angle + 0.4), by - 12 * math.sin(angle + 0.4)),
            ],
            fill=color,
        )
        if active and story.pattern in ("flow", "decision"):
            lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
            position = ((local_time % 2.8) / 2.8) * sum(lengths)
            for (a, b), length in zip(zip(points, points[1:]), lengths):
                if position <= length:
                    fraction = position / length
                    x, y = a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction
                    draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color)
                    break
                position -= length
    for actor in story.actors:
        bounds = boxes[actor.id]
        highlight = actor.id in scene.highlights
        status = scene.states.get(actor.id)
        accent = state_colors.get(status, "#85CBFF" if highlight else "#50627C")
        draw.rounded_rectangle(
            bounds, radius=12, fill="#1D2C40", outline=accent, width=3 if highlight or status else 1
        )
        lines = _wrapped(draw, actor.label, font_set[22, True], 300)
        if len(lines) > 3:
            raise ExternalError("actor_label_does_not_fit", retryable=False)
        for index, line in enumerate(lines):
            x = centers[actor.id][0] - draw.textlength(line, font=font_set[22, True]) / 2
            text(x, bounds[1] + 15 + index * 25, line, 22, heavy=True)
        if status:
            text(bounds[0] + 15, bounds[3] - 25, status.upper(), 17, accent)
    labels = [edge.label for edge in story.edges if edge.id in scene.active_edges and edge.label]
    if labels:
        legend = _wrapped(draw, "Active paths: " + "  |  ".join(labels), font_set[17, False], 1190)
        if len(legend) > 2:
            raise ExternalError("edge_labels_do_not_fit", retryable=False)
        for index, line in enumerate(legend):
            text(40, 556 + index * 20, line, 17, muted)
    draw.rounded_rectangle((30, 604, 1250, 696), radius=12, fill="#24364D")
    captions = _wrapped(draw, scene.caption, font_set[22, False], 1170)
    if len(captions) > 2:
        raise ExternalError("scene_caption_does_not_fit", retryable=False)
    for index, line in enumerate(captions):
        text(50, 613 + index * 27, line, 22)
    text(50, 671, "Illustrative sequence, not real system timing. Follow the lesson references.", 17, muted)
    draw.rectangle((30, 706, 30 + 1220 * progress, 711), fill="#60DFF4")
    return image


def prepare_audio(story: Storyboard, folder: Path, budget: Budget, *, voice=True):
    narrator = shutil.which("espeak-ng") if voice else None
    if voice and not narrator:
        raise ExternalError("offline_narrator_missing_use_voice_off_or_install_espeak_ng", retryable=False)
    durations, audio_chunks = [], []
    rate = 22050
    for index, scene in enumerate(story.scenes):
        if voice:
            script, output = folder / f"scene-{index}.txt", folder / f"scene-{index}.wav"
            script.write_text(scene.narration, encoding="utf-8")
            try:
                result = subprocess.run(
                    [narrator, "-v", "en-us", "-s", "150", "-f", str(script), "-w", str(output)],
                    capture_output=True,
                    timeout=min(20, budget.remaining()),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ExternalError("offline_narration_failed") from None
            if result.returncode or not output.exists():
                raise ExternalError("offline_narration_failed")
            with wave.open(str(output), "rb") as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                    raise ExternalError("unsupported_narration_audio")
                if index and wav.getframerate() != rate:
                    raise ExternalError("narration_sample_rate_changed")
                rate = wav.getframerate()
                pcm = wav.readframes(wav.getnframes())
                spoken = wav.getnframes() / rate
            if not pcm or spoken > 32:
                raise ExternalError("narration_duration_out_of_bounds")
        else:
            spoken, pcm = max(4, len(scene.narration.split()) / 2.5), b""
        duration = math.ceil(max(4, spoken + 0.7) * FPS) / FPS
        durations.append(duration)
        if voice:
            frame_count = round(duration * rate)
            audio_chunks.append(pcm + b"\0" * max(0, frame_count * 2 - len(pcm)))
    if sum(durations) > 165:
        raise ExternalError("storyboard_video_too_long")
    audio_path = folder / "narration.wav"
    if voice:
        with wave.open(str(audio_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(b"".join(audio_chunks))
    return durations, audio_path if voice else None


def render_storyboard(
    story: Storyboard, folder: Path, budget: Budget, *, voice=True, static=False, reviewed=False
):
    font_set = fonts()
    poster = folder / "storyboard.png"
    render_frame(story, 0, 0.7, 0, font_set, reviewed=reviewed, narrated=voice and not static).save(poster)
    if static:
        return poster, {"kind": "photo", "voice": False}
    encoder = shutil.which("ffmpeg")
    if not encoder:
        raise ExternalError("ffmpeg_missing", retryable=False)
    durations, audio = prepare_audio(story, folder, budget, voice=voice)
    output = folder / "storyboard.mp4"
    command = [
        encoder,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
    ]
    if audio:
        command += ["-i", str(audio), "-c:a", "aac", "-b:a", "96k"]
    else:
        command += ["-an"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-t",
        str(sum(durations)),
        str(output),
    ]
    elapsed, total = 0, sum(durations)
    with (folder / "encoder-error.txt").open("wb") as error_log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=error_log)
        try:
            for index, duration in enumerate(durations):
                for frame in range(round(duration * FPS)):
                    budget.remaining()
                    local = frame / FPS
                    image = render_frame(
                        story,
                        index,
                        local,
                        (elapsed + local) / total,
                        font_set,
                        reviewed=reviewed,
                        narrated=voice,
                    )
                    process.stdin.write(image.tobytes())
                elapsed += duration
            process.stdin.close()
            if process.wait(timeout=min(45, budget.remaining())):
                raise ExternalError("storyboard_encoding_failed")
        except (OSError, subprocess.TimeoutExpired):
            raise ExternalError("storyboard_encoding_failed") from None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return output, {
        "kind": "video",
        "voice": voice,
        "duration": total,
        "scene_durations": durations,
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
    }
