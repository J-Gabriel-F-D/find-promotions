"""Identificadores estáveis e determinísticos.

IDs derivados de hash permitem *upsert* idempotente: a mesma loja/oferta
recebida duas vezes gera o mesmo ID, sem duplicar linhas no banco.
"""

from __future__ import annotations

import hashlib


def stable_id(prefix: str, *parts: str) -> str:
    """Gera ``prefix_<16 hex>`` a partir de partes normalizadas."""
    payload = "|".join(part.strip().lower() for part in parts if part is not None)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
