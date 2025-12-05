# creating-video/tests/test_validators.py
import pytest
from pathlib import Path
import sys

# Adjust sys.path to import the script from the parent directory's 'scripts' folder
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from validators import (
    validate_character_recipe,
    validate_scene_recipe,
    validate_motion_recipe,
    validate_resolved_recipe,
    RecipeValidationError, # Import the custom exception
)

# --- Test validate_character_recipe ---
def test_validate_character_recipe_valid():
    data = {"name": "Hero", "description": "A brave hero."}
    validate_character_recipe(data) # Should not raise error

def test_validate_character_recipe_invalid_type():
    with pytest.raises(RecipeValidationError, match="Character data must be a dictionary."):
        validate_character_recipe("not a dict")

def test_validate_character_recipe_missing_name():
    data = {"description": "A brave hero."}
    with pytest.raises(RecipeValidationError, match="Character recipe must have a 'name'"):
        validate_character_recipe(data)

def test_validate_character_recipe_missing_description():
    data = {"name": "Hero"}
    with pytest.raises(RecipeValidationError, match="Character recipe must have a 'description'"):
        validate_character_recipe(data)

# --- Test validate_scene_recipe ---
def test_validate_scene_recipe_valid():
    data = {
        "name": "Forest",
        "environment": "Lush green forest",
        "lighting": {"style": "Daylight"},
        "resolution": {"width": 1920, "height": 1080},
    }
    validate_scene_recipe(data) # Should not raise error

def test_validate_scene_recipe_missing_resolution():
    data = {
        "name": "Forest",
        "environment": "Lush green forest",
        "lighting": {"style": "Daylight"},
    }
    with pytest.raises(RecipeValidationError, match="Scene recipe must have a 'resolution'"):
        validate_scene_recipe(data)

def test_validate_scene_recipe_invalid_resolution_width():
    data = {
        "name": "Forest",
        "environment": "Lush green forest",
        "lighting": {"style": "Daylight"},
        "resolution": {"width": 0, "height": 1080},
    }
    with pytest.raises(RecipeValidationError, match="resolution must have a positive integer 'width'"):
        validate_scene_recipe(data)

# --- Test validate_motion_recipe ---
def test_validate_motion_recipe_valid():
    data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [
            {"name": "Start", "start_time": 0.0, "end_time": 2.0, "pose": "standing"},
            {"name": "Mid", "start_time": 2.0, "end_time": 5.0, "pose": "walking"},
        ],
    }
    validate_motion_recipe(data) # Should not raise error

def test_validate_motion_recipe_empty_phases():
    data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [],
    }
    with pytest.raises(RecipeValidationError, match="Motion recipe must have at least one phase."):
        validate_motion_recipe(data)

def test_validate_motion_recipe_overlapping_phases():
    data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [
            {"name": "Start", "start_time": 0.0, "end_time": 2.5, "pose": "standing"},
            {"name": "Mid", "start_time": 2.0, "end_time": 5.0, "pose": "walking"}, # Overlap
        ],
    }
    with pytest.raises(RecipeValidationError, match="start_time .* does not follow previous phase end_time .*"):
        validate_motion_recipe(data)

def test_validate_motion_recipe_gap_between_phases():
    data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [
            {"name": "Start", "start_time": 0.0, "end_time": 1.0, "pose": "standing"},
            {"name": "Mid", "start_time": 2.0, "end_time": 5.0, "pose": "walking"}, # Gap
        ],
    }
    with pytest.raises(RecipeValidationError, match="start_time .* does not follow previous phase end_time .*"):
        validate_motion_recipe(data)

def test_validate_motion_recipe_duration_mismatch():
    data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [
            {"name": "Start", "start_time": 0.0, "end_time": 4.0, "pose": "standing"},
        ],
    }
    with pytest.raises(RecipeValidationError, match="Last phase end_time .* does not match motion duration_sec."):
        validate_motion_recipe(data)

# --- Test validate_resolved_recipe ---
def test_validate_resolved_recipe_valid():
    char_data = {"name": "Hero", "description": "A brave hero."}
    scene_data = {
        "name": "Forest",
        "environment": "Lush green forest",
        "lighting": {"style": "Daylight"},
        "resolution": {"width": 1920, "height": 1080},
    }
    motion_data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [
            {"name": "Start", "start_time": 0.0, "end_time": 5.0, "pose": "standing"},
        ],
    }
    resolved_recipe = {
        "character": char_data,
        "scene": scene_data,
        "motion": motion_data,
        "resolution": {"width": 1920, "height": 1080},
        "_meta": {},
    }
    validate_resolved_recipe(resolved_recipe) # Should not raise error

def test_validate_resolved_recipe_missing_character():
    resolved_recipe = {
        "scene": {}, "motion": {}, "resolution": {}, "_meta": {}
    }
    with pytest.raises(RecipeValidationError, match="Resolved recipe must contain 'character' data."):
        validate_resolved_recipe(resolved_recipe)

def test_validate_resolved_recipe_resolution_mismatch():
    char_data = {"name": "Hero", "description": "A brave hero."}
    scene_data = {
        "name": "Forest",
        "environment": "Lush green forest",
        "lighting": {"style": "Daylight"},
        "resolution": {"width": 1920, "height": 1080},
    }
    motion_data = {
        "name": "Walk",
        "duration_sec": 5.0,
        "fps_hint": 24,
        "phases": [
            {"name": "Start", "start_time": 0.0, "end_time": 5.0, "pose": "standing"},
        ],
    }
    resolved_recipe = {
        "character": char_data,
        "scene": scene_data,
        "motion": motion_data,
        "resolution": {"width": 1280, "height": 720}, # Mismatch
        "_meta": {},
    }
    with pytest.raises(RecipeValidationError, match="Resolved recipe's top-level resolution must match scene's resolution."):
        validate_resolved_recipe(resolved_recipe)
