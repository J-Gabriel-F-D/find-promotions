"""Simbolos da interface, com variante ASCII para terminais limitados."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Glyphs:
    ok: str
    fail: str
    idle: str
    search: str
    trophy: str
    money: str
    store: str
    star: str
    truck: str
    chart: str
    fire: str
    target: str
    warn: str
    demo: str
    clock: str
    arrow: str


UNICODE = Glyphs(
    ok="✓",
    fail="✗",
    idle="·",
    search="🔎",
    trophy="🏆",
    money="💰",
    store="🏪",
    star="⭐",
    truck="🚚",
    chart="📊",
    fire="🔥",
    target="🎯",
    warn="⚠",
    demo="🧪",
    clock="🕒",
    arrow="→",
)

ASCII = Glyphs(
    ok="[ok]",
    fail="[x]",
    idle="[-]",
    search="[?]",
    trophy="[BEST]",
    money="[MIN]",
    store="loja:",
    star="nota:",
    truck="frete:",
    chart="hist:",
    fire="!",
    target="score:",
    warn="[!]",
    demo="[demo]",
    clock="em:",
    arrow="->",
)


def glyphs_for(unicode_enabled: bool) -> Glyphs:
    return UNICODE if unicode_enabled else ASCII
