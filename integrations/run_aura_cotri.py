"""AURA COTRI — arquivo único.

Toda a aplicação (configuração, estado, leitura de planilhas, histórico,
análise de erro via IA, automação Selenium de assinatura/redistribuição e a
interface gráfica) está consolidada neste único arquivo. Basta executar:

    python run_aura_cotri.py
"""

import csv
import ctypes
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk

from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Modulos compartilhados vivem em shared/ (pasta irma desta, integrations/)
# -- necessario ao rodar este arquivo standalone (import de sibling nao acha
# shared/ sozinho). Quando importado pelo aura.py, ja esta no sys.path, mas
# nao ha problema em inserir de novo.
_caminho_shared = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared")
if _caminho_shared not in sys.path:
    sys.path.insert(0, _caminho_shared)

import aura_db
import aura_infra as _aura_infra
from aura_infra import criar_chrome_driver, _detectar_scaling, _lighten

logger = logging.getLogger("aura_cotri")

__version__ = "2.0"

# ===========================================================================
# CONFIGURAÇÕES GERAIS
# ===========================================================================
VERSAO_ATUAL = "2.0"
GITHUB_REPO = "ranyersp/aura_cotri"
ARQUIVO_CONFIG = os.path.join(os.path.expanduser("~"), ".aura_cotri", "config.json")

# Login padrao do eProc (mesmo usado no AURA Principal/AURA Gabinete) — evita
# pedir login na abertura do AURA COTRI. carregar_config() ainda tem prioridade
# se houver um login diferente salvo anteriormente.
USUARIO_PADRAO = "MG123456"
SENHA_PADRAO = "Senha*123456"
URL_PADRAO = "https://eproc2g-hml.tjmg.jus.br/eproc/"

OUTPUT_DIR = Path.home() / ".aura_cotri"
ARQUIVO_HISTORICO = OUTPUT_DIR / "processos_ajuizados.csv"

ID_FORM_PERSONALIZACAO_PPG = "11778619970168291601828332932"
ID_FORM_PERSONALIZACAO_CODIPRE_PRIVADO = "11762256419534693536132323160"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Pasta onde dumps de diagnostico (HTML + screenshot + inventario) sao gravados
# quando uma linha falha. Fica em ~/.aura_cotri/dumps para ser sempre gravavel,
# inclusive quando o app roda empacotado (.exe).
PASTA_DUMPS = OUTPUT_DIR / "dumps"

# Padrao de URL que indica sessao do eProc encerrada / link sem assinatura.
RE_SESSAO_EXPIRADA = re.compile(
    r"(Sua%20sess%E3o%20foi%20encerrada|Link%20sem%20assinatura"
    r"|Sua sess[ãa]o foi encerrada|Link sem assinatura)",
    re.IGNORECASE,
)


def base_path(filename):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    # Recursos compartilhados (logo, orgaos_caciv.json via run_aura_eventos-
    # cameracivel.py) ficam na raiz do projeto; este arquivo mora em
    # integrations/, por isso sobe um nivel.
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename)


def salvar_config(usuario, senha, url):
    try:
        os.makedirs(os.path.dirname(ARQUIVO_CONFIG), exist_ok=True)
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump({"usuario": usuario, "senha": senha, "url": url}, f)
    except Exception:
        pass


def carregar_config():
    try:
        if os.path.exists(ARQUIVO_CONFIG):
            with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def verificar_atualizacao():
    return _aura_infra.verificar_atualizacao(VERSAO_ATUAL, GITHUB_REPO)


def _normalizar(valor) -> str:
    """Normalização única usada por toda a aplicação: minúsculas, sem acentos."""
    texto = "" if valor is None else str(valor)
    texto = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


# ===========================================================================
# ESTADO DA APLICAÇÃO
# ===========================================================================
@dataclass
class AppState:
    caminho_planilha: Optional[str] = None
    caminho_redistribuicao: Optional[str] = None
    caminho_referencias_redistribuicao: Optional[str] = None
    perfil: str = "COTRI"
    usuario: str = ""
    senha: str = ""
    url: str = ""
    pausado: bool = False
    ultimo_aviso: list = field(default_factory=list)


# ===========================================================================
# TEMA (constantes usadas pelos diálogos de erro e histórico)
# ===========================================================================
BG = "#0f1117"
CARD = "#1a1d27"
BORDER = "#2a2d3e"
AZUL = "#4f8ef7"
AZUL_HOVER = "#3a6fd8"
LARANJA = AZUL
VERDE = "#2ecc71"
AVISO = "#f39c12"
ROXO = "#6c63ff"
TEXTO = "#e8eaf0"
SUBTEXTO = "#7c8098"
INPUT_BG = "#252836"
FONT = "Segoe UI"


def make_btn(parent, text, cor, command, width=26):
    btn = tk.Button(
        parent,
        text=text,
        font=(FONT, 10, "bold"),
        bg=cor,
        fg=TEXTO,
        activebackground=cor,
        activeforeground=TEXTO,
        relief="flat",
        cursor="hand2",
        width=width,
        command=command,
        bd=0,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=_lighten(cor)))
    btn.bind("<Leave>", lambda e: btn.config(bg=cor))
    return btn


# ===========================================================================
# DATA — leitura de CSV de assinatura
# ===========================================================================
_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]

_COLUNAS_NUMERO_PROCESSO = [
    "Número do processo",
    "Numero do processo",
    "Número do Processo",
    "Numero do Processo",
    "número do processo",
    "numero do processo",
    "NÚMERO DO PROCESSO",
    "NUMERO DO PROCESSO",
    # Colunas do CSV gerado pelo AURA principal
    "Numero de processo originario",
    "Número de processo originário",
    "Numero de Processo Originario",
    "NUMERO DE PROCESSO ORIGINARIO",
    "numero de processo originario",
]


def ler_csv(caminho: str) -> list[dict] | None:
    conteudo = None
    for enc in _ENCODINGS:
        try:
            with open(caminho, mode="r", encoding=enc) as f:
                conteudo = f.read()
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.error("Erro ao abrir CSV: %s", e)
            return None

    if conteudo is None:
        return None

    reader = csv.DictReader(io.StringIO(conteudo))
    return list(reader)


def normalizar_numero_processo(linha: dict) -> str:
    valor = ""
    for col in _COLUNAS_NUMERO_PROCESSO:
        v = linha.get(col)
        if v:
            valor = str(v)
            break

    valor = (
        valor.strip()
        .replace("\n", "")
        .replace("\r", "")
        .replace(".", "")
        .replace("-", "")
    )

    if not valor or valor.upper() == "NAO PRECISA" or valor.lower() == "nan":
        return ""

    return valor


# ===========================================================================
# DATA — leitura de planilha de redistribuição e referências
# ===========================================================================
_MAPA_REDISTRIBUIR = {
    "numero_processo": [
        "numero_processo",
        "numero do processo",
        "numero processo",
        "processo",
        "numero de processo originario",
    ],
    "tipo": ["tipo", "tipo_redistribuicao", "tipo redistribuicao"],
    "processo_ref": ["processo_ref", "processo referencia", "num_ref"],
    "competencia": ["competencia"],
    "assunto": ["assunto"],
    "classe_judicial": ["classe_judicial", "classe judicial", "classe"],
    "motivo_retorno": ["motivo_retorno", "motivo retorno", "motivo"],
}

_MAPA_REFERENCIAS = {
    "numero_processo": [
        "numero_processo",
        "numero do processo",
        "numero processo",
        "processo",
        "processo_origem",
        "processo origem",
    ],
    "processo_ref": [
        "processo_ref",
        "processo referencia",
        "processo de referencia",
        "numero_processo_referencia",
        "num_ref",
        "referencia",
    ],
    "competencia": ["competencia"],
    "magistrado_camara": ["magistrado_camara", "magistrado camara", "magistrado", "camara"],
}


def ler_redistribuicao(
    caminho: str,
    caminho_referencias: str | None = None,
) -> tuple[list[dict], list[dict]] | tuple[None, None]:
    ext = Path(caminho).suffix.lower()
    if ext != ".csv":
        logger.error("Arquivo de redistribuicao deve ser CSV separado por virgulas.")
        return None, None
    redistribuir = _ler_csv_mapeado(caminho, _MAPA_REDISTRIBUIR, "numero_processo")
    if redistribuir is None:
        return None, None

    referencias = []
    if caminho_referencias:
        if Path(caminho_referencias).suffix.lower() != ".csv":
            logger.error("Arquivo de referencias deve ser CSV separado por virgulas.")
            return None, None
        referencias = _ler_csv_mapeado(caminho_referencias, _MAPA_REFERENCIAS, None)
        if referencias is None:
            return None, None

    return redistribuir, referencias


def _ler_csv_mapeado(caminho: str, mapa_colunas: dict, coluna_obrigatoria: str | None) -> list[dict] | None:
    conteudo = None
    for enc in _ENCODINGS:
        try:
            with open(caminho, mode="r", encoding=enc) as f:
                conteudo = f.read()
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.error("Erro ao abrir CSV de redistribuicao: %s", e)
            return None

    if conteudo is None:
        return None

    reader = csv.DictReader(io.StringIO(conteudo), delimiter=",")
    if reader.fieldnames and len(reader.fieldnames) == 1 and ";" in reader.fieldnames[0]:
        logger.error("CSV esta separado por ponto-e-virgula; use virgulas.")
        return None

    cabecalho = [_normalizar(h) for h in (reader.fieldnames or [])]
    mapa_indices = _mapear_colunas(cabecalho, mapa_colunas)
    if coluna_obrigatoria and coluna_obrigatoria not in mapa_indices:
        logger.error("CSV sem coluna obrigatoria %s.", coluna_obrigatoria)
        return None

    resultado = []
    for row in reader:
        row_lower = {(_normalizar(k) if k else ""): (v or "") for k, v in row.items()}
        if all(str(v).strip() == "" for v in row_lower.values()):
            continue

        item = {}
        for campo, idx in mapa_indices.items():
            col_original = (reader.fieldnames or [])[idx] if idx < len(reader.fieldnames or []) else ""
            item[campo] = str(row.get(col_original, "") or "").strip()
        resultado.append(item)

    return resultado


def _mapear_colunas(cabecalho: list[str], mapa: dict) -> dict[str, int]:
    resultado = {}
    for campo, sinonimos in mapa.items():
        sinonimos_norm = [_normalizar(s) for s in sinonimos]
        for sin in sinonimos_norm:
            for i, h in enumerate(cabecalho):
                if h == sin or sin in h:
                    resultado[campo] = i
                    break
            if campo in resultado:
                break
    return resultado


def buscar_processo_ref(
    referencias: list[dict],
    competencia: str,
    camara_excluir: str = "",
    numero_processo: str = "",
) -> str:
    """Busca a referencia priorizando processo de origem e competencia (as
    duas usadas em conjunto: primeiro tenta casar pelo numero_processo E pela
    competencia ao mesmo tempo, so depois relaxa para competencia sozinha).

    Um processo nunca pode ser referencia de si mesmo: qualquer candidato cujo
    processo_ref seja o proprio numero_processo e descartado (ver _extrair_ref),
    e a busca segue para o proximo criterio/linha em vez de devolve-lo."""
    competencia_norm = _normalizar(competencia)
    numero_norm = _limpar_numero(numero_processo)

    def _competencia_ok(ref: dict) -> bool:
        if not competencia_norm:
            return True
        comp_ref = _normalizar(ref.get("competencia", ""))
        return competencia_norm in comp_ref or comp_ref in competencia_norm

    def _extrair_ref(ref: dict) -> str:
        candidato = str(ref.get("processo_ref", "") or "").strip()
        if numero_norm and candidato and _limpar_numero(candidato) == numero_norm:
            return ""
        return candidato

    if numero_norm:
        for ref in referencias:
            if _limpar_numero(ref.get("numero_processo", "")) != numero_norm:
                continue
            if _competencia_ok(ref):
                processo_ref = _extrair_ref(ref)
                if processo_ref:
                    return processo_ref

    for ref in referencias:
        if not _competencia_ok(ref):
            continue
        if camara_excluir:
            cam_ref = _extrair_camara(ref.get("magistrado_camara", ""))
            cam_excl = _extrair_camara(camara_excluir)
            if cam_ref and cam_excl and cam_ref == cam_excl:
                continue
        processo_ref = _extrair_ref(ref)
        if processo_ref:
            return processo_ref

    if numero_norm:
        for ref in referencias:
            if _limpar_numero(ref.get("numero_processo", "")) != numero_norm:
                continue
            processo_ref = _extrair_ref(ref)
            if processo_ref:
                logger.warning(
                    "processo_ref '%s' encontrado para '%s' mas competencias divergem "
                    "(esperada: '%s', ref: '%s'). Usando mesmo assim.",
                    processo_ref,
                    numero_processo,
                    competencia,
                    ref.get("competencia", ""),
                )
                return processo_ref
    return ""


def _extrair_camara(magistrado_camara: str) -> str:
    partes = [p.strip() for p in str(magistrado_camara).split(" - ")]
    for parte in partes:
        texto = _normalizar(parte)
        if "caciv" in texto or "camara" in texto:
            return texto.upper()
    return ""


def _limpar_numero(valor) -> str:
    texto = "" if valor is None else str(valor)
    return texto.replace(".", "").replace("-", "").replace("/", "").strip()


# ===========================================================================
# DATA — competência via Google Sheets (aba processos_ajuizados)
# ===========================================================================
def _buscar_mapa_competencias() -> dict[str, str]:
    """Lê a aba processos_ajuizados do Google Sheets (mesma base do AURA
    Principal e do AURA Gabinete) e monta {numero_processo_limpo: competencia}.

    Nunca lança exceção: se a planilha estiver inacessível (sem credenciais,
    sem internet, etc.), retorna um dicionário vazio e a redistribuição
    continua funcionando normalmente com o que já estiver nos CSVs.
    """
    mapa: dict[str, str] = {}
    try:
        for registro in aura_db.ler_processos_ajuizados():
            competencia = (registro.get("Competência") or registro.get("Competencia") or "").strip()
            processo = _limpar_numero(registro.get("Processo", ""))
            if processo and competencia:
                mapa[processo] = competencia
    except Exception as e:
        logger.warning("Nao foi possivel consultar competencias no Google Sheets: %s", e)
    return mapa


def enriquecer_competencia_via_sheets(linhas: list[dict]) -> int:
    """Preenche a coluna 'competencia' das linhas que vieram sem ela, buscando
    pelo numero_processo na aba processos_ajuizados do Google Sheets.

    Cobre qualquer competência presente na planilha (Direito Público, Direito
    Privado, etc.) — não é restrito a uma área específica. Retorna quantas
    linhas foram preenchidas.
    """
    pendentes = [
        linha for linha in linhas
        if not (linha.get("competencia") or "").strip() and (linha.get("numero_processo") or "").strip()
    ]
    if not pendentes:
        return 0

    mapa = _buscar_mapa_competencias()
    if not mapa:
        return 0

    preenchidas = 0
    for linha in pendentes:
        competencia = mapa.get(_limpar_numero(linha.get("numero_processo", "")))
        if competencia:
            linha["competencia"] = competencia
            preenchidas += 1
    return preenchidas


# ===========================================================================
# DATA — histórico de execuções
# ===========================================================================
_COLUNAS_HISTORICO = ["Data", "Classe", "Magistrado", "Processo", "Chave", "Aviso"]


def salvar_no_historico(dados: dict):
    caminho = ARQUIVO_HISTORICO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    file_exists = caminho.is_file()
    try:
        with open(caminho, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUNAS_HISTORICO)
            if not file_exists:
                writer.writeheader()
            writer.writerow(dados)
    except Exception as e:
        logger.error("Erro ao salvar histórico: %s", e)


def ler_historico() -> list[dict]:
    caminho = ARQUIVO_HISTORICO
    if not caminho.is_file():
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        logger.error("Erro ao ler histórico: %s", e)
        return []


# ===========================================================================
# DATA — relatório HTML do dia (inspirado no AURA GABINETE)
# ===========================================================================
def _caminho_relatorio_html() -> Path:
    """Um relatorio por dia, acumulando todas as execucoes."""
    return OUTPUT_DIR / f"relatorio_aura_cotri_{time.strftime('%Y%m%d')}.html"


