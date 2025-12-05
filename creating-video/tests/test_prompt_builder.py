# creating-video/tests/test_prompt_builder.py
import pytest
from pathlib import Path
import sys

# Adjust sys.path to import the script from the parent directory's 'scripts' folder
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from prompt_builder import build_prompts_from_recipe

def test_build_prompts_from_recipe_basic():
    resolved_recipe = {
        "character": {"name": "Alice", "description": "A young woman"},
        "scene": {
            "name": "Park",
            "environment": "a sunny park with green trees",
            "lighting": {"style": "bright natural light"},
            "resolution": {"width": 1920, "height": 1080},
        },
        "motion": {
            "name": "Walking",
            "duration_sec": 3.0,
            "fps_hint": 24,
            "phases": [
                {"name": "Phase 1", "start_time": 0.0, "end_time": 1.5, "pose": "walking slowly"},
                {"name": "Phase 2", "start_time": 1.5, "end_time": 3.0, "pose": "walking quickly"},
            ],
        },
        "resolution": {"width": 1920, "height": 1080},
        "_meta": {},
    }

    before_prompt, after_prompt = build_prompts_from_recipe(resolved_recipe)

    assert "A young woman named Alice." in before_prompt
    assert "The scene is set in a sunny park with green trees with bright natural light." in before_prompt
    assert "The video depicts Alice in a sunny park with green trees." in after_prompt
    assert "The motion unfolds over 3.0 seconds, with 2 distinct phases." in after_prompt
    assert "From 0.0s to 1.5s, Alice is walking slowly. The movement is slow and deliberate." in after_prompt
    assert "From 1.5s to 3.0s, Alice is walking quickly. The movement is rapid and energetic." in after_prompt


def test_build_prompts_from_recipe_with_intent():
    resolved_recipe = {
        "character": {"name": "Bob", "description": "An old man"},
        "scene": {
            "name": "Cafe",
            "environment": "a cozy cafe",
            "lighting": {"style": "warm indoor light"},
            "resolution": {"width": 1280, "height": 720},
        },
        "motion": {
            "name": "Sitting",
            "duration_sec": 5.0,
            "fps_hint": 24,
            "phases": [
                {"name": "Phase 1", "start_time": 0.0, "end_time": 5.0, "pose": "sitting calmly, breathing slowly"},
            ],
            "tags": {"intent": "peaceful contemplation"},
        },
        "resolution": {"width": 1280, "height": 720},
        "_meta": {},
    }

    before_prompt, after_prompt = build_prompts_from_recipe(resolved_recipe)

    assert "The overall intention of the motion is: peaceful contemplation." in before_prompt
    assert "From 0.0s to 5.0s, Bob is sitting calmly, breathing slowly. The movement is slow and deliberate. Subtle movements like breathing or swaying are visible." in after_prompt


def test_build_prompts_from_recipe_minimal_data():
    resolved_recipe = {
        "character": {},
        "scene": {},
        "motion": {},
        "resolution": {},
        "_meta": {},
    }

    before_prompt, after_prompt = build_prompts_from_recipe(resolved_recipe)

    assert "A character named The character." in before_prompt
    assert "The scene is set in a generic environment with neutral lighting." in before_prompt
    assert "The motion unfolds over 0.0 seconds, with 0 distinct phases." in after_prompt
    assert "The video depicts The character in a generic environment." in after_prompt
