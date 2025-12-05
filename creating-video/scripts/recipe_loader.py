import yaml
from pathlib import Path
from typing import Dict, Any
import logging

from .validators import (
    validate_character_recipe,
    validate_scene_recipe,
    validate_motion_recipe,
    validate_resolved_recipe,
)

logger = logging.getLogger(__name__)

def _load_yaml(path: Path) -> Dict[str, Any]:
    """Helper to load a single YAML file."""
    if not path.is_file():
        raise FileNotFoundError(f"Component YAML not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def _deep_merge(source: Dict, destination: Dict) -> Dict:
    """
    Recursively merges dictionaries. 'source' values overwrite 'destination' values.
    This is used to apply overrides from a recipe to its components.
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
            destination[key] = _deep_merge(value, destination[key])
        else:
            destination[key] = value
    return destination

def load_and_resolve_recipe(recipe_path: Path) -> Dict[str, Any]:
    """
    Loads a recipe YAML, its components (character, scene, motion),
    and merges any specified overrides. Includes validation.

    Args:
        recipe_path: The path to the main recipe file.

    Returns:
        A dictionary containing the fully resolved configuration.
    """
    logger.info(f"Loading and resolving recipe from: {recipe_path}")

    project_root = recipe_path.parent.parent # Assuming recipes are in project_root/recipes
    recipe_data = _load_yaml(recipe_path)

    component_paths = {}
    resolved_config = {}

    # 1. Load base components defined in the recipe and validate them
    for component_name in ['character', 'scene', 'motion']:
        if component_name in recipe_data:
            component_path_str = recipe_data[component_name]
            component_path = (project_root / component_path_str).resolve()
            
            component_paths[component_name] = str(component_path)
            component_data = _load_yaml(component_path)
            
            if component_name == 'character':
                validate_character_recipe(component_data)
            elif component_name == 'scene':
                validate_scene_recipe(component_data)
            elif component_name == 'motion':
                validate_motion_recipe(component_data)
            
            resolved_config[component_name] = component_data
        else:
            raise ValueError(f"Recipe '{recipe_path.name}' is missing required component: {component_name}")

    # 2. Apply overrides from the recipe file
    if 'overrides' in recipe_data and recipe_data['overrides']:
        for component_name, overrides in recipe_data['overrides'].items():
            if component_name in resolved_config:
                # Use deep_merge to apply nested overrides correctly
                resolved_config[component_name] = _deep_merge(overrides, resolved_config[component_name])
            else:
                # This case indicates an override was specified for a component that wasn't in the base recipe.
                # This might be an error in the recipe or an intentional override of a non-existent component.
                logger.warning(f"Override for unknown component '{component_name}' in recipe '{recipe_path.name}'. Ignoring.")

    # 3. Add top-level resolution from scene, as expected by prompt_builder and validators
    if "scene" in resolved_config and "resolution" in resolved_config["scene"]:
        resolved_config["resolution"] = resolved_config["scene"]["resolution"]
    else:
        raise ValueError(f"Resolved recipe from '{recipe_path.name}' is missing scene resolution.")

    # 4. Attach metadata for logging purposes
    resolved_config['_meta'] = {
        'recipe_path': str(recipe_path),
        'component_paths': component_paths
    }

    # 5. Final validation of the complete resolved recipe
    validate_resolved_recipe(resolved_config)

    logger.info("Recipe successfully resolved and validated.")
    return resolved_config