def _inicializar_relatorio_html():
    """Cria o cabecalho do relatorio do dia, se ainda nao existir."""
    caminho = _caminho_relatorio_html()
    if caminho.exists():
        return
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<title>Relatório AURA COTRI</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#0f1117;color:#e6edf3;margin:20px;}}
h1{{color:#4f8ef7;}}
table{{border-collapse:collapse;width:100%;background:#161b22;box-shadow:0 1px 3px rgba(0,0,0,.4);border-radius:8px;overflow:hidden;}}
th{{background:#21262d;color:#8b949e;text-align:left;padding:10px;font-size:12px;text-transform:uppercase;letter-spacing:.5px;}}
td{{padding:9px 10px;border-bottom:1px solid #30363d;font-size:12px;vertical-align:top;}}
tr.ok td{{background:#0d1f12;}} tr.warn td{{background:#1f1a0d;}} tr.error td{{background:#1f0d0d;}}
.status{{font-weight:700;text-transform:uppercase;}}
.status.ok{{color:#2ea043;}} .status.warn{{color:#e3b341;}} .status.error{{color:#da3633;}}
.detalhe{{font-family:Consolas,monospace;font-size:11px;color:#8b949e;white-space:pre-wrap;}}
</style></head><body>
<h1>AURA COTRI — Relatório de Execução</h1>
<p style="color:#8b949e">Iniciado em {time.strftime('%d/%m/%Y %H:%M:%S')}</p>
<table><thead><tr>
<th style="width:90px">Hora</th>
<th style="width:180px">Processo</th>
<th style="width:240px">Ação</th>
<th style="width:80px">Status</th>
<th>Detalhe</th>
</tr></thead><tbody>
""")
    except Exception as e:
        logger.debug("Nao foi possivel inicializar o relatorio HTML: %s", e)


def registrar_relatorio_html(processo: str, acao: str, status: str, detalhe: str = ""):
    """Adiciona uma linha ao relatorio do dia. status: OK | WARN | ERROR."""
    _inicializar_relatorio_html()
    try:
        hora = time.strftime("%H:%M:%S")
        classe = (status or "ok").lower()
        det = (detalhe or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        linha = (f'<tr class="{classe}"><td>{hora}</td><td>{processo or "-"}</td>'
                 f'<td>{acao}</td><td class="status {classe}">{status}</td>'
                 f'<td class="detalhe">{det}</td></tr>\n')
        with open(_caminho_relatorio_html(), "a", encoding="utf-8") as f:
            f.write(linha)
    except Exception as e:
        logger.debug("Nao foi possivel registrar no relatorio HTML: %s", e)


def abrir_relatorio_html():
    """Abre o relatorio do dia no navegador/visualizador padrao."""
    caminho = _caminho_relatorio_html()
    _inicializar_relatorio_html()
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(caminho))  # Windows
        else:
            import webbrowser
            webbrowser.open(caminho.as_uri())
    except Exception as e:
        messagebox.showerror("Relatório", f"Não foi possível abrir o relatório:\n{e}")


# ===========================================================================
# IA — análise de erro via Groq (opcional)
# ===========================================================================
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def analisar_erro_com_ia(erro: str, contexto: str = "") -> str | None:
    if not GROQ_API_KEY:
        return None

    prompt = (
        "Você é um assistente técnico do sistema AURA COTRI, um robô de assinatura eletrônica do TJMG.\n"
        "O robô encontrou o seguinte erro durante o fluxo COTRI (assinatura via preferência PPG):\n"
        f"ERRO: {erro}\n"
        f"CONTEXTO: {contexto}\n"
        "Explique em português simples:\n"
        "1. O que causou esse erro\n"
        "2. O que o usuário pode fazer para resolver\n"
        "Seja direto e objetivo. Máximo 5 linhas."
    )
    dados = json.dumps({
        "model": "llama3-8b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
    }).encode("utf-8")

    req = urllib.request.Request(
        _GROQ_URL,
        data=dados,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resultado = json.loads(resp.read())
            return resultado["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("Análise de erro via IA falhou: %s", e)
        return None


# ===========================================================================
# AUTOMAÇÃO — driver e helpers do Selenium
# ===========================================================================
def criar_driver(timeout: int = 60):
    chrome_options = Options()
    chrome_options.add_experimental_option("detach", True)
    driver = criar_chrome_driver(chrome_options)
    wait = WebDriverWait(driver, timeout)
    actions = ActionChains(driver)
    return driver, wait, actions


def clicar_seguro(driver, wait, xpath):
    try:
        elemento = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", elemento)
    except Exception as e:
        logger.warning("clicar_seguro falhou em %s: %s", xpath, e)


def fechar_alerta_silencioso(driver, ultimo_aviso: list, tentativas: int = 5):
    """Aceita alertas do navegador, drenando ate `tentativas` empilhados.

    O eProc frequentemente exibe varios alertas em sequencia (confirm + aviso).
    Trata todos eles num unico passo, acumulando cada texto em `ultimo_aviso`.
    """
    for _ in range(tentativas):
        try:
            alert = driver.switch_to.alert
            msg = alert.text
            alert.accept()
            if msg:
                ultimo_aviso.append(msg)
            time.sleep(0.3)
        except Exception as e:
            logger.debug("Sem mais alertas para fechar: %s", e)
            break


def fechar_abas_extras(driver):
    try:
        while len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            driver.close()
        driver.switch_to.window(driver.window_handles[0])
    except Exception as e:
        logger.warning("fechar_abas_extras falhou: %s", e)


def verificar_pausa(state, status_widget):
    while state.pausado:
        status_widget.config(text="⏸ Pausado — clique em Retomar para continuar...")
        time.sleep(0.5)


def verificar_sessao_ativa(driver) -> bool:
    """Retorna False se a sessao do eProc caiu (URL de sessao expirada,
    tela de login ou navegador encerrado)."""
    if driver is None:
        return False
    try:
        url = driver.current_url
    except Exception as e:
        # "invalid session id" e afins: navegador fechado pelo usuario.
        logger.debug("Sessao do navegador indisponivel: %s", e)
        return False
    if RE_SESSAO_EXPIRADA.search(url):
        logger.warning("Sessao do eProc expirada detectada na URL.")
        return False
    if "externo_controlador.php" in url and "acao=principal" in url:
        logger.warning("Navegador voltou para a tela de login do eProc.")
        return False
    return True


# ===========================================================================
# AUTOMAÇÃO — diagnóstico de falhas (dump de tela)
# ===========================================================================
def _inventariar_campos_tela(driver, limite: int = 120) -> list:
    """Coleta campos/controles visiveis na tela atual para diagnostico."""
    if driver is None:
        return []
    script = """
    const limite = arguments[0] || 120;
    const seletores = [
        'input', 'select', 'textarea', 'button', 'a[href]',
        '[role="button"]', '[contenteditable="true"]'
    ];
    const vistos = new Set();
    const out = [];
    function texto(el) {
        return (el.innerText || el.textContent || el.value || el.title ||
                el.getAttribute('aria-label') || el.placeholder || '').trim()
                .replace(/\\s+/g, ' ').slice(0, 80);
    }
    function visivel(el) {
        const st = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return st && st.display !== 'none' && st.visibility !== 'hidden' &&
               r.width > 0 && r.height > 0;
    }
    document.querySelectorAll(seletores.join(',')).forEach((el) => {
        if (out.length >= limite || !visivel(el)) return;
        const id = el.id || '';
        const name = el.getAttribute('name') || '';
        const tipo = el.getAttribute('type') || '';
        const tag = el.tagName.toLowerCase();
        const key = [tag, id, name, tipo, texto(el)].join('|');
        if (vistos.has(key)) return;
        vistos.add(key);
        out.push({tag, id, name, type: tipo, text: texto(el),
                  classes: (el.className || '').toString().slice(0, 80)});
    });
    return out;
    """
    try:
        return driver.execute_script(script, limite) or []
    except Exception as e:
        logger.debug("Inventario de campos falhou: %s", e)
        return []


def _dump_diagnostico(driver, label: str, extra: str = "") -> str:
    """Salva HTML + screenshot + inventario da tela atual em ~/.aura_cotri/dumps.

    Usado quando uma linha falha, para acelerar a identificacao de mudancas de
    layout entre versoes do eProc. Retorna o basename gerado ou "" se falhar.
    Todas as etapas sao protegidas: um diagnostico nunca deve quebrar o fluxo.
    """
    if driver is None:
        return ""
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(str(PASTA_DUMPS), exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", label)[:40]
        base = f"dump_{ts}_{slug}"

        try:
            with open(os.path.join(str(PASTA_DUMPS), base + ".html"), "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        except Exception as e:
            logger.debug("Dump HTML falhou: %s", e)

        try:
            driver.save_screenshot(os.path.join(str(PASTA_DUMPS), base + ".png"))
        except Exception as e:
            logger.debug("Dump screenshot falhou: %s", e)

        info = [f"Label: {label}", f"Extra: {extra}", f"Data:  {ts}"]
        try:
            info.append(f"URL:   {driver.current_url}")
            info.append(f"Title: {driver.title}")
        except Exception:
            pass
        info.append("\n--- IFRAMES ---")
        try:
            for fr in driver.find_elements(By.TAG_NAME, "iframe"):
                info.append(f"  id={fr.get_attribute('id')!r} name={fr.get_attribute('name')!r}")
        except Exception:
            pass
        info.append("\n--- CAMPOS/CONTROLES VISIVEIS ---")
        for c in _inventariar_campos_tela(driver, limite=200):
            info.append(
                "  {tag} id={id!r} name={name!r} type={type!r} text={text!r}".format(
                    tag=c.get("tag", ""), id=c.get("id", ""), name=c.get("name", ""),
                    type=c.get("type", ""), text=c.get("text", ""),
                )
            )
        try:
            with open(os.path.join(str(PASTA_DUMPS), base + ".txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(info))
        except Exception as e:
            logger.debug("Dump TXT falhou: %s", e)

        logger.info("Dump de diagnostico salvo em dumps/%s.[html|png|txt]", base)
        return base
    except Exception as e:
        logger.debug("Falha ao salvar dump de diagnostico: %s", e)
        return ""


# ===========================================================================
# AUTOMAÇÃO — login e seleção de perfil
# ===========================================================================
def fazer_login(driver, wait, usuario, senha):
    wait.until(EC.presence_of_element_located((By.ID, "txtUsuario"))).send_keys(usuario)
    driver.find_element(By.ID, "pwdSenha").send_keys(senha)
    clicar_seguro(driver, wait, '//*[@id="sbmEntrar"]')
    time.sleep(2)


def selecionar_perfil(driver, perfil: str = "COAPUB", tentativas: int = 20, intervalo: float = 1.0) -> bool:
    """Seleciona, na tela "Seleção de perfil" (lista de <button
    class="list-group-item"> com onclick="acaoLogar('<id>')"), o perfil
    cujo texto (Descrição + Lotação) contém `perfil`.

    Retry em vez de uma única tentativa após sleep fixo: confirmado ao
    vivo (2026-08-16) que uma conta com MUITOS perfis (~86, depois de
    conceder uma lotação nova) pode levar mais que os 3s fixos que este
    código tinha antes pra terminar de renderizar a lista inteira --
    nesse caso as duas estratégias abaixo não achavam nada (lista ainda
    incompleta no DOM) e a função retornava False incorretamente, mesmo
    o perfil certo existindo e aparecendo pouco depois.

    Default "COAPUB": o antigo setor único "COTRI" foi dividido em
    COAPUB (Direito Público) e COAPRI (Direito Privado) -- confirmado
    pelo usuário em 2026-08-20, a tela de Seleção de Perfil não tem mais
    nenhum botão com o texto "COTRI"."""
    time.sleep(1)
    perfil = (perfil or "COAPUB").strip().upper()

    for _ in range(tentativas):
        if _tentar_por_data_descricao(driver, perfil):
            return True
        if _tentar_por_texto_visivel(driver, perfil):
            return True
        time.sleep(intervalo)
    return False


def selecionar_perfil_coapub(driver) -> bool:
    return selecionar_perfil(driver, "COAPUB")


def selecionar_perfil_coapri(driver) -> bool:
    return selecionar_perfil(driver, "COAPRI")


def trocar_perfil_via_combobox(driver, wait, texto_visivel_opcao, log=print) -> bool:
    """Troca o perfil/lotação ativo usando o combobox #selInfraUnidades --
    pra quando o usuário JÁ está logado e precisa mudar de perfil sem
    deslogar (ex: ir pra GERENTE DE USUÁRIOS buscar a sigla de outro
    usuário e depois voltar). Mesmo padrão já usado em
    run_aura_eventoscamaracivel.py e run_aura_sessao_julgamento.py --
    duplicado aqui de propósito (módulos deste projeto evitam import
    cruzado entre si, cada um fica autocontido)."""
    try:
        select_el = WebDriverWait(driver, 8).until(
            lambda d: next((e for e in d.find_elements(By.ID, "selInfraUnidades") if e.is_displayed()), False))
        Select(select_el).select_by_visible_text(texto_visivel_opcao)
        time.sleep(2)
        return True
    except Exception as exc:
        log(f"  [AVISO] Falha ao trocar perfil via combobox pra '{texto_visivel_opcao}': {exc}")
        return False


def buscar_sigla_magistrado_por_nome(driver, wait, nome_magistrado, log=print):
    """Busca a sigla de login de um magistrado pelo NOME, via 'Cadastro de
    Usuários' (perfil GERENTE DE USUÁRIOS) -- mesmo fluxo mapeado ao vivo
    em 27/08/2026 (Usuários > Cadastro de Usuários, campo 'Ou o Nome').
    Generaliza a busca fixa que só cobria os 3 magistrados de teste
    (SIGLAS_MAGISTRADOS_HOMOLOGACAO em aura_regressao_homologacao.py) --
    funciona pra QUALQUER magistrado, de qualquer câmara/vogal.

    Pressupõe `driver` já numa sessão logada com o perfil GERENTE DE
    USUÁRIOS disponível (ex: a mesma conta de teste COTRI/GABINETE que já
    tem esse perfil, como P0125581/RANYER SEGAL PONTES -- confirmado ao
    vivo em 27/08/2026). Troca pra esse perfil via combobox, faz a busca,
    e NÃO troca de volta pro perfil anterior -- decisão de o quê fazer
    depois fica com o chamador.

    NUNCA RODADO via Selenium ainda -- só feito manualmente via
    claude-in-chrome em 27/08/2026 (ver project_aura_sessao_julgamento na
    memória do projeto). Retorna a sigla (ex: 't0026716') ou None se não
    achar ninguém, ou se achar mais de uma sigla MAGISTRADO diferente
    pro mesmo nome (ambíguo -- melhor falhar alto do que logar como a
    pessoa errada)."""
    if not trocar_perfil_via_combobox(driver, wait, "GERENTE DE USUÁRIOS", log=log):
        log("  [ERRO] Não consegui trocar pro perfil GERENTE DE USUÁRIOS -- "
            "confira se a conta atual tem esse perfil disponível.")
        return None

    try:
        clicar_seguro(driver, wait, "//a[contains(normalize-space(.), 'Usuários')]")
        time.sleep(0.6)
        clicar_seguro(driver, wait, "//a[contains(normalize-space(.), 'Cadastro de Usuários')]")
        time.sleep(1.0)
    except Exception as exc:
        log(f"  [ERRO] Não consegui abrir 'Usuários > Cadastro de Usuários': {exc}")
        return None

    try:
        campo_nome = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input[id*='Nome' i]")))
    except Exception:
        log("  [ERRO] Campo 'Ou o Nome' não encontrado na tela de Cadastro de Usuários.")
        return None
    campo_nome.clear()
    campo_nome.send_keys(nome_magistrado)
    clicar_seguro(driver, wait, "//button[contains(., 'Consultar')] | //a[contains(., 'Consultar')]")
    time.sleep(1.2)

    siglas_magistrado = set()
    for linha in driver.find_elements(By.CSS_SELECTOR, "table tr"):
        texto = linha.text or ""
        if "MAGISTRADO" not in texto.upper():
            continue
        celulas = linha.find_elements(By.TAG_NAME, "td")
        if celulas:
            sigla = (celulas[0].text or "").strip()
            if sigla:
                siglas_magistrado.add(sigla)

    if len(siglas_magistrado) == 1:
        sigla = next(iter(siglas_magistrado))
        log(f"  [OK] Sigla encontrada pra '{nome_magistrado}': {sigla}")
        return sigla
    if len(siglas_magistrado) > 1:
        log(f"  [ERRO] Mais de uma sigla MAGISTRADO encontrada pra '{nome_magistrado}': "
            f"{sorted(siglas_magistrado)} -- ambíguo, não decido sozinho.")
        return None
    log(f"  [ERRO] Nenhum registro MAGISTRADO encontrado pra '{nome_magistrado}'.")
    return None


def _tentar_por_data_descricao(driver, perfil: str) -> bool:
    try:
        botoes = driver.find_elements(By.XPATH, "//button[@data-descricao]")
        botoes = [
            b
            for b in botoes
            if _perfil_compativel(b.get_attribute("data-descricao") or "", perfil)
        ]
        botoes.sort(key=lambda b: _prioridade_perfil(b.get_attribute("data-descricao") or ""), reverse=True)
        if botoes:
            _clicar_botao_perfil(driver, botoes[0])
            time.sleep(5)
            return True
    except Exception as e:
        logger.warning("Selecao de perfil por data-descricao falhou: %s", e)
    return False


def _tentar_por_texto_visivel(driver, perfil: str) -> bool:
    try:
        botoes = driver.find_elements(
            By.XPATH,
            '//button[contains(@class, "list-group-item")]',
        )
        botoes = [b for b in botoes if _perfil_compativel(b.text or "", perfil)]
        botoes.sort(key=lambda b: _prioridade_perfil(b.text or ""), reverse=True)
        if botoes:
            _clicar_botao_perfil(driver, botoes[0])
            time.sleep(5)
            return True
    except Exception as e:
        logger.warning("Selecao de perfil por texto visivel falhou: %s", e)
    return False


def _clicar_botao_perfil(driver, botao):
    onclick_attr = botao.get_attribute("onclick") or ""
    match = re.search(r"acaoLogar\(['\"](\d+)['\"]\)", onclick_attr)
    if match:
        driver.execute_script(f"acaoLogar('{match.group(1)}');")
    else:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", botao)


def _perfil_compativel(texto: str, perfil: str) -> bool:
    normalizado = _normalizar(texto)
    perfil_normalizado = _normalizar(perfil)
    return perfil_normalizado in normalizado


def _prioridade_perfil(texto: str) -> int:
    normalizado = _normalizar(texto)
    prioridade = 0
    if "distribuicao" in normalizado:
        prioridade += 1
    if "diretor distribuicao" in normalizado:
        prioridade += 2
    return prioridade


# ===========================================================================
# AUTOMAÇÃO — pesquisa de processo
# ===========================================================================
_IDS_PESQUISA = [
    "txtNumProcessoPesquisaRapida",
    "txtPesquisaRapida",
    "numProcessoPesquisa",
    "txtNumProcesso",
]


def _ler_competencia_da_capa(driver) -> str:
    """Lê a competência atual do processo exibida na capa (#txtCompetencia).

    Fonte confiável e universal (funciona para qualquer processo, mesmo que
    nunca tenha passado pelo AURA Principal). Nunca lança exceção — se o
    campo não existir na tela, retorna string vazia.
    """
    try:
        return driver.find_element(By.ID, "txtCompetencia").text.strip()
    except Exception:
        return ""


def ler_orgao_julgador_da_capa(driver) -> str:
    """Lê o órgão julgador atual do processo exibido na capa
    (#txtOrgaoJulgador, ex: "19ª CACIV - Assento 1"). Fonte confiável e
    universal — funciona pra qualquer câmara/assento, sem precisar fixar
    um órgão específico no código. Nunca lança exceção — se o campo não
    existir na tela, retorna string vazia."""
    try:
        return driver.find_element(By.ID, "txtOrgaoJulgador").text.strip()
    except Exception:
        return ""


def pesquisar_processo(driver, url, num_processo):
    _abrir_consulta_processo(driver)
    campo = _encontrar_campo(driver)
    if campo:
        _pesquisar_via_campo(driver, campo, num_processo)
    else:
        base = url.rstrip("/")
        driver.get(
            f"{base}/controlador.php"
            f"?acao=processo_consultar_pesquisa_rapida&txtNumProcesso={num_processo}"
        )
        _aguardar_resultado_pesquisa(driver, num_processo)


def _abrir_consulta_processo(driver):
    """Abre a funcionalidade 'Consultar Processo', quando ela estiver recolhida."""
    if _encontrar_campo(driver):
        return

    try:
        elemento = WebDriverWait(driver, 1.5).until(
            EC.element_to_be_clickable((By.LINK_TEXT, "Consultar o Processo"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
        time.sleep(0.1)
        driver.execute_script("arguments[0].click();", elemento)
        WebDriverWait(driver, 2).until(lambda d: _encontrar_campo(d))
    except Exception as e:
        logger.debug("Atalho Consultar o Processo nao abriu: %s", e)


def _encontrar_campo(driver):
    for id_campo in _IDS_PESQUISA:
        try:
            elementos = driver.find_elements(By.ID, id_campo)
            if elementos:
                return elementos[0]
        except Exception as e:
            logger.debug("Campo %s não encontrado: %s", id_campo, e)
    return None


def _pesquisar_via_campo(driver, campo, num_processo):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo)
        time.sleep(0.1)
        driver.execute_script("arguments[0].focus();", campo)
        time.sleep(0.1)
        driver.execute_script("arguments[0].value = '';", campo)
        campo.send_keys(num_processo)
        time.sleep(0.2)

        # Clica explicitamente no botão "mesma janela" para evitar abrir nova aba
        try:
            btn = driver.find_element(By.NAME, "btnPesquisaRapidaSubmit")
            driver.execute_script("arguments[0].click();", btn)
        except Exception:
            campo.send_keys(Keys.RETURN)

        _aguardar_resultado_pesquisa(driver, num_processo)
    except Exception as e:
        logger.warning("Pesquisa via campo falhou, tentando JS: %s", e)
        driver.execute_script("arguments[0].value = arguments[1];", campo, num_processo)
        driver.execute_script(
            "var f = arguments[0].closest('form'); if(f) f.submit();",
            campo,
        )
        _aguardar_resultado_pesquisa(driver, num_processo)


def _aguardar_resultado_pesquisa(driver, num_processo):
    numero_limpo = num_processo.replace(".", "").replace("-", "")
    try:
        WebDriverWait(driver, 8).until(
            lambda d: (
                "processo_selecionar" in d.current_url
                or "acao=processo_selecionar" in d.current_url
                or num_processo in d.page_source
                or numero_limpo in d.page_source
                or d.find_elements(By.XPATH, "//a[contains(@href, 'acao=redistribuicao_processo')]")
            )
        )
    except Exception as e:
        logger.debug("Resultado da pesquisa nao confirmou carregamento: %s", e)


# ===========================================================================
# AUTOMAÇÃO — movimentação
# ===========================================================================
def executar_movimentacao(driver, wait, status, num_fila):
    """Após a assinatura, executa o procedimento de movimentação:
    1. Abre o painel 'Preferências de movimentação'
    2. Clica em 'Ações Preferenciais'
    """
    _clicar_preferencias_movimentacao(driver, wait, status, num_fila)
    _clicar_acoes_preferenciais(driver, wait, status, num_fila)


def _clicar_preferencias_movimentacao(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Abrindo preferências de movimentação...")
    try:
        btn = wait.until(EC.element_to_be_clickable((By.ID, "btn-preferencias-movimentacao")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", btn)
        # Aguarda o painel collapse abrir (aria-expanded passa para "true")
        WebDriverWait(driver, 10).until(
            lambda d: d.find_element(By.ID, "btn-preferencias-movimentacao")
                       .get_attribute("aria-expanded") == "true"
        )
        time.sleep(1)
    except Exception as e:
        logger.warning("Preferências de movimentação não encontrado: %s", e)
        raise Exception(
            "Não foi possível abrir 'Preferências de movimentação'. "
            "Verifique se o processo retornou corretamente após a assinatura."
        )


def _clicar_acoes_preferenciais(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Clicando em 'Ações Preferenciais'...")
    try:
        # Link com href="#/" e data-toggle="dropdown" contendo img title="Ações Preferenciais"
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//a[@href='#/' and @data-toggle='dropdown'][.//img[@title='Ações Preferenciais']]"
        )))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
    except Exception as e:
        logger.warning("Ações Preferenciais não encontrado: %s", e)
        raise Exception(
            "Não foi possível clicar em 'Ações Preferenciais'. "
            "Verifique se o painel de movimentação abriu corretamente."
        )


def preencher_evento_movimentar(driver, wait, evento: str, campo_id: str = "txtEvento") -> str:
    """Preenche o campo de evento (autocomplete) na tela de Movimentação
    Processual e seleciona a sugestão cujo texto melhor corresponde ao
    evento informado. Mesma técnica usada em
    integrations/auragabinete.py (_preencher_autocomplete), adaptada ao
    estilo de função livre deste arquivo.
    """
    campo = wait.until(EC.presence_of_element_located((By.ID, campo_id)))
    campo.click()
    campo.clear()
    for ch in evento:
        campo.send_keys(ch)
        time.sleep(0.04)
    time.sleep(2.5)

    try:
        container = driver.find_element(By.ID, f"divInfraAjax{campo_id}")
        alvo_norm = _normalizar(evento)
        for item in container.find_elements(By.TAG_NAME, "li"):
            texto = (item.text or "").strip()
            if texto and alvo_norm in _normalizar(texto):
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", item)
                time.sleep(0.2)
                try:
                    # .click() nativo dispara mousedown/mouseup de verdade --
                    # o widget de autocomplete do eproc seleciona no mousedown
                    # (para disparar antes do blur fechar a lista). Um clique
                    # via execute_script só gera um evento 'click' sintético e
                    # NÃO registra a seleção (hdnEvento fica vazio).
                    item.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", item)
                time.sleep(1)
                return texto
    except Exception as e:
        logger.warning("Sugestao de evento (AJAX) nao encontrada para '%s': %s", evento, e)

    # Fallback: seta + enter (pega o primeiro item da lista nativa do navegador)
    campo.send_keys(Keys.ARROW_DOWN)
    time.sleep(0.4)
    campo.send_keys(Keys.RETURN)
    time.sleep(1)
    return ""


def clicar_movimentar(driver, wait):
    """Clica no botão final 'Movimentar' (submit) da tela de Movimentação
    Processual. Há dois botões com o mesmo id 'sbmMovimentar' (topo e
    rodapé do formulário) mais um terceiro para 'Movimentação Sucessiva'
    -- filtra pelo texto exato "Movimentar"."""
    botoes = driver.find_elements(By.ID, "sbmMovimentar")
    alvo = next((b for b in botoes if (b.text or "").strip() == "Movimentar"), None)
    if alvo is None:
        raise Exception("Botao 'Movimentar' (submit) nao encontrado na tela de movimentacao.")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", alvo)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", alvo)


def executar_movimentar_com_evento(driver, wait, status, num_fila, evento: str, submeter: bool = True) -> str:
    """Abre 'Movimentar Processo' a partir da capa (processo já deve estar
    carregado via pesquisar_processo), preenche o evento informado e,
    opcionalmente, submete a movimentação. Retorna o texto do evento
    efetivamente selecionado (string vazia se o fallback seta+enter foi
    usado, já que nesse caso não sabemos o texto exato escolhido)."""
    status.config(text=f"L{num_fila}: Abrindo Movimentar Processo...")
    link = driver.find_element(By.XPATH, "//a[contains(., 'Movimentar Processo')]")
    driver.execute_script("arguments[0].click();", link)
    time.sleep(3)

    status.config(text=f"L{num_fila}: Preenchendo evento '{evento}'...")
    texto_selecionado = preencher_evento_movimentar(driver, wait, evento)

    if submeter:
        status.config(text=f"L{num_fila}: Submetendo movimentação...")
        clicar_movimentar(driver, wait)
        time.sleep(2)
        fechar_alerta_silencioso(driver, [])

    return texto_selecionado


# ===========================================================================
# AUTOMAÇÃO — preferência de minuta (PPG / CODIPRE)
# ===========================================================================
PREFERENCIAS_POR_PERFIL = {
    "COTRI": {
        "nome": "Prevenção por Afinidade - PPG",
        "termos": ("prevencao por afinidade", "ppg"),
        "id_form": ID_FORM_PERSONALIZACAO_PPG,
    },
    "CODIPRE": {
        "nome": "Competência de Direito Privado",
        "termos": ("competencia de direito privado",),
        "id_form": ID_FORM_PERSONALIZACAO_CODIPRE_PRIVADO,
    },
}


def localizar_link_preferencia(driver, perfil="COTRI"):
    perfil_norm = (perfil or "COTRI").strip().upper()
    preferencia = PREFERENCIAS_POR_PERFIL.get(perfil_norm, PREFERENCIAS_POR_PERFIL["COTRI"])

    # No eProc, o link da preferência fica dentro de um painel recolhido
    # (#div-preferencia-minuta). É preciso clicar em "Preferências" para
    # expandi-lo e garantir que as preferências da unidade estejam visíveis
    # antes de procurar o link.
    abrir_painel_preferencias(driver)

    # Tenta localizar com algumas repetições, pois o painel renderiza os
    # links de forma assíncrona após expandir.
    for tentativa in range(6):
        link = _localizar_link(driver, preferencia)
        if link is not None:
            return link
        time.sleep(0.8)
    return None


def abrir_painel_preferencias(driver):
    """Expande o painel 'Preferências de minutas' e garante que os switches
    de exibição (sempre aberto + preferências da unidade) estejam ligados,
    de modo que o link da preferência apareça no DOM."""

    # 1) Clica no botão "Preferências" se o painel ainda estiver recolhido.
    try:
        botoes = driver.find_elements(By.ID, "btn-preferencias-minutas")
        if botoes:
            botao = botoes[0]
            recolhido = (
                "collapsed" in (botao.get_attribute("class") or "")
                or (botao.get_attribute("aria-expanded") or "").lower() != "true"
            )
            if recolhido:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", botao)
                # Aguarda o painel expandir
                try:
                    WebDriverWait(driver, 4).until(
                        EC.visibility_of_element_located((By.ID, "div-preferencia-minuta"))
                    )
                except Exception:
                    time.sleep(1)
    except Exception as e:
        logger.warning("Não foi possível expandir o painel de preferências: %s", e)

    # 2) Garante que os switches de exibição estejam marcados, especialmente
    #    o de "preferências da unidade" — sem ele o link pode não aparecer.
    for switch_id in ("switch-preferencia-minuta-collapse", "switch-preferencia-minuta-unidade"):
        try:
            switches = driver.find_elements(By.ID, switch_id)
            if switches and not switches[0].is_selected():
                driver.execute_script("arguments[0].click();", switches[0])
                time.sleep(0.5)
        except Exception as e:
            logger.debug("Switch %s não pôde ser ajustado: %s", switch_id, e)


def localizar_link_ppg(driver):
    return localizar_link_preferencia(driver, "COTRI")


def nome_preferencia_perfil(perfil="COTRI"):
    perfil_norm = (perfil or "COTRI").strip().upper()
    return PREFERENCIAS_POR_PERFIL.get(perfil_norm, PREFERENCIAS_POR_PERFIL["COTRI"])["nome"]


def _localizar_link(driver, preferencia):
    termos = preferencia["termos"]
    id_form = preferencia["id_form"]

    try:
        links = driver.find_elements(By.CSS_SELECTOR, "a.content-link.text-primary")
        for link in links:
            texto = _normalizar(link.text or "")
            if all(termo in texto for termo in termos):
                return link
    except Exception as e:
        logger.warning("Estrategia 1 preferencia (classe CSS) falhou: %s", e)

    try:
        return driver.find_element(
            By.XPATH,
            f"//a[contains(@href, 'num_id_form_personalizacao={id_form}')]",
        )
    except Exception as e:
        logger.warning("Estrategia 2 preferencia (ID form) falhou: %s", e)

    try:
        links = driver.find_elements(By.XPATH, "//a")
        for link in links:
            texto = _normalizar(link.text or "")
            if all(termo in texto for termo in termos):
                return link
    except Exception as e:
        logger.warning("Estrategia 3 preferencia (texto generico) falhou: %s", e)

    return None


# ===========================================================================
# AUTOMAÇÃO — distribuição via preferência de minuta da unidade (Passo 1 v2)
# ===========================================================================
# Descoberto e validado ao vivo em homologação (2026-08-16): substitui o
# caminho por "Movimentar Processo" (executar_movimentar_com_evento) quando
# existe uma preferência de minuta cadastrada na unidade pra competência do
# processo. Diferença: aqui o evento é agendado DENTRO da minuta e disparado
# junto com a assinatura (executar_assinatura), num fluxo só -- combina
# minuta + evento + assinatura, com documento anexado de verdade.
_STOPWORDS_PREFERENCIA_UNIDADE = frozenset({"do", "da", "de", "dos", "das", "e", "a", "o"})


def _termos_significativos(texto: str) -> list[str]:
    """Palavras normalizadas de `texto`, sem conectivos (do/da/de/...).
    Usado pra casar preferências de unidade por CONTEÚDO, não por texto
    exato -- o eproc não é consistente no nome entre órgãos/sessões (ex:
    "Competência Direito Público" x "Competência do Direito Público",
    achado ao vivo em 2026-08-20 -- um substring exato falhava porque o
    "do" extra quebra a contiguidade)."""
    return [p for p in _normalizar(texto).split() if p not in _STOPWORDS_PREFERENCIA_UNIDADE]


def localizar_link_preferencia_unidade(driver, termo_busca: str):
    """Acha o link de uma preferência de minuta da UNIDADE (diferente de
    PPG/CODIPRE em PREFERENCIAS_POR_PERFIL) pelo texto visível (ex:
    "Competência Direito Público"). Reaproveita abrir_painel_preferencias
    (garante o toggle 'Mostrar preferências da unidade' ligado) -- a
    estratégia de busca aqui é por PALAVRAS significativas (todas
    precisam aparecer no texto do link, em qualquer ordem, ignorando
    conectivos), não substring exato -- ver _termos_significativos."""
    abrir_painel_preferencias(driver)
    alvo_termos = _termos_significativos(termo_busca)
    for tentativa in range(6):
        try:
            links = driver.find_elements(By.CSS_SELECTOR, "a.content-link.text-primary")
            for link in links:
                texto_norm = _normalizar(link.text or "")
                if alvo_termos and all(termo in texto_norm for termo in alvo_termos):
                    return link
        except Exception as e:
            logger.debug("Busca de link de preferência (tentativa %s) falhou: %s", tentativa, e)
        time.sleep(0.8)
    return None


def marcar_evento_agendamento(driver, wait):
    """Marca o checkbox 'Agendar lançamento de evento/troca do localizador'
    (chkEventoAgendamento) na tela Nova Minuta -- vem DESMARCADO por padrão
    quando aberta a partir de uma preferência de unidade."""
    chk = wait.until(EC.presence_of_element_located((By.ID, "chkEventoAgendamento")))
    if not chk.is_selected():
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", chk)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", chk)
        time.sleep(1)


def selecionar_orgao_nova_minuta(driver, wait, orgao_texto: str) -> str:
    """Seleciona o <select id="selOrgao"> (nativo, ~270 opções -- todos os
    órgãos do tribunal) que aparece depois de marcar_evento_agendamento.

    `orgao_texto` casa por SUBSTRING normalizada contra o texto de cada
    opção, o que aceita tanto a sigla curta (ex: "19CACIV-A1", prefixo da
    opção) quanto o texto de exibição da capa lido por
    ler_orgao_julgador_da_capa (ex: "19ª CACIV - Assento 1", sufixo da
    opção "19CACIV-A1 - 19ª CACIV - Assento 1") -- não precisa converter
    entre os dois formatos. NÃO usar a primeira opção ("Devolver/remeter
    para o órgão julgador do processo.") -- é um valor genérico, não o
    órgão explícito que o processo precisa. Retorna o texto completo da
    opção escolhida."""
    sel_el = wait.until(EC.presence_of_element_located((By.ID, "selOrgao")))
    select = Select(sel_el)
    alvo_norm = _normalizar(orgao_texto)
    for opcao in select.options:
        if alvo_norm in _normalizar(opcao.text):
            select.select_by_visible_text(opcao.text)
            return opcao.text
    raise Exception(f"Órgão '{orgao_texto}' não encontrado no select selOrgao.")


def distribuir_com_preferencia_unidade(
    driver, wait, num_processo, url, senha, ultimo_aviso, status, num_fila,
    termo_preferencia: str, evento: str, orgao_destino: str | None = None,
):
    """Passo 1 v2 completo: pesquisa o processo, abre a preferência de
    minuta da unidade indicada, agenda o evento + órgão de destino, e
    assina (o que dispara o evento agendado). Ver comentário da seção
    acima para o porquê desse caminho substituir o antigo Movimentar
    Processo.

    `orgao_destino=None` (padrão) lê o órgão julgador ATUAL do processo
    direto da capa (ler_orgao_julgador_da_capa) -- funciona pra qualquer
    câmara/assento, sem precisar fixar um órgão específico no código.
    Só passe `orgao_destino` explicitamente se o destino da distribuição
    for diferente do órgão julgador atual do processo."""
    status.config(text=f"L{num_fila}: Pesquisando processo {num_processo}...")
    pesquisar_processo(driver, url, num_processo)

    if not orgao_destino:
        orgao_destino = ler_orgao_julgador_da_capa(driver)
        if not orgao_destino:
            raise Exception(
                "Não foi possível ler o órgão julgador atual da capa do processo "
                "(#txtOrgaoJulgador) -- informe orgao_destino explicitamente."
            )

    status.config(text=f"L{num_fila}: Localizando preferência '{termo_preferencia}'...")
    link = localizar_link_preferencia_unidade(driver, termo_preferencia)
    if link is None:
        raise Exception(
            f"Preferência de minuta '{termo_preferencia}' não encontrada na unidade. "
            "Verifique se ela está cadastrada para o órgão/perfil atual "
            "(ícone de configurações ao lado do título 'Minutas' na capa -> "
            "'Mostrar preferências da unidade')."
        )

    # O link tem onclick="window.open(this.href,'_blank')" -- usar driver.get()
    # com o href navegaria na MESMA aba, deixando o eproc preso na tela
    # pós-assinatura sem o cabeçalho normal (sem #selInfraUnidades), o que
    # quebra a troca de perfil do Passo 2 logo em seguida. Precisa ser um
    # clique real (sintético via JS não dispara o window.open, é bloqueado
    # pelo Chrome) para abrir numa aba nova de verdade, igual ao padrão já
    # usado nas preferências PPG/CODIPRE.
    janela_principal = driver.current_window_handle
    janelas_antes = set(driver.window_handles)
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
    time.sleep(0.3)
    try:
        link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", link)

    nova_janela = None
    for _ in range(10):
        extras = set(driver.window_handles) - janelas_antes
        if extras:
            nova_janela = extras.pop()
            break
        time.sleep(0.5)
    if nova_janela:
        driver.switch_to.window(nova_janela)
    time.sleep(1)
    wait.until(EC.url_contains("minuta_cadastrar"))

    status.config(text=f"L{num_fila}: Agendando evento '{evento}'...")
    marcar_evento_agendamento(driver, wait)
    preencher_evento_movimentar(driver, wait, evento)

    status.config(text=f"L{num_fila}: Selecionando órgão de destino '{orgao_destino}'...")
    selecionar_orgao_nova_minuta(driver, wait, orgao_destino)

    executar_assinatura(driver, wait, senha, ultimo_aviso, status, num_fila)

    # A assinatura pode fechar a aba nova sozinha (comportamento observado
    # ao vivo) ou deixar o eproc numa tela de confirmação sem o cabeçalho
    # completo -- garante voltar pra `janela_principal` (capa/menu com
    # #selInfraUnidades) antes de retornar, já que o Passo 2 depende disso
    # logo em seguida.
    if janela_principal in driver.window_handles:
        for h in driver.window_handles:
            if h != janela_principal:
                driver.switch_to.window(h)
                driver.close()
        driver.switch_to.window(janela_principal)
    else:
        driver.switch_to.window(driver.window_handles[0])
    return orgao_destino


# ===========================================================================
# AUTOMAÇÃO — assinatura da minuta
# ===========================================================================
def executar_assinatura(driver, wait, senha, ultimo_aviso, status, num_fila):
    _salvar_e_editar(driver, wait, status, num_fila)
    fechar_alerta_silencioso(driver, ultimo_aviso)

    _assinar_no_editor(driver, wait, status, num_fila)
    fechar_alerta_silencioso(driver, ultimo_aviso)

    _inserir_senha_e_confirmar(driver, wait, senha, status, num_fila)
    fechar_alerta_silencioso(driver, ultimo_aviso)

    # NÃO clicar em "Salvar e Sair" após assinar com senha.
    # A assinatura com senha é o ato final no editor — a minuta é consumida
    # pelo sistema nesse momento e deixa de ser rascunho. Qualquer tentativa
    # de "Salvar e Sair" depois disso causa o erro do eProc:
    # "Nenhuma minuta encontrada".
    # A navegação de retorno ao processo é gerenciada pelo fluxo de assinatura.


def _salvar_e_editar(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Clicando em 'Salvar e Editar'...")
    btn = wait.until(EC.presence_of_element_located((By.NAME, "sbmCadastrarEditarMinuta")))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(6)


def _assinar_no_editor(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Clicando em 'Assinar' no editor...")

    # Classe correta do <a> do botão Assinar no CKEditor.
    # Nota: "cke_button__minuta_assinar2" é a classe do <span> do ícone interno,
    # não do <a> clicável — o botão em si tem class="cke_button__assinar".
    btn = wait.until(EC.presence_of_element_located((
        By.CSS_SELECTOR, "a.cke_button__assinar"
    )))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(5)

    # Aguarda o iframe do modal de assinatura (ifrSubFrm) aparecer na página
    wait.until(EC.presence_of_element_located((By.ID, "ifrSubFrm")))


def _inserir_senha_e_confirmar(driver, wait, senha, status, num_fila):
    # A página "Assinar Minuta" é carregada dentro do iframe ifrSubFrm
    # (div#divInfraAvisoFundo). É preciso entrar no frame antes de interagir
    # com txtSenha e sbmAssinarComSenha.
    status.config(text=f"L{num_fila}: Inserindo senha para assinatura...")

    iframe = wait.until(EC.presence_of_element_located((By.ID, "ifrSubFrm")))
    driver.switch_to.frame(iframe)

    try:
        # O campo tem id="txtSenha", type="text" e class="masked" — um JS de
        # mascaramento sincroniza o valor com o campo oculto type="password".
        # Tentamos várias estratégias para garantir que o valor seja aceito.
        campo_senha = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "txtSenha"))
        )

        _preencher_senha(driver, campo_senha, senha, status, num_fila)

        status.config(text=f"L{num_fila}: Assinando com senha...")
        btn_assinar = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "sbmAssinarComSenha"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn_assinar)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", btn_assinar)

        # Aguarda o modal fechar (ifrSubFrm some do DOM) como confirmação de
        # que o peticionamento foi concluído — timeout de 30s
        _aguardar_conclusao_assinatura(driver, status, num_fila)

    finally:
        # Retorna ao documento principal independentemente de sucesso ou erro.
        # A aba da minuta costuma fechar sozinha logo após assinar (confirmado
        # ao vivo: "a aba do editor fechou sozinha, indicando sucesso") -- se
        # isso já aconteceu, driver está preso numa janela que não existe mais
        # e switch_to.default_content() levanta NoSuchWindowException. Como é
        # só um "voltar pro estado seguro" best-effort (quem chama já garante
        # voltar pra janela principal depois), engolir o erro aqui em vez de
        # deixar mascarar o resultado real do passo.
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def _preencher_senha(driver, campo, senha, status, num_fila):
    """Tenta inserir a senha no campo masked com múltiplas estratégias."""

    # Estratégia 1: send_keys direto após limpar com clear()
    try:
        status.config(text=f"L{num_fila}: Inserindo senha (tentativa 1)...")
        campo.clear()
        campo.send_keys(senha)
        time.sleep(0.5)
        if _senha_preenchida(driver, campo, senha):
            return
    except Exception as e:
        logger.debug("Senha estratégia 1 falhou: %s", e)

    # Estratégia 2: seleciona tudo com Ctrl+A, apaga e digita
    try:
        status.config(text=f"L{num_fila}: Inserindo senha (tentativa 2)...")
        campo.click()
        time.sleep(0.3)
        campo.send_keys(Keys.CONTROL + "a")
        campo.send_keys(Keys.DELETE)
        time.sleep(0.3)
        campo.send_keys(senha)
        time.sleep(0.5)
        if _senha_preenchida(driver, campo, senha):
            return
    except Exception as e:
        logger.debug("Senha estratégia 2 falhou: %s", e)

    # Estratégia 3: define o valor via JS no campo visível e dispara eventos
    try:
        status.config(text=f"L{num_fila}: Inserindo senha (tentativa 3)...")
        driver.execute_script("""
            var el = arguments[0];
            var val = arguments[1];
            el.focus();
            el.value = val;
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
        """, campo, senha)
        time.sleep(0.5)
        if _senha_preenchida(driver, campo, senha):
            return
    except Exception as e:
        logger.debug("Senha estratégia 3 falhou: %s", e)

    # Estratégia 4: define o valor diretamente no campo oculto type="password"
    # (name="txtSenha", sem id) que é o que o formulário envia
    try:
        status.config(text=f"L{num_fila}: Inserindo senha (tentativa 4)...")
        driver.execute_script("""
            var inputs = document.querySelectorAll('input[name="txtSenha"]');
            for (var i = 0; i < inputs.length; i++) {
                inputs[i].value = arguments[0];
                inputs[i].dispatchEvent(new Event('input',  {bubbles: true}));
                inputs[i].dispatchEvent(new Event('change', {bubbles: true}));
            }
        """, senha)
        time.sleep(0.5)
        logger.debug("Senha inserida via campo oculto (estratégia 4)")
        return
    except Exception as e:
        logger.debug("Senha estratégia 4 falhou: %s", e)

    # Estratégia 5: ActionChains — clica no campo e digita caractere a caractere
    try:
        status.config(text=f"L{num_fila}: Inserindo senha (tentativa 5)...")
        driver.execute_script("arguments[0].value = '';", campo)
        time.sleep(0.2)
        ActionChains(driver).click(campo).send_keys(senha).perform()
        time.sleep(0.5)
        if _senha_preenchida(driver, campo, senha):
            return
    except Exception as e:
        logger.debug("Senha estratégia 5 falhou: %s", e)

    logger.warning("Todas as estratégias de preenchimento da senha foram tentadas.")


def _senha_preenchida(driver, campo, senha):
    """Verifica se o campo visível ou o oculto tem o valor esperado."""
    try:
        visivel = driver.execute_script("return arguments[0].value;", campo)
        if visivel == senha:
            return True
        # Verifica também o campo oculto type="password"
        oculto = driver.execute_script(
            "var el = document.querySelector('input[type=\"password\"][name=\"txtSenha\"]');"
            "return el ? el.value : '';"
        )
        return oculto == senha
    except Exception:
        return False


def _aguardar_conclusao_assinatura(driver, status, num_fila):
    """Aguarda o fechamento do modal ifrSubFrm como sinal de que a assinatura
    foi concluída. Faz polling no documento principal."""
    status.config(text=f"L{num_fila}: Aguardando conclusão da assinatura...")
    # Sai do iframe para poder verificar o DOM principal
    driver.switch_to.default_content()
    try:
        # Aguarda o ifrSubFrm desaparecer (invisível ou removido)
        WebDriverWait(driver, 30).until(
            lambda d: not d.find_elements(By.ID, "ifrSubFrm") or
                      not d.find_element(By.ID, "ifrSubFrm").is_displayed()
        )
        logger.debug("Modal ifrSubFrm fechou — assinatura concluída.")
    except Exception:
        # Se o modal não fechar em 30s, continua mesmo assim
        logger.warning("Timeout aguardando fechamento do modal — continuando.")
        time.sleep(4)
    # Volta ao iframe para que o finally em _inserir_senha_e_confirmar
    # faça o default_content() corretamente (sem erro duplo)
    try:
        iframe = driver.find_element(By.ID, "ifrSubFrm")
        driver.switch_to.frame(iframe)
    except Exception:
        pass  # Modal já fechou, sem problema


def _salvar_e_sair(driver, status, num_fila):
    status.config(text=f"L{num_fila}: Salvando e saindo do editor...")
    try:
        # Classe correta do botão Salvar e Sair.
        # Nota: "cke_button__salvaresair" é só a classe do ícone interno;
        # o <a> clicável tem class="cke_button__salvarminutaesair".
        btn = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, "a.cke_button__salvarminutaesair"
            ))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(4)
    except Exception as e:
        logger.debug("Botão salvar-e-sair não encontrado (sistema já saiu): %s", e)


# ===========================================================================
# AUTOMAÇÃO — redistribuição
# ===========================================================================
# Arquivo onde fica a "impressao digital" de referencia da estrutura da pagina
_ARQUIVO_ESTRUTURA = os.path.join(str(OUTPUT_DIR), "estrutura_redistribuicao.json")
_ARQUIVO_ESTRUTURA_ATUAL = os.path.join(str(OUTPUT_DIR), "estrutura_redistribuicao_atual.txt")

# Hash SHA-256 da estrutura do formulario de redistribuicao calculado a partir
# do codigo-fonte da pagina eProc TJMG v9.20.0 (referencia fixa).
# Se o hash da pagina atual divergir deste, o robo avisa o usuario.
_HASH_REFERENCIA = "5ee9cbc27f6121dcd79850cd75e3fc5cc4b9c504ad882c827a5a08702fa8cda4"
_VERSAO_REFERENCIA = "9.20.0"

TIPO_PADRAO = "Dependencia a Juizo"

TIPO_RADIO_ID = {
    "Dependencia a Juizo": "rdodependenciaJuizo",
    "Dependencia a Processo/Colegiado": "rdodependenciaProcessoColegiado",
    "Dependencia a Processo/Magistrado": "rdodependenciaProcesso",
    "Impedimento do Magistrado": "rdoimpedido",
    "Suspeicao do Magistrado": "rdosuspeito",
    "Incompetencia": "rdoincompetencia",
    "Incompetencia c/ Dependencia Colegiado": "rdoincompetenciaDependenciaProcessoColegiado",
    "Incompetencia c/ Dependencia Magistrado": "rdoincompetenciaDependenciaProcessoMagistrado",
    "Livre": "rdolivre",
    "Retorna Autos": "rdodependenciaRetornarAutos",
    "Alteracao da Competencia do Orgao Julgador": "rdoalteracaoCompetencia",
    "Por dependencia por Alteracao da Competencia": "rdodependenciaPorCompetencia",
}

TIPO_ALIASES = {
    "Incompetencia com dependencia a Processo/Colegiado": "Incompetencia c/ Dependencia Colegiado",
    "Incompetencia com dependencia Processo/Colegiado": "Incompetencia c/ Dependencia Colegiado",
    "Incompetencia com dependencia a Processo/Magistrado": "Incompetencia c/ Dependencia Magistrado",
    "Incompetencia com dependencia Processo/Magistrado": "Incompetencia c/ Dependencia Magistrado",
    "Por dependencia por Alteracao da Competencia do Orgao julgador": "Por dependencia por Alteracao da Competencia",
    "Por dependencia por Alteracao da Competencia do Orgao Julgador": "Por dependencia por Alteracao da Competencia",
}

_COM_COMPETENCIA = frozenset({
    "Incompetencia",
    "Incompetencia c/ Dependencia Colegiado",
    "Incompetencia c/ Dependencia Magistrado",
    "Livre",
    "Alteracao da Competencia do Orgao Julgador",
})

_COM_PROCESSO_REF = frozenset({
    "Dependencia a Processo/Colegiado",
    "Dependencia a Processo/Magistrado",
    "Por dependencia por Alteracao da Competencia",
    "Incompetencia c/ Dependencia Colegiado",
    "Incompetencia c/ Dependencia Magistrado",
    "Livre",
    "Alteracao da Competencia do Orgao Julgador",
})

_MOTIVO_RETORNO_ID = {
    "Erro material": "rdoTipoRedistribuicaoErroMaterial",
    "Extincao de Unidade Judiciaria": "rdoTipoRedistribuicaoExtincaoDeUnidadeJudiciaria",
    "Recusa de Prevencao/Dependencia": "rdoTipoRedistribuicaoRecusaDePrevencaoDependencia",
    "Alteracao de Competencia do Orgao": "rdoTipoRedistribuicaoAlteracaoDeCompetenciaDoOrgao",
    "Incompetencia - Decisao Judicial de Orgao Superior": "rdoTipoRedistribuicaoIncompetenciaDecisaoJudicialOrgaoSuperior",
}


def executar_redistribuicao(driver, wait, status, num_fila, linha=None, referencias=None):
    linha = linha or {}
    referencias = referencias or []

    _clicar_redistribuicao_na_capa(driver, wait, status, num_fila)

    # Confere se a pagina mantem a estrutura esperada (deteccao de mudanca de versao)
    validar_pagina_redistribuicao(driver, status, num_fila)

    tipo = (linha.get("tipo") or TIPO_PADRAO).strip() or TIPO_PADRAO
    tipo_resolvido, radio_id = _resolver_tipo(tipo)
    if not radio_id:
        tipos_validos = ", ".join(sorted(TIPO_RADIO_ID))
        raise ValueError(f"Tipo de redistribuicao desconhecido: '{tipo}'. Tipos validos: {tipos_validos}")

    _selecionar_tipo(driver, wait, radio_id, tipo_resolvido, status, num_fila)
    _preencher_campos_do_tipo(driver, wait, linha, referencias, tipo_resolvido, status, num_fila)
    return _clicar_redistribuir(driver, wait, status, num_fila)


def validar_linha_redistribuicao(linha: dict, referencias: list[dict] | None = None) -> list[str]:
    referencias = referencias or []
    tipo = (linha.get("tipo") or TIPO_PADRAO).strip() or TIPO_PADRAO
    tipo_resolvido, radio_id = _resolver_tipo(tipo)
    pendencias = []

    if not radio_id:
        pendencias.append(f"tipo desconhecido '{tipo}'")
        return pendencias

    processo_ref = (linha.get("processo_ref") or "").strip()
    if not processo_ref:
        processo_ref = buscar_processo_ref(
            referencias,
            linha.get("competencia", ""),
            numero_processo=linha.get("numero_processo", ""),
        )

    if tipo_resolvido in _COM_PROCESSO_REF and not processo_ref:
        pendencias.append("processo_ref")

    # competencia não bloqueia mais aqui: quando ausente, é lida ao vivo da
    # capa do processo (#txtCompetencia) durante a execução. Só vira erro
    # (por linha, não trava o lote) se nem a capa tiver o campo — ver
    # _preencher_campos_do_tipo.

    return pendencias


# Âncoras estruturais esperadas na página de redistribuição. Servem para
# detectar se o eProc mudou o layout entre versões (o robô testa versões).
_ANCORAS_PAGINA = {
    "formulario (frmRedistribuicaoProcesso)": (By.ID, "frmRedistribuicaoProcesso"),
    "fieldset de motivos (fldGeneroRedistribuicao)": (By.ID, "fldGeneroRedistribuicao"),
    "grupo de radios (rdoTipoRedistribuicao)": (By.NAME, "rdoTipoRedistribuicao"),
    "botao Redistribuir (sbmConfirmaRedistribuicao)": (By.NAME, "sbmConfirmaRedistribuicao"),
}


def validar_pagina_redistribuicao(driver, status=None, num_fila=0):
    """Verifica se a estrutura da página de redistribuição continua a esperada.

    Como o robô é usado para testar versões do sistema, esta checagem detecta
    quando o eProc altera o layout: confere as âncoras estruturais e quais
    motivos (radios) estão presentes. Levanta erro claro se algo essencial
    sumiu, e registra em log um relatório dos motivos disponíveis.
    """
    if status is not None:
        status.config(text=f"L{num_fila}: Validando estrutura da pagina de redistribuicao...")

    faltando = []
    for descricao, (by, valor) in _ANCORAS_PAGINA.items():
        if not driver.find_elements(by, valor):
            faltando.append(descricao)

    if faltando:
        raise RuntimeError(
            "A pagina de redistribuicao mudou de estrutura nesta versao do eProc. "
            "Elementos esperados nao encontrados: " + "; ".join(faltando)
        )

    # Mapeia quais motivos conhecidos estão presentes (por value, robusto a sufixo)
    presentes, ausentes = [], []
    for nome, radio_id in TIPO_RADIO_ID.items():
        token = radio_id[3:] if radio_id.startswith("rdo") else radio_id
        seletor = f"input[name='rdoTipoRedistribuicao'][value^='{token}|']"
        if driver.find_elements(By.CSS_SELECTOR, seletor):
            presentes.append(nome)
        else:
            ausentes.append(nome)

    logger.info(
        "Validacao da pagina de redistribuicao: %d motivos presentes, %d ausentes. Ausentes: %s",
        len(presentes), len(ausentes), ", ".join(ausentes) or "nenhum",
    )

    if ausentes:
        lista = "\n".join(f"  • {m}" for m in ausentes)
        messagebox.showwarning(
            "Motivos de Redistribuição Ausentes",
            f"Os seguintes motivos cadastrados no robô NÃO foram encontrados na "
            f"página de redistribuição do eProc:\n\n{lista}\n\n"
            "Isso pode indicar uma mudança de versão do sistema.\n"
            "A automação continuará, mas esses motivos não poderão ser usados.",
        )

    # Impressao digital da estrutura do formulario (detecta qualquer mudanca
    # relevante de codigo-fonte entre versoes do eProc).
    assinatura, hash_atual = _assinatura_estrutura(driver)
    if hash_atual:
        _verificar_mudanca_estrutura(hash_atual, assinatura, status, num_fila)

    return {"presentes": presentes, "ausentes": ausentes, "hash": hash_atual}


def _assinatura_estrutura(driver):
    """Gera uma assinatura canonica da estrutura do formulario de redistribuicao.

    Coleta apenas tag/type/name/id e o token do value dos radios, removendo o
    sufixo numerico dos ids (volatil entre versoes) e ignorando valores
    dinamicos (hashes, numeros de processo). Assim a assinatura so muda quando
    a ESTRUTURA do formulario muda de fato.
    """
    try:
        dados = driver.execute_script(
            r"""
            var form = document.getElementById('frmRedistribuicaoProcesso');
            if (!form) return null;
            var els = form.querySelectorAll('input, select, textarea, button');
            var itens = [];
            els.forEach(function(el){
                var tag  = el.tagName.toLowerCase();
                var type = (el.getAttribute('type') || '').toLowerCase();
                var name = el.getAttribute('name') || '';
                var id   = (el.getAttribute('id') || '').replace(/[0-9]+$/, '');
                var extra = '';
                if (type === 'radio' && name === 'rdoTipoRedistribuicao') {
                    extra = (el.getAttribute('value') || '').split('|')[0];
                }
                itens.push([tag, type, name, id, extra].join(':'));
            });
            itens.sort();
            return itens.join('\n');
            """
        )
    except Exception as e:
        logger.debug("Nao foi possivel coletar assinatura da estrutura: %s", e)
        return None, None

    if not dados:
        return None, None
    h = hashlib.sha256(dados.encode("utf-8")).hexdigest()
    return dados, h


def _verificar_mudanca_estrutura(hash_atual, assinatura, status, num_fila):
    # Usa o hash hardcodado (calculado do codigo-fonte v9.20.0) como referencia primaria.
    hash_ref = _HASH_REFERENCIA
    versao_ref = _VERSAO_REFERENCIA

    # Verifica se ha uma referencia customizada salva localmente (permite aceitar nova versao).
    try:
        if os.path.exists(_ARQUIVO_ESTRUTURA):
            with open(_ARQUIVO_ESTRUTURA, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            if baseline.get("hash") and baseline["hash"] != _HASH_REFERENCIA:
                # Usuario aceitou uma versao diferente da referencia embutida.
                hash_ref = baseline["hash"]
                versao_ref = baseline.get("versao", "customizada")
    except Exception as e:
        logger.debug("Nao foi possivel ler a referencia de estrutura customizada: %s", e)

    if hash_ref == hash_atual:
        logger.info(
            "Estrutura da pagina de redistribuicao confere com a referencia v%s.", versao_ref
        )
        return

    logger.warning(
        "ATENCAO: a estrutura da pagina de redistribuicao MUDOU "
        "(referencia v%s %s..., atual %s...).",
        versao_ref, hash_ref[:12], hash_atual[:12],
    )
    if status is not None:
        status.config(
            text=f"L{num_fila}: ⚠ AVISO - a estrutura da pagina de redistribuicao mudou! "
            "Verifique se o robo precisa de ajuste para esta versao do eProc."
        )
    # Salva a estrutura atual para inspecao/comparacao manual.
    try:
        os.makedirs(str(OUTPUT_DIR), exist_ok=True)
        with open(_ARQUIVO_ESTRUTURA_ATUAL, "w", encoding="utf-8") as f:
            f.write(assinatura)
    except Exception as e:
        logger.debug("Nao foi possivel salvar snapshot da estrutura atual: %s", e)
    messagebox.showwarning(
        "Estrutura da Página Alterada",
        f"A estrutura da página de redistribuição do eProc MUDOU em relação "
        f"à referência embutida no robô (v{versao_ref}).\n\n"
        f"Hash de referência (v{versao_ref}): {hash_ref[:16]}...\n"
        f"Hash atual:                         {hash_atual[:16]}...\n\n"
        "O robô pode não funcionar corretamente nesta versão do sistema.\n\n"
        f"O snapshot atual foi salvo em:\n{_ARQUIVO_ESTRUTURA_ATUAL}\n\n"
        "Se esta versão foi homologada, atualize a referência no arquivo:\n"
        f"{_ARQUIVO_ESTRUTURA}",
    )


def _salvar_baseline(hash_atual, assinatura):
    try:
        os.makedirs(str(OUTPUT_DIR), exist_ok=True)
        with open(_ARQUIVO_ESTRUTURA, "w", encoding="utf-8") as f:
            json.dump(
                {"hash": hash_atual, "estrutura": assinatura, "registrado_em": time.strftime("%d/%m/%Y %H:%M:%S")},
                f, ensure_ascii=False, indent=2,
            )
    except Exception as e:
        logger.debug("Nao foi possivel salvar a referencia de estrutura: %s", e)


def _clicar_redistribuicao_na_capa(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Abrindo Redistribuicao na capa...")
    seletores = [
        (
            By.XPATH,
            "//a[contains(concat(' ', normalize-space(@class), ' '), ' infraButton ') "
            "and contains(@href, 'acao=redistribuicao_processo') "
            "and contains(@href, 'acao_origem=processo_selecionar') "
            "and not(contains(@href, 'redistribuicao_processo_bloco')) "
            "and contains(normalize-space(.), 'Redistribui')]",
        ),
        (
            By.XPATH,
            "//fieldset[@id='fldAcoes']//a[contains(@href, 'acao=redistribuicao_processo') "
            "and contains(@href, 'acao_origem=processo_selecionar') "
            "and not(contains(@href, 'redistribuicao_processo_bloco')) "
            "and contains(normalize-space(.), 'Redistribui')]",
        ),
    ]
    _clicar_primeiro_disponivel(driver, wait, seletores, "botao Redistribuicao da capa")
    wait.until(lambda d: "redistribuicao_processo" in d.current_url or d.find_elements(By.ID, "frmRedistribuicaoProcesso"))
    time.sleep(2)


def _resolver_tipo(tipo: str) -> tuple[str | None, str | None]:
    tipo_norm = _normalizar(tipo)
    for alias, tipo_canonico in TIPO_ALIASES.items():
        if tipo_norm == _normalizar(alias):
            return tipo_canonico, TIPO_RADIO_ID[tipo_canonico]

    for nome, radio_id in TIPO_RADIO_ID.items():
        if tipo_norm == _normalizar(nome):
            return nome, radio_id

    for nome, radio_id in sorted(TIPO_RADIO_ID.items(), key=lambda item: len(item[0]), reverse=True):
        nome_norm = _normalizar(nome)
        if tipo_norm in nome_norm or nome_norm in tipo_norm:
            return nome, radio_id
    return None, None


def _selecionar_tipo(driver, wait, radio_id: str, tipo: str, status, num_fila):
    status.config(text=f"L{num_fila}: Selecionando tipo {tipo}...")
    radio = _localizar_radio_tipo(driver, radio_id, wait)
    if radio is None:
        raise Exception(
            f"Nao foi possivel localizar o radio do motivo '{tipo}' na pagina de "
            "redistribuicao. O codigo da pagina pode ter mudado nesta versao do eProc."
        )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", radio)
    time.sleep(0.3)

    if not radio.is_selected():
        driver.execute_script("arguments[0].click();", radio)
        time.sleep(4)
        try:
            wait.until(EC.presence_of_element_located((By.ID, "frmRedistribuicaoProcesso")))
        except Exception:
            logger.debug("Formulario de redistribuicao nao confirmou recarga apos selecionar tipo.")
        time.sleep(1)


def _localizar_radio_tipo(driver, radio_id: str, wait=None):
    """Localiza o radio do motivo de redistribuicao de forma robusta.

    Os IDs no eProc trazem um sufixo numerico variavel (ex: 'rdoincompetencia6'),
    que pode mudar entre versoes do sistema. O atributo value, porem, segue o
    padrao estavel 'token|numero' (ex: 'incompetencia|6'). Por isso a busca
    principal e feita pelo prefixo do value, com o '|' garantindo que
    'incompetencia|' nao case com 'incompetenciaDependencia...|'.
    """
    token = radio_id[3:] if radio_id.startswith("rdo") else radio_id

    # 1) Por prefixo do value (estavel entre versoes). Aguarda ate ~10s.
    seletor_value = f"input[name='rdoTipoRedistribuicao'][value^='{token}|']"
    if wait is not None:
        try:
            return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, seletor_value)))
        except Exception:
            logger.debug("Radio nao encontrado por value '%s|'.", token)
    else:
        els = driver.find_elements(By.CSS_SELECTOR, seletor_value)
        if els:
            return els[0]

    # 2) Por ID exato (versoes antigas, sem sufixo numerico)
    els = driver.find_elements(By.ID, radio_id)
    if els:
        return els[0]

    # 3) Por ID que comeca com o base seguido apenas de digitos
    for el in driver.find_elements(By.CSS_SELECTOR, f"input[id^='{radio_id}']"):
        resto = (el.get_attribute("id") or "")[len(radio_id):]
        if resto == "" or resto.isdigit():
            return el

    return None


def _preencher_campos_do_tipo(driver, wait, linha, referencias, tipo, status, num_fila):
    competencia = (linha.get("competencia") or "").strip()
    assunto = (linha.get("assunto") or "").strip()
    classe_judicial = (linha.get("classe_judicial") or "").strip()
    processo_ref = (linha.get("processo_ref") or "").strip()
    motivo_retorno = (linha.get("motivo_retorno") or "").strip()

    if tipo in _COM_PROCESSO_REF and not processo_ref:
        processo_ref = buscar_processo_ref(
            referencias,
            competencia,
            numero_processo=linha.get("numero_processo", ""),
        )
        if not processo_ref:
            raise ValueError(
                f"O tipo '{tipo}' exige processo de referencia, mas a planilha nao informou "
                "na coluna processo_ref nem no CSV de referencias."
            )

    if tipo in _COM_COMPETENCIA:
        if not competencia:
            raise ValueError(
                f"O tipo '{tipo}' exige competencia, mas ela nao foi informada na planilha "
                "e nao foi possivel obte-la da capa do processo (#txtCompetencia)."
            )
        _selecionar_competencia(driver, competencia, status, num_fila)
        if classe_judicial:
            _selecionar_classe_judicial(driver, classe_judicial, status, num_fila)
        if assunto:
            _incluir_assunto(driver, wait, assunto, status, num_fila)

    if tipo in _COM_PROCESSO_REF:
        _preencher_processo_ref(driver, wait, processo_ref, status, num_fila)

    if tipo == "Retorna Autos":
        _selecionar_motivo_retorno(driver, motivo_retorno, status, num_fila)

    if _campo_localidade_existe(driver):
        _selecionar_primeira_localidade(driver, wait, status, num_fila)


def _campo_localidade_existe(driver):
    try:
        return bool(driver.find_elements(By.ID, "txtJuizoLocalidadeJudicial"))
    except Exception:
        return False


def _selecionar_competencia(driver, competencia: str, status, num_fila):
    status.config(text=f"L{num_fila}: Selecionando competencia...")
    try:
        select = Select(driver.find_element(By.ID, "selIdCompentencia"))
        for opt in select.options:
            if _normalizar(competencia) in _normalizar(opt.text):
                select.select_by_visible_text(opt.text)
                time.sleep(1)
                return
        select.select_by_visible_text(competencia)
        time.sleep(1)
    except Exception as e:
        logger.warning("Nao foi possivel selecionar competencia '%s': %s", competencia, e)


def _selecionar_classe_judicial(driver, classe: str, status, num_fila):
    status.config(text=f"L{num_fila}: Selecionando classe judicial...")
    try:
        WebDriverWait(driver, 10).until(
            lambda d: len(Select(d.find_element(By.ID, "selIdClasseJudicial")).options) > 1
        )
        select = Select(driver.find_element(By.ID, "selIdClasseJudicial"))
        for opt in select.options:
            if _normalizar(classe) in _normalizar(opt.text):
                select.select_by_visible_text(opt.text)
                time.sleep(0.5)
                return
        select.select_by_visible_text(classe)
        time.sleep(0.5)
    except Exception as e:
        logger.warning("Nao foi possivel selecionar classe judicial '%s': %s", classe, e)


def _incluir_assunto(driver, wait, assunto: str, status, num_fila):
    status.config(text=f"L{num_fila}: Incluindo assunto...")
    try:
        campo = wait.until(EC.presence_of_element_located((By.ID, "txtDesAssunto")))
        driver.execute_script("arguments[0].click();", campo)
        driver.execute_script("arguments[0].value = '';", campo)
        campo.clear()
        campo.send_keys(assunto)
        time.sleep(2)
        _clicar_sugestao_assunto(driver, assunto)

        try:
            chk = driver.find_element(By.ID, "chkAssuntoPrincipal")
            if not chk.is_selected():
                driver.execute_script("arguments[0].click();", chk)
        except Exception as e:
            logger.debug("Checkbox de assunto principal nao encontrado: %s", e)

        try:
            btn = driver.find_element(By.ID, "btnIncluirAssunto")
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(1)
        except Exception as e:
            logger.warning("Botao Incluir Assunto nao encontrado: %s", e)
    except Exception as e:
        logger.warning("Erro ao incluir assunto '%s': %s", assunto, e)


def _clicar_sugestao_assunto(driver, assunto: str):
    try:
        sugestoes = WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".ui-autocomplete .ui-menu-item"))
        )
        assunto_norm = _normalizar(assunto)
        for sug in sugestoes:
            if assunto_norm in _normalizar(sug.text):
                driver.execute_script("arguments[0].click();", sug)
                return
        if sugestoes:
            driver.execute_script("arguments[0].click();", sugestoes[0])
    except Exception as e:
        logger.debug("Autocomplete de assunto nao abriu: %s", e)


def _preencher_processo_ref(driver, wait, processo_ref: str, status, num_fila):
    status.config(text=f"L{num_fila}: Informando processo de referencia...")
    campo = wait.until(EC.presence_of_element_located((By.ID, "txtNumProcessoDependencia")))
    driver.execute_script("arguments[0].value = '';", campo)
    campo.clear()
    campo.send_keys(processo_ref)
    time.sleep(0.5)
    driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", campo)
    driver.execute_script("arguments[0].blur();", campo)
    time.sleep(1)


def _selecionar_motivo_retorno(driver, motivo: str, status, num_fila):
    status.config(text=f"L{num_fila}: Selecionando motivo de retorno...")
    radio_id = None
    motivo_norm = _normalizar(motivo)
    for nome, rid in _MOTIVO_RETORNO_ID.items():
        nome_norm = _normalizar(nome)
        if motivo_norm and (motivo_norm == nome_norm or motivo_norm in nome_norm):
            radio_id = rid
            break

    radio_id = radio_id or "rdoTipoRedistribuicaoErroMaterial"
    try:
        radio = driver.find_element(By.ID, radio_id)
        if not radio.is_selected():
            driver.execute_script("arguments[0].click();", radio)
            time.sleep(0.5)
    except Exception as e:
        logger.warning("Nao foi possivel selecionar motivo retorno %s: %s", radio_id, e)


def _selecionar_primeira_localidade(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Selecionando primeira localidade...")
    campo = wait.until(EC.element_to_be_clickable((By.ID, "txtJuizoLocalidadeJudicial")))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", campo)
    time.sleep(0.5)

    _abrir_lista_todos_orgaos(driver, wait)

    if _clicar_primeira_opcao_autocomplete_js(driver):
        time.sleep(1)
        if _localidade_selecionada(driver):
            return

    if _clicar_primeira_opcao_autocomplete(driver):
        time.sleep(1)
        if _localidade_selecionada(driver):
            return

    if _selecionar_primeira_opcao_por_select(driver):
        time.sleep(1)
        if _localidade_selecionada(driver):
            return

    try:
        campo.send_keys(Keys.ARROW_DOWN)
        campo.send_keys(Keys.ENTER)
        time.sleep(1)
        if _localidade_selecionada(driver):
            return
    except Exception as e:
        logger.debug("Selecao por teclado da localidade falhou: %s", e)

    raise Exception("Nao foi possivel selecionar a primeira localidade da lista.")


def _abrir_lista_todos_orgaos(driver, wait):
    # Verifica primeiro se o elemento existe antes de esperar com timeout longo
    elementos = driver.find_elements(By.ID, "lblListarOrgaos")
    if not elementos:
        logger.debug("lblListarOrgaos nao existe na pagina, pulando listagem de orgaos.")
        return
    try:
        label = elementos[0]
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", label)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", label)
        time.sleep(1)
    except Exception as e:
        logger.debug("Label lblListarOrgaos nao clicavel: %s", e)
        try:
            driver.execute_script("if (typeof listarTodosOrgaos === 'function') listarTodosOrgaos();")
            time.sleep(1.5)
        except Exception as e2:
            logger.debug("Chamada JS listarTodosOrgaos falhou: %s", e2)


def _clicar_primeira_opcao_autocomplete_js(driver):
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script(
                """
                var div = document.getElementById('divInfraAjaxtxtJuizoLocalidadeJudicial');
                return !!(div && div.textContent && div.textContent.trim().length);
                """
            )
        )
        return bool(driver.execute_script(
            """
            var div = document.getElementById('divInfraAjaxtxtJuizoLocalidadeJudicial');
            if (!div) return false;

            function visivel(el) {
                var box = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                return box.width >= 0 && box.height >= 0 &&
                       style.display !== 'none' && style.visibility !== 'hidden';
            }

            var itens = Array.from(div.querySelectorAll('a, li, tr, td, div, span'))
                .filter(function(el) {
                    return el !== div && visivel(el) && (el.innerText || el.textContent || '').trim();
                });

            var item = itens.find(function(el) {
                return !Array.from(el.children || []).some(function(child) {
                    return (child.innerText || child.textContent || '').trim() ===
                           (el.innerText || el.textContent || '').trim();
                });
            }) || itens[0];

            if (!item) return false;
            item.scrollIntoView({block: 'center'});
            ['mouseover', 'mousedown', 'mouseup', 'click'].forEach(function(tipo) {
                item.dispatchEvent(new MouseEvent(tipo, {bubbles: true, cancelable: true, view: window}));
            });
            return true;
            """
        ))
    except Exception as e:
        logger.debug("Clique JS na primeira opcao do autocomplete falhou: %s", e)
        return False


def _selecionar_primeira_opcao_por_select(driver):
    try:
        selecionou = driver.execute_script(
            """
            var sel = document.getElementById('selJuizoLocalidadeJudicial');
            var txt = document.getElementById('txtJuizoLocalidadeJudicial');
            if (!sel || !sel.options || sel.options.length === 0) return false;
            for (var i = 0; i < sel.options.length; i++) {
                var opt = sel.options[i];
                var value = (opt.value || '').trim();
                var text = (opt.text || '').trim();
                if (value && text && text.toLowerCase().indexOf('selecione') === -1) {
                    sel.value = value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    if (txt) {
                        txt.value = text;
                        txt.dispatchEvent(new Event('input', {bubbles: true}));
                        txt.dispatchEvent(new Event('change', {bubbles: true}));
                        txt.dispatchEvent(new KeyboardEvent('blur', {bubbles: true}));
                    }
                    return true;
                }
            }
            return false;
            """
        )
        return bool(selecionou)
    except Exception as e:
        logger.debug("Selecao da localidade por select oculto falhou: %s", e)
        return False


def _clicar_primeira_opcao_autocomplete(driver):
    try:
        opcao = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//*[@id='divInfraAjaxtxtJuizoLocalidadeJudicial']"
                "//*[self::a or self::div or self::td or self::li or self::span]"
                "[normalize-space() and not(contains(@style, 'display: none'))][1]",
            ))
        )
        driver.execute_script("arguments[0].click();", opcao)
        return True
    except Exception as e:
        logger.debug("Clique na primeira opcao do autocomplete falhou: %s", e)
        return False


def _localidade_selecionada(driver):
    try:
        return bool(driver.execute_script(
            """
            var hidden = document.getElementById('selJuizoLocalidadeJudicial');
            var campo = document.getElementById('txtJuizoLocalidadeJudicial');
            if (hidden) return !!String(hidden.value || '').trim();
            return !!(campo && String(campo.value || '').trim());
            """
        ))
    except Exception:
        return False


def _clicar_redistribuir(driver, wait, status, num_fila):
    status.config(text=f"L{num_fila}: Confirmando redistribuicao...")
    try:
        driver.execute_script("window.confirm = function(){ return true; };")
    except Exception as e:
        logger.debug("Nao foi possivel sobrescrever confirm: %s", e)

    seletores = [
        (By.NAME, "sbmConfirmaRedistribuicao"),
        (By.CSS_SELECTOR, "input[name='sbmConfirmaRedistribuicao']"),
        (By.XPATH, "//input[@type='submit' and @value='Redistribuir']"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Redistribuir')]"),
        (By.XPATH, "//input[contains(@value, 'Redistribuir')]"),
    ]
    _clicar_primeiro_disponivel(driver, wait, seletores, "botao Redistribuir")

    mensagem = ""
    try:
        alert = WebDriverWait(driver, 5).until(EC.alert_is_present())
        mensagem = (alert.text or "").strip()
        alert.accept()
    except Exception as e:
        logger.debug("Nenhum alerta de confirmacao de redistribuicao: %s", e)

    time.sleep(3)
    return mensagem or "Redistribuido com sucesso."


def _clicar_primeiro_disponivel(driver, wait, seletores, descricao):
    for by, valor in seletores:
        try:
            elemento = wait.until(EC.element_to_be_clickable((by, valor)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", elemento)
            return elemento
        except Exception as e:
            logger.debug("%s nao encontrado com %s=%s: %s", descricao, by, valor, e)
    raise Exception(f"Nao foi possivel localizar {descricao}.")


# ===========================================================================
# FLUXO — assinatura COTRI / CODIPRE em lote
# ===========================================================================
_CABECALHO_CSV_ASSINATURA = ["Data", "Hora", "Processo", "Perfil", "Status", "Mensagem"]
_CABECALHO_CSV_REDIST = ["Data", "Hora", "Processo", "Tipo", "Status", "Mensagem"]


def _salvar_resultado_csv(caminho_csv: str, linha_resultado: dict, fieldnames: list[str]):
    novo = not os.path.exists(caminho_csv)
    with open(caminho_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if novo:
            writer.writeheader()
        writer.writerow(linha_resultado)


def _caminho_csv_resultado(caminho_planilha: str) -> str:
    base = os.path.splitext(caminho_planilha)[0]
    return f"{base}_resultados.csv"


def _validar_planilha_assinatura(linhas: list[dict]) -> list[str]:
    pendencias = []
    for idx, linha in enumerate(linhas, 1):
        num = normalizar_numero_processo(linha)
        if not num:
            pendencias.append(f"Linha {idx}: número de processo vazio ou inválido")
    return pendencias


def executar_assinatura_cotri(state, status, progresso=None):
    perfil = getattr(state, "perfil", "COTRI") or "COTRI"
    nome_preferencia = nome_preferencia_perfil(perfil)
    acao_rel = f"Assinatura {perfil}"

    def _prog(atual, total):
        if progresso:
            try:
                progresso(atual, total)
            except Exception:
                pass
    if not state.caminho_planilha:
        messagebox.showerror("AURA COTRI", "Selecione a Planilha CSV com os números de processo.")
        return
    if not state.url:
        messagebox.showerror("AURA COTRI", "Informe a URL do sistema.")
        return
    if not state.usuario or not state.senha:
        messagebox.showerror("AURA COTRI", "Informe o usuário e a senha.")
        return

    status.config(text="Status: Lendo planilha...")
    linhas = ler_csv(state.caminho_planilha)
    if linhas is None:
        messagebox.showerror(
            "AURA COTRI",
            "Não foi possível ler o CSV. Salve-o como UTF-8 e tente novamente.",
        )
        return

    pendencias = _validar_planilha_assinatura(linhas)
    if pendencias:
        messagebox.showerror(
            "AURA COTRI",
            "A planilha possui inconsistências antes de iniciar:\n\n"
            + "\n".join(pendencias[:12])
            + ("\n..." if len(pendencias) > 12 else ""),
        )
        status.config(text="Status: Planilha com inconsistências.")
        return

    num_total = len(linhas)
    sucessos = erros = pulados = 0
    caminho_csv = _caminho_csv_resultado(state.caminho_planilha)

    try:
        status.config(text="Status: Inicializando Chrome...")
        driver, wait, _ = criar_driver()
        driver.get(state.url)
        driver.maximize_window()

        status.config(text=f"Status: Autenticando (perfil {perfil})...")
        fazer_login(driver, wait, state.usuario, state.senha)

        if not selecionar_perfil(driver, perfil):
            messagebox.showerror(
                "AURA COTRI",
                f"Nao foi possivel selecionar o perfil {perfil}. "
                "Verifique se o usuario possui esse perfil de distribuicao no eProc.",
            )
            return

        idx = 0
        while idx < len(linhas):
            linha = linhas[idx]
            num_fila = idx + 1
            state.ultimo_aviso.clear()

            status.config(text=f"[{num_fila}/{num_total}] Preparando...")
            _prog(num_fila - 1, num_total)
            verificar_pausa(state, status)

            if not verificar_sessao_ativa(driver):
                status.config(text="Status: Sessão do eProc encerrada — lote interrompido.")
                messagebox.showerror(
                    "AURA COTRI",
                    "A sessão do eProc expirou ou o navegador foi fechado. "
                    "Faça login novamente e reinicie o lote.",
                )
                return

            try:
                num_processo = normalizar_numero_processo(linha)

                if not num_processo:
                    status.config(text=f"[{num_fila}/{num_total}] Sem número de processo, pulando...")
                    registrar_relatorio_html(f"linha {num_fila}", acao_rel, "WARN",
                                             "Sem número de processo — linha pulada.")
                    pulados += 1
                    idx += 1
                    continue

                status.config(text=f"[{num_fila}/{num_total}] Consultando processo {num_processo}...")
                pesquisar_processo(driver, state.url, num_processo)

                status.config(text=f"[{num_fila}/{num_total}] Localizando preferencia {nome_preferencia}...")
                link_ppg = localizar_link_preferencia(driver, perfil)

                if link_ppg is None:
                    raise Exception(
                        f"Preferencia '{nome_preferencia}' nao encontrada. "
                        "Verifique se o processo tem essa preferencia disponivel."
                    )

                driver.get(link_ppg.get_attribute("href"))
                time.sleep(5)

                executar_assinatura(driver, wait, state.senha, state.ultimo_aviso, status, num_fila)

                status.config(text=f"[{num_fila}/{num_total}] Aguardando retorno ao processo após assinatura...")
                time.sleep(5)

                status.config(text=f"[{num_fila}/{num_total}] ✅ Processo {num_processo} concluído!")
                salvar_no_historico({
                    "Data": time.strftime("%d/%m/%Y"),
                    "Classe": f"{perfil} - {nome_preferencia}",
                    "Magistrado": "",
                    "Processo": num_processo,
                    "Chave": "",
                    "Aviso": " | ".join(state.ultimo_aviso),
                })
                _salvar_resultado_csv(caminho_csv, {
                    "Data": time.strftime("%d/%m/%Y"),
                    "Hora": time.strftime("%H:%M:%S"),
                    "Processo": num_processo,
                    "Perfil": perfil,
                    "Status": "Sucesso",
                    "Mensagem": "Assinatura concluída com sucesso.",
                }, _CABECALHO_CSV_ASSINATURA)
                registrar_relatorio_html(num_processo, acao_rel, "OK",
                                         " | ".join(state.ultimo_aviso) or "Assinatura concluída.")
                sucessos += 1
                idx += 1
                _prog(num_fila, num_total)
                time.sleep(2)

            except Exception as e_linha:
                num_processo_err = normalizar_numero_processo(linha) or "desconhecido"
                # Captura o estado da tela ANTES de qualquer navegacao de recuperacao.
                _dump_diagnostico(driver, f"assinatura_L{num_fila}_{num_processo_err}", str(e_linha)[:200])
                registrar_relatorio_html(num_processo_err, acao_rel, "ERROR", str(e_linha))
                _salvar_resultado_csv(caminho_csv, {
                    "Data": time.strftime("%d/%m/%Y"),
                    "Hora": time.strftime("%H:%M:%S"),
                    "Processo": num_processo_err,
                    "Perfil": perfil,
                    "Status": "Erro",
                    "Mensagem": str(e_linha),
                }, _CABECALHO_CSV_ASSINATURA)
                erros += 1

                decisao = mostrar_erro_linha(num_fila, e_linha, status, contexto=f"Linha {num_fila}")

                try:
                    driver.switch_to.alert.accept()
                except Exception:
                    pass

                if decisao == "parar":
                    status.config(text="Status: Interrompido pelo usuário.")
                    return

                fechar_abas_extras(driver)

                try:
                    driver.get(state.url)
                    time.sleep(3)
                except Exception as e:
                    logger.warning("Erro ao recuperar após falha: %s", e)

                if decisao != "repetir":
                    idx += 1

        _prog(num_total, num_total)
        status.config(text=f"Status: Lote {perfil} finalizado! ✅  {sucessos} ok · {erros} erros · {pulados} pulados")
        messagebox.showinfo(
            "AURA COTRI",
            f"Processamento finalizado!\n\n"
            f"✅  Concluídos: {sucessos}\n"
            f"❌  Erros:      {erros}\n"
            f"⏭  Pulados:    {pulados}\n\n"
            f"Resultados salvos em:\n{caminho_csv}",
        )

    except Exception as e:
        logger.error("Erro geral: %s", e)
        status.config(text="Erro geral.")
        messagebox.showerror("Erro AURA COTRI", str(e))


# ===========================================================================
# FLUXO — redistribuição em lote
# ===========================================================================
def executar_redistribuicao_cotri(state, status, progresso=None):
    caminho = state.caminho_redistribuicao or state.caminho_planilha
    caminho_referencias = getattr(state, "caminho_referencias_redistribuicao", None)
    perfil = getattr(state, "perfil", "COTRI") or "COTRI"
    acao_rel = f"Redistribuição {perfil}"

    def _prog(atual, total):
        if progresso:
            try:
                progresso(atual, total)
            except Exception:
                pass

    if not caminho:
        messagebox.showerror("AURA COTRI", "Selecione a planilha de redistribuicao.")
        return
    if not caminho_referencias:
        messagebox.showerror("AURA COTRI", "Selecione o CSV de referencias da redistribuicao.")
        return
    if not state.url:
        messagebox.showerror("AURA COTRI", "Informe a URL do sistema.")
        return
    if not state.usuario or not state.senha:
        messagebox.showerror("AURA COTRI", "Informe o usuario e a senha.")
        return

    status.config(text="Status: Lendo planilha de redistribuicao...")
    linhas, referencias = ler_redistribuicao(caminho, caminho_referencias)
    if linhas is None:
        messagebox.showerror(
            "AURA COTRI",
            "Nao foi possivel ler a planilha. Use somente CSV separado por virgulas.",
        )
        return

    if not linhas:
        messagebox.showinfo("AURA COTRI", "A planilha de redistribuicao esta vazia.")
        return

    status.config(text="Status: Buscando competencias no Google Sheets...")
    n_preenchidas = enriquecer_competencia_via_sheets(linhas)
    if n_preenchidas:
        logger.info("Competencia preenchida via Google Sheets em %d linha(s).", n_preenchidas)

    pendencias = _validar_planilha_redistribuicao(linhas, referencias)
    if pendencias:
        messagebox.showerror(
            "AURA COTRI",
            "A planilha precisa ser corrigida antes de iniciar a redistribuicao:\n\n"
            + "\n".join(pendencias[:12])
            + ("\n..." if len(pendencias) > 12 else ""),
        )
        status.config(text="Status: Planilha com pendencias.")
        return

    caminho_csv = _caminho_csv_resultado(caminho)
    num_total = len(linhas)
    sucessos = erros = pulados = 0

    try:
        status.config(text="Status: Inicializando Chrome...")
        driver, wait, _ = criar_driver()
        driver.get(state.url)
        driver.maximize_window()

        status.config(text=f"Status: Autenticando (perfil {perfil})...")
        fazer_login(driver, wait, state.usuario, state.senha)

        if not selecionar_perfil(driver, perfil):
            messagebox.showerror(
                "AURA COTRI",
                f"Nao foi possivel selecionar o perfil {perfil}. "
                "Verifique se o usuario possui esse perfil de distribuicao no eProc.",
            )
            return

        idx = 0
        while idx < len(linhas):
            linha = linhas[idx]
            num_fila = idx + 1
            state.ultimo_aviso.clear()

            status.config(text=f"[{num_fila}/{num_total}] Preparando redistribuicao...")
            _prog(num_fila - 1, num_total)
            verificar_pausa(state, status)

            if not verificar_sessao_ativa(driver):
                status.config(text="Status: Sessão do eProc encerrada — lote interrompido.")
                messagebox.showerror(
                    "AURA COTRI",
                    "A sessão do eProc expirou ou o navegador foi fechado. "
                    "Faça login novamente e reinicie o lote.",
                )
                return

            try:
                num_processo = _extrair_numero(linha)
                if not num_processo:
                    status.config(text=f"[{num_fila}/{num_total}] Sem numero de processo, pulando...")
                    registrar_relatorio_html(f"linha {num_fila}", acao_rel, "WARN",
                                             "Sem número de processo — linha pulada.")
                    pulados += 1
                    idx += 1
                    continue

                tipo = (linha.get("tipo") or TIPO_PADRAO).strip() or TIPO_PADRAO

                status.config(text=f"[{num_fila}/{num_total}] Consultando processo {num_processo}...")
                pesquisar_processo(driver, state.url, num_processo)

                if not (linha.get("competencia") or "").strip():
                    comp_capa = _ler_competencia_da_capa(driver)
                    if comp_capa:
                        linha["competencia"] = comp_capa
                        logger.info("Competencia obtida da capa do processo %s: %s", num_processo, comp_capa)

                mensagem = executar_redistribuicao(driver, wait, status, num_fila, linha, referencias)

                status.config(text=f"[{num_fila}/{num_total}] ✅ Processo {num_processo} redistribuido.")
                salvar_no_historico({
                    "Data": time.strftime("%d/%m/%Y"),
                    "Classe": f"{perfil} - Redistribuicao - {tipo}",
                    "Magistrado": "",
                    "Processo": num_processo,
                    "Chave": "",
                    "Aviso": " | ".join(state.ultimo_aviso),
                })
                _salvar_resultado_csv(caminho_csv, {
                    "Data": time.strftime("%d/%m/%Y"),
                    "Hora": time.strftime("%H:%M:%S"),
                    "Processo": num_processo,
                    "Tipo": tipo,
                    "Status": "Sucesso",
                    "Mensagem": mensagem or "Redistribuido com sucesso.",
                }, _CABECALHO_CSV_REDIST)
                registrar_relatorio_html(num_processo, f"{acao_rel} - {tipo}", "OK",
                                         mensagem or "Redistribuído com sucesso.")
                sucessos += 1
                idx += 1
                _prog(num_fila, num_total)
                time.sleep(2)

            except Exception as e_linha:
                num_processo_err = _extrair_numero(linha) or "desconhecido"
                tipo_err = (linha.get("tipo") or TIPO_PADRAO).strip() or TIPO_PADRAO
                # Captura o estado da tela ANTES de qualquer navegacao de recuperacao.
                _dump_diagnostico(driver, f"redistribuicao_L{num_fila}_{num_processo_err}", str(e_linha)[:200])
                registrar_relatorio_html(num_processo_err, f"{acao_rel} - {tipo_err}", "ERROR", str(e_linha))
                _salvar_resultado_csv(caminho_csv, {
                    "Data": time.strftime("%d/%m/%Y"),
                    "Hora": time.strftime("%H:%M:%S"),
                    "Processo": num_processo_err,
                    "Tipo": tipo_err,
                    "Status": "Erro",
                    "Mensagem": str(e_linha),
                }, _CABECALHO_CSV_REDIST)
                erros += 1

                decisao = mostrar_erro_linha(num_fila, e_linha, status, contexto=f"Redistribuicao - linha {num_fila}")

                try:
                    driver.switch_to.alert.accept()
                except Exception:
                    pass

                if decisao == "parar":
                    status.config(text="Status: Interrompido pelo usuario.")
                    return

                if not verificar_sessao_ativa(driver):
                    status.config(text="Status: Sessao do navegador encerrada.")
                    messagebox.showerror(
                        "AURA COTRI",
                        "A sessao do navegador foi encerrada. Inicie o fluxo novamente.",
                    )
                    return

                fechar_abas_extras(driver)

                try:
                    driver.get(state.url)
                    time.sleep(3)
                except Exception as e:
                    logger.warning("Erro ao recuperar apos falha: %s", e)

                if decisao != "repetir":
                    idx += 1

        _prog(num_total, num_total)
        status.config(text=f"Status: Redistribuicao concluida! ✅  {sucessos} ok · {erros} erros · {pulados} pulados")
        messagebox.showinfo(
            "AURA COTRI",
            f"Redistribuicao finalizada!\n\n"
            f"✅  Concluídos: {sucessos}\n"
            f"❌  Erros:      {erros}\n"
            f"⏭  Pulados:    {pulados}\n\n"
            f"Resultados salvos em:\n{caminho_csv}",
        )

    except Exception as e:
        logger.error("Erro geral na redistribuicao: %s", e)
        status.config(text="Erro geral na redistribuicao.")
        messagebox.showerror("Erro AURA COTRI", str(e))


def _extrair_numero(linha: dict) -> str:
    num = (linha.get("numero_processo") or "").strip()
    num = num.replace("\n", "").replace("\r", "").replace(".", "").replace("-", "")
    if not num or num.upper() == "NAO PRECISA" or num.lower() == "nan":
        return ""
    return num


def _validar_planilha_redistribuicao(linhas: list[dict], referencias: list[dict]) -> list[str]:
    pendencias = []
    for idx, linha in enumerate(linhas, 1):
        num = _extrair_numero(linha) or "sem numero"
        campos = validar_linha_redistribuicao(linha, referencias)
        if campos:
            pendencias.append(f"Linha {idx} ({num}): preencher {', '.join(campos)}")
    return pendencias


# ===========================================================================
# UI — diálogo de erro por linha
# ===========================================================================
def mostrar_erro_linha(num_fila, erro, status, contexto: str = "") -> str:
    """Exibe o dialogo de erro imediatamente e consulta a IA em segundo plano.

    Antes, a sugestao da Groq era buscada de forma sincrona (bloqueando a thread
    de automacao por ate ~15s) antes do dialogo aparecer. Agora o dialogo abre
    na hora e a sugestao e preenchida assincronamente.
    """
    status.config(text=f"L{num_fila}: ERRO — aguardando decisão...")
    resultado = tk.StringVar(value="")

    tem_ia = bool(GROQ_API_KEY)
    altura = 380 if tem_ia else 300
    janela = tk.Toplevel()
    janela.title(f"⚠ Erro na Linha {num_fila}")
    janela.geometry(f"520x{altura}")
    janela.configure(bg=CARD)
    janela.grab_set()
    janela.lift()
    janela.focus_force()

    tk.Label(
        janela, text=f"Erro na Linha {num_fila}",
        font=("Segoe UI", 13, "bold"), bg=CARD, fg="#F59E0B",
    ).pack(pady=(18, 6))
    tk.Label(
        janela, text=str(erro)[:300], wraplength=480,
        font=("Segoe UI", 9), bg=CARD, fg=TEXTO, justify="left",
    ).pack(padx=20)

    if tem_ia:
        tk.Frame(janela, bg=BORDER, height=1).pack(fill="x", padx=20, pady=8)
        tk.Label(janela, text="Sugestão da IA:", font=("Segoe UI", 8, "bold"),
                 bg=CARD, fg=SUBTEXTO).pack(anchor="w", padx=20)
        lbl_ia = tk.Label(
            janela, text="🤖  Consultando assistente...", wraplength=480,
            font=("Segoe UI", 8), bg=CARD, fg=SUBTEXTO, justify="left",
        )
        lbl_ia.pack(padx=20)

        def _carregar_ia():
            sugestao = analisar_erro_com_ia(str(erro), contexto)
            texto = (sugestao or "Não foi possível consultar o assistente.")[:400]
            try:
                lbl_ia.config(text=texto)
            except Exception:
                pass  # janela ja fechada

        threading.Thread(target=_carregar_ia, daemon=True).start()

    tk.Label(janela, text="O que deseja fazer?",
             font=("Segoe UI", 10), bg=CARD, fg=SUBTEXTO).pack(pady=(12, 4))

    frame_btns = tk.Frame(janela, bg=CARD)
    frame_btns.pack(pady=12)

    for texto, cor, valor in [
        ("🔄  REPETIR LINHA", "#2563EB", "repetir"),
        ("⏭  PULAR LINHA", "#F59E0B", "pular"),
        ("⏹  PARAR TUDO", "#EF4444", "parar"),
    ]:
        tk.Button(
            frame_btns, text=texto, font=("Segoe UI", 10, "bold"),
            bg=cor, fg="white", relief="flat", width=16,
            command=lambda v=valor: [resultado.set(v), janela.destroy()],
        ).pack(side="left", padx=6)

    janela.wait_window()
    return resultado.get()


# ===========================================================================
# UI — janela de histórico de execuções
# ===========================================================================
_COLUNAS_HIST_VIEW = ("Data", "Classe", "Processo", "Magistrado", "Aviso")
_LARGURAS = {"Data": 90, "Classe": 200, "Processo": 160, "Magistrado": 130, "Aviso": 220}


def abrir_consulta():
    janela = tk.Toplevel()
    janela.title("Histórico de Execuções")
    janela.geometry("900x560")
    janela.configure(bg=BG)
    janela.resizable(True, True)

    # Barra de busca
    barra = tk.Frame(janela, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    barra.pack(fill="x", padx=10, pady=(10, 0))

    tk.Label(barra, text="Buscar:", font=(FONT, 9), bg=CARD, fg=SUBTEXTO).pack(side="left", padx=(10, 4), pady=8)
    busca_var = tk.StringVar()
    tk.Entry(
        barra, textvariable=busca_var, font=(FONT, 9),
        bg=INPUT_BG, fg=TEXTO, insertbackground=AZUL,
        relief="flat", highlightbackground=BORDER, highlightthickness=1,
        width=30,
    ).pack(side="left", padx=(0, 10), pady=6, ipady=4)

    total_label = tk.Label(barra, text="", font=(FONT, 8), bg=CARD, fg=SUBTEXTO)
    total_label.pack(side="right", padx=10)

    # Notebook com abas
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Hist.Treeview", background=CARD, foreground=TEXTO,
                    fieldbackground=CARD, rowheight=24, font=(FONT, 9))
    style.configure("Hist.Treeview.Heading", background=BORDER, foreground=SUBTEXTO,
                    font=(FONT, 9, "bold"))
    style.map("Hist.Treeview", background=[("selected", AZUL)])
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=CARD, foreground=SUBTEXTO,
                    font=(FONT, 9), padding=(12, 5))
    style.map("TNotebook.Tab", background=[("selected", BORDER)], foreground=[("selected", TEXTO)])

    notebook = ttk.Notebook(janela)
    notebook.pack(fill="both", expand=True, padx=10, pady=8)

    trees = {}
    for aba, titulo in (("todos", "Todos"), ("erros", "⚠ Com Erros / Avisos")):
        frame_aba = tk.Frame(notebook, bg=BG)
        notebook.add(frame_aba, text=titulo)

        tree = ttk.Treeview(frame_aba, columns=_COLUNAS_HIST_VIEW, show="headings", style="Hist.Treeview")
        for col in _COLUNAS_HIST_VIEW:
            tree.heading(col, text=col, command=lambda c=col, t=tree: _ordenar(t, c, False))
            tree.column(col, width=_LARGURAS.get(col, 120), anchor="w")
        tree.tag_configure("erro", foreground="#e74c3c")
        tree.tag_configure("aviso", foreground="#f39c12")

        vsb = ttk.Scrollbar(frame_aba, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame_aba, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame_aba.rowconfigure(0, weight=1)
        frame_aba.columnconfigure(0, weight=1)
        trees[aba] = tree

    todos_dados = []

    def _carregar():
        nonlocal todos_dados
        todos_dados = ler_historico()
        _filtrar()

    def _filtrar(*_):
        termo = busca_var.get().lower()
        for t in trees.values():
            t.delete(*t.get_children())

        total = exibidos_todos = exibidos_erros = 0
        for row in todos_dados:
            vals = (
                row.get("Data", ""),
                row.get("Classe", ""),
                row.get("Processo", ""),
                row.get("Magistrado", ""),
                row.get("Aviso", ""),
            )
            if termo and not any(termo in str(v).lower() for v in vals):
                continue

            aviso = row.get("Aviso", "").strip()
            classe = row.get("Classe", "").lower()
            tag = "erro" if "erro" in classe else ("aviso" if aviso else "")

            trees["todos"].insert("", tk.END, values=vals, tags=(tag,) if tag else ())
            exibidos_todos += 1

            if tag:
                trees["erros"].insert("", tk.END, values=vals, tags=(tag,))
                exibidos_erros += 1

            total += 1

        total_label.config(
            text=f"{exibidos_todos} registros · {exibidos_erros} com erros/avisos"
        )

    busca_var.trace_add("write", _filtrar)

    # Rodapé
    rodape = tk.Frame(janela, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    rodape.pack(fill="x", padx=10, pady=(0, 10))
    make_btn(rodape, "ATUALIZAR", VERDE, _carregar, width=16).pack(side="left", padx=10, pady=6, ipady=4)
    tk.Label(rodape, text="Arquivo: ~/.aura_cotri/processos_ajuizados.csv",
             font=(FONT, 8), bg=CARD, fg=SUBTEXTO).pack(side="left", padx=4)

    _carregar()


def _ordenar(tree, col, reverso):
    dados = [(tree.set(k, col), k) for k in tree.get_children("")]
    dados.sort(reverse=reverso)
    for i, (_, k) in enumerate(dados):
        tree.move(k, "", i)
    tree.heading(col, command=lambda: _ordenar(tree, col, not reverso))


# ===========================================================================
# DPI / scaling e configuração do customtkinter
# ===========================================================================
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

try:
    import customtkinter.windows.widgets.ctk_scrollable_frame as _ctk_sf
    _orig = _ctk_sf.CTkScrollableFrame.check_if_master_is_canvas
    def _patched(self, w):
        try:
            return _orig(self, w)
        except AttributeError:
            return False
    _ctk_sf.CTkScrollableFrame.check_if_master_is_canvas = _patched
except Exception:
    pass


_scale = _detectar_scaling()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
ctk.set_window_scaling(_scale)
ctk.set_widget_scaling(_scale)
ctk.deactivate_automatic_dpi_awareness()

# ---------------------------------------------------------------------------
# Tema do app principal
# ---------------------------------------------------------------------------
COR_BG       = "#0f1117"
COR_PAINEL   = "#1a1d27"
COR_BORDA    = "#2a2d3e"
COR_PRIMARIA = "#4f8ef7"
COR_HOVER    = "#3a6fd8"
COR_SUCESSO  = "#2ecc71"
COR_AVISO    = "#f39c12"
COR_ERRO     = "#e74c3c"
COR_TEXTO    = "#e8eaf0"
COR_SUBTEXTO = "#7c8098"
COR_INPUT_BG = "#252836"
COR_ROXO     = "#6c63ff"


# ---------------------------------------------------------------------------
# Status com log colorido — intercepta .config(text=) e grava no painel de log
# ---------------------------------------------------------------------------
_COR_OK    = "#2ecc71"
_COR_ERRO  = "#e74c3c"
_COR_AVISO = "#f39c12"
_COR_INFO  = "#4f8ef7"
_COR_SEP   = "#2a2d3e"


class _StatusComLog:
    def __init__(self, label, log_widget: tk.Text, dot_label):
        self._label = label
        self._log = log_widget
        self._dot = dot_label
        log_widget.tag_configure("ok",    foreground=_COR_OK)
        log_widget.tag_configure("erro",  foreground=_COR_ERRO)
        log_widget.tag_configure("aviso", foreground=_COR_AVISO)
        log_widget.tag_configure("info",  foreground=_COR_INFO)
        log_widget.tag_configure("sep",   foreground=_COR_SEP)

    def config(self, **kwargs):
        texto = kwargs.get("text", "")
        if texto:
            self._label.configure(text=texto)
        if not texto:
            return
        tag = self._tag(texto)
        ts = time.strftime("%H:%M:%S")
        self._log.config(state="normal")
        if any(k in texto.lower() for k in ("preparando", "consultando processo")):
            self._log.insert(tk.END, "─" * 60 + "\n", "sep")
        self._log.insert(tk.END, f"[{ts}] {texto}\n", tag)
        self._log.see(tk.END)
        self._log.config(state="disabled")
        self._dot.configure(text_color=self._cor_dot(tag, texto.lower()))

    def _tag(self, texto):
        t = texto.lower()
        if any(k in t for k in ("concluído", "concluido", "sucesso", "✅", "redistribuido", "finalizado")):
            return "ok"
        if any(k in t for k in ("erro", "falha", "nao foi possivel", "interrompido", "inconsistencia")):
            return "erro"
        if any(k in t for k in ("pulando", "aviso", "aguardando", "pausado", "sem número")):
            return "aviso"
        return "info"

    def _cor_dot(self, tag, texto_lower):
        if "pausado" in texto_lower or "pausar" in texto_lower:
            return COR_AVISO
        if tag == "ok":
            return _COR_OK
        if tag == "erro":
            return _COR_ERRO
        return _COR_INFO


# ===========================================================================
# APP PRINCIPAL
# ===========================================================================
class AuraCotriApp(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("AURA COTRI")
        self.configure(fg_color=COR_BG)
        self.after(200, self._aplicar_icone)

        _cfg = carregar_config()
        usuario = (_cfg.get("usuario") or USUARIO_PADRAO).strip()
        senha = (_cfg.get("senha") or SENHA_PADRAO).strip()
        url = (_cfg.get("url") or URL_PADRAO).strip()
        salvar_config(usuario, senha, url)

        self._state = AppState(usuario=usuario, senha=senha, url=url)
        self.geometry("560x820")
        self.resizable(True, True)
        self.minsize(520, 700)
        self._build_principal()
        threading.Thread(target=self._checar_update, daemon=True).start()

    def _aplicar_icone(self):
        # Define o icone da janela (barra de titulo / barra de tarefas) com a
        # logo do AURA COTRI. Nunca deve quebrar a abertura caso o arquivo falte.

        # 1) Windows: .ico nativo (melhor na barra de tarefas), se existir.
        try:
            ico = base_path("aura_logo.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        # 2) Multiplataforma: usa a propria logo (aura_logo.png) como icone,
        #    centralizada num canvas quadrado para nao distorcer e ficar legivel.
        try:
            img = Image.open(base_path("aura_logo.png")).convert("RGBA")
            lado = max(img.width, img.height)
            quadrado = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
            quadrado.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2), img)
            quadrado = quadrado.resize((64, 64), Image.LANCZOS)
            # Mantem a referencia viva (Tk descarta PhotoImage sem referencia).
            self._icone_ref = ImageTk.PhotoImage(quadrado)
            self.iconphoto(True, self._icone_ref)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _logo_img(self, size=(73, 67)):
        # aura_logo.png nao tem canal alpha (fundo branco solido), entao
        # convertemos os pixels quase-brancos para transparentes — mesma
        # tecnica usada em aura.py (AURA principal) para a mesma logo.
        try:
            img = Image.open(base_path("aura_logo.png")).convert("RGBA")
            dados = img.getdata()
            img.putdata([(r, g, b, 0) if r > 220 and g > 220 and b > 220 else (r, g, b, a)
                         for r, g, b, a in dados])
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _build_login(self):
        self.frame_login = ctk.CTkFrame(self, fg_color=COR_BG, corner_radius=0)
        self.frame_login.pack(fill="both", expand=True)

        header = ctk.CTkFrame(self.frame_login, fg_color=COR_PAINEL, corner_radius=0)
        header.pack(fill="x")
        logo = self._logo_img((73, 67))
        if logo:
            ctk.CTkLabel(header, image=logo, text="", fg_color="transparent").pack(pady=(16, 0))
        ctk.CTkLabel(header, text="AURA COTRI",
                     font=ctk.CTkFont("Segoe UI", 28, "bold"),
                     text_color=COR_PRIMARIA).pack()
        ctk.CTkLabel(header, text="Assinatura e Redistribuição de Processos",
                     font=ctk.CTkFont("Segoe UI", 10), text_color="#6B7280").pack(pady=(2, 0))
        ctk.CTkLabel(header, text="Desenvolvido por CESUPE  ·  TJMG",
                     font=ctk.CTkFont("Segoe UI", 8), text_color="#4B5563").pack(pady=(2, 12))

        card = ctk.CTkFrame(self.frame_login, fg_color=COR_PAINEL,
                            corner_radius=10, border_width=1, border_color=COR_BORDA)
        card.pack(padx=40, pady=20, fill="x")

        _cfg = carregar_config()

        def campo(label, show=None, default=""):
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont("Segoe UI", 9),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=20, pady=(10, 2))
            e = ctk.CTkEntry(card, font=ctk.CTkFont("Segoe UI", 11),
                             fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                             border_color=COR_BORDA, border_width=1,
                             corner_radius=6, height=36, show=show or "")
            if default:
                e.insert(0, default)
            e.pack(fill="x", padx=20)
            return e

        self.entry_usuario = campo("USUÁRIO EPROC", default=_cfg.get("usuario", ""))
        self.entry_senha   = campo("SENHA", show="*", default=_cfg.get("senha", ""))
        self.entry_url     = campo("URL DO SISTEMA",
                                   default=_cfg.get("url", "https://eproc2g-hml.tjmg.jus.br/eproc/"))

        ctk.CTkFrame(card, fg_color=COR_BORDA, height=1).pack(fill="x", padx=20, pady=16)
        ctk.CTkButton(card, text="→  ACESSAR SISTEMA",
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      fg_color=COR_PRIMARIA, hover_color=COR_HOVER,
                      height=42, corner_radius=8,
                      command=self._confirmar_login).pack(fill="x", padx=20, pady=(0, 20))
        self.bind("<Return>", lambda e: self._confirmar_login())
        ctk.CTkLabel(self.frame_login, text=f"v{VERSAO_ATUAL} · 2026 · CESUPE / TJMG",
                     font=ctk.CTkFont("Segoe UI", 8), text_color=COR_BORDA).pack(pady=8)

    def _confirmar_login(self):
        usuario = self.entry_usuario.get().strip()
        senha   = self.entry_senha.get().strip()
        url     = self.entry_url.get().strip()
        if not (usuario and senha and url):
            messagebox.showerror("AURA COTRI", "Preencha todos os campos.")
            return
        salvar_config(usuario, senha, url)
        self._state = AppState(usuario=usuario, senha=senha, url=url)
        self.frame_login.destroy()
        self.geometry("560x820")
        self.resizable(True, True)
        self.minsize(520, 700)
        self._build_principal()
        threading.Thread(target=self._checar_update, daemon=True).start()

    def _checar_update(self):
        tem, versao_nova, url_dl = verificar_atualizacao()
        if tem:
            self.after(0, lambda: self._avisar_update(versao_nova, url_dl))

    def _avisar_update(self, versao_nova, url_dl):
        jan = ctk.CTkToplevel(self)
        jan.title("Atualização disponível")
        jan.geometry("420x200")
        jan.configure(fg_color=COR_PAINEL)
        jan.grab_set()
        jan.lift()
        ctk.CTkLabel(jan, text="Nova versão disponível!",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_SUCESSO).pack(pady=(20, 4))
        ctk.CTkLabel(jan, text=f"Atual: v{VERSAO_ATUAL}  →  Nova: v{versao_nova}",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=COR_SUBTEXTO).pack()

        def abrir():
            import webbrowser
            webbrowser.open(url_dl)
            jan.destroy()

        ctk.CTkButton(jan, text="Baixar atualização",
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      fg_color=COR_SUCESSO, hover_color="#27ae60",
                      height=38, corner_radius=8, command=abrir).pack(padx=30, fill="x", pady=(16, 4))
        ctk.CTkButton(jan, text="Agora não", font=ctk.CTkFont("Segoe UI", 9),
                      fg_color="transparent", hover_color=COR_BORDA,
                      text_color=COR_SUBTEXTO, height=28,
                      command=jan.destroy).pack(pady=4)

    # ------------------------------------------------------------------
    def _build_principal(self):
        state = self._state

        # Topbar
        topbar = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0,
                              border_width=1, border_color=COR_BORDA)
        topbar.pack(fill="x")
        logo2 = self._logo_img((32, 29))
        if logo2:
            ctk.CTkLabel(topbar, image=logo2, text="",
                         fg_color="transparent").pack(side="left", padx=(12, 4), pady=6)
        ctk.CTkLabel(topbar, text="AURA COTRI",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_PRIMARIA).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(topbar, text="Modulo COTRI/CODIPRE — Assinatura e Redistribuição",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_SUBTEXTO).pack(side="left")
        ctk.CTkLabel(topbar, text=f"v{VERSAO_ATUAL}",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_BORDA).pack(side="right", padx=12)
        ctk.CTkButton(topbar, text="TROCAR LOGIN",
                      font=ctk.CTkFont("Segoe UI", 9),
                      fg_color="#21262D", hover_color=COR_BORDA,
                      height=28, corner_radius=6, width=110,
                      command=self._voltar_login).pack(side="right", padx=8, pady=7)

        # Status bar (bottom)
        status_bar = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0,
                                  border_width=1, border_color=COR_BORDA, height=30)
        status_bar.pack(fill="x", side="bottom")
        dot_lbl = ctk.CTkLabel(status_bar, text="●", font=ctk.CTkFont("Segoe UI", 10),
                               text_color=COR_SUCESSO)
        dot_lbl.pack(side="left", padx=(12, 4))
        status_lbl = ctk.CTkLabel(status_bar, text="Aguardando...",
                                  font=ctk.CTkFont("Segoe UI", 9),
                                  text_color=COR_SUBTEXTO)
        status_lbl.pack(side="left")

        self._lbl_pct = ctk.CTkLabel(status_bar, text="",
                                     font=ctk.CTkFont("Segoe UI", 9, "bold"),
                                     text_color=COR_SUBTEXTO)
        self._lbl_pct.pack(side="right", padx=12)

        # Barra de progresso (fica logo acima da status bar)
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=0,
                                           fg_color=COR_BORDA, progress_color=COR_PRIMARIA)
        self.progress.set(0)
        self.progress.pack(fill="x", side="bottom")

        # Dict que armazenará o status após criação do log widget
        status_ref = {}

        # Corpo scrollável
        corpo = ctk.CTkScrollableFrame(self, fg_color=COR_BG, corner_radius=0,
                                       scrollbar_button_color=COR_BORDA,
                                       scrollbar_button_hover_color=COR_PRIMARIA)
        corpo.pack(fill="both", expand=True, padx=16, pady=12)

        def secao(titulo):
            f = ctk.CTkFrame(corpo, fg_color=COR_PAINEL, corner_radius=8,
                             border_width=1, border_color=COR_BORDA)
            f.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(f, text=titulo, font=ctk.CTkFont("Segoe UI", 9, "bold"),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=14, pady=(10, 4))
            ctk.CTkFrame(f, fg_color=COR_BORDA, height=1).pack(fill="x", padx=14, pady=(0, 8))
            return f

        def btn(parent, texto, cor, cmd):
            ctk.CTkButton(parent, text=texto,
                          font=ctk.CTkFont("Segoe UI", 11, "bold"),
                          fg_color=cor, hover_color=_lighten(cor),
                          height=40, corner_radius=7,
                          command=cmd).pack(fill="x", padx=14, pady=3)

        def row_arquivo(parent, texto_btn, cmd):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkButton(row, text=texto_btn, font=ctk.CTkFont("Segoe UI", 10),
                          fg_color="#21262D", hover_color=COR_BORDA,
                          width=180, height=34, corner_radius=6,
                          command=cmd).pack(side="left")
            lbl = ctk.CTkLabel(row, text="nenhum arquivo selecionado",
                               font=ctk.CTkFont("Segoe UI", 9),
                               text_color=COR_SUBTEXTO)
            lbl.pack(side="left", padx=10)
            return lbl

        # ── ARQUIVO CSV (Assinatura) ───────────────────────────────────
        s_arq = secao("ARQUIVO")
        ctk.CTkLabel(s_arq, text="CSV com a coluna Numero do processo",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_BORDA).pack(anchor="w", padx=14, pady=(0, 4))

        def sel_csv():
            f = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
            if f:
                state.caminho_planilha = f
                lbl_csv.configure(text=os.path.basename(f), text_color=COR_SUCESSO)

        lbl_csv = row_arquivo(s_arq, "PLANILHA CSV", sel_csv)

        # Perfil
        row_perfil = ctk.CTkFrame(s_arq, fg_color="transparent")
        row_perfil.pack(fill="x", padx=14, pady=(8, 10))
        ctk.CTkLabel(row_perfil, text="Perfil de trabalho:",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO).pack(side="left", padx=(0, 10))
        perfil_var = tk.StringVar(value=getattr(state, "perfil", "COTRI") or "COTRI")

        def alterar_perfil(*_):
            state.perfil = perfil_var.get()

        perfil_var.trace_add("write", alterar_perfil)
        for p in ("COTRI", "CODIPRE"):
            tk.Radiobutton(row_perfil, text=p, value=p, variable=perfil_var,
                           command=alterar_perfil,
                           font=("Segoe UI", 9, "bold"),
                           bg=COR_PAINEL, fg=COR_SUBTEXTO,
                           activebackground=COR_PAINEL,
                           activeforeground=COR_PRIMARIA,
                           selectcolor=COR_INPUT_BG,
                           cursor="hand2").pack(side="left", padx=(0, 12))

        # ── ASSINATURA COTRI / CODIPRE ─────────────────────────────────
        s_ass = secao("ASSINATURA COTRI / CODIPRE")
        ctk.CTkLabel(s_ass, text="COTRI: PPG  |  CODIPRE: Competência de Direito Privado",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_BORDA).pack(anchor="w", padx=14, pady=(0, 4))

        def iniciar_assinatura():
            self.progress.set(0)
            threading.Thread(
                target=executar_assinatura_cotri,
                args=(state, status_ref["status"], self._atualizar_progresso),
                daemon=True,
            ).start()

        btn(s_ass, "▶  ASSINAR — COTRI / CODIPRE", COR_PRIMARIA, iniciar_assinatura)

        btn_pausa_ass = ctk.CTkButton(
            s_ass, text="⏸  PAUSAR",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            fg_color=COR_AVISO, hover_color=_lighten(COR_AVISO),
            height=38, corner_radius=7)

        def toggle_pausa_ass():
            state.pausado = not state.pausado
            if state.pausado:
                btn_pausa_ass.configure(text="▶  RETOMAR", fg_color=COR_SUCESSO,
                                        hover_color=_lighten(COR_SUCESSO))
            else:
                btn_pausa_ass.configure(text="⏸  PAUSAR", fg_color=COR_AVISO,
                                        hover_color=_lighten(COR_AVISO))

        btn_pausa_ass.configure(command=toggle_pausa_ass)
        btn_pausa_ass.pack(fill="x", padx=14, pady=(3, 10))

        # ── REDISTRIBUIÇÃO ─────────────────────────────────────────────
        s_red = secao("REDISTRIBUIÇÃO")
        ctk.CTkLabel(s_red, text="Abre redistribuição e preenche os campos conforme a planilha",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_BORDA).pack(anchor="w", padx=14, pady=(0, 4))

        def sel_redist():
            f = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
            if f:
                state.caminho_redistribuicao = f
                lbl_redist.configure(text=os.path.basename(f), text_color=COR_SUCESSO)

        def sel_refs():
            f = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
            if f:
                state.caminho_referencias_redistribuicao = f
                lbl_refs.configure(text=os.path.basename(f), text_color=COR_SUCESSO)

        lbl_redist = row_arquivo(s_red, "PLANILHA REDISTRIBUIÇÃO", sel_redist)
        lbl_refs   = row_arquivo(s_red, "CSV REFERÊNCIAS", sel_refs)

        def iniciar_redistribuicao():
            self.progress.set(0)
            threading.Thread(
                target=executar_redistribuicao_cotri,
                args=(state, status_ref["status"], self._atualizar_progresso),
                daemon=True,
            ).start()

        btn(s_red, "▶  REDISTRIBUIR PROCESSOS", COR_ROXO, iniciar_redistribuicao)
        ctk.CTkFrame(s_red, fg_color="transparent", height=4).pack()

        # ── REGISTROS ─────────────────────────────────────────────────
        s_reg = secao("REGISTROS")

        # Painel de log em tempo real (tk.Text nativo dentro do CTK)
        log_outer = tk.Frame(s_reg, bg=COR_PAINEL)
        log_outer.pack(fill="x", padx=14, pady=(0, 6))

        log_text = tk.Text(
            log_outer,
            bg="#0d1117", fg=COR_SUBTEXTO,
            font=("Consolas", 8),
            relief="flat",
            highlightbackground=COR_BORDA, highlightthickness=1,
            state="disabled",
            wrap="none",
            height=10,
        )
        vsb_log = tk.Scrollbar(log_outer, orient="vertical", command=log_text.yview)
        log_text.configure(yscrollcommand=vsb_log.set)
        log_text.pack(side="left", fill="both", expand=True)
        vsb_log.pack(side="right", fill="y")

        def _limpar_log():
            log_text.config(state="normal")
            log_text.delete("1.0", tk.END)
            log_text.config(state="disabled")

        def _exportar_log():
            caminho = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Arquivo de texto", "*.txt")],
                initialfile=f"aura_log_{time.strftime('%Y%m%d_%H%M%S')}.txt",
            )
            if caminho:
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(log_text.get("1.0", tk.END))

        row_log = ctk.CTkFrame(s_reg, fg_color="transparent")
        row_log.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkButton(row_log, text="🗂  CONSULTAR HISTÓRICO",
                      font=ctk.CTkFont("Segoe UI", 10, "bold"),
                      fg_color=COR_SUCESSO, hover_color=_lighten(COR_SUCESSO),
                      height=34, corner_radius=7,
                      command=abrir_consulta).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row_log, text="📄  RELATÓRIO DO DIA",
                      font=ctk.CTkFont("Segoe UI", 10, "bold"),
                      fg_color=COR_ROXO, hover_color=_lighten(COR_ROXO),
                      height=34, corner_radius=7,
                      command=abrir_relatorio_html).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row_log, text="EXPORTAR LOG",
                      font=ctk.CTkFont("Segoe UI", 10),
                      fg_color=COR_PRIMARIA, hover_color=_lighten(COR_PRIMARIA),
                      height=34, corner_radius=7,
                      command=_exportar_log).pack(side="left", padx=(0, 4))
        ctk.CTkButton(row_log, text="LIMPAR LOG",
                      font=ctk.CTkFont("Segoe UI", 10),
                      fg_color=COR_BORDA, hover_color=_lighten(COR_BORDA),
                      height=34, corner_radius=7,
                      command=_limpar_log).pack(side="left")
        ctk.CTkFrame(s_reg, fg_color="transparent", height=4).pack()

        # Inicializa o status com log e dot
        status_ref["status"] = _StatusComLog(status_lbl, log_text, dot_lbl)

    # ------------------------------------------------------------------
    def _atualizar_progresso(self, atual, total):
        """Callback thread-safe para atualizar a barra de progresso e o %.

        Chamado pelas threads de automacao; agenda a atualizacao no laco
        principal do Tk via self.after para evitar acesso cross-thread direto.
        """
        frac = (atual / total) if total else 0
        frac = max(0.0, min(frac, 1.0))

        def _aplicar():
            try:
                self.progress.set(frac)
                self._lbl_pct.configure(text=f"{int(frac * 100)}%  ({atual}/{total})")
            except Exception:
                pass

        try:
            self.after(0, _aplicar)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _voltar_login(self):
        for widget in self.winfo_children():
            widget.destroy()
        self.geometry("520x620")
        self.resizable(False, False)
        self._state = None
        self._build_login()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _root = ctk.CTk()
    _root.withdraw()
    app = AuraCotriApp(_root)
    app.protocol("WM_DELETE_WINDOW", _root.destroy)
    app.mainloop()
