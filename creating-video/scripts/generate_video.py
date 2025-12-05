import argparse
import datetime
import sys
from pathlib import Path
import yaml

# Import the generator interface and implementations
from scripts.model_adapter import DummyVideoGenerator, DiffusersVideoGenerator

# Conditional imports for recipe and prompt building
try:
    from scripts.recipe_loader import load_and_resolve_recipe
    from scripts.prompt_builder import build_prompts_from_recipe
    from scripts.validators import validate_resolved_recipe, RecipeValidationError
except ImportError:
    load_and_resolve_recipe = None
    build_prompts_from_recipe = None
    validate_resolved_recipe = None
    RecipeValidationError = None

def load_config(config_path: Path) -> dict:
    """Loads the YAML configuration file."""
    print(f"Loading configuration from: {config_path}")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config

def ensure_dirs(config: dict) -> tuple[Path, Path]:
    """Ensures that the output directories for videos and logs exist."""
    project_root = Path(__file__).parent.parent
    video_dir = project_root / config['paths']['output_dir']
    log_dir = project_root / config['paths']['log_dir']
    
    video_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Ensured video output directory exists: {video_dir}")
    print(f"Ensured log output directory exists: {log_dir}")
    return video_dir, log_dir

def generate_dummy_video(resolved_recipe: dict, video_dir: Path, timestamp: str) -> Path:
    """
    Selects a backend and calls it to generate the video.
    The function name is kept for backward compatibility with tests.
    """
    output_path = video_dir / f"{timestamp}_{resolved_recipe['motion']['name'].replace(' ', '_')}.mp4"

    # Prepare a motion_spec dictionary for the generator
    motion_spec = {
        "duration_sec": resolved_recipe['motion']['duration_sec'],
        "fps": resolved_recipe['motion']['fps_hint'], # Use fps_hint from motion
        "resolution": resolved_recipe['resolution'],
        "output_path": output_path
    }

    # Select the generator based on the backend configuration
    backend_cfg = resolved_recipe.get("backend", {}) or {}
    backend_type = backend_cfg.get("type", "dummy")
    
    print(f"Selected backend: {backend_type}")

    if backend_type == "dummy":
        generator = DummyVideoGenerator()
    elif backend_type == "diffusers":
        generator = DiffusersVideoGenerator(model_config=backend_cfg.get("diffusers", {}))
    else:
        print(
            f"Warning: Unknown backend type '{backend_type}'. Falling back to 'dummy'.",
            file=sys.stderr
        )
        generator = DummyVideoGenerator()

    # Call the selected generator's generate method
    video_path = generator.generate(
        input_frames=None,
        motion_spec=motion_spec,
        seed=resolved_recipe.get('seed')
    )
    
    return video_path

def write_log(config: dict, video_path: Path, log_dir: Path, timestamp: str, run_meta: dict, backend_type: str, motion_phases_count: int):
    """Writes a YAML log file with details of the generation run."""
    log_data = {
        'run_timestamp': timestamp,
        **run_meta,  # Includes recipe_path, component_paths, and prompts
        'motion': {
            'duration_sec': config['motion']['duration_sec'],
            'fps': config['motion']['fps'],
            'phases_count': motion_phases_count, # New logging field
        },
        'resolution': config['resolution'],
        'output_video_path': str(video_path),
        'backend_type': backend_type, # New logging field
    }
    
    log_path = log_dir / f"{timestamp}_run.yaml"
    with open(log_path, 'w') as f:
        yaml.dump(log_data, f, default_flow_style=False, sort_keys=False)
        
    print(f"Wrote run log to: {log_path}")

