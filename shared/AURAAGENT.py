"""
AURAAGENT — Módulo LLM do AURA
Responsabilidade única: agente conversacional via Groq.

Uso em aura.py:
    import AURAAGENT
    AURAAGENT.init(groq_key)
    AURAAGENT.abrir_chat_agente(parent, get_ctx)
"""

import json
import re
import threading
import tkinter as tk
from tkinter import scrolledtext

from aura_db import ler_processos_ajuizados

# ── Estado interno ────────────────────────────────────────────
_GROQ_KEY = ""
_HISTORICO: list[dict] = []
_MODEL = "llama-3.3-70b-versatile"

# ── Design System (espelha aura.py) ──────────────────────────
_COR_BG       = "#0f1117"
_COR_PAINEL   = "#1a1d27"
_COR_PRIMARIA = "#4f8ef7"
_COR_TEXTO    = "#e8eaf0"
_COR_SUBTEXTO = "#7c8098"
_COR_INPUT_BG = "#252836"
_COR_BORDA    = "#2a2d3e"


# ── Inicialização ─────────────────────────────────────────────

def init(groq_key: str) -> None:
    """Configura a chave Groq. Chamar após carregar o config."""
    global _GROQ_KEY
    _GROQ_KEY = groq_key


# ── API Groq ──────────────────────────────────────────────────

