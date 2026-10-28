"""Consulta e cache de ``robots.txt``.

Aplicado a fontes que não são APIs oficiais (ex.: feed JSON de uma loja).
APIs oficiais são regidas pelos seus proprios termos de uso.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from dealhunter.adapters.http.client import HttpClient


class RobotsGuard:
    def __init__(
        self,
        http: HttpClient,
        *,
        user_agent: str,
        ttl_seconds: int = 3600,
    ) -> None:
        self._http = http
        self._agent = user_agent
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, RobotFileParser | None]] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return False

        base = f"{parts.scheme}://{parts.netloc}"
        parser = await self._parser_for(base)
        if parser is None:
            # Sem robots.txt acessivel: o acesso público e permitido.
            return True
        return parser.can_fetch(self._agent, url)

    async def _parser_for(self, base: str) -> RobotFileParser | None:
        cached = self._cache.get(base)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]

        body = await self._http.get_text(f"{base}/robots.txt", allow_not_found=True)
        if body is None:
            self._cache[base] = (now + self._ttl, None)
            return None

        parser = RobotFileParser()
        parser.parse(body.splitlines())
        self._cache[base] = (now + self._ttl, parser)
        return parser
