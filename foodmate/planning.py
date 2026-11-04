"""Hard-constraint meal planning with deterministic validation."""

from __future__ import annotations

from itertools import combinations
from typing import Any

from .catalog import find_food, normalize_text
from .nutrition import combine_recipe_items, nutrition_for_items


def split_terms(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else str(value).replace("，", ",").replace("、", ",").replace(";", ",").split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def _term_matches_food(term: str, food_id: str) -> bool:
    food = find_food(food_id)
    if not food:
        return normalize_text(term) in normalize_text(food_id)
    needle = normalize_text(term)
    names = [food["id"], food["name"], food.get("name_en", ""), *food.get("aliases", [])]
    return any(needle == normalize_text(name) or needle in normalize_text(name) for name in names if name)


def _recipe_food_ids(recipe: dict[str, Any]) -> set[str]:
    return {str(item.get("food_id", "")) for item in recipe.get("ingredients", []) if item.get("food_id")}


def _recipe_allergens(recipe: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for food_id in _recipe_food_ids(recipe):
        food = find_food(food_id)
        if food:
            result.update(food.get("allergens", []))
    return result


def _contains_any_term(recipe: dict[str, Any], terms: list[str]) -> bool:
    food_ids = _recipe_food_ids(recipe)
    return any(_term_matches_food(term, food_id) for term in terms for food_id in food_ids)


def _soft_preference_score(recipes: tuple[dict[str, Any], ...], preference: str) -> int:
    preference = preference.strip().lower()
    ingredients = [ingredient for recipe in recipes for ingredient in recipe.get("ingredients", [])]
    names = [find_food(str(item.get("food_id", ""))) for item in ingredients]
    names = [food for food in names if food]
    meat_or_seafood = {"鸡胸肉", "猪里脊", "牛肉", "虾仁", "鲈鱼"}
    score = 0
    if preference in {"素食倾向", "vegetarian"}:
        score += 3 if not any(food["name"] in meat_or_seafood for food in names) else 0
    if preference in {"少油", "清淡", "low-oil", "light"}:
        oil_grams = sum(float(item.get("grams", 0)) for item in ingredients if item.get("food_id") == "cooking_oil")
        score += max(0, 3 - int(oil_grams // 8))
    return score


def build_meal_plans(
    recipe_catalog: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    dish_count: int,
    min_kcal: float,
    max_kcal: float,
    required_ingredients: str | list[str] | None = None,
    excluded_ingredients: str | list[str] | None = None,
    excluded_allergens: list[str] | tuple[str, ...] | None = None,
    max_cooking_minutes: int | None = None,
    preference: str = "不限",
    limit: int = 3,
) -> dict[str, Any]:
    """Return only combinations that satisfy every hard constraint.

    Meal time is deliberately conservative: per-dish minutes are summed, rather
    than assuming all cooking can happen in parallel.
    """
    required = split_terms(required_ingredients)
    excluded = split_terms(excluded_ingredients)
    allergens = {str(item).strip() for item in (excluded_allergens or []) if str(item).strip()}
    candidates: list[dict[str, Any]] = []
    rejected = {"excluded_ingredient": 0, "allergen": 0, "time": 0}

    for recipe in recipe_catalog:
        if _contains_any_term(recipe, excluded):
            rejected["excluded_ingredient"] += 1
            continue
        if allergens.intersection(_recipe_allergens(recipe)):
            rejected["allergen"] += 1
            continue
        minutes = int(recipe.get("cooking_minutes", 0))
        if max_cooking_minutes is not None and minutes > max_cooking_minutes:
            rejected["time"] += 1
            continue
        candidates.append(recipe)

    valid: list[dict[str, Any]] = []
    if dish_count <= 0 or dish_count > len(candidates) or min_kcal > max_kcal:
        return {"plans": [], "candidate_count": len(candidates), "rejected": rejected}

    for group in combinations(candidates, dish_count):
        ids = set().union(*(_recipe_food_ids(recipe) for recipe in group))
        if required and not all(any(_term_matches_food(term, food_id) for food_id in ids) for term in required):
            continue
        total_minutes = sum(int(recipe.get("cooking_minutes", 0)) for recipe in group)
        if max_cooking_minutes is not None and total_minutes > max_cooking_minutes:
            continue
        nutrition = nutrition_for_items(combine_recipe_items(group))
        if not nutrition["complete"]:
            continue
        kcal = nutrition["totals"]["kcal"]
        if not min_kcal <= kcal <= max_kcal:
            continue
        valid.append(
            {
                "recipes": list(group),
                "nutrition": nutrition,
                "cooking_minutes": total_minutes,
                "preference_score": _soft_preference_score(group, preference),
            }
        )

    midpoint = (min_kcal + max_kcal) / 2
    valid.sort(
        key=lambda plan: (
            -plan["preference_score"],
            abs(plan["nutrition"]["totals"]["kcal"] - midpoint),
            tuple(recipe["id"] for recipe in plan["recipes"]),
        )
    )
    return {"plans": valid[:limit], "candidate_count": len(candidates), "rejected": rejected}


def recommend_recipes(
    recipe_catalog: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    confirmed_items: list[dict[str, Any]],
    *,
    preference: str = "不限",
    max_cooking_minutes: int | None = None,
    difficulty: str = "不限",
    cookware: str = "不限",
    limit: int = 3,
) -> list[dict[str, Any]]:
    selected = {str(item.get("food_id") or (find_food(item.get("name", "")) or {}).get("id", "")) for item in confirmed_items}
    selected.discard("")
    ranked: list[tuple[int, dict[str, Any]]] = []
    for recipe in recipe_catalog:
        minutes = int(recipe.get("cooking_minutes", 0))
        if max_cooking_minutes is not None and minutes > max_cooking_minutes:
            continue
        if difficulty != "不限" and recipe.get("difficulty", "普通") != difficulty:
            continue
        if cookware != "不限" and cookware not in recipe.get("cookware", []):
            continue
        recipe_ids = _recipe_food_ids(recipe)
        overlap = len(selected.intersection(recipe_ids))
        if overlap == 0:
            continue
        score = overlap * 3 + _soft_preference_score((recipe,), preference)
        ranked.append((score, recipe))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [recipe for _, recipe in ranked[:limit]]
