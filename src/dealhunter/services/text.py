"""Normalização de texto e extração de especificações.

Objetivo: transformar titulos ruidosos de marketplaces em chaves comparaveis,
sem nunca concluir que dois produtos são iguais apenas por nome parecido.
"""

from __future__ import annotations

import re
import unicodedata

from dealhunter.domain.ids import stable_id

# Marca canonica -> aliases observados nos titulos.
BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    "xiaomi": ("xiaomi", "redmi", "poco", "mi"),
    "samsung": ("samsung", "galaxy"),
    "apple": ("apple", "iphone", "ipad", "macbook"),
    "motorola": ("motorola", "moto"),
    "lenovo": ("lenovo", "thinkpad", "ideapad"),
    "acer": ("acer", "aspire", "nitro"),
    "dell": ("dell", "inspiron", "xps", "alienware"),
    "asus": ("asus", "vivobook", "zenbook", "rog", "tuf"),
    "hp": ("hp", "pavilion", "omen"),
    "nvidia": ("nvidia", "geforce", "rtx", "gtx"),
    "amd": ("amd", "ryzen", "radeon"),
    "intel": ("intel", "core"),
    "lg": ("lg",),
    "positivo": ("positivo",),
    "realme": ("realme",),
    "oneplus": ("oneplus",),
}

CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "smartphone": ("celular", "smartphone", "telefone", "phone"),
    "notebook": ("notebook", "laptop", "ultrabook"),
    "tablet": ("tablet",),
    "gpu": ("placa de video", "gpu", "placa-de-video"),
    "console": ("console", "videogame", "playstation", "xbox", "nintendo"),
    "tv": ("smart tv", "televisao", " tv "),
    "headphone": ("fone", "headphone", "headset", "earbud"),
}

# Palavras que não identificam o modelo (marketing/estado/embalagem).
_NOISE = {
    "novo",
    "lacrado",
    "original",
    "oferta",
    "promocao",
    "frete",
    "gratis",
    "nfe",
    "nota",
    "fiscal",
    "garantia",
    "nacional",
    "importado",
    "com",
    "sem",
    "de",
    "da",
    "do",
    "e",
    "para",
    "por",
    "em",
    "a",
    "o",
    "os",
    "as",
    "unico",
    "exclusivo",
    "kit",
    "versao",
    "global",
    "brasil",
    "dual",
    "chip",
    "camera",
    "tela",
    "bateria",
    "ram",
    "rom",
    "ssd",
    "hd",
    "nfc",
    "sim",
    "wifi",
    "bluetooth",
    "smartphone",
    "celular",
    "telefone",
    "notebook",
    "tablet",
    "console",
    "videogame",
    "5g",
    "4g",
    "lte",
    "gamer",
    "placa",
    "video",
    "geforce",
    "radeon",
}

# Tokens de componente (CPU), não de modelo: a familia termina antes deles.
# Assim "IdeaPad 3 Ryzen 5" e "IdeaPad 3" apontam para o mesmo produto.
_COMPONENT_STOP = {
    "ryzen",
    "athlon",
    "intel",
    "core",
    "celeron",
    "pentium",
    "i3",
    "i5",
    "i7",
    "i9",
    "snapdragon",
    "mediatek",
    "dimensity",
    "exynos",
    "unisoc",
}

_COLORS = {
    "preto",
    "branco",
    "azul",
    "verde",
    "cinza",
    "grafite",
    "prata",
    "dourado",
    "roxo",
    "rosa",
    "vermelho",
    "titanio",
    "midnight",
    "starlight",
}

_STORAGE = re.compile(r"\b(\d{1,4})\s*(gb|tb)\b", re.IGNORECASE)
_RAM = re.compile(r"\b(\d{1,2})\s*gb\s*(?:de\s*)?ram\b|\bram\s*(\d{1,2})\s*gb\b", re.IGNORECASE)
_SCREEN = re.compile(r"(\d{1,2}[.,]\d)\s*(?:pol(?:egadas)?|\")", re.IGNORECASE)
_CAPACITY_TOKEN = re.compile(r"(?:\d+(?:gb|tb|mp|mah|hz|w|pol)|gddr\d+\w*)$")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_text(text: str) -> str:
    """Minusculas, sem acento, pontuacao virando espaco."""
    lowered = strip_accents(text).lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def tokens(text: str) -> list[str]:
    return [token for token in normalize_text(text).split() if token]


