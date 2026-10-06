"""The price catalog: model rates that live with the store.

Pricing used to require carrying a ``--prices file.json`` on every
door that spends money. The catalog puts the table where the traces
are — ``<store>/prices.json`` — managed by ``approximately prices
set/unset``, and consumed by every spend-aware door that wasn't given
an explicit ``--prices``. Explicit always wins: a catalog is a
default, not an override.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Optional, Union

CATALOG_NAME = "prices.json"

# Root-level store artifacts that are not traces; retention and any
# other glob-*.json pass must leave them alone.
STORE_ARTIFACTS = frozenset({CATALOG_NAME, "stats.json"})


def catalog_path(store_dir: Union[str, Path]) -> Path:
    return Path(store_dir) / CATALOG_NAME


def validate_table(table: object) -> Dict[str, float]:
    """Coerce and check a price table: model -> finite, non-negative
    rate in $/1k tokens. Raises ValueError with the offending model
    named — refusal, not a silently $0 model."""
    if not isinstance(table, dict):
        raise ValueError("price table must map model -> number")
    out: Dict[str, float] = {}
    for model, rate in table.items():
        if (not isinstance(model, str) or not model
                or any(c in model for c in "\n\r\t")):
            raise ValueError(f"price table: bad model name {model!r}")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise ValueError(f"price table: {model} rate must be a "
                             "number")
        rate_f = float(rate)
        if not math.isfinite(rate_f) or rate_f < 0:
            raise ValueError(f"price table: {model} rate must be "
                             "finite and non-negative")
        out[model] = rate_f
    return out


def load_catalog(store_dir: Union[str, Path]) -> Optional[dict]:
    """The store's catalog, or None when there isn't one.

    A corrupt catalog raises ValueError — spend doors must refuse to
    guess prices from a broken table.
    """
    path = catalog_path(store_dir)
    if not path.is_file():
        return None
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"price catalog {path}: {exc}") from None
    return validate_table(table)


def save_catalog(store_dir: Union[str, Path], table: dict) -> Path:
    path = catalog_path(store_dir)
    clean = validate_table(table)
    path.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def set_rate(store_dir: Union[str, Path], model: str,
             rate: float) -> dict:
    """Upsert one rate; returns the whole (validated) table."""
    table = load_catalog(store_dir) or {}
    table[str(model)] = rate
    save_catalog(store_dir, table)
    return load_catalog(store_dir) or {}


def unset_rate(store_dir: Union[str, Path], model: str) -> dict:
    """Remove one rate; KeyError names the model when it wasn't set."""
    table = load_catalog(store_dir)
    if not table or str(model) not in table:
        raise KeyError(f"no rate on file for {model!r}")
    del table[str(model)]
    save_catalog(store_dir, table)
    return load_catalog(store_dir) or {}


def resolve_prices(store_dir: Union[str, Path],
                   explicit_path: Optional[str]) -> Optional[dict]:
    """The spend doors' resolution chain: an explicit ``--prices``
    file wins; else the store catalog; else None (unpriced tokens
    stay honestly unpriced downstream). Any read/parse/validation
    failure raises ValueError with the path named."""
    if explicit_path:
        path = Path(explicit_path)
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"prices file {path}: {exc}") from None
        return validate_table(table)
    return load_catalog(store_dir)
