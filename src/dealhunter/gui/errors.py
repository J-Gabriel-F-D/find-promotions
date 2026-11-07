"""Erros próprios da interface gráfica (sem importar Tkinter)."""

from __future__ import annotations


class GuiError(RuntimeError):
    """Entrada inválida ou falha recuperável exibida ao usuário."""


class GuiUnavailable(RuntimeError):
    """Tkinter ausente ou ambiente sem display para abrir a janela."""
