"""
Parse LLM output (OpenAI or Gemini) into a list of inventory item dicts.
Shared by OpenAI and Gemini extractors to avoid duplication.
"""

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Remove ``` / ```json wrappers if present."""
    t = text.strip()
    if "```" not in t:
        return t
    m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", t, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    lines = [ln for ln in t.split("\n") if not ln.strip().startswith("```")]
    return "\n".join(lines).strip()


def _load_json_lenient(text: str) -> Any:
    """
    Parse JSON; on failure, find first top-level JSON array or object in text.

    Handles models that add a short preamble (e.g. 'Here is the JSON:').
    No extra API calls.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as first_err:
        dec = json.JSONDecoder()
        for i, c in enumerate(text):
            if c not in "[{":
                continue
            try:
                obj, _end = dec.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                continue
        logger.error("Invalid JSON from model: %s", text[:300])
        raise ValueError(
            f"Failed to parse model response as JSON: {first_err}"
        ) from first_err


def parse_inventory_items_from_llm_text(content: str) -> List[Dict[str, Any]]:
    """
    Parse JSON array (or {items: [...]} / single object) from model response.

    Raises:
        ValueError: On invalid JSON or no valid items
    """
    if not content or not content.strip():
        raise ValueError("Empty model content")

    text = _strip_code_fences(content.strip())
    data = _load_json_lenient(text)

    if isinstance(data, dict) and "items" in data:
        data = data["items"]

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        logger.error("Model returned unsupported structure: %s", type(data))
        raise ValueError("Expected a JSON array or an object with 'items' key.")

    items: List[Dict[str, Any]] = []
    for idx, raw in enumerate(data):
        if not isinstance(raw, dict):
            logger.warning("Skipping non-object item at index %d: %r", idx, raw)
            continue

        keys = set(raw.keys())
        required = {"brand", "flavor", "best_by", "quantity", "category"}
        if not required.issubset(keys):
            logger.warning("Item %d missing keys. Got: %s", idx, list(keys))

        items.append(
            {
                "brand": raw.get("brand"),
                "flavor": raw.get("flavor"),
                "category": raw.get("category"),
                "best_by": raw.get("best_by"),
                "quantity": raw.get("quantity"),
            }
        )

    if not items:
        raise ValueError("No valid inventory items found in model response.")

    logger.debug("Parsed %d items from model JSON", len(items))
    return items
