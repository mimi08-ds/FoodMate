"""Small DeepSeek Responses API client. Secrets are passed by the caller."""

from __future__ import annotations

import base64
import json
import time
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
        "reasoning": {"effort": "none"},
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
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
    payload: dict[str, Any] | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ModelError("模型服务返回的数据格式不正确，请重试。")
            payload = decoded
            break
        except urllib.error.HTTPError as exc:
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt == 0:
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                try:
                    pause = min(3.0, max(0.5, float(retry_after))) if retry_after else 1.0
                except ValueError:
                    pause = 1.0
                time.sleep(pause)
                continue
            try:
                raw_details = exc.read().decode("utf-8", errors="replace")
                detail_payload = json.loads(raw_details)
                details = str(detail_payload.get("error", {}).get("message", ""))
            except (ValueError, AttributeError, TypeError):
                details = ""
            details = " ".join(details.split())[:240]
            common = {
                401: "API 密钥无效或已失效，请检查部署 Secrets。",
                402: "DeepSeek 账户余额不足，请检查账户状态。",
                413: "图片或请求内容过大，请换用较小的照片。",
                422: "请求参数未被模型服务接受。",
                429: "模型服务暂时限流，请稍后再试。",
                500: "模型服务暂时出错，请稍后再试。",
                502: "模型服务暂时不可用，请稍后再试。",
                503: "模型服务繁忙，请稍后再试。",
                504: "模型服务响应超时，请稍后再试。",
            }
            message = common.get(exc.code, f"模型服务请求失败（HTTP {exc.code}）。")
            if details and exc.code not in {401, 402}:
                message += f" 服务说明：{details}"
            raise ModelError(message) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) and attempt == 0:
                time.sleep(1.0)
                continue
            if isinstance(exc.reason, TimeoutError):
                raise ModelError("模型请求超时；请稍后重试，或先使用演示模式。") from None
            raise ModelError("无法连接模型服务；请检查网络后重试。") from None
        except TimeoutError:
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise ModelError("模型请求超时；请稍后重试，或先使用演示模式。") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ModelError("模型服务返回了无法读取的响应，请重试。") from None

    if payload is None:
        raise ModelError("模型请求没有完成，请稍后重试。")
    status = payload.get("status")
    if status == "failed":
        error = payload.get("error") or {}
        message = str(error.get("message", "模型处理失败。")) if isinstance(error, dict) else "模型处理失败。"
        raise ModelError("模型处理失败：" + " ".join(message.split())[:240])
    if status == "incomplete":
        reason = (payload.get("incomplete_details") or {}).get("reason", "")
        if reason == "max_output_tokens":
            raise ModelError("模型输出超出长度限制，请缩小图片或稍后重试。")
        raise ModelError("模型未能完成本次响应，请检查图片后重试。")

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

