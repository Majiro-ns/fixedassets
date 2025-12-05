import sys
import yaml
from pathlib import Path

# Add project root to sys.path to allow importing from 'scripts'
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.generate_video import main as generate_video_main

def test_video_generation_smoke(tmp_path: Path):
    """
    A smoke test that runs the main video generation script.
    It uses a temporary config to create a very short video,
    then asserts that an MP4 file was actually created.
    """
    # 1. Create temporary directories for outputs
    temp_video_dir = tmp_path / "videos"
    temp_log_dir = tmp_path / "logs"
    temp_video_dir.mkdir()
    temp_log_dir.mkdir()

    # 2. Create a temporary config file for a fast run
    test_config_data = {
        'motion': {'duration_sec': 0.5, 'fps': 4},
        'resolution': {'width': 64, 'height': 64},
        'paths': {
            'output_dir': str(temp_video_dir),
            'log_dir': str(temp_log_dir)
        }
    }
    
    temp_config_path = tmp_path / "test_config.yaml"
    with open(temp_config_path, 'w') as f:
        yaml.dump(test_config_data, f)

    # 3. Run the main script with the temporary config
    # We pass arguments as a list to simulate command-line usage
    result = generate_video_main(['--config', str(temp_config_path)])
    
    assert result == 0, "Script should exit with code 0 on success"

    # 4. Assert that an output video file was created
    video_files = list(temp_video_dir.glob("*.mp4"))
    assert len(video_files) > 0, "At least one MP4 file should have been created"
    
    # 5. Assert that a log file was created
    log_files = list(temp_log_dir.glob("*.yaml"))
    assert len(log_files) > 0, "At least one YAML log file should have been created"

    print(f"\nSmoke test passed. Found video: {video_files[0]}")
