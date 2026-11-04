"""Small DeepSeek Responses API client. Secrets are passed by the caller."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class ModelError(RuntimeError):
    """A safe, user-displayable model request error."""


def _response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    for output in payload.get("output", []):
        if output.get("type") != "message":
            continue
        for part in output.get("content", []):
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def call_json(
    prompt: str,
    *,
    schema_name: str,
    schema: dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    image: tuple[bytes, str] | None = None,
    timeout: float = 50.0,
) -> dict[str, Any]:
    if not api_key.strip():
        raise ModelError("未配置 DeepSeek API 密钥。请在本地或部署平台 Secrets 中设置 DEEPSEEK_API_KEY。")

    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    if image:
        image_bytes, mime_type = image
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append({"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}", "detail": "auto"})

    body = {
        "model": model or DEFAULT_MODEL,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
        "max_output_tokens": 2500,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not include request headers or the API key in the displayed error.
        try:
            details = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            details = ""
        raise ModelError(f"模型服务返回 HTTP {exc.code}。{details}") from None
    except urllib.error.URLError as exc:
        raise ModelError(f"无法连接模型服务：{exc.reason}") from None
    except TimeoutError:
        raise ModelError("模型请求超时，请稍后重试或使用演示模式。") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ModelError("模型服务返回了无法读取的响应。") from None

    text = _response_text(payload)
    if not text:
        raise ModelError("模型未返回可读取的 JSON 内容，请重试。")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        raise ModelError("模型响应格式不正确，请重试。") from None
    if not isinstance(result, dict):
        raise ModelError("模型响应不是有效对象，请重试。")
    return result


FOOD_RECOGNITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "foods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name_zh": {"type": "string"},
                    "name_en": {"type": "string"},
                    "grams": {"type": "number"},
                    "confidence": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["name_zh", "name_en", "grams", "confidence", "notes"],
                "additionalProperties": False,
            },
        },
        "uncertain_items": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["foods", "uncertain_items", "summary"],
    "additionalProperties": False,
}


RECIPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recipes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "cooking_minutes": {"type": "integer"},
                    "difficulty": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"food_id": {"type": "string"}, "grams": {"type": "number"}},
                            "required": ["food_id", "grams"],
                            "additionalProperties": False,
                        },
                    },
                    "steps": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "cooking_minutes", "difficulty", "ingredients", "steps"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recipes"],
    "additionalProperties": False,
}
