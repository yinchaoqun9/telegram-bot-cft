"""
When local fuzzy + transcript substring both miss the brand catalog, optionally
run Google Programmable Search (Custom Search JSON API) and a short LLM pass
to suggest an official brand name, then fuzzy-match again.

Costs: 1 CSE request + 1 small chat completion per item that triggers (rare).
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from services.brand_catalog import BrandCatalog
    from services.gemini_service import GeminiService
    from services.openai_service import OpenAIService

logger = logging.getLogger(__name__)


async def fetch_google_cse_snippets(query: str, limit: int = 5) -> str:
    key = (os.environ.get("GOOGLE_CSE_API_KEY") or "").strip()
    cx = (
        os.environ.get("GOOGLE_CSE_CX")
        or os.environ.get("GOOGLE_CSE_ENGINE_ID")
        or ""
    ).strip()
    if not key or not cx:
        logger.warning(
            "Brand web search enabled but GOOGLE_CSE_API_KEY or GOOGLE_CSE_CX missing"
        )
        return ""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": key, "cx": cx, "q": query, "num": min(max(limit, 1), 10)}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.exception("Google CSE request failed: %s", e)
        return ""
    items = data.get("items") or []
    parts = []
    for it in items[:limit]:
        t = (it.get("title") or "").strip()
        s = (it.get("snippet") or "").strip()
        if t or s:
            parts.append(f"{t}\n{s}")
    return "\n---\n".join(parts)[:6000]


def _refine_gemini_sync(api_key: str, model: str, user_block: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    r = m.generate_content(
        [
            "Output exactly one line: the cat food brand name only, or UNKNOWN.",
            user_block,
        ],
        generation_config={"temperature": 0},
    )
    text = ""
    try:
        if getattr(r, "text", None):
            text = r.text
    except Exception:
        for cand in getattr(r, "candidates", None) or []:
            for part in getattr(cand.content, "parts", []) or []:
                if getattr(part, "text", None):
                    text += part.text
    return (text or "").strip().split("\n")[0].strip()


async def _refine_openai(openai_svc: "OpenAIService", user_block: str) -> str:
    resp = await openai_svc.client.chat.completions.create(
        model=os.environ.get("BRAND_REFINE_OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": "Reply with exactly one line: the cat food brand name, or UNKNOWN.",
            },
            {"role": "user", "content": user_block},
        ],
        temperature=0,
    )
    c = resp.choices[0].message.content
    return (c or "").strip().split("\n")[0].strip()


async def refine_brand_via_llm(
    snippets: str,
    brand_raw: str,
    transcription: str,
    openai_svc: Optional["OpenAIService"],
    gemini_svc: Optional["GeminiService"],
) -> str:
    excerpt = (transcription or "")[:500]
    hint = (brand_raw or "")[:200]
    user_block = (
        "Web search snippets about cat food:\n---\n"
        + snippets[:5500]
        + "\n---\nUser/ASR brand hint: "
        + hint
        + "\nTranscript excerpt: "
        + excerpt
        + "\nWhat is the official brand name? One line only, or UNKNOWN."
    )
    want = os.environ.get("AI_EXTRACT_PROVIDER", "gemini").strip().lower()
    if want == "gemini" and gemini_svc is not None:
        try:
            return await asyncio.to_thread(
                _refine_gemini_sync,
                gemini_svc.api_key,
                gemini_svc.model_name,
                user_block,
            )
        except Exception as e:
            logger.warning("Gemini brand refine failed, trying OpenAI: %s", e)
    if openai_svc is not None:
        try:
            return await _refine_openai(openai_svc, user_block)
        except Exception as e:
            logger.exception("OpenAI brand refine failed: %s", e)
    return ""


async def maybe_refine_brand_with_web_search(
    brand_cat: "BrandCatalog",
    brand_raw: str,
    transcription: str,
    openai_svc: Optional["OpenAIService"],
    gemini_svc: Optional["GeminiService"],
) -> str:
    base = brand_cat.resolve_brand(brand_raw, transcription)
    if not brand_cat.needs_web_search_fallback(brand_raw, transcription):
        return base
    raw = (brand_raw or "").strip()
    tr = (transcription or "").strip()
    query = (
        f"{raw} cat food brand 猫粮"
        if raw
        else f"{tr[:180]} cat food brand 猫粮"
    ).strip()
    if len(query) < 3:
        return base
    logger.info("Brand web search (Google CSE), query_len=%d", len(query))
    snippets = await fetch_google_cse_snippets(query)
    if not snippets.strip():
        logger.warning("Brand web search: empty snippets; keeping local resolve")
        return base
    if openai_svc is None and gemini_svc is None:
        logger.warning("Brand web search: no LLM client for snippet refinement")
        return base
    try:
        refined = await refine_brand_via_llm(
            snippets, brand_raw or "", transcription or "", openai_svc, gemini_svc
        )
    except Exception as e:
        logger.exception("Brand LLM refine failed: %s", e)
        return base
    if not refined or refined.upper() == "UNKNOWN":
        return base
    normalized = brand_cat.normalize_brand(refined)
    out = (normalized or refined).strip()
    if out and out != base:
        logger.info("Brand adjusted after web+LLM: %r -> %r", base, out)
    return out or base