def main(argv=None):
    """Main function to generate the video."""
    parser = argparse.ArgumentParser(
        description="Generate a video from a config file or a recipe.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--config', 
        type=Path, 
        default=Path(__file__).parent.parent / 'configs' / 'default.yaml',
        help='Path to a single configuration YAML file.\n(default: %(default)s)'
    )
    group.add_argument(
        '--recipe', 
        type=Path,
        help='Path to a recipe YAML file (e.g., recipes/idol_forward_collapse.yaml).\nThis takes precedence over --config.'
    )
    args = parser.parse_args(argv)

    config = {}
    run_meta = {}
    backend_type = "dummy" # Default backend type
    motion_phases_count = 0

    if args.recipe:
        # --- Recipe-based execution path ---
        if None in [load_and_resolve_recipe, build_prompts_from_recipe, validate_resolved_recipe]:
            print("Error: A required helper module could not be imported. Cannot process recipe.", file=sys.stderr)
            return 1
        
        print(f"Processing recipe: {args.recipe}")
        if not args.recipe.is_file():
            print(f"Error: Recipe file not found at {args.recipe}", file=sys.stderr)
            return 1
        
        try:
            resolved_recipe = load_and_resolve_recipe(args.recipe)
            # validate_resolved_recipe(resolved_recipe) # Already called inside load_and_resolve_recipe
        except (FileNotFoundError, ValueError, RecipeValidationError) as e:
            print(f"Error processing recipe: {e}", file=sys.stderr)
            return 1

        # Build prompts from the resolved recipe
        prompts = build_prompts_from_recipe(resolved_recipe)
        print("Built 'before' prompt:", prompts[0]) # Accessing tuple elements
        print("Built 'after' prompt:", prompts[1]) # Accessing tuple elements

        # Build a minimal internal config compatible with the generator functions
        config = {
            "backend": resolved_recipe.get("backend", {"type": "dummy"}),
            "motion": {
                "duration_sec": resolved_recipe['motion']['duration_sec'],
                "fps": resolved_recipe['motion']['fps_hint'] # Use fps_hint from motion
            },
            "resolution": {
                "width": resolved_recipe['resolution']['width'],
                "height": resolved_recipe['resolution']['height']
            },
            "paths": {
                "output_dir": "outputs/videos",
                "log_dir": "outputs/logs"
            },
            "seed": resolved_recipe.get('seed')
        }
        
        # Populate metadata for the log file
        run_meta = resolved_recipe.get('_meta', {})
        run_meta['prompts'] = {"before_prompt": prompts[0], "after_prompt": prompts[1]} # Store as dict

        backend_type = config.get("backend", {}).get("type", "dummy")
        motion_phases_count = len(resolved_recipe['motion']['phases'])

    else:
        # --- Config-based execution path (backward compatible) ---
        print(f"Processing config: {args.config}")
        if not args.config.is_file():
            print(f"Error: Config file not found at {args.config}", file=sys.stderr)
            return 1
        config = load_config(args.config)
        run_meta['config_path'] = str(args.config)
        # For config-based, we need to construct a resolved_recipe for consistency
        # This is a simplified resolved_recipe based on the config structure
        resolved_recipe = {
            "character": {"name": "Config Character", "description": "Generated from config"},
            "scene": {
                "name": "Config Scene",
                "environment": "Config environment",
                "lighting": {"style": "Config lighting"},
                "resolution": config.get("resolution", {"width": 512, "height": 512})
            },
            "motion": {
                "name": "Config Motion",
                "duration_sec": config.get("motion", {}).get("duration_sec", 1.0),
                "fps_hint": config.get("motion", {}).get("fps", 10),
                "phases": [
                    {"name": "P1", "start_time": 0.0, "end_time": config.get("motion", {}).get("duration_sec", 1.0), "pose": "config pose"}
                ]
            },
            "resolution": config.get("resolution", {"width": 512, "height": 512}),
            "backend": config.get("backend", {"type": "dummy"}),
            "seed": config.get("seed"),
            "_meta": {"config_path": str(args.config)}
        }
        # Validate this constructed resolved_recipe
        try:
            validate_resolved_recipe(resolved_recipe)
        except RecipeValidationError as e:
            print(f"Error validating constructed recipe from config: {e}", file=sys.stderr)
            return 1
        
        backend_type = resolved_recipe.get("backend", {}).get("type", "dummy")
        motion_phases_count = len(resolved_recipe['motion']['phases'])

    # --- Common execution path ---
    video_dir, log_dir = ensure_dirs(config)
    
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # This function now selects the backend and calls the appropriate generator
    video_path = generate_dummy_video(resolved_recipe, video_dir, timestamp)
    
    write_log(config, video_path, log_dir, timestamp, run_meta, backend_type, motion_phases_count)
    
    print("\nGeneration complete.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
