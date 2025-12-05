from typing import Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

def build_prompts_from_recipe(resolved_recipe: Dict[str, Any]) -> Tuple[str, str]:
    """
    Builds 'before' and 'after' text prompts from a resolved recipe,
    incorporating details from character, scene, and motion phases.
    """
    character = resolved_recipe.get("character", {})
    scene = resolved_recipe.get("scene", {})
    motion = resolved_recipe.get("motion", {})
    resolution = resolved_recipe.get("resolution", {})

    # Base elements for the prompt
    char_desc = character.get("description", "A character")
    char_name = character.get("name", "The character")
    scene_env = scene.get("environment", "a generic environment")
    scene_light = scene.get("lighting", {}).get("style", "neutral lighting") # Access style from dict
    
    # Optional tags/intent from motion or top-level recipe
    motion_intent = motion.get("tags", {}).get("intent", "")
    if not motion_intent:
        motion_intent = resolved_recipe.get("tags", {}).get("intent", "")

    # Build 'before' prompt
    before_prompt_parts = [
        f"{char_desc} named {char_name}.",
        f"The scene is set in {scene_env} with {scene_light}.",
    ]
    if motion_intent:
        before_prompt_parts.append(f"The overall intention of the motion is: {motion_intent}.")
    
    before_prompt = " ".join(before_prompt_parts)

    # Build 'after' prompt, focusing on motion phases and details
    after_prompt_parts = [
        f"The video depicts {char_name} in {scene_env}.",
        f"The motion unfolds over {motion.get('duration_sec', 0):.1f} seconds, with {len(motion.get('phases', []))} distinct phases."
    ]

    for i, phase in enumerate(motion.get("phases", [])):
        phase_name = phase.get("name", f"Phase {i+1}")
        start = phase.get("start_time", 0.0)
        end = phase.get("end_time", 0.0)
        pose = phase.get("pose", "a specific pose")
        
        # Add more descriptive language based on pose or other phase attributes
        phase_description_parts = [f"From {start:.1f}s to {end:.1f}s, {char_name} is {pose}."]
        # Example of adding more detail based on keywords in pose
        if "slow" in pose.lower() or "deliberate" in pose.lower():
            phase_description_parts.append("The movement is slow and deliberate.")
        if "rapid" in pose.lower() or "quick" in pose.lower() or "energetic" in pose.lower():
            phase_description_parts.append("The movement is rapid and energetic.")
        if "breathing" in pose.lower() or "swaying" in pose.lower() or "subtle" in pose.lower():
            phase_description_parts.append("Subtle movements like breathing or swaying are visible.")
        
        after_prompt_parts.append(" ".join(phase_description_parts))

    after_prompt = " ".join(after_prompt_parts)

    logger.debug(f"Generated Before Prompt: {before_prompt}")
    logger.debug(f"Generated After Prompt: {after_prompt}")

    return before_prompt, after_prompt