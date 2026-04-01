"""
Parse LLM output (OpenAI or Gemini) into a list of inventory item dicts.
Shared by OpenAI and Gemini extractors to avoid duplication.
"""

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def parse_inventory_items_from_llm_text(content: str) -> List[Dict[str, Any]]:
    """
    Parse JSON array (or {items: [...]} / single object) from model response.

    Raises:
        ValueError: On invalid JSON or no valid items
    """
    if not content or not content.strip():
        raise ValueError("Empty model content")

    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON from model: %s", text[:200])
        raise ValueError(f"Failed to parse model response as JSON: {e}") from e

    if isinstance(data, dict) and "items" in data:
        data = data["items"]

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        logger.error("Model returned unsupported structure: %s", type(data))
        raise ValueError("Expected a JSON array or an object with 'items' key.")

    required = {"brand", "flavor", "best_by", "quantity"}
    items: List[Dict[str, Any]] = []
    for idx, raw in enumerate(data):
        if not isinstance(raw, dict):
            logger.warning("Skipping non-object item at index %d: %r", idx, raw)
            continue

        if not required.issubset(raw.keys()):
            logger.warning("Item %d missing keys. Got: %s", idx, list(raw.keys()))

        items.append(
            {
                "brand": raw.get("brand"),
                "flavor": raw.get("flavor"),
                "best_by": raw.get("best_by"),
                "quantity": raw.get("quantity"),
            }
        )

    if not items:
        raise ValueError("No valid inventory items found in model response.")

    logger.debug("Parsed %d items from model JSON", len(items))
    return items
