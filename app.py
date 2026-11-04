from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import streamlit as st

from foodmate.catalog import find_food, food_by_id, foods, recipes
from foodmate.image_processing import ImageInputError, prepare_food_image
from foodmate.model_client import (
    DEFAULT_MODEL,
    FOOD_RECOGNITION_SCHEMA,
    RECIPE_SCHEMA,
    ModelError,
    call_json,
)
from foodmate.nutrition import nutrition_for_items, nutrition_for_recipe
from foodmate.planning import NON_MATCHING_RECIPE_FOODS, build_meal_plans, recommend_recipes


ROOT = Path(__file__).resolve().parent
DEMO_IMAGE = ROOT / "assets" / "demo_meal.svg"
DISCLAIMER = "食刻提供一般饮食信息与估算，不替代医生或注册营养师建议；照片无法精确测出重量，也无法可靠识别全部隐藏油糖。"
ALLERGEN_OPTIONS = ["蛋类", "乳制品", "大豆", "小麦", "花生", "坚果", "甲壳类", "鱼类", "芝麻"]

st.set_page_config(page_title="食刻 · FoodMate", page_icon="🍽️", layout="wide")


def get_setting(name: str, default: str = "") -> str:
    value = ""
    try:
        value = str(st.secrets.get(name, ""))
    except Exception:
        value = ""
    if not value:
        value = os.getenv(name, "")
    return value or default


def demo_ingredients() -> list[dict[str, Any]]:
    rows = [
        ("cooked_rice", 180),
        ("chicken_breast", 120),
        ("broccoli", 100),
        ("tomato", 80),
        ("cooking_oil", 6),
    ]
    return [
        {"row_id": uuid.uuid4().hex[:10], "food_id": food_id, "name": food_by_id(food_id)["name"], "grams": grams}
        for food_id, grams in rows
    ]


