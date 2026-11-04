"""Load the small, self-authored FoodMate demo catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def normalize_text(value: str) -> str:
    return "".join(str(value).strip().lower().split())


@lru_cache(maxsize=1)
def foods() -> tuple[dict[str, Any], ...]:
    with (DATA_DIR / "foods.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return tuple(payload["foods"])


@lru_cache(maxsize=1)
def recipes() -> tuple[dict[str, Any], ...]:
    with (DATA_DIR / "recipes.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return tuple(payload["recipes"])


def food_by_id(food_id: str) -> dict[str, Any] | None:
    return next((food for food in foods() if food["id"] == food_id), None)


def find_food(query: str | None) -> dict[str, Any] | None:
    if not query:
        return None
    needle = normalize_text(query)
    for food in foods():
        candidates = [food["id"], food["name"], food.get("name_en", ""), *food.get("aliases", [])]
        if any(normalize_text(candidate) == needle for candidate in candidates if candidate):
            return food
    return None


def food_names() -> list[str]:
    return [food["name"] for food in foods()]


def recipe_by_id(recipe_id: str) -> dict[str, Any] | None:
    return next((recipe for recipe in recipes() if recipe["id"] == recipe_id), None)
