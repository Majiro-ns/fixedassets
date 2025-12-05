import argparse
import json
import subprocess
from pathlib import Path
import sys
import yaml

def get_video_duration_sec(video_path: Path) -> float:
    """
    Gets the duration of a video file in seconds using ffprobe.

    Args:
        video_path: Path to the video file.

    Returns:
        The duration of the video in seconds.

    Raises:
        FileNotFoundError: If the video file does not exist.
        RuntimeError: If ffprobe fails or returns unexpected output.
    """
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file not found at: {video_path}")

    command = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8"
        )
        metadata = json.loads(result.stdout)
        duration = float(metadata["format"]["duration"])
        return duration
    except FileNotFoundError:
        raise RuntimeError("ffprobe command not found. Please ensure ffprobe is installed and in your PATH.")
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"Failed to get video duration for {video_path}. Error: {e}") from e


def build_phases_from_duration(duration_sec: float, num_phases: int) -> list[dict]:
    """
    Divides a duration into a specified number of phases.

    Returns a list of dicts like:
    [
      {"name": "Phase 1", "start_time": 0.0, "end_time": 1.5, "pose": "phase 1 placeholder"},
      ...
    ]
    """
    if num_phases <= 0:
        return []
    if duration_sec < 0:
        duration_sec = 0

    phase_duration = duration_sec / num_phases
    phases = []
    current_time = 0.0

    for i in range(num_phases):
        start_time = current_time
        end_time = start_time + phase_duration
        phases.append({
            "name": f"Phase {i + 1}",
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "pose": f"phase {i + 1} placeholder",
        })
        current_time = end_time

    # Ensure the last phase ends exactly at the total duration
    if phases:
        phases[-1]["end_time"] = round(duration_sec, 3)

    return phases


def write_motion_yaml(
    out_path: Path,
    video_path: Path,
    duration_sec: float,
    phases: list[dict],
    fps_hint: int = 24,
):
    """Writes the motion data to a YAML file."""
    motion_data = {
        "name": f"Auto-generated motion from {video_path.name}",
        "source_video": str(video_path.resolve()),
        "duration_sec": round(duration_sec, 3),
        "fps_hint": fps_hint,
        "phases": phases,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.dump({"motion": motion_data}, f, default_flow_style=False, sort_keys=False, indent=2)
    print(f"Successfully wrote motion YAML to: {out_path}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a motion YAML file from a video."
    )
    parser.add_argument(
        "--video",
        type=Path,
        required=True,
        help="Path to the source video file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to the output YAML file. Defaults to 'recipes/<video_name>_motion.yaml'.",
    )
    parser.add_argument(
        "--num-phases",
        type=int,
        default=3,
        help="Number of phases to divide the video into.",
    )
    args = parser.parse_args()

    try:
        duration_sec = get_video_duration_sec(args.video)
        phases = build_phases_from_duration(duration_sec, args.num_phases)

        out_path = args.out
        if out_path is None:
            # The user prompt specifies the project root is `creating-video`,
            # so the script is likely run from there.
            # Default output path should be relative to `creating-video` root.
            out_path = Path("recipes") / f"{args.video.stem}_motion.yaml"

        write_motion_yaml(out_path, args.video, duration_sec, phases)

    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