def init_state() -> None:
    defaults = {
        "run_mode": "演示模式",
        "ingredients": demo_ingredients(),
        "editor_version": 0,
        "recognition_summary": "演示数据：示例餐食由预设样例提供，不来自模型识别。",
        "recognition_uncertain": [],
        "recipe_results": [],
        "recipe_offset": 0,
        "recipe_filter_signature": None,
        "planner_results": [],
        "planner_notice": "",
        "recipe_notice": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def set_ingredients(rows: list[dict[str, Any]], summary: str | None = None) -> None:
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        try:
            grams = float(row.get("grams", 0))
        except (TypeError, ValueError):
            continue
        if grams <= 0:
            continue
        food = find_food(name) or (food_by_id(str(row.get("food_id", ""))) if row.get("food_id") else None)
        cleaned.append(
            {
                "row_id": str(row.get("row_id") or uuid.uuid4().hex[:10]),
                "food_id": food["id"] if food else "",
                "name": food["name"] if food else name,
                "grams": round(grams, 1),
                "confidence": row.get("confidence"),
            }
        )
    st.session_state.ingredients = cleaned
    st.session_state.editor_version += 1
    st.session_state.recipe_results = []
    st.session_state.planner_results = []
    if summary is not None:
        st.session_state.recognition_summary = summary


def nutrition_text(result: dict[str, Any]) -> str:
    t = result["totals"]
    return f"{t['kcal']:.0f} kcal · 蛋白质 {t['protein_g']:.1f} g · 脂肪 {t['fat_g']:.1f} g · 碳水 {t['carbs_g']:.1f} g"


def show_nutrition(result: dict[str, Any], label: str = "营养估算") -> None:
    st.markdown(f"**{label}**")
    values = result["totals"]
    cols = st.columns(2)
    metrics = [("热量", f"{values['kcal']:.0f}", "kcal"), ("蛋白质", f"{values['protein_g']:.1f}", "g"), ("脂肪", f"{values['fat_g']:.1f}", "g"), ("碳水", f"{values['carbs_g']:.1f}", "g")]
    for index, (name, value, unit) in enumerate(metrics):
        cols[index % 2].metric(name, value, unit)
    if result["missing"]:
        st.warning("以下食材没有匹配到营养数据，当前数值只是已知食材小计：" + "、".join(result["missing"]))
    else:
        st.caption("数值由程序按本地演示数据换算，属于估算。")


def show_item_nutrition(items: list[dict[str, Any]]) -> None:
    detail_rows = []
    for item in items:
        result = nutrition_for_items([item])
        totals = result["totals"]
        detail_rows.append(
            {
                "食材": item["name"],
                "重量（克）": item["grams"],
                "热量（kcal）": totals["kcal"] if result["complete"] else "缺数据",
                "蛋白质（克）": totals["protein_g"] if result["complete"] else "—",
                "脂肪（克）": totals["fat_g"] if result["complete"] else "—",
                "碳水（克）": totals["carbs_g"] if result["complete"] else "—",
            }
        )
    if detail_rows:
        with st.expander("查看逐食材营养明细"):
            for row in detail_rows:
                with st.container(border=True):
                    st.markdown(f"**{row['食材']}** · {row['重量（克）']:g} g")
                    if row["热量（kcal）"] == "缺数据":
                        st.caption("营养数据缺失；未估算该食材的数值。")
                    else:
                        st.caption(
                            f"{row['热量（kcal）']:.0f} kcal · 蛋白质 {row['蛋白质（克）']:.1f} g · "
                            f"脂肪 {row['脂肪（克）']:.1f} g · 碳水 {row['碳水（克）']:.1f} g"
                        )
            st.caption("数据为本项目自制的近似演示值；未知食材不会被估成虚假的精确数字。")


def render_ingredient_editor() -> None:
    def current_rows() -> list[dict[str, Any]]:
        rows = []
        for item in st.session_state.ingredients:
            row_id = item["row_id"]
            if st.session_state.get(f"ingredient_remove_{row_id}", False):
                continue
            rows.append(
                {
                    "row_id": row_id,
                    "name": st.session_state.get(f"ingredient_name_{row_id}", item["name"]),
                    "grams": st.session_state.get(f"ingredient_grams_{row_id}", item["grams"]),
                }
            )
        return rows

    with st.form("ingredient_form", clear_on_submit=False):
        for item in st.session_state.ingredients:
            row_id = item["row_id"]
            with st.container(border=True):
                name_col, grams_col = st.columns([2, 1])
                name_col.text_input(
                    "食材名称",
                    value=item["name"],
                    key=f"ingredient_name_{row_id}",
                    placeholder="例如：番茄",
                )
                grams_col.number_input(
                    "重量（克）",
                    min_value=0.0,
                    max_value=3000.0,
                    step=5.0,
                    value=float(item["grams"]),
                    key=f"ingredient_grams_{row_id}",
                )
                st.checkbox("删除这项食材", key=f"ingredient_remove_{row_id}")
        saved = st.form_submit_button("保存并重新计算", type="primary", use_container_width=True)
        add_row = st.form_submit_button("＋ 添加一项食材", use_container_width=True)

    if saved:
        updated = current_rows()
        set_ingredients(updated)
        st.success("已保存；营养数据已重新计算。")
    elif add_row:
        updated = current_rows()
        set_ingredients(updated)
        st.session_state.ingredients.append(
            {"row_id": uuid.uuid4().hex[:10], "food_id": "", "name": "", "grams": 100.0}
        )
        st.rerun()


def render_demo_illustration() -> None:
    if not DEMO_IMAGE.exists():
        st.info("演示插画未找到，仍可继续查看预设样例结果。")
        return
    svg = DEMO_IMAGE.read_text(encoding="utf-8")
    import base64

    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    st.markdown(
        f'<div class="demo-image"><img alt="食刻演示餐食插画" src="data:image/svg+xml;base64,{encoded}" /></div>',
        unsafe_allow_html=True,
    )
    st.caption("自制示例插画 · 演示模式中的食材和识别结果为预设样例。")


def recognition_schema_prompt() -> str:
    catalog = ", ".join(f"{food['id']}: {food['name']} ({food['name_en']})" for food in foods())
    return (
        "请识别这张单餐食物照片。用中文列出可见食物和可能的主要食材，并估计每项可食部克数。"
        "不要把热量或营养值写入结果；后续由程序计算。看不准时仍可列出候选，但把置信度调低并说明不确定。"
        "份量只是照片估算，不能声称精确测量。若食物匹配下面目录，请原样返回对应 food_id；目录外食物的 food_id 填空字符串，不要猜造 ID。目录：" + catalog
    )


def recipe_schema_prompt(confirmed: list[dict[str, Any]], purpose: str) -> str:
    known = "\n".join(f"- {food['id']}: {food['name']}" for food in foods())
    item_lines = "、".join(f"{item['name']} {item['grams']:g}g" for item in confirmed)
    return (
        f"你是一般家常菜助手。{purpose}\n"
        f"用户已确认食材：{item_lines or '未提供'}。\n"
        "只可使用下面清单里的 food_id，不得添加清单外食材；每道菜必须包含至少一种用户已确认的非调味食材。"
        "食用油、酱油、大蒜、生姜不算匹配食材；可以补充清单内其他食材，页面会标出尚需准备的食材。不得生成营养或热量数字。"
        "给出最多 4 道中式家常菜，每道含具体食材克数、步骤、预计分钟数和难度。"
        "避免疾病治疗或极端节食建议。\n" + known
    )


def sanitize_ai_recipes(payload: dict[str, Any], confirmed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known_ids = {food["id"] for food in foods()}
    confirmed_ids = {
        str(item.get("food_id") or (find_food(item.get("name", "")) or {}).get("id", ""))
        for item in confirmed
    } - NON_MATCHING_RECIPE_FOODS - {""}
    safe: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("recipes", [])):
        ingredients: list[dict[str, Any]] = []
        valid = True
        for ingredient in raw.get("ingredients", []):
            food_id = str(ingredient.get("food_id", ""))
            try:
                grams = float(ingredient.get("grams", 0))
            except (TypeError, ValueError):
                valid = False
                break
            if food_id not in known_ids or not 1 <= grams <= 1500:
                valid = False
                break
            ingredients.append({"food_id": food_id, "grams": round(grams, 1)})
        steps = [str(step).strip() for step in raw.get("steps", []) if str(step).strip()]
        try:
            minutes = int(raw.get("cooking_minutes", 0))
        except (TypeError, ValueError):
            minutes = 0
        name = str(raw.get("name", "")).strip()
        recipe_core_ids = {item["food_id"] for item in ingredients} - NON_MATCHING_RECIPE_FOODS
        if (
            not valid
            or not name
            or not ingredients
            or not steps
            or not 1 <= minutes <= 180
            or not confirmed_ids.intersection(recipe_core_ids)
        ):
            continue
        safe.append(
            {
                "id": f"ai_{index}_{uuid.uuid4().hex[:6]}",
                "name": name,
                "description": str(raw.get("description", "AI 生成的家常菜候选；请按个人情况调整。")),
                "cooking_minutes": minutes,
                "difficulty": str(raw.get("difficulty", "普通")),
                "ingredients": ingredients,
                "steps": steps,
                "source": "AI 生成候选；营养由程序按本地数据重算",
            }
        )
    return safe


def request_generated_recipes(purpose: str, confirmed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    key = get_setting("DEEPSEEK_API_KEY")
    model = get_setting("DEEPSEEK_MODEL", DEFAULT_MODEL)
    base_url = get_setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    payload = call_json(
        recipe_schema_prompt(confirmed, purpose),
        schema_name="foodmate_recipes",
        schema=RECIPE_SCHEMA,
        api_key=key,
        model=model,
        base_url=base_url,
    )
    return sanitize_ai_recipes(payload, confirmed)


def render_recognition() -> None:
    st.subheader("① 食物识别与营养分析")
    if st.session_state.run_mode == "演示模式":
        render_demo_illustration()
        st.info("演示模式 · 当前结果为预设样例，不会调用模型，也不会读取你上传的照片。")
        st.write(st.session_state.recognition_summary)
    else:
        st.info("真实 AI 模式 · 上传的图片会发送到 DeepSeek 进行识别；食刻不会将图片写入磁盘或长期保存。请勿上传包含个人隐私的图片。")
        st.caption("💡 温馨提示：尽量使用本地相机拍摄食物照片后再上传，清晰、完整的原图有助于减少误判。")
        image_source = st.radio("图片来源", ["上传图片", "打开摄像头"], horizontal=True, key="recognition_image_source")
        if image_source == "上传图片":
            upload = st.file_uploader(
                "上传一张餐食照片",
                type=["jpg", "jpeg", "png", "webp", "heic", "heif", "avif"],
                help="支持 JPG、PNG、WebP、AVIF 和手机常见的 HEIC；单张上限 100 MB，上传后会自动压缩。",
                key="food_image_upload",
                max_upload_size=100,
            )
            if upload is None:
                st.caption("如果文件卡片出现红色感叹号，代表浏览器尚未完成上传；请确认图片不超过 100 MB，再重新选择并保持网络连接。")
        else:
            upload = st.camera_input("拍摄一张餐食照片", key="food_camera_capture")
        if upload:
            original_bytes = upload.getvalue()
            if len(original_bytes) > 100 * 1024 * 1024:
                st.error("图片超过 100 MB，请压缩后重试。")
            else:
                try:
                    image_bytes = prepare_food_image(original_bytes)
                except ImageInputError as exc:
                    st.error(str(exc))
                else:
                    st.caption(f"图片已优化：{len(original_bytes) / 1024 / 1024:.1f} MB → {len(image_bytes) / 1024 / 1024:.1f} MB JPEG。")
                    st.image(image_bytes, caption="已校正方向并优化的本次识别图片", width="stretch")
                    if st.button("识别食材", type="primary", key="recognize_button", use_container_width=True):
                        try:
                            with st.spinner("正在识别图片，请保持页面开启；网络繁忙时会自动重试一次…"):
                                result = call_json(
                                    recognition_schema_prompt(),
                                    schema_name="foodmate_food_recognition",
                                    schema=FOOD_RECOGNITION_SCHEMA,
                                    api_key=get_setting("DEEPSEEK_API_KEY"),
                                    model=get_setting("DEEPSEEK_MODEL", DEFAULT_MODEL),
                                    base_url=get_setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                                    image=(image_bytes, "image/jpeg"),
                                )
                            rows = []
                            for raw in result.get("foods", []):
                                name = str(raw.get("name_zh") or raw.get("name_en") or "").strip()
                                try:
                                    grams = float(raw.get("grams", 0))
                                    confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
                                except (TypeError, ValueError):
                                    continue
                                if name and 1 <= grams <= 3000:
                                    food = (
                                        food_by_id(str(raw.get("food_id", "")))
                                        or find_food(name)
                                        or find_food(str(raw.get("name_en", "")))
                                    )
                                    rows.append({"name": food["name"] if food else name, "food_id": food["id"] if food else "", "grams": grams, "confidence": confidence})
                            if not rows:
                                st.warning("模型没有返回可确认的食材。请上传光线清楚、食物完整可见的照片，或手动添加食材。")
                            else:
                                set_ingredients(rows, str(result.get("summary", "识别完成，请检查食材与份量。")))
                                st.session_state.recognition_uncertain = result.get("uncertain_items", [])
                                st.success("识别完成。请核对或修改食材和份量。")
                        except ModelError as exc:
                            st.error(f"识别失败：{exc} 你可以重试或手动填写；不会自动伪装成识别成功。")
                        except Exception as exc:
                            st.error(f"图片识别流程异常（{type(exc).__name__}）。请重试，或手动填写食材。")

    if st.session_state.recognition_uncertain:
        st.warning("模型标记为不确定：" + "、".join(st.session_state.recognition_uncertain))
    st.markdown("#### 核对食材和份量")
    render_ingredient_editor()
    if st.session_state.ingredients:
        result = nutrition_for_items(st.session_state.ingredients)
        show_nutrition(result)
        show_item_nutrition(st.session_state.ingredients)
    else:
        st.info("添加至少一种食材后，可以查看营养估算、推荐菜谱或规划一餐。")
    st.caption(DISCLAIMER)


def render_recipe_card(recipe: dict[str, Any], index: int) -> None:
    nutrition = nutrition_for_recipe(recipe)
    confirmed_amounts: dict[str, float] = {}
    for item in st.session_state.ingredients:
        food = find_food(item.get("name", "")) or food_by_id(str(item.get("food_id", "")))
        if food:
            confirmed_amounts[food["id"]] = confirmed_amounts.get(food["id"], 0.0) + float(item.get("grams", 0))
    matched: list[str] = []
    to_prepare: list[str] = []
    for item in recipe.get("ingredients", []):
        food = food_by_id(item.get("food_id", ""))
        if not food:
            continue
        needed = float(item.get("grams", 0))
        available = confirmed_amounts.get(food["id"], 0.0)
        if available >= needed:
            matched.append(f"{food['name']}（{needed:g}g）")
        elif available > 0:
            matched.append(f"{food['name']}（已有 {available:g}g，还需 {needed - available:g}g）")
            to_prepare.append(f"{food['name']} {needed - available:g}g")
        else:
            to_prepare.append(f"{food['name']} {needed:g}g")
    with st.container(border=True):
        title_col, meta_col = st.columns([3, 1])
        title_col.markdown(f"### {index}. {recipe['name']}")
        meta_col.caption(f"⏱ {recipe.get('cooking_minutes', '—')} 分钟 · {recipe.get('difficulty', '普通')}")
        st.caption(recipe.get("description", ""))
        st.markdown("**已确认并匹配：** " + ("、".join(matched) if matched else "无"))
        st.markdown("**还需准备：** " + ("、".join(to_prepare) if to_prepare else "无"))
        st.markdown("**做法：** " + " → ".join(recipe.get("steps", [])))
        st.caption(nutrition_text(nutrition) + (" · 部分数据缺失" if not nutrition["complete"] else ""))
        st.caption(recipe.get("source", "本项目示例数据"))


def render_recipes() -> None:
    st.subheader("② 智能菜谱推荐")
    st.write("优先匹配识别页确认的非调味食材；油、酱油、蒜、姜不会单独触发无关菜谱。推荐卡会分别列出已确认食材和还需准备的食材。")
    if not st.session_state.ingredients:
        st.info("请先在识别页添加或确认食材。")
        return

    unmapped = [
        str(item.get("name", "")).strip()
        for item in st.session_state.ingredients
        if not (item.get("food_id") or find_food(str(item.get("name", ""))))
    ]
    if unmapped:
        st.warning("这些确认食材未匹配到本地目录，暂不参与菜谱匹配和营养计算：" + "、".join(unmapped))

    controls = st.columns(4)
    preference = controls[0].selectbox("口味偏好", ["不限", "清淡", "少油", "素食倾向"], key="recipe_preference")
    max_time = controls[1].selectbox("烹饪时间", ["不限", "15 分钟内", "30 分钟内", "45 分钟内"], key="recipe_time")
    difficulty = controls[2].selectbox("难度", ["不限", "简单", "普通"], key="recipe_difficulty")
    cookware = controls[3].selectbox("厨具", ["不限", "炒锅", "汤锅", "蒸锅", "电饭煲"], key="recipe_cookware")
    minutes = {"不限": None, "15 分钟内": 15, "30 分钟内": 30, "45 分钟内": 45}[max_time]
    local = recommend_recipes(recipes(), st.session_state.ingredients, preference=preference, max_cooking_minutes=minutes, difficulty=difficulty, cookware=cookware, limit=10)

    ingredient_signature = tuple(
        sorted(
            (
                str(item.get("food_id") or (find_food(item.get("name", "")) or {}).get("id", "")),
                round(float(item.get("grams", 0)), 1),
            )
            for item in st.session_state.ingredients
        )
    )
    filter_signature = (ingredient_signature, preference, minutes, difficulty, cookware, st.session_state.run_mode)
    if st.session_state.recipe_filter_signature != filter_signature:
        st.session_state.recipe_filter_signature = filter_signature
        st.session_state.recipe_results = []
        st.session_state.recipe_offset = 0
        st.session_state.recipe_notice = ""

    if st.button("为我推荐 / 换一批", type="primary", key="recommend_recipes"):
        st.session_state.recipe_notice = ""
        results: list[dict[str, Any]] = []
        if local:
            offset = st.session_state.recipe_offset % len(local)
            results = [local[(offset + index) % len(local)] for index in range(min(3, len(local)))]
            st.session_state.recipe_offset = (offset + len(results)) % len(local)
        confirmed_core_ids = {
            str(item.get("food_id") or (find_food(item.get("name", "")) or {}).get("id", ""))
            for item in st.session_state.ingredients
        } - NON_MATCHING_RECIPE_FOODS - {""}
        if not local and not confirmed_core_ids:
            st.session_state.recipe_notice = "当前确认的食材只有油、酱油、蒜、姜等调味料，无法据此推荐主菜；请在识别页确认至少一种主食材。"
        elif len(results) < 3 and st.session_state.run_mode == "真实 AI 模式":
            try:
                with st.spinner("正在生成候选菜谱，并检查可计算的食材…"):
                    ai = request_generated_recipes("请优先使用用户现有食材。", st.session_state.ingredients)
                results.extend(ai[: 3 - len(results)])
            except ModelError as exc:
                st.session_state.recipe_notice = f"AI 补充失败：{exc}；仅显示匹配到的本地菜谱。"
        st.session_state.recipe_results = results
        st.rerun()

    if st.session_state.recipe_notice:
        st.warning(st.session_state.recipe_notice)
    results = st.session_state.recipe_results or local[:3]
    if not results:
        if st.session_state.run_mode == "演示模式":
            st.info("当前演示菜谱中没有符合已确认主食材和筛选条件的菜谱；不会显示无关菜谱。请调整筛选条件或确认其他食材。")
        else:
            st.info("当前还没有匹配的菜谱。点击上方按钮尝试生成候选，或调整筛选条件、确认其他食材。")
        return
    st.caption(f"当前展示 {len(results)} 道菜谱；热量和营养均由本地数据重算。")
    for index, recipe in enumerate(results, start=1):
        render_recipe_card(recipe, index)


def render_plan_card(plan: dict[str, Any], index: int) -> None:
    recipes_in_plan = plan["recipes"]
    with st.container(border=True):
        st.markdown(f"### 方案 {index} · " + " + ".join(recipe["name"] for recipe in recipes_in_plan))
        st.caption(f"预计总耗时 {plan['cooking_minutes']} 分钟（各菜耗时相加） · 硬性条件已通过")
        show_nutrition(plan["nutrition"], "整餐估算")
        for recipe in recipes_in_plan:
            with st.expander(f"{recipe['name']} · {recipe.get('cooking_minutes', '—')} 分钟"):
                st.write("、".join(f"{food_by_id(item['food_id'])['name']} {item['grams']:g}g" for item in recipe.get("ingredients", []) if food_by_id(item.get("food_id", ""))))
                for step_no, step in enumerate(recipe.get("steps", []), start=1):
                    st.write(f"{step_no}. {step}")


def render_planner() -> None:
    st.subheader("③ 智能饮食规划")
    st.write("设置一餐的热量、菜品数和食材限制。硬性条件由程序验证；软性偏好尽量满足。")
    with st.form("planner_form"):
        first, second, third = st.columns(3)
        min_kcal = first.number_input("最低热量（kcal）", min_value=100, max_value=3000, value=450, step=50)
        max_kcal = second.number_input("最高热量（kcal）", min_value=100, max_value=4000, value=1000, step=50)
        dish_count = third.number_input("菜品数量", min_value=1, max_value=5, value=2, step=1)
        required = st.text_input("必须包含的食材（逗号分隔）", placeholder="例如：鸡肉、番茄")
        excluded = st.text_input("排除的食材（逗号分隔）", placeholder="例如：虾、花生")
        preference_col, time_col = st.columns(2)
        preference = preference_col.selectbox("饮食偏好（软性）", ["不限", "清淡", "少油", "素食倾向"], key="planner_preference")
        max_time = time_col.number_input("烹饪时间上限（分钟）", min_value=10, max_value=240, value=60, step=5)
        excluded_allergens = st.multiselect("已知过敏原（硬性排除）", ALLERGEN_OPTIONS, help="仅能依据示例数据和菜谱明确标记的成分过滤；不完整数据不能保证无过敏原。")
        submitted = st.form_submit_button("生成饮食方案", type="primary")

    if submitted:
        if min_kcal > max_kcal:
            st.session_state.planner_results = []
            st.session_state.planner_notice = "最低热量不能高于最高热量。"
        else:
            st.session_state.planner_notice = ""
            criteria = {
                "dish_count": int(dish_count),
                "min_kcal": float(min_kcal),
                "max_kcal": float(max_kcal),
                "required_ingredients": required,
                "excluded_ingredients": excluded,
                "excluded_allergens": excluded_allergens,
                "max_cooking_minutes": int(max_time),
                "preference": preference,
            }
            available = list(recipes())
            result = build_meal_plans(available, **criteria)
            if not result["plans"] and st.session_state.run_mode == "真实 AI 模式":
                try:
                    with st.spinner("本地菜谱未找到合规组合，正在生成候选并由程序检查…"):
                        ai_recipes = request_generated_recipes(
                            "生成适合一餐搭配的候选菜。用户要求："
                            f"热量 {min_kcal:g}–{max_kcal:g} kcal；{int(dish_count)} 道菜；"
                            f"必选食材 {required or '无'}；排除食材 {excluded or '无'}；"
                            f"总烹饪时间不超过 {int(max_time)} 分钟。",
                            st.session_state.ingredients,
                        )
                    available.extend(ai_recipes)
                    result = build_meal_plans(available, **criteria)
                except ModelError as exc:
                    st.session_state.planner_notice = f"模型候选生成失败：{exc}"
            st.session_state.planner_results = result["plans"]
            if not result["plans"] and not st.session_state.planner_notice:
                st.session_state.planner_notice = "当前数据中没有满足全部硬性条件的方案。请放宽热量区间、时间上限或食材限制；系统不会自动放松条件。"
            elif result["plans"]:
                st.session_state.planner_notice = ""

    if st.session_state.planner_notice:
        st.info(st.session_state.planner_notice)
    if st.session_state.planner_results:
        st.caption("展示最多 3 套有效方案。必选食材、排除食材、过敏原、热量、菜品数和总耗时均已通过程序校验。")
        for index, plan in enumerate(st.session_state.planner_results, start=1):
            render_plan_card(plan, index)
    st.caption(DISCLAIMER)


def main() -> None:
    init_state()
    st.markdown(
        """
        <style>
        .stApp { background: #f7faf7; }
        [data-testid="stHeader"] { background: rgba(247,250,247,.86); }
        .hero { padding: 1.35rem 1.5rem; border-radius: 20px; background: linear-gradient(115deg,#e7f3e9,#f4f8ec); border: 1px solid #d9e9da; margin-bottom: .75rem; }
        .hero h1 { color: #173f2b; margin: 0; font-size: clamp(1.65rem, 5vw, 2.25rem); }
        .hero p { color: #496b54; margin: .35rem 0 0; }
        .demo-image { max-width: 440px; margin: .8rem auto; }
        .demo-image img { width: 100%; height: auto; border-radius: 18px; border: 1px solid #dce8dd; }
        @media (max-width: 760px) {
            .block-container { padding-left: 1rem !important; padding-right: 1rem !important; padding-top: 1rem !important; }
            .hero { padding: 1rem; border-radius: 16px; }
            .demo-image { max-width: 100%; }
            [data-testid="stHorizontalBlock"] { display: grid !important; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .65rem !important; }
            [data-testid="stHorizontalBlock"] > [data-testid="column"] { width: auto !important; min-width: 0 !important; flex: none !important; }
            [data-testid="stTabs"] [role="tablist"] { display: grid !important; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .25rem; }
            [data-testid="stTabs"] button[role="tab"] { min-height: 2.8rem; padding: .45rem .25rem; white-space: normal; font-size: .88rem; line-height: 1.2; }
            [data-testid="stMetric"] { padding: .7rem .55rem; }
            [data-testid="stMetricValue"] { font-size: 1.55rem; }
            [data-testid="stForm"] button { min-height: 2.9rem; }
            input, textarea, [role="combobox"] { font-size: 16px !important; }
        }
        @media (max-width: 390px) {
            .block-container { padding-left: .75rem !important; padding-right: .75rem !important; }
            [data-testid="stHorizontalBlock"] { grid-template-columns: minmax(0, 1fr); }
            [data-testid="stTabs"] [role="tablist"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            [data-testid="stTabs"] button[role="tab"] { font-size: .8rem; }
        }
        </style>
        <div class="hero"><h1>食刻 · FoodMate</h1><p>让每一餐，都有科学依据。</p></div>
        """,
        unsafe_allow_html=True,
    )
    mode_col, mode_status = st.columns([1, 2])
    mode_col.selectbox("使用模式", ["演示模式", "真实 AI 模式"], key="run_mode")
    if st.session_state.run_mode == "演示模式":
        mode_status.success("演示模式 · 结果为预设样例")
    elif get_setting("DEEPSEEK_API_KEY"):
        mode_status.success("真实 AI 模式 · 已检测到密钥")
    else:
        mode_status.warning("未检测到 API 密钥；可继续手动填写食材。")
    with st.expander("隐私与使用说明"):
        st.caption("图片仅在当前识别流程中处理，不写入项目文件。真实 AI 模式会将图片发送给 DeepSeek；请勿上传敏感图片。")
        st.caption(DISCLAIMER)

    recognition_tab, recipe_tab, planner_tab = st.tabs(["📷 食物识别", "🥘 菜谱推荐", "🗓️ 饮食规划"])
    with recognition_tab:
        render_recognition()
    with recipe_tab:
        render_recipes()
    with planner_tab:
        render_planner()
    st.divider()
    st.caption("FoodMate MVP · 当前版本不提供账号、跨设备同步或长期饮食记录。营养数据仅为演示数据。")


if __name__ == "__main__":
    main()

