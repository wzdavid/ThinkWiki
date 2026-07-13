from __future__ import annotations

"""
ThinkWiki Module: bge_client

Purpose:
- Wrap BGE-M3 embedding HTTP calls for semantic entity matching.
- Exposes bge_embed (batch text -> normalized vectors) and cosine_similarity.

Usage:
- Imported by utils.py for the embedding branch of ambiguous_entity_merge_candidates.
- Not intended for direct execution.
"""


import json
import os
import sys
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

# SiliconFlow BGE-M3 embedding endpoint (OpenAI-style /v1/embeddings).
DEFAULT_BGE_ENDPOINTS = (
    "https://api.siliconflow.cn/v1/embeddings",
)
BGE_TIMEOUT = 10
BGE_MODEL = "BAAI/bge-m3"
USER_AGENT = "ThinkWiki/1.0"


class BgeServiceUnavailable(Exception):
    """Raised when all BGE-M3 endpoints are unreachable."""


def _resolve_endpoints() -> list[str]:
    env_value = os.environ.get("BGE_ENDPOINTS", "").strip()
    if env_value:
        endpoints = [item.strip() for item in env_value.split(",") if item.strip()]
        if endpoints:
            return endpoints
        print("Warning: BGE_ENDPOINTS is set but contains no valid endpoints; falling back to defaults.", file=sys.stderr)
    return list(DEFAULT_BGE_ENDPOINTS)


def _resolve_api_key() -> str:
    return os.environ.get("SILICONFLOW_API_KEY", "").strip()


def _post_json(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=BGE_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_embeddings(response: dict, count: int) -> list[list[float]]:
    # Parse priority: OpenAI format (data[].embedding) > raw array.
    # SiliconFlow returns the OpenAI-style shape.
    data = response.get("data")
    if isinstance(data, list) and data:
        vectors: list[list[float]] = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("embedding"), list):
                vectors.append([float(x) for x in item["embedding"]])
        if len(vectors) == count:
            return vectors
    if isinstance(response, list) and len(response) == count:
        return [[float(x) for x in item] for item in response]
    raise ValueError("Unexpected BGE-M3 response shape")


def _normalize(vector: list[float]) -> list[float]:
    norm = sum(x * x for x in vector) ** 0.5
    if norm == 0:
        return vector
    return [x / norm for x in vector]


def bge_embed(texts: Iterable[str]) -> list[list[float]]:
    """Embed a batch of texts via BGE-M3. Returns normalized vectors.

    Requires SILICONFLOW_API_KEY. Tries each endpoint in order.
    Raises BgeServiceUnavailable if the key is missing or all endpoints fail.
    4xx errors (including 401/403 auth failures) short-circuit immediately.
    """
    text_list = [str(t).strip() for t in texts if str(t).strip()]
    if not text_list:
        return []
    api_key = _resolve_api_key()
    if not api_key:
        raise BgeServiceUnavailable("SILICONFLOW_API_KEY is not set")
    payload = {"input": text_list, "model": BGE_MODEL}
    last_error: Exception | None = None
    for endpoint in _resolve_endpoints():
        try:
            response = _post_json(endpoint, payload, api_key)
            vectors = _extract_embeddings(response, len(text_list))
            return [_normalize(v) for v in vectors]
        except urllib_error.HTTPError as exc:
            if 400 <= exc.code <= 499:
                if exc.code in (401, 403):
                    raise BgeServiceUnavailable(
                        f"BGE-M3 auth failed (HTTP {exc.code}): check SILICONFLOW_API_KEY"
                    ) from exc
                raise BgeServiceUnavailable(f"BGE-M3 client error (HTTP {exc.code})") from exc
            last_error = exc
            continue
        except (urllib_error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
    raise BgeServiceUnavailable(f"All BGE-M3 endpoints failed: {last_error}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    bge_embed already L2-normalizes vectors before returning them, so for
    vectors from bge_embed this degenerates to a dot product. The norm
    recalculation below is kept defensively in case callers pass raw vectors.
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