def detect_brand(text: str) -> str | None:
    found = tokens(text)
    if not found:
        return None
    # Aliases mais longos primeiro para "placa de video" não casar por engano.
    for brand, aliases in BRAND_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if " " in alias:
                if alias in normalize_text(text):
                    return brand
            elif alias in found:
                return brand
    return None


def detect_category(text: str) -> str | None:
    normalized = f" {normalize_text(text)} "
    for category, terms in CATEGORY_TERMS.items():
        if any(term in normalized for term in terms):
            return category
    return None


def _unit_to_gb(value: int, unit: str) -> int:
    return value * 1024 if unit.lower() == "tb" else value


def parse_storage_gb(text: str) -> int | None:
    """Extrai armazenamento, ignorando o valor que pertencer a RAM."""
    ram_values = {int(a or b) for a, b in _RAM.findall(text)}
    candidates = [
        _unit_to_gb(int(value), unit)
        for value, unit in _STORAGE.findall(text)
        if int(value) not in ram_values
    ]
    if not candidates:
        return None
    # Em titulos com "256GB" e "1TB", o armazenamento e o maior valor.
    return max(candidates)


def parse_ram_gb(text: str) -> int | None:
    matches = _RAM.findall(text)
    if not matches:
        return None
    values = [int(ram or direct) for ram, direct in matches]
    return max(values)


def infer_ram_gb(text: str, storage_gb: int | None) -> int | None:
    """Inferir RAM quando o titulo traz duas capacidades mas não diz qual e qual.

    "Notebook 16GB 512GB" -> 16 GB de RAM (o maior valor e o armazenamento).
    """
    if storage_gb is None:
        return None
    values = {
        _unit_to_gb(int(value), unit)
        for value, unit in _STORAGE.findall(text)
        if 2 <= _unit_to_gb(int(value), unit) < storage_gb and _unit_to_gb(int(value), unit) <= 64
    }
    return max(values) if values else None


def parse_screen_inches(text: str) -> float | None:
    match = _SCREEN.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def marketing_free_tokens(text: str) -> list[str]:
    """Remove ruido, cores e capacidades numericas do titulo.

    Numeros "soltos" (ex.: ``14``, ``24``, ``4070``) **não** são removidos:
    eles fazem parte do modelo. So capacidades com unidade (``256GB``, ``8GB``)
    e ruido comercial saem.
    """
    result: list[str] = []
    for token in tokens(text):
        if token in _NOISE or token in _COLORS:
            continue
        if _CAPACITY_TOKEN.fullmatch(token):
            continue
        result.append(token)
    return result


def model_family(title: str, brand: str | None = None) -> str:
    """Familia do modelo: primeiros tokens uteis, no máximo tres.

    Sub-marcas (``redmi``, ``galaxy``, ``iphone``) são mantidas, porque fazem
    parte do nome do modelo. Apenas a marca-mae (``xiaomi``, ``samsung``) sai.
    A extração para no primeiro token de componente (CPU), para que variacoes de
    descrição do mesmo aparelho caiam na mesma familia.

    "Xiaomi Redmi Note 14 256GB 8GB RAM Preto" -> "redmi note 14"
    """
    cleaned = marketing_free_tokens(title)
    if brand and brand in cleaned:
        cleaned = [token for token in cleaned if token != brand]
    for index, token in enumerate(cleaned):
        if token in _COMPONENT_STOP:
            cleaned = cleaned[:index]
            break
    return " ".join(cleaned[:3])


def build_identity(
    *,
    title: str,
    brand: str | None,
    storage_gb: int | None,
    ram_gb: int | None,
    gtin: str | None = None,
    mpn: str | None = None,
) -> tuple[str, str]:
    """Chave de identidade do produto, em cascata.

    Só usa ``title`` como ultimo recurso -- nesse caso o produto **não** é
    fundido com outros, porque nome parecido não é prova de igualdade.
    """
    if gtin and re.fullmatch(r"\d{8,14}", gtin):
        return ("gtin", gtin)

    if mpn and brand:
        return ("mpn", f"{brand}:{normalize_text(mpn)}")

    family = model_family(title, brand)
    if brand and family and storage_gb:
        suffix = f"|ram{ram_gb}" if ram_gb else ""
        return ("model", f"{brand}|{family}|{storage_gb}{suffix}")

    return ("title", stable_id("t", normalize_text(title)))
