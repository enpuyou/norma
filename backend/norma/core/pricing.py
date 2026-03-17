from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float
    output_per_1m: float
    context_window: int


_PRICING_FILE = Path(__file__).with_name("pricing_models.yaml")


@lru_cache(maxsize=1)
def _catalog() -> dict:
    if not _PRICING_FILE.exists():
        return {
            "default": {
                "input_per_1m": 5.0,
                "output_per_1m": 15.0,
                "context_window": 128000,
            },
            "models": {},
        }
    with _PRICING_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_model_pricing(model: str) -> ModelPricing:
    catalog = _catalog()
    default = catalog.get("default", {})
    models = catalog.get("models", {})

    entry = models.get(model) or default
    return ModelPricing(
        input_per_1m=float(entry.get("input_per_1m", 5.0)),
        output_per_1m=float(entry.get("output_per_1m", 15.0)),
        context_window=int(entry.get("context_window", 128000)),
    )


def calculate_llm_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pricing = get_model_pricing(model)
    in_cost = (max(0, tokens_in) / 1_000_000.0) * pricing.input_per_1m
    out_cost = (max(0, tokens_out) / 1_000_000.0) * pricing.output_per_1m
    return round(in_cost + out_cost, 8)


def context_utilization_ratio(model: str, tokens_in: int) -> float | None:
    pricing = get_model_pricing(model)
    if pricing.context_window <= 0:
        return None
    return min(1.0, max(0.0, tokens_in / pricing.context_window))
