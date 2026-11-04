import unittest

from foodmate.catalog import recipes
from foodmate.nutrition import nutrition_for_items
from foodmate.planning import build_meal_plans


class NutritionTests(unittest.TestCase):
    def test_known_food_is_calculated_per_100_grams(self):
        result = nutrition_for_items([{"food_id": "tomato", "name": "番茄", "grams": 100}])
        self.assertEqual(result["totals"]["kcal"], 18.0)
        self.assertTrue(result["complete"])

    def test_unknown_food_is_not_fabricated(self):
        result = nutrition_for_items([{"name": "未知食材", "grams": 100}])
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing"], ["未知食材"])
        self.assertEqual(result["totals"]["kcal"], 0.0)

    def test_editing_weight_changes_calculation(self):
        small = nutrition_for_items([{"food_id": "egg", "name": "鸡蛋", "grams": 50}])
        large = nutrition_for_items([{"food_id": "egg", "name": "鸡蛋", "grams": 100}])
        self.assertEqual(large["totals"]["kcal"], small["totals"]["kcal"] * 2)


class PlanningTests(unittest.TestCase):
    def test_hard_constraints_and_sum_of_cooking_times(self):
        result = build_meal_plans(
            recipes(),
            dish_count=2,
            min_kcal=500,
            max_kcal=650,
            required_ingredients="鸡肉",
            excluded_ingredients="虾",
            excluded_allergens=["甲壳类"],
            max_cooking_minutes=30,
        )
        self.assertTrue(result["plans"])
        plan = result["plans"][0]
        self.assertEqual(len(plan["recipes"]), 2)
        self.assertLessEqual(plan["cooking_minutes"], 30)
        self.assertTrue(500 <= plan["nutrition"]["totals"]["kcal"] <= 650)
        names = " ".join(recipe["name"] for recipe in plan["recipes"])
        self.assertIn("鸡", names)

    def test_allergen_is_a_hard_exclusion(self):
        result = build_meal_plans(
            recipes(),
            dish_count=1,
            min_kcal=0,
            max_kcal=2000,
            excluded_allergens=["蛋类"],
        )
        self.assertTrue(result["plans"])
        self.assertNotIn("番茄炒蛋", [p["recipes"][0]["name"] for p in result["plans"]])

    def test_infeasible_constraints_return_no_plan(self):
        result = build_meal_plans(
            recipes(),
            dish_count=5,
            min_kcal=5000,
            max_kcal=5100,
            required_ingredients="不存在的食材",
            max_cooking_minutes=10,
        )
        self.assertEqual(result["plans"], [])


if __name__ == "__main__":
    unittest.main()
