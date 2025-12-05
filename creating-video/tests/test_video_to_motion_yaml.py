import pytest
from pathlib import Path
import yaml
import sys
import subprocess

# Adjust sys.path to import the script from the parent directory's 'scripts' folder
# This assumes pytest is run from the 'creating-video' directory.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from video_to_motion_yaml import (
    get_video_duration_sec,
    build_phases_from_duration,
    write_motion_yaml,
    main as video_to_motion_yaml_main, # Rename main to avoid conflict
)


def test_build_phases_from_duration_basic():
    duration = 9.0
    num_phases = 3
    phases = build_phases_from_duration(duration, num_phases)

    assert len(phases) == 3
    assert phases[0]["name"] == "Phase 1"
    assert phases[0]["start_time"] == 0.0
    assert phases[0]["end_time"] == 3.0
    assert "pose" in phases[0]

    assert phases[1]["name"] == "Phase 2"
    assert phases[1]["start_time"] == 3.0
    assert phases[1]["end_time"] == 6.0

    assert phases[2]["name"] == "Phase 3"
    assert phases[2]["start_time"] == 6.0
    assert phases[2]["end_time"] == 9.0

    # Check for continuity
    for i in range(num_phases - 1):
        assert phases[i]["end_time"] == phases[i+1]["start_time"]


def test_build_phases_handles_non_divisible_duration():
    duration = 10.0
    num_phases = 3
    phases = build_phases_from_duration(duration, num_phases)

    assert len(phases) == 3
    assert phases[0]["start_time"] == 0.0
    assert abs(phases[2]["end_time"] - 10.0) < 1e-9

    # Check for continuity and coverage
    assert phases[0]["end_time"] == pytest.approx(10.0 / 3, rel=1e-3)
    assert phases[1]["start_time"] == pytest.approx(10.0 / 3, rel=1e-3)
    assert phases[1]["end_time"] == pytest.approx(2 * 10.0 / 3, rel=1e-3)
    assert phases[2]["start_time"] == pytest.approx(2 * 10.0 / 3, rel=1e-3)


def test_build_phases_zero_phases():
    assert build_phases_from_duration(10.0, 0) == []


def test_build_phases_negative_duration():
    phases = build_phases_from_duration(-5.0, 2)
    assert len(phases) == 2
    assert phases[0]['start_time'] == 0.0
    assert phases[1]['end_time'] == 0.0


def test_write_motion_yaml_creates_expected_structure(tmp_path):
    out_file = tmp_path / "test_motion.yaml"
    video_file = Path("/fake/video.mp4")
    duration = 5.0
    phases = [
        {"name": "Phase 1", "start_time": 0.0, "end_time": 5.0, "pose": "placeholder"}
    ]

    write_motion_yaml(out_file, video_file, duration, phases)

    assert out_file.is_file()
    with out_file.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "motion" in data
    motion_data = data["motion"]

    assert motion_data["name"] == f"Auto-generated motion from {video_file.name}"
    assert motion_data["source_video"] == str(video_file.resolve())
    assert motion_data["duration_sec"] == 5.0
    assert "fps_hint" in motion_data
    assert len(motion_data["phases"]) == 1
    assert motion_data["phases"][0]["name"] == "Phase 1"


def test_cli_flow_success(monkeypatch, tmp_path):
    """
    Simulates the CLI behavior, mocking external dependencies.
    """
    # Mock get_video_duration_sec
    mock_get_duration = lambda path: 15.0
    monkeypatch.setattr("video_to_motion_yaml.get_video_duration_sec", mock_get_duration)

    # Mock write_motion_yaml to capture arguments
    captured_args = {}
    def mock_write_motion_yaml(out_path, video_path, duration_sec, phases, **kwargs):
        captured_args['out_path'] = out_path
        captured_args['video_path'] = video_path
        captured_args['duration_sec'] = duration_sec
        captured_args['phases'] = phases
    monkeypatch.setattr("video_to_motion_yaml.write_motion_yaml", mock_write_motion_yaml)

    # Mock sys.argv
    video_path = tmp_path / "input.mp4"
    video_path.touch() # create dummy file
    out_path = tmp_path / "output.yaml"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scripts/video_to_motion_yaml.py",
            "--video", str(video_path),
            "--out", str(out_path),
            "--num-phases", "5",
        ],
    )

    video_to_motion_yaml_main()

    assert captured_args['out_path'] == out_path
    assert captured_args['video_path'] == video_path
    assert captured_args['duration_sec'] == 15.0
    assert len(captured_args['phases']) == 5
    assert captured_args['phases'][-1]['end_time'] == 15.0


def test_cli_flow_default_out_path(monkeypatch, tmp_path):
    """
    Tests that the default output path is handled correctly.
    """
    # Change CWD for this test to simulate running from `creating-video`
    # This is important for default path resolution.
    original_cwd = Path.cwd()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "recipes").mkdir() # Create the recipes directory

    # Mock dependencies
    monkeypatch.setattr("video_to_motion_yaml.get_video_duration_sec", lambda path: 10.0)

    captured_args = {}
    def mock_write_motion_yaml(out_path, video_path, duration_sec, phases, **kwargs):
        captured_args['out_path'] = out_path
    monkeypatch.setattr("video_to_motion_yaml.write_motion_yaml", mock_write_motion_yaml)

    video_path = tmp_path / "source_vid.mov"
    video_path.touch()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scripts/video_to_motion_yaml.py",
            "--video", str(video_path),
        ],
    )

    video_to_motion_yaml_main()

    expected_path = Path("recipes") / "source_vid_motion.yaml"
    assert captured_args['out_path'] == expected_path
    monkeypatch.chdir(original_cwd) # Restore original CWD


def test_cli_file_not_found(monkeypatch, capsys):
    """
    Tests error handling when the video file doesn't exist.
    """
    # Mock sys.argv
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scripts/video_to_motion_yaml.py",
            "--video", "non_existent_file.mp4",
        ],
    )

    with pytest.raises(SystemExit) as e:
        video_to_motion_yaml_main()

    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Video file not found" in captured.err


def test_get_video_duration_ffprobe_missing(monkeypatch, tmp_path):
    """
    Tests error handling when ffprobe is not installed.
    """
    def mock_subprocess_run(*args, **kwargs):
        raise FileNotFoundError # Simulate ffprobe not found
    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    dummy_video = tmp_path / "dummy.mp4"
    dummy_video.touch() # Create a dummy file so FileNotFoundError is from ffprobe, not video itself

    with pytest.raises(RuntimeError, match="ffprobe command not found"):
        get_video_duration_sec(dummy_video)

