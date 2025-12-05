# creating-video/scripts/validators.py
from pathlib import Path

class RecipeValidationError(ValueError):
    """Custom exception for recipe validation errors."""
    pass

def validate_character_recipe(character_data: dict):
    """Validates the structure and content of a character recipe."""
    if not isinstance(character_data, dict):
        raise RecipeValidationError("Character data must be a dictionary.")
    if "name" not in character_data or not isinstance(character_data["name"], str):
        raise RecipeValidationError("Character recipe must have a 'name' (string).")
    if "description" not in character_data or not isinstance(character_data["description"], str):
        raise RecipeValidationError("Character recipe must have a 'description' (string).")
    # Add more specific validations as needed, e.g., for image paths, style, etc.

def validate_scene_recipe(scene_data: dict):
    """Validates the structure and content of a scene recipe."""
    if not isinstance(scene_data, dict):
        raise RecipeValidationError("Scene data must be a dictionary.")
    if "name" not in scene_data or not isinstance(scene_data["name"], str):
        raise RecipeValidationError("Scene recipe must have a 'name' (string).")
    if "environment" not in scene_data or not isinstance(scene_data["environment"], str):
        raise RecipeValidationError("Scene recipe must have an 'environment' (string).")
    if "lighting" not in scene_data or not isinstance(scene_data["lighting"], dict):
        raise RecipeValidationError("Scene recipe must have 'lighting' (dictionary).")
    if "style" not in scene_data["lighting"] or not isinstance(scene_data["lighting"]["style"], str):
        raise RecipeValidationError("Scene lighting must have a 'style' (string).")
    if "resolution" not in scene_data or not isinstance(scene_data["resolution"], dict):
        raise RecipeValidationError("Scene recipe must have a 'resolution' (dictionary).")
    if "width" not in scene_data["resolution"] or not isinstance(scene_data["resolution"]["width"], int) or scene_data["resolution"]["width"] <= 0:
        raise RecipeValidationError("Scene resolution must have a positive integer 'width'.")
    if "height" not in scene_data["resolution"] or not isinstance(scene_data["resolution"]["height"], int) or scene_data["resolution"]["height"] <= 0:
        raise RecipeValidationError("Scene resolution must have a positive integer 'height'.")
    # Add more specific validations as needed, e.g., for camera angles, weather, etc.

def validate_motion_recipe(motion_data: dict):
    """Validates the structure and content of a motion recipe."""
    if not isinstance(motion_data, dict):
        raise RecipeValidationError("Motion data must be a dictionary.")
    if "name" not in motion_data or not isinstance(motion_data["name"], str):
        raise RecipeValidationError("Motion recipe must have a 'name' (string).")
    if "duration_sec" not in motion_data or not isinstance(motion_data["duration_sec"], (int, float)) or motion_data["duration_sec"] <= 0:
        raise RecipeValidationError("Motion recipe must have a positive 'duration_sec' (number).")
    if "fps_hint" not in motion_data or not isinstance(motion_data["fps_hint"], int) or motion_data["fps_hint"] <= 0:
        raise RecipeValidationError("Motion recipe must have a positive integer 'fps_hint'.")
    if "phases" not in motion_data or not isinstance(motion_data["phases"], list):
        raise RecipeValidationError("Motion recipe must have 'phases' (list).")
    if not motion_data["phases"]:
        raise RecipeValidationError("Motion recipe must have at least one phase.")

    last_end_time = 0.0
    for i, phase in enumerate(motion_data["phases"]):
        if not isinstance(phase, dict):
            raise RecipeValidationError(f"Phase {i+1} in motion recipe must be a dictionary.")
        if "name" not in phase or not isinstance(phase["name"], str):
            raise RecipeValidationError(f"Phase {i+1} must have a 'name' (string).")
        if "start_time" not in phase or not isinstance(phase["start_time"], (int, float)) or phase["start_time"] < 0:
            raise RecipeValidationError(f"Phase {i+1} must have a non-negative 'start_time' (number).")
        if "end_time" not in phase or not isinstance(phase["end_time"], (int, float)) or phase["end_time"] <= phase["start_time"]:
            raise RecipeValidationError(f"Phase {i+1} must have an 'end_time' (number) greater than its 'start_time'.")
        if "pose" not in phase or not isinstance(phase["pose"], str):
            raise RecipeValidationError(f"Phase {i+1} must have a 'pose' (string).")

        # Check for continuity (no gaps or overlaps)
        if i > 0 and abs(phase["start_time"] - last_end_time) > 1e-6:
            raise RecipeValidationError(f"Phase {i+1} start_time ({phase['start_time']}) does not follow previous phase end_time ({last_end_time}).")
        last_end_time = phase["end_time"]

    # Check if the total duration matches the last phase's end time
    if abs(last_end_time - motion_data["duration_sec"]) > 1e-6:
        raise RecipeValidationError(f"Last phase end_time ({last_end_time}) does not match motion duration_sec ({motion_data['duration_sec']}).")


def validate_resolved_recipe(resolved_recipe: dict):
    """Validates the complete resolved recipe structure."""
    if not isinstance(resolved_recipe, dict):
        raise RecipeValidationError("Resolved recipe must be a dictionary.")
    if "character" not in resolved_recipe:
        raise RecipeValidationError("Resolved recipe must contain 'character' data.")
    if "scene" not in resolved_recipe:
        raise RecipeValidationError("Resolved recipe must contain 'scene' data.")
    if "motion" not in resolved_recipe:
        raise RecipeValidationError("Resolved recipe must contain 'motion' data.")
    if "resolution" not in resolved_recipe:
        raise RecipeValidationError("Resolved recipe must contain 'resolution' data.")

    validate_character_recipe(resolved_recipe["character"])
    validate_scene_recipe(resolved_recipe["scene"])
    validate_motion_recipe(resolved_recipe["motion"])

    # Check resolution consistency
    if resolved_recipe["resolution"]["width"] != resolved_recipe["scene"]["resolution"]["width"] or \
       resolved_recipe["resolution"]["height"] != resolved_recipe["scene"]["resolution"]["height"]:
        raise RecipeValidationError("Resolved recipe's top-level resolution must match scene's resolution.")

    # Check duration consistency
    if resolved_recipe["motion"]["duration_sec"] <= 0:
        raise RecipeValidationError("Resolved recipe motion duration_sec must be positive.")
