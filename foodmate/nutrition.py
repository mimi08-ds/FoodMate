"""Deterministic nutrition calculations over the bundled demo catalog."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .catalog import find_food, food_by_id


NUTRIENTS = ("kcal", "protein_g", "fat_g", "carbs_g")
DISPLAY_NAMES = {
    "kcal": "热量",
    "protein_g": "蛋白质",
    "fat_g": "脂肪",
    "carbs_g": "碳水化合物",
}


def nutrition_for_items(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {key: 0.0 for key in NUTRIENTS}
    missing: list[str] = []
    included: list[str] = []
    for item in items:
        name = str(item.get("name", "")).strip()
        grams_value = item.get("grams", 0)
        try:
            grams = float(grams_value)
        except (TypeError, ValueError):
            missing.append(name or "未命名食材")
            continue
        if not name or grams <= 0:
            if name and grams < 0:
                missing.append(name)
            continue

        food = food_by_id(str(item.get("food_id", ""))) if item.get("food_id") else None
        food = food or find_food(name)
        if food is None:
            missing.append(name)
            continue

        per_100g = food["per_100g"]
        for nutrient in NUTRIENTS:
            totals[nutrient] += float(per_100g[nutrient]) * grams / 100.0
        included.append(food["name"])

    rounded = {key: round(value, 1) for key, value in totals.items()}
    return {
        "totals": rounded,
        "missing": missing,
        "included": included,
        "complete": not missing,
    }


def nutrition_for_recipe(recipe: Mapping[str, Any]) -> dict[str, Any]:
    items = []
    for ingredient in recipe.get("ingredients", []):
        food = food_by_id(str(ingredient.get("food_id", "")))
        items.append(
            {
                "food_id": ingredient.get("food_id"),
                "name": food["name"] if food else str(ingredient.get("name", "")),
                "grams": ingredient.get("grams", 0),
            }
        )
    return nutrition_for_items(items)


def combine_recipe_items(recipes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for recipe in recipes:
        for ingredient in recipe.get("ingredients", []):
            food = food_by_id(str(ingredient.get("food_id", "")))
            combined.append(
                {
                    "food_id": ingredient.get("food_id"),
                    "name": food["name"] if food else str(ingredient.get("name", "")),
                    "grams": ingredient.get("grams", 0),
                }
            )
    return combined
