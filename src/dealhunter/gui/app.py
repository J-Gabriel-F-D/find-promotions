"""Janela Tkinter opcional do DealHunter.

A janela é uma camada de apresentação: toda a lógica fica em
``GuiController``, que chama os mesmos casos de uso da CLI. Operações de rede
rodam em uma thread e devolvem o resultado à thread principal por uma fila.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import TypeVar

from dealhunter.application.dto import HistoryReport, SearchReport, StoredAlert
from dealhunter.application.use_cases.alerts import AlertOutcome
from dealhunter.application.use_cases.monitor import MonitorRunResult
from dealhunter.application.use_cases.reviews import ReviewReport
from dealhunter.domain.models import OfferView
from dealhunter.domain.value_objects.money import Money
from dealhunter.gui.controller import (
    RISK_OPTIONS,
    SORT_OPTIONS,
    SOURCE_OPTIONS,
    GuiController,
)
from dealhunter.gui.errors import GuiError, GuiUnavailable
from dealhunter.gui.format import history_text, money, offer_detail, reviews_text, when
from dealhunter.runtime.container import RuntimeContext

T = TypeVar("T")


def _alert_rule_text(alert: StoredAlert) -> str:
    parts: list[str] = []
    if alert.max_price_cents is not None:
        parts.append(f"<= {Money(alert.max_price_cents)}")
    if alert.min_discount_pct is not None:
        parts.append(f">= {alert.min_discount_pct:g}% desconto")
    parts.extend(alert.rule.describe())
    return " e ".join(parts) if parts else "-"


class DealHunterApp:
    """Monta e mantém os widgets da janela principal."""

    def __init__(self, root: tk.Tk, controller: GuiController) -> None:
        self.root = root
        self.controller = controller
        self._events: queue.Queue[Callable[[], None]] = queue.Queue()
        self._busy = False
        self._search_views: list[OfferView] = []
        self._alerts_by_id: dict[int, StoredAlert] = {}

        self.root.title("DealHunter")
        self.root.geometry("1120x760")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_var = tk.StringVar(value="Pronto.")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self._build_search_tab()
        self._build_history_tab()
        self._build_reviews_tab()
        self._build_alerts_tab()
        self._build_monitor_tab()

        ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=(6, 2),
        ).pack(fill="x", padx=6, pady=6)

        self.root.after(100, self._drain_events)
        self._refresh_alerts()
        self._refresh_monitor()

    # ------------------------------------------------------------------ infra

    def _drain_events(self) -> None:
        try:
            while True:
                callback = self._events.get_nowait()
                callback()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _show_error(self, error: BaseException) -> None:
        text = str(error).strip() or type(error).__name__
        self._set_status(f"Erro: {text}")
        messagebox.showerror("DealHunter", text)

    def _run_async(self, work: Callable[[], T], on_success: Callable[[T], None]) -> None:
        if self._busy:
            self._set_status("Aguarde: já existe uma operação em andamento.")
            return
        self._busy = True
        self._set_status("Consultando...")

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # a janela precisa mostrar a falha, não sumir

                def report_error(error: BaseException = exc) -> None:
                    self._finish_error(error)

                self._events.put(report_error)
                return

            def report_success() -> None:
                self._finish_success(result, on_success)

            self._events.put(report_success)

        threading.Thread(target=runner, daemon=True).start()

    def _finish_success(self, result: T, on_success: Callable[[T], None]) -> None:
        self._busy = False
        on_success(result)

    def _finish_error(self, error: BaseException) -> None:
        self._busy = False
        self._show_error(error)

    def _on_close(self) -> None:
        self.root.destroy()

    @staticmethod
    def _readonly_text(parent: tk.Misc, *, height: int) -> tk.Text:
        widget = tk.Text(parent, height=height, wrap="word", state="disabled", padx=6, pady=4)
        return widget

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _selected_index(self, tree: ttk.Treeview) -> int | None:
        selection = tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _selected_alert(self) -> StoredAlert | None:
        selection = self.alerts_tree.selection()
        if not selection:
            return None
        try:
            return self._alerts_by_id.get(int(selection[0]))
        except ValueError:
            return None

    # ---------------------------------------------------------------- busca

    def _build_search_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Busca")
        for column in (1, 3, 5, 7, 9):
            tab.columnconfigure(column, weight=1 if column == 1 else 0)
        tab.rowconfigure(1, weight=3)
        tab.rowconfigure(3, weight=2)

        self.search_query = tk.StringVar()
        self.search_max_price = tk.StringVar()
        self.search_source = tk.StringVar(value="config")
        self.search_sort = tk.StringVar(value="best")
        self.search_limit = tk.IntVar(value=20)

        ttk.Label(tab, text="Busca").grid(row=0, column=0, sticky="w")
        query_entry = ttk.Entry(tab, textvariable=self.search_query)
        query_entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))
        query_entry.bind("<Return>", self._on_search_enter)
        ttk.Label(tab, text="Preço máx.").grid(row=0, column=2, sticky="w")
        ttk.Entry(tab, textvariable=self.search_max_price, width=12).grid(
            row=0, column=3, sticky="w", padx=(4, 10)
        )
        ttk.Label(tab, text="Fonte").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            tab,
            textvariable=self.search_source,
            values=list(SOURCE_OPTIONS),
            state="readonly",
            width=12,
        ).grid(row=0, column=5, sticky="w", padx=(4, 10))
        ttk.Label(tab, text="Ordenar").grid(row=0, column=6, sticky="w")
        ttk.Combobox(
            tab,
            textvariable=self.search_sort,
            values=list(SORT_OPTIONS),
            state="readonly",
            width=12,
        ).grid(row=0, column=7, sticky="w", padx=(4, 10))
        ttk.Label(tab, text="Limite").grid(row=0, column=8, sticky="w")
        ttk.Spinbox(tab, from_=1, to=200, textvariable=self.search_limit, width=6).grid(
            row=0, column=9, sticky="w", padx=(4, 10)
        )
        ttk.Button(tab, text="Buscar", command=self._do_search).grid(row=0, column=10, sticky="e")

        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=1, column=0, columnspan=11, sticky="nsew", pady=(10, 6))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        columns = ("titulo", "loja", "preco", "frete", "score", "confianca", "risco")
        self.search_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=9)
        headings = {
            "titulo": ("Produto", 320),
            "loja": ("Loja", 150),
            "preco": ("Preço final", 110),
            "frete": ("Frete", 90),
            "score": ("Score", 70),
            "confianca": ("Confiança", 110),
            "risco": ("Risco", 90),
        }
        for name, (label, width) in headings.items():
            self.search_tree.heading(name, text=label)
            self.search_tree.column(name, width=width, anchor="w")
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.search_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.search_tree.configure(yscrollcommand=scrollbar.set)
        self.search_tree.bind("<<TreeviewSelect>>", self._on_search_select)
        self.search_tree.bind("<Double-1>", self._on_search_open)

        detail_frame = ttk.LabelFrame(tab, text="Detalhes da oferta", padding=4)
        detail_frame.grid(row=3, column=0, columnspan=11, sticky="nsew")
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.search_detail = self._readonly_text(detail_frame, height=10)
        self.search_detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(
            detail_frame, orient="vertical", command=self.search_detail.yview
        )
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.search_detail.configure(yscrollcommand=detail_scroll.set)

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=11, sticky="ew", pady=(6, 0))
        ttk.Button(
            actions, text="Abrir oferta no navegador", command=self._open_selected_offer
        ).pack(side="left")
        ttk.Label(
            actions,
            text="Dados da fonte; confiança é probabilística, não veredito de fraude.",
        ).pack(side="left", padx=12)

    def _on_search_enter(self, _event: object) -> None:
        self._do_search()

    def _search_limit(self) -> int:
        try:
            value = int(self.search_limit.get())
        except (tk.TclError, ValueError) as exc:
            raise GuiError("limite deve ser um número entre 1 e 200") from exc
        if not 1 <= value <= 200:
            raise GuiError("limite deve ficar entre 1 e 200")
        return value

    def _do_search(self) -> None:
        query = self.search_query.get()
        max_price = self.search_max_price.get()
        source = self.search_source.get()
        sort = self.search_sort.get()
        try:
            limit = self._search_limit()
        except GuiError as exc:
            self._show_error(exc)
            return
        self._run_async(
            lambda: self.controller.search(
                query=query,
                max_price=max_price,
                source=source,
                limit=limit,
                sort=sort,
            ),
            self._show_search,
        )

    def _show_search(self, report: SearchReport) -> None:
        self._search_views = list(report.views)
        self.search_tree.delete(*self.search_tree.get_children())
        for index, view in enumerate(self._search_views):
            trust = view.trust
            self.search_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    view.product.title,
                    view.store.name,
                    money(view.offer.final_price),
                    money(view.offer.shipping),
                    f"{view.deal_score:.1f}",
                    (
                        f"{trust.score:.0f}/100 ({trust.analysis_confidence:.0%})"
                        if trust is not None
                        else "n/d"
                    ),
                    trust.risk_band if trust is not None else "n/d",
                ),
            )

        sources = ", ".join(f"{status.label}: {status.status}" for status in report.sources)
        self._set_status(
            f"{len(report.views)} resultado(s) em {len(report.sources)} fonte(s) "
            f"({report.duration_ms} ms). {sources}"
        )
        if self._search_views:
            self.search_tree.selection_set("0")
            self.search_tree.focus("0")
            self._show_search_detail(0)
        else:
            self._set_text(
                self.search_detail,
                "Nenhum resultado.\n\n"
                + "\n".join(f"fonte {status.label}: {status.status}" for status in report.sources)
                + ("\n\nAvisos: " + " | ".join(report.warnings) if report.warnings else ""),
            )

    def _on_search_select(self, _event: object) -> None:
        index = self._selected_index(self.search_tree)
        if index is not None:
            self._show_search_detail(index)

    def _show_search_detail(self, index: int) -> None:
        if not 0 <= index < len(self._search_views):
            return
        self._set_text(self.search_detail, offer_detail(self._search_views[index]))

    def _on_search_open(self, _event: object) -> None:
        self._open_selected_offer()

    def _open_selected_offer(self) -> None:
        index = self._selected_index(self.search_tree)
        if index is None or not 0 <= index < len(self._search_views):
            self._set_status("Selecione uma oferta para abrir.")
            return
        url = self._search_views[index].offer.url
        if self.controller.open_url(url):
            self._set_status("Oferta aberta no navegador padrão.")
        else:
            self._set_status("URL inválida ou navegador indisponível.")

    # ------------------------------------------------------------- histórico

    def _build_history_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Histórico")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)

        self.history_term = tk.StringVar()
        self.history_days = tk.StringVar()
        ttk.Label(tab, text="Termo ou ID").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(tab, textvariable=self.history_term)
        entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))
        entry.bind("<Return>", self._on_history_enter)
        ttk.Label(tab, text="Dias").grid(row=0, column=2, sticky="w")
        ttk.Entry(tab, textvariable=self.history_days, width=8).grid(
            row=0, column=3, sticky="w", padx=(4, 10)
        )
        ttk.Button(tab, text="Consultar", command=self._do_history).grid(
            row=0, column=4, sticky="e"
        )

        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=1, column=0, columnspan=5, sticky="nsew", pady=(10, 6))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.history_tree = ttk.Treeview(
            tree_frame, columns=("data", "preco", "fonte"), show="headings", height=8
        )
        for name, label, width in (
            ("data", "Coletado em", 190),
            ("preco", "Preço", 140),
            ("fonte", "Fonte", 160),
        ):
            self.history_tree.heading(name, text=label)
            self.history_tree.column(name, width=width, anchor="w")
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.history_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        stats_frame = ttk.LabelFrame(tab, text="Estatísticas", padding=4)
        stats_frame.grid(row=3, column=0, columnspan=5, sticky="nsew")
        stats_frame.rowconfigure(0, weight=1)
        stats_frame.columnconfigure(0, weight=1)
        self.history_stats = self._readonly_text(stats_frame, height=10)
        self.history_stats.grid(row=0, column=0, sticky="nsew")

    def _on_history_enter(self, _event: object) -> None:
        self._do_history()

    def _history_days(self) -> int | None:
        raw = self.history_days.get().strip()
        if not raw:
            return None
        try:
            days = int(raw)
        except ValueError as exc:
            raise GuiError("dias deve ser um inteiro positivo") from exc
        if days <= 0:
            raise GuiError("dias deve ser um inteiro positivo")
        return days

    def _do_history(self) -> None:
        term = self.history_term.get()
        try:
            days = self._history_days()
        except GuiError as exc:
            self._show_error(exc)
            return
        self._run_async(lambda: self.controller.history(term, days=days), self._show_history)

    def _show_history(self, report: HistoryReport | None) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        if report is None:
            self._set_text(self.history_stats, "Nenhum histórico encontrado para o termo.")
            self._set_status("Histórico não encontrado.")
            return
        for point in report.points:
            self.history_tree.insert(
                "",
                "end",
                values=(when(point.collected_at), str(point.price), point.source),
            )
        self._set_text(self.history_stats, history_text(report))
        self._set_status(f"{len(report.points)} amostra(s) de preço para {report.product_title}.")

    # ------------------------------------------------------------- avaliações

    def _build_reviews_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Avaliações")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(2, weight=1)

        self.reviews_term = tk.StringVar()
        self.reviews_include_text = tk.BooleanVar(value=False)
        ttk.Label(tab, text="Termo ou ID").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(tab, textvariable=self.reviews_term)
        entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))
        entry.bind("<Return>", self._on_reviews_enter)
        ttk.Checkbutton(
            tab,
            text="Incluir textos publicados",
            variable=self.reviews_include_text,
        ).grid(row=0, column=2, sticky="w", padx=(0, 10))
        ttk.Button(tab, text="Consultar", command=self._do_reviews).grid(
            row=0, column=3, sticky="e"
        )

        text_frame = ttk.LabelFrame(tab, text="Agregado e análise", padding=4)
        text_frame.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        self.reviews_text = self._readonly_text(text_frame, height=24)
        self.reviews_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.reviews_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.reviews_text.configure(yscrollcommand=scrollbar.set)

    def _on_reviews_enter(self, _event: object) -> None:
        self._do_reviews()

    def _do_reviews(self) -> None:
        term = self.reviews_term.get()
        include_text = bool(self.reviews_include_text.get())
        self._run_async(
            lambda: self.controller.reviews(term, include_text=include_text),
            self._show_reviews,
        )

    def _show_reviews(self, result: tuple[ReviewReport | None, list[str]]) -> None:
        report, warnings = result
        if report is None:
            message = "\n".join(warnings) or "Nenhuma avaliação encontrada."
            self._set_text(self.reviews_text, message)
            self._set_status("Avaliações não encontradas.")
            return
        text = reviews_text(report)
        if warnings:
            text += "\n\nAvisos: " + " | ".join(warnings)
        self._set_text(self.reviews_text, text)
        self._set_status(f"Avaliações de {report.product_title} carregadas.")

    # ---------------------------------------------------------------- alertas

    def _build_alerts_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Alertas")
        for column in (1, 3, 5, 7):
            tab.columnconfigure(column, weight=1)
        tab.rowconfigure(3, weight=2)
        tab.rowconfigure(5, weight=1)

        self.alert_query = tk.StringVar()
        self.alert_price = tk.StringVar()
        self.alert_discount = tk.StringVar()
        self.alert_label = tk.StringVar()
        self.alert_min_trust = tk.StringVar()
        self.alert_max_risk = tk.StringVar(value="")
        self.alert_min_confidence = tk.StringVar()
        self.alert_require_real = tk.BooleanVar(value=False)
        self.alert_source = tk.StringVar(value="config")

        form = ttk.LabelFrame(tab, text="Novo alerta", padding=6)
        form.grid(row=0, column=0, columnspan=8, sticky="ew")
        for column in (1, 3, 5, 7):
            form.columnconfigure(column, weight=1)

        ttk.Label(form, text="Busca").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.alert_query).grid(
            row=0, column=1, sticky="ew", padx=(4, 10)
        )
        ttk.Label(form, text="Preço-alvo").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.alert_price, width=12).grid(
            row=0, column=3, sticky="w", padx=(4, 10)
        )
        ttk.Label(form, text="Desconto %").grid(row=0, column=4, sticky="w")
        ttk.Entry(form, textvariable=self.alert_discount, width=10).grid(
            row=0, column=5, sticky="w", padx=(4, 10)
        )
        ttk.Label(form, text="Rótulo").grid(row=0, column=6, sticky="w")
        ttk.Entry(form, textvariable=self.alert_label).grid(
            row=0, column=7, sticky="ew", padx=(4, 0)
        )

        ttk.Label(form, text="Confiança mín.").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.alert_min_trust, width=12).grid(
            row=1, column=1, sticky="w", padx=(4, 10), pady=(6, 0)
        )
        ttk.Label(form, text="Risco máx.").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Combobox(
            form,
            textvariable=self.alert_max_risk,
            values=list(RISK_OPTIONS),
            state="readonly",
            width=10,
        ).grid(row=1, column=3, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(form, text="Cobertura mín.").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.alert_min_confidence, width=10).grid(
            row=1, column=5, sticky="w", padx=(4, 10), pady=(6, 0)
        )
        ttk.Checkbutton(
            form,
            text="Exigir desconto corroborado",
            variable=self.alert_require_real,
        ).grid(row=1, column=6, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(form, text="Criar alerta", command=self._do_create_alert).grid(
            row=2, column=7, sticky="e", pady=(8, 0)
        )

        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=3, column=0, columnspan=8, sticky="nsew", pady=(10, 6))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.alerts_tree = ttk.Treeview(
            tree_frame,
            columns=("id", "label", "query", "regra", "status", "ultima"),
            show="headings",
            height=7,
        )
        for name, label, width in (
            ("id", "ID", 50),
            ("label", "Rótulo", 170),
            ("query", "Busca", 220),
            ("regra", "Regra", 260),
            ("status", "Status", 90),
            ("ultima", "Última checagem", 160),
        ):
            self.alerts_tree.heading(name, text=label)
            self.alerts_tree.column(name, width=width, anchor="w")
        self.alerts_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.alerts_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.alerts_tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=8, sticky="ew")
        ttk.Button(actions, text="Atualizar", command=self._refresh_alerts).pack(side="left")
        ttk.Button(actions, text="Pausar/Retomar", command=self._toggle_alert).pack(
            side="left", padx=6
        )
        ttk.Button(actions, text="Excluir", command=self._delete_alert).pack(side="left")
        ttk.Label(actions, text="Fonte da checagem").pack(side="left", padx=(18, 4))
        ttk.Combobox(
            actions,
            textvariable=self.alert_source,
            values=list(SOURCE_OPTIONS),
            state="readonly",
            width=12,
        ).pack(side="left")
        ttk.Button(actions, text="Verificar agora", command=self._check_alerts).pack(
            side="left", padx=6
        )

        result_frame = ttk.LabelFrame(tab, text="Resultado da checagem", padding=4)
        result_frame.grid(row=5, column=0, columnspan=8, sticky="nsew", pady=(8, 0))
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.alerts_result = self._readonly_text(result_frame, height=8)
        self.alerts_result.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.alerts_result.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.alerts_result.configure(yscrollcommand=scrollbar.set)

    def _refresh_alerts(self) -> None:
        try:
            alerts = self.controller.list_alerts()
        except Exception as exc:
            self._show_error(exc)
            return
        self._alerts_by_id = {alert.id: alert for alert in alerts}
        self.alerts_tree.delete(*self.alerts_tree.get_children())
        for alert in alerts:
            self.alerts_tree.insert(
                "",
                "end",
                iid=str(alert.id),
                values=(
                    alert.id,
                    alert.label,
                    alert.query,
                    _alert_rule_text(alert),
                    "ativo" if alert.active else "pausado",
                    when(alert.last_checked_at),
                ),
            )
        self._set_status(f"{len(alerts)} alerta(s) cadastrado(s).")

    def _do_create_alert(self) -> None:
        query = self.alert_query.get()
        max_price = self.alert_price.get()
        discount = self.alert_discount.get()
        label = self.alert_label.get()
        min_trust = self.alert_min_trust.get()
        max_risk = self.alert_max_risk.get()
        min_confidence = self.alert_min_confidence.get()
        require_real = bool(self.alert_require_real.get())
        self._run_async(
            lambda: self.controller.create_alert(
                query=query,
                max_price=max_price,
                discount=discount,
                label=label,
                min_trust=min_trust,
                max_risk=max_risk,
                require_real_discount=require_real,
                min_analysis_confidence=min_confidence,
            ),
            self._show_alert_created,
        )

    def _show_alert_created(self, alert_id: int) -> None:
        self._set_status(f"Alerta #{alert_id} criado.")
        self._refresh_alerts()

    def _toggle_alert(self) -> None:
        alert = self._selected_alert()
        if alert is None:
            self._set_status("Selecione um alerta.")
            return
        active = not alert.active
        self._run_async(
            lambda: self.controller.set_alert_active(alert.id, active=active),
            lambda changed: self._after_alert_change(alert.id, changed),
        )

    def _after_alert_change(self, alert_id: int, changed: bool) -> None:
        self._set_status(
            f"Alerta #{alert_id} atualizado." if changed else f"Alerta #{alert_id} não encontrado."
        )
        self._refresh_alerts()

    def _delete_alert(self) -> None:
        alert = self._selected_alert()
        if alert is None:
            self._set_status("Selecione um alerta.")
            return
        if not messagebox.askyesno("DealHunter", f"Excluir o alerta #{alert.id}?"):
            return
        self._run_async(
            lambda: self.controller.delete_alert(alert.id),
            lambda deleted: self._after_alert_delete(alert.id, deleted),
        )

    def _after_alert_delete(self, alert_id: int, deleted: bool) -> None:
        self._set_status(
            f"Alerta #{alert_id} excluído." if deleted else f"Alerta #{alert_id} não encontrado."
        )
        self._refresh_alerts()

    def _check_alerts(self) -> None:
        alert = self._selected_alert()
        alert_id = alert.id if alert is not None else None
        source = self.alert_source.get()
        self._run_async(
            lambda: self.controller.check_alerts(alert_id=alert_id, source=source),
            self._show_outcomes,
        )

    def _show_outcomes(self, outcomes: list[AlertOutcome]) -> None:
        if not outcomes:
            self._set_text(self.alerts_result, "Nenhum alerta ativo para verificar.")
            self._set_status("Nenhum alerta ativo.")
            return
        lines: list[str] = []
        for outcome in outcomes:
            if not outcome.matched:
                lines.append(f"#{outcome.alert_id} {outcome.label}: {outcome.note}")
                continue
            lines.append(f"#{outcome.alert_id} {outcome.label}: {outcome.price} — {outcome.note}")
            if outcome.trust_score is not None:
                lines.append(
                    f"  confiança {outcome.trust_score:.0f}/100; risco {outcome.risk_band}; "
                    f"cobertura {outcome.analysis_confidence:.0%}"
                )
            for channel, ok, error in outcome.channels_sent:
                lines.append(
                    f"  {channel}: ok" if ok else f"  {channel}: falhou ({error or 'erro'})"
                )
        self._set_text(self.alerts_result, "\n".join(lines))
        self._set_status(f"{len(outcomes)} alerta(s) verificado(s).")

    # ---------------------------------------------------------------- monitor

    def _build_monitor_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Monitor")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(4, weight=2)

        controls = ttk.Frame(tab)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="Fonte").pack(side="left")
        self.monitor_source = tk.StringVar(value="config")
        ttk.Combobox(
            controls,
            textvariable=self.monitor_source,
            values=list(SOURCE_OPTIONS),
            state="readonly",
            width=12,
        ).pack(side="left", padx=(4, 12))
        self.monitor_ignore_quiet = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls,
            text="Ignorar quiet hours",
            variable=self.monitor_ignore_quiet,
        ).pack(side="left", padx=(0, 12))
        ttk.Button(controls, text="Executar um ciclo", command=self._run_monitor).pack(side="left")
        ttk.Button(controls, text="Atualizar estado", command=self._refresh_monitor).pack(
            side="left", padx=6
        )

        last_frame = ttk.LabelFrame(tab, text="Última execução registrada", padding=4)
        last_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 6))
        last_frame.rowconfigure(0, weight=1)
        last_frame.columnconfigure(0, weight=1)
        self.monitor_last = self._readonly_text(last_frame, height=6)
        self.monitor_last.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            tab,
            text=(
                "Para execução permanente use, no terminal: "
                "dealhunter monitor --daemon --interval 900 "
                "(e dealhunter monitor --stop para encerrar)."
            ),
            wraplength=1000,
        ).grid(row=2, column=0, sticky="w", pady=(0, 6))

        result_frame = ttk.LabelFrame(tab, text="Resultado do ciclo", padding=4)
        result_frame.grid(row=4, column=0, sticky="nsew")
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.monitor_result = self._readonly_text(result_frame, height=12)
        self.monitor_result.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            result_frame, orient="vertical", command=self.monitor_result.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.monitor_result.configure(yscrollcommand=scrollbar.set)

    def _refresh_monitor(self) -> None:
        try:
            last = self.controller.last_monitor_run()
        except Exception as exc:
            self._show_error(exc)
            return
        if last is None:
            self._set_text(self.monitor_last, "Nenhuma execução do monitor registrada.")
            return
        lines = [
            f"Run #{last.get('id', '?')} | status: {last.get('status', '?')} | "
            f"gatilho: {last.get('trigger', '?')}",
            f"Início: {when(str(last.get('started_at') or ''))} | "
            f"Fim: {when(str(last.get('finished_at') or ''))}",
            f"Ciclos: {last.get('cycles', 0)} | alertas verificados: "
            f"{last.get('alerts_checked', 0)} | correspondências: {last.get('matched', 0)}",
            f"Envios: {last.get('notifications', 0)}",
        ]
        if last.get("error"):
            lines.append(f"Erro: {last['error']}")
        self._set_text(self.monitor_last, "\n".join(lines))

    def _run_monitor(self) -> None:
        source = self.monitor_source.get()
        ignore_quiet = bool(self.monitor_ignore_quiet.get())
        self._run_async(
            lambda: self.controller.monitor_once(source=source, ignore_quiet_hours=ignore_quiet),
            self._show_monitor,
        )

    def _show_monitor(self, result: MonitorRunResult) -> None:
        lines = [
            f"Run #{result.run_id} | status: {result.status} | gatilho: {result.trigger}",
            f"Início: {when(result.started_at)} | Fim: {when(result.finished_at)}",
            f"Ciclos: {len(result.cycles)} | verificados: {result.checked} | "
            f"correspondências: {result.matched} | envios: {result.notifications} | "
            f"cooldown: {result.skipped_cooldown}",
        ]
        if result.error:
            lines.append(f"Erro: {result.error}")
        for warning in result.warnings:
            lines.append(f"Aviso: {warning}")
        for cycle in result.cycles:
            lines.append(
                f"\nCiclo {cycle.run_id} ({cycle.status}): {cycle.checked} verificado(s), "
                f"{cycle.matched} correspondência(s), {cycle.notifications} envio(s)"
            )
            if cycle.note:
                lines.append(f"  {cycle.note}")
            for outcome in cycle.outcomes:
                if outcome.matched:
                    lines.append(
                        f"  #{outcome.alert_id} {outcome.label}: {outcome.price} — {outcome.note}"
                    )
                else:
                    lines.append(f"  #{outcome.alert_id} {outcome.label}: {outcome.note}")
        self._set_text(self.monitor_result, "\n".join(lines))
        self._set_status(f"Ciclo do monitor concluído com status {result.status}.")
        self._refresh_monitor()


def launch(rt: RuntimeContext) -> None:
    """Abre a janela e bloqueia até o usuário fechá-la."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise GuiUnavailable("não foi possível abrir a janela (ambiente sem display?)") from exc
    controller = GuiController(rt)
    DealHunterApp(root, controller)
    root.mainloop()
