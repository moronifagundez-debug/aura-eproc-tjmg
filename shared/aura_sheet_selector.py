# ============================================================
#  aura_sheet_selector.py  —  Seletor de Competências AURA
#  CESUPE  |  Componente compartilhado por todos os AURAs
# ============================================================
#
#  Uso em qualquer AURA:
#
#    from aura_sheet_selector import SheetSelectorFrame
#
#    selector = SheetSelectorFrame(parent, on_select=minha_funcao)
#    selector.pack(fill="x", padx=12, pady=4)
#
#  Callback on_select recebe (nome_aba, linhas):
#    nome_aba : str         — nome da aba selecionada
#    linhas   : list[dict]  — linhas da competência
# ============================================================

import threading
import customtkinter as ctk
from aura_db import listar_abas_competencias, ler_competencia

# ── Design System AURA ──────────────────────────────────────
COR_BG       = "#0f1117"
COR_PAINEL   = "#161b22"
COR_PRIMARIA = "#4f8ef7"
COR_HOVER    = "#3a7be0"
COR_SUCESSO  = "#2ea043"
COR_ERRO     = "#da3633"
COR_AVISO    = "#e3b341"
COR_BORDA    = "#30363d"
COR_SUBTEXTO = "#8b949e"
COR_TEXTO    = "#e6edf3"


class SheetSelectorFrame(ctk.CTkFrame):
    """
    Frame reutilizável que lista abas da planilha de competências
    e dispara on_select(nome_aba, linhas) quando o usuário confirma.
    """

    def __init__(self, master, on_select=None, **kwargs):
        kwargs.setdefault("fg_color", COR_PAINEL)
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COR_BORDA)
        super().__init__(master, **kwargs)

        self._on_select = on_select
        self._abas      = []
        self._aba_var   = ctk.StringVar(value="")
        self._status    = ctk.StringVar(value="Carregando competências...")

        self._build()
        self._carregar_abas()

    # ── Build ────────────────────────────────────────────────
    def _build(self):
        ctk.CTkLabel(self,
                     text="COMPETÊNCIA",
                     font=ctk.CTkFont("Segoe UI", 9, "bold"),
                     text_color=COR_SUBTEXTO,
                     anchor="w").pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkFrame(self, fg_color=COR_BORDA, height=1).pack(fill="x", padx=12, pady=(0, 6))

        # Dropdown de abas
        self._combo = ctk.CTkComboBox(
            self,
            variable=self._aba_var,
            values=["Carregando..."],
            font=ctk.CTkFont("Segoe UI", 10),
            fg_color="#21262d",
            border_color=COR_BORDA,
            button_color=COR_PRIMARIA,
            button_hover_color=COR_HOVER,
            dropdown_fg_color=COR_PAINEL,
            dropdown_text_color=COR_TEXTO,
            dropdown_hover_color=COR_BORDA,
            height=32,
            corner_radius=6,
            state="disabled",
            command=self._on_combo_change,
        )
        self._combo.pack(fill="x", padx=12, pady=(0, 4))

        # Linha de status + botão recarregar
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 4))

        self._lbl_status = ctk.CTkLabel(
            row,
            textvariable=self._status,
            font=ctk.CTkFont("Segoe UI", 9),
            text_color=COR_SUBTEXTO,
            anchor="w",
        )
        self._lbl_status.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            row,
            text="↻",
            font=ctk.CTkFont("Segoe UI", 11),
            fg_color="#21262d",
            hover_color=COR_BORDA,
            width=30,
            height=26,
            corner_radius=5,
            command=self._carregar_abas,
        ).pack(side="right")

        # Botão confirmar
        self._btn_confirmar = ctk.CTkButton(
            self,
            text="✓  Usar esta competência",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=COR_SUCESSO,
            hover_color="#27ae60",
            height=34,
            corner_radius=6,
            state="disabled",
            command=self._confirmar,
        )
        self._btn_confirmar.pack(fill="x", padx=12, pady=(0, 10))

    # ── Carregar abas do Sheets ──────────────────────────────
    def _carregar_abas(self):
        self._status.set("Carregando competências...")
        self._combo.configure(state="disabled", values=["Carregando..."])
        self._btn_confirmar.configure(state="disabled")
        threading.Thread(target=self._carregar_abas_thread, daemon=True).start()

    def _carregar_abas_thread(self):
        try:
            abas = listar_abas_competencias()
            self._abas = abas
            self.after(0, lambda: self._atualizar_combo(abas))
        except Exception as e:
            self.after(0, lambda: self._status.set(f"Erro: {type(e).__name__}: {str(e)[:50]}"))

    def _atualizar_combo(self, abas: list[str]):
        if not abas:
            self._status.set("Nenhuma competência encontrada.")
            return
        self._combo.configure(state="normal", values=abas)
        self._aba_var.set(abas[0])
        self._status.set(f"{len(abas)} competência(s) disponível(is)")
        self._btn_confirmar.configure(state="normal")

    def _on_combo_change(self, valor: str):
        self._aba_var.set(valor)
        self._status.set(f"Selecionada: {valor}")

    # ── Confirmar seleção ────────────────────────────────────
    def _confirmar(self):
        nome_aba = self._aba_var.get().strip()
        if not nome_aba or nome_aba == "Carregando...":
            return
        self._status.set(f"Carregando linhas de '{nome_aba}'...")
        self._btn_confirmar.configure(state="disabled")
        threading.Thread(
            target=self._carregar_linhas_thread,
            args=(nome_aba,),
            daemon=True,
        ).start()

    def _carregar_linhas_thread(self, nome_aba: str):
        try:
            linhas = ler_competencia(nome_aba)
            self.after(0, lambda: self._finalizar(nome_aba, linhas))
        except Exception as e:
            self.after(0, lambda: self._status.set(f"Erro: {type(e).__name__}: {str(e)[:50]}"))
            self.after(0, lambda: self._btn_confirmar.configure(state="normal"))

    def _finalizar(self, nome_aba: str, linhas: list[dict]):
        n = len(linhas)
        self._status.set(f"✓ {nome_aba} — {n} linha(s) carregada(s)")
        self._btn_confirmar.configure(state="normal")
        if self._on_select:
            self._on_select(nome_aba, linhas)

    # ── API pública ──────────────────────────────────────────
    def aba_selecionada(self) -> str:
        return self._aba_var.get().strip()

    def set_status(self, texto: str, cor: str = COR_SUBTEXTO):
        self._status.set(texto)
        self._lbl_status.configure(text_color=cor)