def chamar_groq(mensagens: list[dict]) -> str:
    import urllib.request
    if not _GROQ_KEY:
        return "Chave Groq não configurada. Adicione 'groq_key' ao aura_config.json."
    try:
        dados = json.dumps({
            "model": _MODEL,
            "messages": mensagens,
            "max_tokens": 1024,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=dados,
            headers={
                "Authorization": f"Bearer {_GROQ_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "AURA-TJMG/9.21",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Erro ao consultar o agente: {e}"


# ── Chamadas seguras (uso interno no fluxo de peticionamento) ──
# Nunca lançam exceção e usam timeout curto: uma falha ou lentidão do Groq
# não pode travar nem derrubar o lote de peticionamento em execução.

def _chamar_groq_seguro(mensagens: list[dict], timeout: int = 10, max_tokens: int = 300) -> str | None:
    import urllib.request
    if not _GROQ_KEY:
        return None
    try:
        dados = json.dumps({
            "model": _MODEL,
            "messages": mensagens,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=dados,
            headers={
                "Authorization": f"Bearer {_GROQ_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "AURA-TJMG/9.21",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def sugerir_campo_desconhecido(tela: str, campos_novos: list, dados_linha: dict) -> str | None:
    """Sugestão consultiva sobre campos do eProc que o robô não conhece.

    Uso apenas de log/aviso: o robô não altera a tela sozinho com base nisso,
    então uma resposta ruim ou ausente da IA nunca compromete o peticionamento.
    """
    contexto_linha = ", ".join(f"{k}={v}" for k, v in list(dados_linha.items())[:12])
    prompt = f"""Você é o assistente técnico do AURA (robô de peticionamento eletrônico do TJMG).
Na tela "{tela}" apareceram campos de formulário que o robô não conhece: {", ".join(campos_novos)}.

Dados da linha da planilha que está sendo peticionada: {contexto_linha}

Em até 3 linhas, diga objetivamente: (1) o que esses campos provavelmente representam e
(2) se algum deles parece obrigatório e precisa de atenção manual antes de continuar."""
    return _chamar_groq_seguro([{"role": "user", "content": prompt}], timeout=10, max_tokens=200)


def escolher_assunto_similar(assunto_desejado: str, opcoes: list) -> str | None:
    """Escolhe, entre as opções realmente exibidas na busca do eProc, a mais
    compatível com o assunto pedido na planilha. Só retorna um código se ele
    estiver entre as opções recebidas — nunca inventa um valor.

    opcoes: lista de tuplas (codigo, texto_descricao).
    """
    if not opcoes:
        return None
    lista = "\n".join(f"{cod} — {txt}" for cod, txt in opcoes[:40])
    prompt = f"""O robô AURA está peticionando no eProc/TJMG e precisa selecionar um Assunto processual.
A planilha pede o assunto: "{assunto_desejado}"
A busca no eProc não encontrou esse texto exato, mas retornou estas opções (código — descrição):
{lista}

Responda APENAS com o código exato de uma das opções acima que mais se aproxima do assunto pedido.
Se nenhuma opção for uma correspondência razoável, responda apenas: NENHUM"""
    resposta = _chamar_groq_seguro([{"role": "user", "content": prompt}], timeout=10, max_tokens=20)
    if not resposta:
        return None
    resposta = resposta.strip().splitlines()[0].strip()
    codigos_validos = {cod for cod, _ in opcoes}
    return resposta if resposta in codigos_validos else None


def revisar_dados_peticao(dados: dict) -> str | None:
    """Revisão consultiva dos dados de uma linha antes da confirmação final.

    Não bloqueia o fluxo: o robô apenas registra o resultado para auditoria,
    exatamente como as outras chamadas de IA deste módulo.
    """
    resumo = ", ".join(f"{k}={v}" for k, v in dados.items() if v)
    prompt = f"""Revise rapidamente estes dados de uma petição eletrônica prestes a ser confirmada no eProc/TJMG:
{resumo}

Em até 2 linhas, aponte APENAS se algo parecer claramente inconsistente ou incompleto
(ex: campo obrigatório vazio, CPF/CNPJ com formato inválido). Se estiver tudo normal,
responda apenas: OK"""
    return _chamar_groq_seguro([{"role": "user", "content": prompt}], timeout=10, max_tokens=120)


# ── Ferramentas ───────────────────────────────────────────────

def _executar_ferramenta(ferramenta: str) -> str:
    if ferramenta == "consultar_historico":
        try:
            processos = ler_processos_ajuizados()
        except Exception as e:
            return f"Erro ao consultar histórico: {e}"
        if not processos:
            return "Nenhum processo ajuizado encontrado."
        resumo = f"Total de {len(processos)} processos ajuizados.\n"
        resumo += "\n".join(
            f"- {p.get('Processo', '')} | {p.get('Classe', '')} | {p.get('Data', '')}"
            for p in processos[-10:]
        )
        return resumo
    return "Ferramenta não reconhecida."


# ── Agent loop ────────────────────────────────────────────────

def agente_responder(mensagem: str, contexto: dict) -> str:
    """
    Processa uma mensagem do usuário e retorna a resposta do agente.
    contexto: dict com chaves 'pdf', 'competencia', 'usuario'
    """
    global _HISTORICO

    sistema = f"""Você é o AURA, assistente inteligente do sistema de peticionamento eletrônico do TJMG.
Você pode:
- Interpretar erros do sistema eProc
- Consultar histórico de processos ajuizados
- Orientar sobre o uso do AURA
- Durante o peticionamento em lote, você também atua nos bastidores: sugere o que
  fazer com campos desconhecidos do eProc, ajuda a escolher o Assunto processual
  quando a busca exata falha, e revisa os dados antes da confirmação final.

Quando o usuário pedir para consultar histórico, responda com: [FERRAMENTA:consultar_historico]
Para ações de peticionamento, oriente a usar os botões da interface.

Contexto atual:
- PDF selecionado: {contexto.get('pdf') or 'Nenhum'}
- Competência ativa: {contexto.get('competencia') or 'Nenhuma'}
- Usuário logado: {contexto.get('usuario') or 'Não logado'}
Responda sempre em português, de forma direta e objetiva."""

    _HISTORICO.append({"role": "user", "content": mensagem})
    mensagens = [{"role": "system", "content": sistema}] + _HISTORICO
    resposta = chamar_groq(mensagens)

    match = re.search(r'\[FERRAMENTA:(\w+)\]', resposta)
    if match:
        resultado = _executar_ferramenta(match.group(1))
        resposta = resposta.replace(match.group(0), "\n\n" + resultado)

    _HISTORICO.append({"role": "assistant", "content": resposta})
    if len(_HISTORICO) > 20:
        _HISTORICO = _HISTORICO[-20:]

    return resposta


# ── UI — Chat window ──────────────────────────────────────────

def abrir_chat_agente(parent: tk.Tk, get_ctx) -> None:
    """
    Abre a janela de chat do agente.

    parent  : janela principal (tk.Tk ou CTk)
    get_ctx : callable() → dict com 'pdf', 'competencia', 'usuario'
    """
    global _HISTORICO
    _HISTORICO = []

    jan = tk.Toplevel(parent)
    jan.title("AURA Agent")
    jan.geometry("620x680")
    jan.configure(bg=_COR_BG)

    # Header
    header = tk.Frame(jan, bg=_COR_PAINEL, pady=10)
    header.pack(fill="x")
    tk.Label(
        header, text="🤖  AURA Agent",
        font=("Segoe UI", 13, "bold"), bg=_COR_PAINEL, fg=_COR_PRIMARIA,
    ).pack(side="left", padx=16)
    tk.Label(
        header, text="llama-3.3-70b · Groq",
        font=("Segoe UI", 8), bg=_COR_PAINEL, fg=_COR_SUBTEXTO,
    ).pack(side="left")

    def _limpar():
        global _HISTORICO
        _HISTORICO = []
        chat_box.configure(state="normal")
        chat_box.delete("1.0", "end")
        chat_box.configure(state="disabled")
        _add("Histórico limpo. Como posso ajudar?", "sistema")

    tk.Button(
        header, text="🗑 Limpar", font=("Segoe UI", 8),
        bg=_COR_PAINEL, fg=_COR_SUBTEXTO, relief="flat",
        command=_limpar,
    ).pack(side="right", padx=16)

    # Chat
    chat_box = scrolledtext.ScrolledText(
        jan, font=("Segoe UI", 10), bg="#0D1117", fg=_COR_TEXTO,
        relief="flat", wrap="word", state="disabled", padx=12, pady=8,
    )
    chat_box.pack(fill="both", expand=True, padx=12, pady=(8, 0))
    chat_box.tag_configure("usuario",  foreground=_COR_PRIMARIA, font=("Segoe UI", 10, "bold"))
    chat_box.tag_configure("agente",   foreground=_COR_TEXTO)
    chat_box.tag_configure("sistema",  foreground=_COR_SUBTEXTO, font=("Segoe UI", 9, "italic"))

    def _add(texto: str, tag: str) -> None:
        chat_box.configure(state="normal")
        chat_box.insert("end", texto + "\n\n", tag)
        chat_box.see("end")
        chat_box.configure(state="disabled")

    _add("AURA Agent iniciado. Como posso ajudar?", "sistema")

    # Input
    frame_input = tk.Frame(jan, bg=_COR_BG, pady=8)
    frame_input.pack(fill="x", padx=12, pady=(4, 12))

    txt_input = tk.Text(
        frame_input, font=("Segoe UI", 10), height=3,
        bg=_COR_INPUT_BG, fg=_COR_TEXTO, insertbackground=_COR_PRIMARIA,
        relief="flat", wrap="word",
        highlightbackground=_COR_BORDA, highlightthickness=1,
    )
    txt_input.pack(side="left", fill="x", expand=True, padx=(0, 8))

    def _enviar() -> None:
        mensagem = txt_input.get("1.0", "end").strip()
        if not mensagem:
            return
        txt_input.delete("1.0", "end")
        _add(f"Você: {mensagem}", "usuario")
        btn_enviar.configure(state="disabled", text="...")

        def _processar() -> None:
            ctx = get_ctx() if callable(get_ctx) else {}
            resposta = agente_responder(mensagem, ctx)
            jan.after(0, lambda: _add(f"AURA: {resposta}", "agente"))
            jan.after(0, lambda: btn_enviar.configure(state="normal", text="Enviar"))

        threading.Thread(target=_processar, daemon=True).start()

    btn_enviar = tk.Button(
        frame_input, text="Enviar",
        font=("Segoe UI", 10, "bold"),
        bg=_COR_PRIMARIA, fg="white", relief="flat",
        width=8, command=_enviar,
    )
    btn_enviar.pack(side="right")
    txt_input.bind("<Return>", lambda e: [_enviar(), "break"][1])
    txt_input.bind("<Shift-Return>", lambda e: None)
    txt_input.focus()
