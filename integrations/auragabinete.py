"""
AURA GABINETE — RPA de Minutar / Movimentar para o TJMG
Integrado ao AURA (lê processos_ajuizados do Google Sheets via aura_db).
Motor: EprocBotV4 · Visual: AURA Design System
Requisitos: pip install selenium customtkinter pillow webdriver-manager
"""

# ══════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════
import os, sys, re, time, logging, threading, unicodedata, json, subprocess, shutil

# Modulos compartilhados vivem em shared/ (pasta irma desta, integrations/)
# -- necessario ao rodar este arquivo standalone (import de sibling nao acha
# shared/ sozinho). Quando importado pelo aura.py, ja esta no sys.path, mas
# nao ha problema em inserir de novo.
_caminho_shared = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared")
if _caminho_shared not in sys.path:
    sys.path.insert(0, _caminho_shared)

import tkinter as tk
import tkinter.scrolledtext as _st
from tkinter import filedialog, messagebox
from datetime import datetime
from aura_db import ler_processos_ajuizados
from aura_infra import criar_chrome_driver
from logging.handlers import RotatingFileHandler
import AURAAGENT as _agente_mod

import customtkinter as ctk
from PIL import Image, ImageTk

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, ElementClickInterceptedException,
    StaleElementReferenceException, UnexpectedAlertPresentException,
    NoAlertPresentException, JavascriptException,
)
from webdriver_manager.chrome import ChromeDriverManager


# ══════════════════════════════════════════════
# AURA Design System
# ══════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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

# ══════════════════════════════════════════════
# Eventos Cíveis
# ══════════════════════════════════════════════
EVENTOS_CIVEIS = [
    'Acolhida a exceção de Impedimento ou Suspeição',
    'Acolhida a exceção de Incompetência',
    'Acolhida exceção de pré-executividade',
    'Adiamento do Julgamento (Art. 935 do CPC)',
    'Admissão de Incidente de Assunção de Competência',
    'Admissão de Incidente de Resolução de Demandas Repetitivas',
    'Afetação ao rito dos recursos repetitivos',
    'Aguarda Decisão RESP Repetitivo (STJ) e REXT com Repercussão Geral (STF)',
    'Anulada a(o) sentença/acórdão',
    'Assistência Judiciária Gratuita não concedida a parte',
    'Autorizada saída temporária',
    'Autorizado Trabalho Externo',
    'Baixa Definitiva',
    'Baixa Definitiva - Declinada Competência',
    'Baixa Definitiva - Por erro de distribuição',
    'Baixa Definitiva - Remetido a(o)',
    'Baixa Definitiva - Remetido à Conciliação',
    'Cancelamento de Distribuição',
    'Comunicação eletrônica recebida - baixado',
    'Comunicação eletrônica recebida - decisão proferida em',
    'Comunicação eletrônica recebida - distribuído',
    'Comunicação eletrônica recebida - julgado',
    'Concedida a Antecipação de tutela',
    'Concedida a Assistência Judiciária Gratuita a parte',
    'Concedida a Medida Liminar',
    'Concedida a Permissão de saída',
    'Concedida a Segurança',
    'Concedida a substituição/sucessão de parte',
    'Concedida em parte a Antecipação de Tutela',
    'Concedida em parte a Medida Liminar',
    'Concedida em parte a Segurança',
    'Concedido Direito de visita',
    'Concedido efeito suspensivo Impugnação ao cumprimento de sentença',
    'Concedido efeito suspensivo ao recurso',
    'Concedido em parte o Habeas Data',
    'Concedido em parte o Mandado de Injunção',
    'Concedido o Habeas Data',
    'Concedido o Mandado de injunção',
    'Concedido o indulto',
    'Conhecido em parte o recurso e não-provido',
    'Conhecido em parte o recurso e provido',
    'Conhecido em parte o recurso e provido em parte',
    'Conhecido o recurso e não provido',
    'Conhecido o recurso e não-provido',
    'Conhecido o recurso e provido',
    'Conhecido o recurso e provido em parte',
    'Convertido o julgamento em diligência',
    'Decisão Interlocutória de Mérito',
    'Decisão final em incidente revogada',
    'Decisão interlocutória',
    'Embargos Infringentes - Admitidos',
    'Embargos Infringentes - Inadmitidos',
    'de Expediente Abrindo vista ao MP',
    'de Expediente Indeferindo o pedido',
    'de Expediente deferindo o pedido',
    'Declarada decadência ou prescrição',
    'Declarada incompetência',
    'Declarada suspeição',
    'Declarado competente',
    'Declarado competente outro juízo',
    'Declarado impedimento',
    'Decretada a indisponibilidade de bens',
    'Decretada a revelia',
    'Deferido o pedido',
    'Definição de tese jurídica no incidente repetitivo',
    'Deliberado em Sessão - Adiado',
    'Deliberado em Sessão - Convertido em diligência',
    'Deliberado em Sessão - Pedido de Vista',
    'Deliberado em Sessão - Retificado',
    'Deliberado em Sessão - Sobrestado',
    'Deliberado em Sessão - Sobrestado - art. 942 do CPC',
    'Deliberado em Sessão - declinada a competência',
    'Denegada a Segurança',
    'Denegado o Habeas Data',
    'Denegado o Mandado de injunção',
    'Desafetação ao Rito dos Recursos Repetititvos',
    'Despacho',
    'Arquivamento',
    'Declinada a Competência',
    'Determina Citação',
    'Determina Intimação',
    'Embargos de Declaração - Não Conhecidos',
    'Embargos de Declaração - Rejeitados',
    'Final em Incidente Revogada',
    'Impedimento/Suspeição',
    'Interlocutória',
    'Interlocutória Convertendo em RE retido',
    'Interlocutória Convertendo em REsp retido',
    'Interlocutória Deferida em parte',
    'Liminar/Antecipação de Tutela Deferida',
    'Liminar/Antecipação de Tutela Indeferida',
    'Liminar/Antecipação de Tutela Revogada',
    'Substituição/Sucessão',
    'Terminativa - Declarando Competência',
    'Terminativa - Indeferimento da Inicial',
    'Terminativa - Julgando extinto o processo',
    'Terminativa - Negando seguimento',
    'Terminativa - Não conhecimento',
    'Terminativa Improvimento',
    'Terminativa Provimento',
    'Terminativa Provimento em Parte',
    'de Expediente',
    'Determinada Requisição de Informações',
    'Determinada a citação',
    'Determinada a emenda à inicial',
    'Determinada a intimação',
    'Determinada a quebra do sigilo bancário',
    'Determinada a quebra do sigilo fiscal',
    'Determinada a quebra do sigilo telemático',
    'Determinado o Arquivamento',
    'Determinado o Levantamento da Suspensão ou Dessobrestamento',
    'Determinado o bloqueio/penhora on line',
    'Determinado o cancelamento da distribuição',
    'Determinação de suspensão ou sobrestamento em razão de prescrição intercorrente',
    'Distribuído por dependência',
    'Distribuído por prevenção',
    'Distribuído por sorteio',
    'Embargos Infringentes e de Nulidade Admitidos',
    'Embargos Infringentes e de Nulidade Não Admitidos',
    'Embargos de Declaração Acolhidos',
    'Embargos de Declaração Acolhidos em Parte',
    'Embargos de Declaração Não Acolhidos',
    'Embargos de Declaração Não-acolhidos',
    'Emitido Juízo de retratação pelo colegiado',
    'Emitido Juízo de retratação pelo colegiado (pai)',
    'Expedição de mandado de notificação',
    'Expedição de ofício',
    'Extinta a execução ou o cumprimento da sentença',
    'Extinto o processo por Perempção, litispendência ou coisa julgada',
    'Extinto o processo por abandono da causa pelo autor',
    'Extinto o processo por ausência das condições da ação',
    'Extinto o processo por ausência de pressupostos processuais',
    'Extinto o processo por convenção de arbitragem',
    'Extinto o processo por desistência',
    'Extinto o processo por negligência das partes',
    'Extinto o processo por ser a ação intransmissível',
    'Extinto o processo sem resolução de mérito por continência',
    'Extinto o processo sem resolução do mérito',
    'Homologada renúncia pelo autor',
    'Homologado o Acordo em Execução ou em Cumprimento de Sentença',
    'Indeferida a petição inicial',
    'Indeferido o Arquivamento',
    'Indeferido o pedido',
    'Julgado improcedente o pedido',
    'Julgado procedente em parte o pedido',
    'Julgado procedente o pedido',
    'Julgamento - Declarando competência',
    'Julgamento - Referendada a Decisão Monocrática',
    'Julgamento Anulado',
    'Julgamento Retificado - Declarando Competência',
    'Julgamento Retificado - Declinada a Competência',
    'Julgamento Retificado - Improvido',
    'Julgamento Retificado - Não conhecido',
    'Julgamento Retificado - Prejudicado',
    'Julgamento Retificado - Provido em Parte',
    'Julgamento Suscitado Conflito de Competência',
    'Julgamento do Incidente  - Anulado',
    'Julgamento do Incidente - Convertido em Diligência',
    'Julgamento do Incidente - Declarando Competência',
    'Julgamento do Incidente - Declinada a Competência',
    'Julgamento do Incidente - Mantida a Sentença',
    'Julgamento do Incidente - Prorrogado',
    'Julgamento do Incidente - Reformada a Sentença',
    'Julgamento do Incidente - Sobrestado',
    'Julgamento do Incidente - Suscitado Conflito de Competência',
    'Julgamento do Incidente Provido em Parte',
    'Juntada de certidão - traslado de peças para o processo ',
    'Levantada a suspensão do processo em razão de ação coletiva',
    'Levantada a suspensão ou sobrestamento dos autos',
    'Mantido o Acórdão Divergente',
    'Negado seguimento a Recurso',
    'Negado seguimento ao recurso',
    'Não Concedida a Antecipação de tutela',
    'Não Concedida a Medida Liminar',
    'Não conhecido o recurso',
    'Não conhecidos os embargos de declaração',
    'Não ratificada a liminar',
    'Não recebido o recurso',
    'Não-admissão de Incidente de Assunção de Competência',
    'Não-admissão de Incidente de Resolução de Demandas Repetitivas',
    'Outras decisões',
    'Pedido não conhecido',
    'Prejudicada a liminar',
    'Prejudicado',
    'Prejudicado o recurso',
    'Processo  suspenso por Recurso Especial Repetitivo',
    'Processo Suspenso ou Sobrestado Por Decisão Judicial',
    'Processo Suspenso ou Sobrestado por Conflito de Competência',
    'Processo Suspenso ou Sobrestado por Exceção da Verdade',
    'Processo Suspenso ou Sobrestado por Força maior',
    'Processo Suspenso ou Sobrestado por Incidente de Insanidade Mental',
    'Processo Suspenso ou Sobrestado por Recebimento de Embargos de Execução',
    'Processo Suspenso por Convenção das Partes',
    'Processo Suspenso por Exceção de Incompetência, suspeição ou Impedimento',
    'Processo Suspenso por Execução Frustrada',
    'Processo Suspenso por Morte ou perda da capacidade',
    'Processo Suspenso por Recurso Extraordinário com repercussão geral',
    'Processo Suspenso por depender do julgamento de outra causa, de outro juízo ou declaração incidente',
    'Provimento por decisão monocrática',
    'Ratificada a liminar',
    'Ratificada em parte a liminar',
    'Recebida a emenda à inicial',
    'Recebido o recurso com efeito suspensivo',
    'Recebido o recurso sem efeito suspensivo',
    'Recebidos os autos para Diligências',
    'Recurso Especial - Encaminhado para retratação',
    'Recurso Especial não admitido',
    'Recurso Extraordinário - Encaminhado para retratação',
    'Recurso Extraordinário não admitido',
    'Recurso especial admitido',
    'Recurso extraordinário admitido',
    'Reformada decisão anterior',
    'Registrado para Cadastramento Eletrônico de processo físico',
    'Rejeitada a  exceção de incompetência',
    'Rejeitada a exceção de pré-executividade',
    'Rejeitada a representação por ato infracional',
    'Rejeitada exceção de impedimento ou de suspeição',
    'Remetidos os Autos em diligência',
    'Remetidos os Autos para Secretaria de Recursos 1° CAROT',
    'Retirada de pauta',
    'Revogada a Antecipação de Tutela Jurisdicional',
    'Revogada a Assistência Judiciária Gratuita',
    'Revogada a Medida Liminar',
    'Revogada decisão anterior datada',
    'Sentença confirmada',
    'Sentença confirmada em parte',
    'Sentença desconstituída',
    'Suscitado Conflito de Competência',
    'Suspensão por Incidente de Resolução de Demandas Repetitivas',
    'Terminativa Homologando a Desistência',
    'Transitado em Julgado',
    'Vista ao MP',
]

EVENTOS_REMESSA = [
    "Conclusos para decisão com Agravo",
    "Conclusos para decisão com Contrarrazões",
    "Conclusos para decisão com Embargos de Declaração",
    "Conclusos para decisão com Embargos Infringentes e de Nulidade",
    "Conclusos para decisão com Informações",
    "Conclusos para decisão com Ofício",
    "Conclusos para decisão com Parecer do MP",
    "Conclusos para decisão com Petição",
    "Conclusos para decisão/despacho",
    "Conclusos para julgamento - Acórdão",
    "Conclusos para julgamento - Declaração de Voto",
    "Conclusos para julgamento - Relatório/Voto",
    "Conclusos para julgamento - Retificação de Acórdão",
    "Conclusos para julgamento - Revisão",
    "Conclusos para julgamento - Voto Divergente",
    "Conclusos para julgamento - Voto-Vista",
    "Remessa Interna à Contadoria",
    "Remetidos os Autos",
    "Remetidos os Autos - devolução ao Relator pelo Revisor",
    "Remetidos os Autos admitindo a prevenção",
    "Remetidos os Autos com acórdão",
    "Remetidos os Autos com acórdão - Urgente",
    "Remetidos os Autos com decisão/despacho",
    "Remetidos os Autos com decisão/despacho - Urgente",
    "Remetidos os Autos com declaração de voto",
    "Remetidos os Autos com despacho de resolução de dúvida de competência",
    "Remetidos os autos com dúvida/conflito de competência",
    "Remetidos os Autos com ofício",
    "Remetidos os Autos com pedido de dia pelo relator",
    "Remetidos os Autos com pedido de dia pelo revisor",
    "Remetidos os Autos com revisão de autuação",
    "Remetidos os Autos com voto divergente",
    "Remetidos os Autos com voto-vista",
    "Remetidos os Autos em diligência",
    "Remetidos os Autos não admitindo a prevenção",
    "Remetidos os Autos para baixa em diligência",
    "Remetidos os Autos para redistribuir",
    "Remetidos os Autos para revisão da autuação",
    "Remetidos os Autos para vista ao MP",
]

# ══════════════════════════════════════════════
# Configurações
# ══════════════════════════════════════════════
# Planos B (usados só quando o Gabinete roda AVULSO, sem passar pela tela
# inicial). O normal é herdar usuario/senha/url do aura_config.json (a mesma
# fonte da tela inicial do AURA Principal) — ver carregar_config() abaixo.
URL_EPROC_GABINETE_PADRAO = "https://eproc2g-hml.tjmg.jus.br/eproc/"
if hasattr(sys, "_MEIPASS"):
    PASTA_SCRIPT = os.path.dirname(sys.executable)
elif os.environ.get("AURA_BASE_DIR"):
    PASTA_SCRIPT = os.environ["AURA_BASE_DIR"]
else:
    PASTA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
VERSAO_GABINETE      = "9.21"
USUARIO_EPROC_PADRAO = "MG123456"
SENHA_EPROC_PADRAO   = "Senha*123456"
TIMEOUT            = 15
TIMEOUT_LONGO      = 45

RE_SESSAO_EXPIRADA = re.compile(
    r"(Sua%20sess%E3o%20foi%20encerrada|Link%20sem%20assinatura"
    r"|Sua sess[ãa]o foi encerrada|Link sem assinatura)",
    re.IGNORECASE,
)

def _base_path(filename: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    # Recursos compartilhados (logo, aura_api_padrao.json) ficam na raiz do
    # projeto; este arquivo mora em integrations/, por isso sobe um nivel.
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filename)


def _caminhos_config() -> list:
    """Locais candidatos do aura_config.json, em ordem de prioridade. Cobre o
    .exe (ao lado do executável), o subprocesso lançado pelo AURA (AURA_BASE_DIR)
    e a execução por código-fonte (raiz do projeto — este arquivo mora em
    integrations/, por isso sobe um nível)."""
    cands = []
    if os.environ.get("AURA_BASE_DIR"):
        cands.append(os.path.join(os.environ["AURA_BASE_DIR"], "aura_config.json"))
    cands.append(os.path.join(PASTA_SCRIPT, "aura_config.json"))
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands.append(os.path.join(raiz, "aura_config.json"))
    vistos, unicos = set(), []
    for c in cands:
        if c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return unicos


def carregar_config() -> dict:
    """Lê usuario/senha/url do aura_config.json — a MESMA fonte da tela inicial
    do AURA Principal. É isso que faz o Gabinete usar sempre o mesmo endereço e o
    mesmo usuário definidos na tela inicial. Sem config, devolve {} (aí valem os
    planos B *_PADRAO)."""
    for caminho in _caminhos_config():
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return {}


def _carregar_groq_key() -> str:
    """Lê a chave da IA do aura_config.json (mesmo arquivo usado pelo AURA principal).
    Se ainda não houver chave salva, usa a chave padrão embutida no próprio .exe."""
    chave = carregar_config().get("groq_key", "")
    if chave:
        return chave
    try:
        with open(_base_path("aura_api_padrao.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("groq_key", "")
    except Exception:
        return ""

def _cor_hover(cor: str) -> str:
    try:
        r, g, b = int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)
        f = 0.85
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"
    except Exception:
        return cor

def _normalizar_texto(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower().strip()

def _lista_de(valor) -> list:
    if not valor:
        return []
    if isinstance(valor, list):
        return [str(x).strip() for x in valor if str(x).strip()]
    return [s.strip() for s in re.split(r"[;,]", str(valor)) if s.strip()]

def _setup_logger():
    log_path = os.path.join(PASTA_SCRIPT, "aura_gabinete.log")
    logger   = logging.getLogger("aura_gabinete")
    logger.setLevel(logging.INFO)
    handler  = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    if not logger.handlers:
        logger.addHandler(handler)
    return logger

LOG_FILE = _setup_logger()

class EprocBotV4:
    def __init__(self, log_callback=None):
        self.driver = None
        self.wait = None
        self.wait_longo = None
        self.log_cb = log_callback or print
        self._janela_principal = None
        self.perfil_ativo = ""
        self.dados_minuta = {}

    # ── Logging ─────────────────────────────────
    def log(self, mensagem: str, nivel: str = "INFO"):
        prefixo = f"[{nivel}] " if nivel != "INFO" else ""
        msg = f"{prefixo}{mensagem}"
        try:
            self.log_cb(msg)
        except Exception:
            pass
        if nivel == "ERROR":
            LOG_FILE.error(mensagem)
        elif nivel == "WARN":
            LOG_FILE.warning(mensagem)
        else:
            LOG_FILE.info(mensagem)

    # ── Helpers ─────────────────────────────────
    def _dump_diagnostico(self, label: str, extra: str = "") -> str:
        """Salva HTML + screenshot + info diagnóstica em dumps/.
        Retorna o basename ou '' se falhar."""
        if not self.driver:
            return ""
        try:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pasta = os.path.join(PASTA_SCRIPT, "dumps")
            os.makedirs(pasta, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", label)[:40]
            base = f"dump_{ts}_{slug}"
            # HTML do frame atual
            try:
                with open(os.path.join(pasta, base + ".html"), "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
            except Exception as e:
                self.log(f"Dump HTML falhou: {e}", nivel="WARN")
            # Screenshot
            try:
                self.driver.save_screenshot(os.path.join(pasta, base + ".png"))
            except Exception as e:
                self.log(f"Dump screenshot falhou: {e}", nivel="WARN")
            # TXT diagnóstico: URL, selects/inputs visíveis com IDs
            info = [
                f"Label: {label}",
                f"Extra: {extra}",
                f"Data:  {ts}",
                f"URL:   {self.driver.current_url}",
                f"Title: {self.driver.title}",
                "",
                "--- SELECTS NA PÁGINA (id, name, opções) ---",
            ]
            try:
                for s in self.driver.find_elements(By.TAG_NAME, "select"):
                    try:
                        sid = s.get_attribute("id") or ""
                        sname = s.get_attribute("name") or ""
                        if not sid and not sname:
                            continue
                        opts = s.find_elements(By.TAG_NAME, "option")
                        vis = "✓" if s.is_displayed() else " "
                        info.append(f"  [{vis}] id={sid!r} name={sname!r} opts={len(opts)}")
                    except Exception:
                        continue
            except Exception:
                pass
            info.append("\n--- INPUTS COM ID/NAME (até 40) ---")
            try:
                for inp in self.driver.find_elements(By.TAG_NAME, "input")[:40]:
                    try:
                        iid = inp.get_attribute("id") or ""
                        iname = inp.get_attribute("name") or ""
                        itype = inp.get_attribute("type") or ""
                        if not iid and not iname:
                            continue
                        info.append(f"  type={itype} id={iid!r} name={iname!r}")
                    except Exception:
                        continue
            except Exception:
                pass
            info.append("\n--- IFRAMES ---")
            try:
                for f in self.driver.find_elements(By.TAG_NAME, "iframe"):
                    info.append(f"  id={f.get_attribute('id')!r} name={f.get_attribute('name')!r}")
            except Exception:
                pass
            with open(os.path.join(pasta, base + ".txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(info))
            self.log(f"🔍 Dump salvo em dumps/{base}.[html|png|txt]")
            return base
        except Exception as e:
            self.log(f"Falha ao salvar dump: {e}", nivel="WARN")
            return ""

    def _tratar_alert(self, aceitar=True):
        textos = []
        for _ in range(5):
            try:
                alert = self.driver.switch_to.alert
                texto = alert.text
                textos.append(texto)
                self.log(f"Alert detectado: '{texto}'")
                alert.accept() if aceitar else alert.dismiss()
                time.sleep(0.5)
            except NoAlertPresentException:
                break
        return textos[0] if textos else None

    def _aguardar_elemento(self, by, valor, timeout: int = TIMEOUT):
        return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, valor)))

    def _aguardar_clicavel(self, by, valor, timeout: int = TIMEOUT):
        return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, valor)))

    def _aguardar_url_conter(self, texto: str, timeout: int = TIMEOUT):
        WebDriverWait(self.driver, timeout).until(EC.url_contains(texto))

    def _atalho(self, modificador: str, tecla: str, descricao: str = ""):
        """Dispara atalho global. Modificador: 'ctrl' | 'alt' | 'ctrl+shift'."""
        actions = ActionChains(self.driver)
        if modificador == "ctrl":
            actions.key_down(Keys.CONTROL).send_keys(tecla).key_up(Keys.CONTROL)
        elif modificador == "alt":
            actions.key_down(Keys.ALT).send_keys(tecla).key_up(Keys.ALT)
        elif modificador == "ctrl+shift":
            actions.key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys(tecla).key_up(Keys.SHIFT).key_up(Keys.CONTROL)
        actions.perform()
        if descricao:
            self.log(f"Atalho disparado: {modificador}+{tecla.upper()} ({descricao})")

    # ──────────────────────────────────────────
    # PASSO 1 — Abrir navegador
    # ──────────────────────────────────────────
    def abrir_navegador(self, url: str = None):
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        self.log("Iniciando Chrome via ChromeDriverManager...")
        self.driver = criar_chrome_driver(options)

        self.wait = WebDriverWait(self.driver, TIMEOUT)
        self.wait_longo = WebDriverWait(self.driver, TIMEOUT_LONGO)
        self.url = (url or URL_EPROC_GABINETE_PADRAO).strip()
        self.driver.get(self.url)
        self._janela_principal = self.driver.current_window_handle
        self.log("Site aberto. Faça login + escolha o perfil, depois clique em '② Confirmar Login'.")

    def fazer_login(self, usuario: str, senha: str):
        """Preenche e submete o formulário de login do eProc."""
        self.log("Realizando login automático...")
        campo_u = self._aguardar_elemento(By.ID, "txtUsuario", timeout=20)
        campo_u.clear()
        campo_u.send_keys(usuario)
        campo_s = self.driver.find_element(By.ID, "pwdSenha")
        campo_s.clear()
        campo_s.send_keys(senha)
        self.driver.find_element(By.ID, "sbmEntrar").click()
        WebDriverWait(self.driver, 30).until(
            lambda d: not ("externo_controlador.php" in d.current_url
                           and "acao=principal" in d.current_url)
        )
        self.log("✓ Login realizado.")

    # ──────────────────────────────────────────
    # Seleção automática de perfil (tela "Seleção de perfil")
    # ──────────────────────────────────────────
    @staticmethod
    def _norm_perfil(texto: str) -> str:
        """Normaliza para casar perfis: minúsculo, sem acento, SEM o código entre
        parênteses (ex.: '(1SCIV-A3)') e SEM zeros à esquerda em números (assim
        '01ª CÂMARA' casa com '1ª Câmara'). Remover o código evita falso-positivo
        (o número do código poderia satisfazer, ex., o 'Assento 1' do alvo)."""
        s = EprocBotV4._normalizar(texto or "")
        s = re.sub(r"\([^)]*\)", " ", s)    # remove (1SCIV-A3), (12CACIV-A4), ...
        s = re.sub(r"\b0+(\d)", r"\1", s)   # 01 -> 1, 010 -> 10
        return re.sub(r"\s+", " ", s).strip()

    def _clicar_botao_perfil(self, botao):
        onclick = botao.get_attribute("onclick") or ""
        m = re.search(r"acaoLogar\(['\"](\d+)['\"]\)", onclick)
        if m:
            self.driver.execute_script(f"acaoLogar('{m.group(1)}');")
        else:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao)
            time.sleep(0.3)
            self.driver.execute_script("arguments[0].click();", botao)

    def selecionar_perfil(self, alvo: str, tentativas: int = 20, intervalo: float = 1.0) -> bool:
        """Na tela 'Seleção de perfil', clica no perfil do gabinete cujo
        câmara/assento casa com `alvo`. Casa pelos NÚMEROS (nº da câmara/seção +
        assento) e pela FAMÍLIA (Câmara vs Seção), ignorando as palavras — assim
        'Câmara Cível' casa com 'CACIV', mas '1ª' NÃO casa com '11ª' e
        'Assento 1' NÃO casa com 'Assento 3'. Prioriza 'GERENTE GABINETE'.
        Retorna True se selecionou; False se não achou ou se ficou ambíguo (o
        chamador então pede seleção manual — nunca chuta um perfil)."""
        def _tokens(s: str) -> list:
            return re.findall(r"[a-z]+|\d+", self._norm_perfil(s))

        def _nums(s: str) -> list:
            return [t for t in _tokens(s) if t.isdigit()]

        def _familia(s: str) -> str:
            toks = set(_tokens(s))
            if toks & {"secao", "sciv"}:
                return "S"
            if toks & {"camara", "caciv", "caciveesp"}:
                return "C"
            return ""

        alvo_nums = _nums(alvo)
        alvo_fam = _familia(alvo)
        if not alvo_nums:
            # Sem números não dá para identificar o gabinete com segurança.
            self.log(f"Alvo de perfil sem números ('{alvo}') — seleção manual.", nivel="WARN")
            return False

        def _prio(texto: str) -> int:
            return 2 if "gerente gabinete" in self._norm_perfil(texto) else 0

        def _compat(texto: str) -> bool:
            if _nums(texto) != alvo_nums:            # câmara/assento têm que bater
                return False
            fam = _familia(texto)
            if alvo_fam and fam and alvo_fam != fam:  # não confundir Câmara com Seção
                return False
            return True

        def _rotulo(b) -> str:
            return (b.get_attribute("data-descricao") or (b.text or "").splitlines()[0] or "").strip()

        time.sleep(1)
        for _ in range(tentativas):
            try:
                todos = self.driver.find_elements(
                    By.XPATH, '//button[contains(@class,"list-group-item")]')
            except Exception:
                todos = []
            # Casa contra data-descricao OU texto visível (Lotação).
            candidatos = [
                b for b in todos
                if _compat(b.get_attribute("data-descricao") or "") or _compat(b.text or "")
            ]
            if candidatos:
                candidatos.sort(
                    key=lambda b: _prio((b.get_attribute("data-descricao") or "") + " " + (b.text or "")),
                    reverse=True,
                )
                # Se sobrar mais de um perfil com a MESMA prioridade, é ambíguo:
                # não arrisca escolher o gabinete errado.
                top = _prio((candidatos[0].get_attribute("data-descricao") or "") + " " + (candidatos[0].text or ""))
                empatados = [b for b in candidatos
                             if _prio((b.get_attribute("data-descricao") or "") + " " + (b.text or "")) == top]
                if len(empatados) > 1:
                    self.log(
                        "Mais de um perfil casou com o alvo — ambíguo, seleção manual: "
                        + " | ".join(_rotulo(b) for b in empatados[:4]),
                        nivel="WARN")
                    return False
                self.log(f"Perfil encontrado: {_rotulo(candidatos[0])}")
                self._clicar_botao_perfil(candidatos[0])
                time.sleep(4)
                return True
            time.sleep(intervalo)
        return False

    def fechar_navegador(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.log("Navegador fechado.")

    # ──────────────────────────────────────────
    # PASSO 2 — Confirmar login + listar perfis
    # ──────────────────────────────────────────
    def verificar_sessao_ativa(self) -> bool:
        try:
            url = self.driver.current_url
        except Exception as e:
            self.log(f"Nao foi possivel ler a URL do driver (possivel crash do driver/browser): {e}", nivel="ERROR")
            return False
        if RE_SESSAO_EXPIRADA.search(url):
            self.log("Sessão expirada detectada.", nivel="ERROR")
            return False
        if "externo_controlador.php" in url and "acao=principal" in url:
            self.log("Tela de login.", nivel="ERROR")
            return False
        return True

    def confirmar_login(self) -> dict:
        """Verifica login, lê selInfraUnidades, retorna {ativo, opcoes}."""
        try:
            self.driver.find_element(By.ID, "txtNumProcessoPesquisaRapida")
        except NoSuchElementException:
            raise RuntimeError("Não logado: txtNumProcessoPesquisaRapida não encontrado.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa.")

        info = {"ativo": "", "opcoes": []}
        try:
            sel = self.driver.find_element(By.ID, "selInfraUnidades")
            select = Select(sel)
            try:
                info["ativo"] = (select.first_selected_option.text or "").strip()
            except Exception:
                info["ativo"] = ""
            info["opcoes"] = [(opt.get_attribute("value") or "", (opt.text or "").strip())
                              for opt in select.options]
            self.perfil_ativo = info["ativo"]
            self.log(f"Login OK. Perfil ativo: {info['ativo']}")
            self.log(f"Total de perfis disponíveis: {len(info['opcoes'])}")
        except NoSuchElementException:
            self.log("selInfraUnidades não encontrado — usuário pode ter apenas um perfil.", nivel="WARN")
        return info

    # ──────────────────────────────────────────
    # PASSO 3 — Pesquisar processo
    # ──────────────────────────────────────────
    def pesquisar_processo(self, num_processo: str):
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão expirada — faça login novamente.")
        num = re.sub(r"[^\d]", "", num_processo)
        self.log(f"Pesquisando: {num_processo} (norm: {num})")
        campo = self._aguardar_elemento(By.ID, "txtNumProcessoPesquisaRapida")
        campo.clear()
        time.sleep(0.3)
        campo.send_keys(num)
        time.sleep(0.3)
        campo.send_keys(Keys.RETURN)
        self._aguardar_url_conter("processo_selecionar", timeout=20)
        time.sleep(2)
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão expirou ao abrir processo.")
        self.log("Capa do processo aberta.")

    # ──────────────────────────────────────────
    # PASSO 4 — Abrir Nova Minuta
    # ──────────────────────────────────────────
    def abrir_nova_minuta(self):
        """Abre a tela de Nova Minuta (acao=minuta_cadastrar).

        Robustez (2026-09-18): a versão antiga dependia de
        `number_of_windows_to_be(2)` — contagem fixa de janelas. Em lote, se
        sobrava uma aba de minuta anterior (ou o Ctrl+M abria junto com o botão),
        ficavam 3 janelas e a espera por "exatamente 2" nunca acontecia,
        estourando TimeoutException com "Message:" vazio — mesmo com a minuta já
        aberta. Agora a gente NÃO conta janelas: procura, entre TODAS as abas
        abertas, aquela cuja URL contém `minuta_cadastrar` e troca pra ela.
        Prioriza o clique em #btn-minutar (que faz window.open, como a página
        realmente faz); Ctrl+M vira reserva."""
        # A aba atual é a do processo (capa). Guarda como principal para o retorno.
        try:
            self._janela_principal = self.driver.current_window_handle
        except Exception:
            pass

        # Fecha abas de minuta REMANESCENTES de um processo anterior — se
        # sobrarem, atrapalham a detecção e, pior, poderiam confundir com a
        # minuta certa (aba de OUTRO processo). Nunca fecha a aba principal.
        try:
            for h in list(self.driver.window_handles):
                if h == self._janela_principal:
                    continue
                try:
                    self.driver.switch_to.window(h)
                    if "minuta_cadastrar" in (self.driver.current_url or ""):
                        self.driver.close()
                except Exception:
                    pass
            self.driver.switch_to.window(self._janela_principal)
        except Exception:
            pass

        handles_antes = set(self.driver.window_handles)

        def _ir_para_minuta(timeout: float = 12.0) -> bool:
            """Troca para a aba/janela cuja URL contém minuta_cadastrar (nova aba
            ou a própria). Retorna True se chegou lá."""
            fim = time.time() + timeout
            while time.time() < fim:
                # Nova(s) aba(s) aberta(s) depois da ação
                for h in [h for h in self.driver.window_handles if h not in handles_antes]:
                    try:
                        self.driver.switch_to.window(h)
                        if "minuta_cadastrar" in (self.driver.current_url or ""):
                            return True
                    except Exception:
                        continue
                # Ou abriu na MESMA aba (principal)
                try:
                    if self._janela_principal in self.driver.window_handles:
                        self.driver.switch_to.window(self._janela_principal)
                        if "minuta_cadastrar" in (self.driver.current_url or ""):
                            return True
                except Exception:
                    pass
                time.sleep(0.5)
            return False

        # 1) Caminho preferido: clicar no botão Minutar (window.open _blank).
        clicou = False
        try:
            btn = self._aguardar_clicavel(By.ID, "btn-minutar", timeout=8)
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
            clicou = True
        except (TimeoutException, NoSuchElementException):
            self.log("#btn-minutar não encontrado — tentando Ctrl+M...", nivel="WARN")

        # 2) Se o botão não estava disponível, tenta o atalho Ctrl+M.
        if not clicou:
            try:
                self._atalho("ctrl", "m", "Nova minuta")
            except Exception as e:
                self.log(f"Ctrl+M não disparou: {e}", nivel="WARN")

        if _ir_para_minuta(timeout=12):
            self.log("Nova Minuta aberta.")
            return

        # 3) Última tentativa: volta à principal e tenta o atalho de novo.
        try:
            if self._janela_principal in self.driver.window_handles:
                self.driver.switch_to.window(self._janela_principal)
            self._atalho("ctrl", "m", "Nova minuta (retry)")
        except Exception:
            pass
        if _ir_para_minuta(timeout=10):
            self.log("Nova Minuta aberta (retry).")
            return

        self._tratar_alert()
        raise NoSuchElementException(
            "Não consegui abrir a Nova Minuta: nem o botão 'Minutar' nem Ctrl+M "
            "levaram à tela minuta_cadastrar (verifique se a capa do processo "
            "estava aberta e se há pop-up bloqueando)."
        )

    def _trocar_para_nova_aba(self, timeout: int = 10):
        WebDriverWait(self.driver, timeout).until(EC.number_of_windows_to_be(2))
        for handle in self.driver.window_handles:
            if handle != self._janela_principal:
                self.driver.switch_to.window(handle)
                return

    def _voltar_para_aba_principal(self):
        """A aba da minuta costuma fechar sozinha depois de salvar/assinar
        (comportamento do próprio eproc, confirmado ao vivo) -- se isso já
        aconteceu, o driver fica preso numa janela que não existe mais, e
        até `current_window_handle` levanta NoSuchWindowException. Por isso
        cada chamada abaixo é protegida individualmente: o objetivo aqui é
        só garantir que terminamos na aba principal, não em levantar erro
        por uma aba que já sumiu sozinha."""
        try:
            handles = self.driver.window_handles
        except Exception:
            return
        if self._janela_principal not in handles:
            # Aba principal também sumiu (não deveria acontecer) -- não há
            # pra onde voltar; deixa como está em vez de mascarar o erro real.
            return
        try:
            atual = self.driver.current_window_handle
        except Exception:
            atual = None
        if atual != self._janela_principal:
            if atual is not None and atual in handles:
                try:
                    self.driver.close()
                except Exception:
                    pass
            try:
                self.driver.switch_to.window(self._janela_principal)
            except Exception:
                pass

    # ──────────────────────────────────────────
    # PASSO 5 — Tipo de documento / Modelo
    # ──────────────────────────────────────────
    def _preencher_autocomplete(self, campo_id: str, texto: str, descricao: str = "", aguardar_segundos: float = 3.0):
        label = descricao or campo_id
        self.log(f"Preenchendo {label}: {texto}")
        campo = self._aguardar_elemento(By.ID, campo_id)
        campo.click()
        time.sleep(0.3)
        campo.clear()
        time.sleep(0.3)
        for ch in texto:
            campo.send_keys(ch)
            time.sleep(0.05)
        time.sleep(aguardar_segundos)

        # 1) Tenta selecionar a MELHOR sugestão da lista AJAX (master: #divInfraAjax<campo_id>)
        clicou = self._selecionar_melhor_sugestao_autocomplete(campo_id, texto)
        if not clicou:
            # 2) Fallback: ARROW_DOWN + ENTER (pega o primeiro item)
            self.log(f"  (sem lista AJAX detectada — usando seta+enter)")
            campo.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.4)
            campo.send_keys(Keys.RETURN)
        time.sleep(1.5)

        # Tenta ler hdnIdX se existir
        for hdn_id in [campo_id.replace("txt", "hdnId"), "hdn" + campo_id[3:]]:
            try:
                hdn = self.driver.find_element(By.ID, hdn_id)
                hdn_valor = hdn.get_attribute("value") or ""
                if hdn_valor:
                    self.log(f"{label} → ID {hdn_valor}")
                    return hdn_valor
            except NoSuchElementException:
                continue
        return ""

    def _selecionar_melhor_sugestao_autocomplete(self, campo_id: str, texto_alvo: str) -> bool:
        """
        Lê as sugestões em #divInfraAjax<campo_id> e clica na que MELHOR casa com texto_alvo.
        Itens que começam com '***' são tipos básicos (eproc renderiza em cinza); são
        despriorizados frente a modelos padrão concretos.
        """
        container_id = f"divInfraAjax{campo_id}"
        try:
            container = self.driver.find_element(By.ID, container_id)
        except NoSuchElementException:
            return False
        items = container.find_elements(By.TAG_NAME, "li")
        if not items:
            return False

        alvo_norm = self._normalizar(texto_alvo)
        alvo_tokens = set(t for t in alvo_norm.split() if len(t) >= 3)

        # Helper: tira sufixo " (NNN)" e prefixo "decisao/despacho - " (etc.)
        # para comparar nome puro vs alvo.
        def _nucleo(s: str) -> str:
            s = re.sub(r"\s*\(\d+\)\s*$", "", s).strip()
            if " - " in s:
                s = s.split(" - ", 1)[1].strip()
            return s

        alvo_nucleo = _nucleo(alvo_norm)

        melhor = None
        melhor_score = -10**9
        sugestoes = []

        for li in items:
            try:
                txt = (li.text or "").strip()
            except Exception:
                continue
            if not txt:
                continue
            txt_norm = self._normalizar(txt)
            sugestoes.append(txt)
            eh_basico = txt.strip().startswith("***")
            txt_clean = txt_norm.strip("*").strip()
            txt_nucleo = _nucleo(txt_clean)

            score = 0
            # PRIORIDADE 1: match exato no núcleo (sem prefixo "X -" nem "(N)")
            if alvo_nucleo and txt_nucleo == alvo_nucleo:
                score = 100000
            # PRIORIDADE 2: alvo é PREFIXO do núcleo do item
            elif alvo_nucleo and txt_nucleo.startswith(alvo_nucleo):
                # quanto menos sobra além do alvo, melhor
                extra = len(txt_nucleo) - len(alvo_nucleo)
                score = 50000 - extra
            # PRIORIDADE 3: alvo é substring do núcleo do item
            elif alvo_nucleo and alvo_nucleo in txt_nucleo:
                # Penaliza distância pelo "extra" — palavras antes (ex: "não ") inflam
                extra = len(txt_nucleo) - len(alvo_nucleo)
                score = 5000 - extra * 10
            # PRIORIDADE 4: alvo é substring do texto bruto (cobre quando o núcleo
            # foi alterado pelo split mas o alvo ainda aparece no item completo)
            elif alvo_norm and alvo_norm in txt_clean:
                extra = len(txt_clean) - len(alvo_norm)
                score = 1000 - extra
            else:
                # FALLBACK: overlap de tokens, preferindo o MAIS CURTO (sinaliza melhor match)
                tokens_item = set(t for t in txt_clean.split() if len(t) >= 3)
                comuns = alvo_tokens & tokens_item
                score = len(comuns) * 50 - len(txt_clean)
            # Penaliza item "básico" (*** ...)
            if eh_basico:
                score -= 500

            if score > melhor_score:
                melhor_score = score
                melhor = li

        # Loga as sugestões para debug
        if sugestoes:
            self.log(f"  Sugestões ({len(sugestoes)}): {sugestoes[:5]}")
        if not melhor:
            return False

        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", melhor)
            time.sleep(0.2)
            try:
                melhor.click()
            except ElementClickInterceptedException:
                self.driver.execute_script("arguments[0].click();", melhor)
            self.log(f"  → Sugestão escolhida: {(melhor.text or '').strip()[:120]}")
            return True
        except Exception as e:
            self.log(f"  Falha ao clicar sugestão: {str(e)[:120]}", nivel="WARN")
            return False

    def preencher_tipo_modelo(self, tipo_modelo: str):
        """Preenche o campo Tipo de documento/Modelo (id real: txtModelo)."""
        return self._preencher_autocomplete("txtModelo", tipo_modelo, "Tipo/Modelo")

    # ──────────────────────────────────────────
    # PASSO 6 — Dados básicos
    # ──────────────────────────────────────────
    def _selecionar_dropdown(self, select_id: str, valor_texto: str, descricao: str = ""):
        if not valor_texto:
            return
        label = descricao or select_id
        self.log(f"Selecionando {label}: {valor_texto}")
        elemento = self._aguardar_elemento(By.ID, select_id)
        select = Select(elemento)
        try:
            select.select_by_visible_text(valor_texto)
            return
        except NoSuchElementException:
            pass
        # Match parcial (case-insensitive, sem acentos)
        alvo_norm = self._normalizar(valor_texto)
        for opt in select.options:
            txt = (opt.text or "").strip()
            if alvo_norm in self._normalizar(txt):
                select.select_by_visible_text(txt)
                self.log(f"  match parcial: {txt}")
                return
        # Não achou — loga as opções disponíveis para debug
        opcoes_visiveis = [(opt.text or "").strip() for opt in select.options if (opt.text or "").strip()]
        self.log(f"AVISO: '{valor_texto}' não encontrado em {label}.", nivel="WARN")
        if opcoes_visiveis:
            preview = opcoes_visiveis[:15]
            self.log(f"  Opções disponíveis ({len(opcoes_visiveis)} total): {preview}", nivel="WARN")

    @staticmethod
    def _normalizar(texto: str) -> str:
        """Normaliza para comparação tolerante: minúsculo + sem acentos comuns."""
        if not texto:
            return ""
        s = texto.lower().strip()
        repl = (("á","a"),("à","a"),("â","a"),("ã","a"),("ä","a"),
                ("é","e"),("ê","e"),("è","e"),("ë","e"),
                ("í","i"),("ì","i"),("î","i"),("ï","i"),
                ("ó","o"),("ò","o"),("ô","o"),("õ","o"),("ö","o"),
                ("ú","u"),("ù","u"),("û","u"),("ü","u"),
                ("ç","c"))
        for a, b in repl:
            s = s.replace(a, b)
        return s

    def listar_opcoes_dropdown(self, select_id: str) -> list:
        """Helper de debug: retorna e loga as opções de um <select>."""
        try:
            elem = self.driver.find_element(By.ID, select_id)
            opts = [(opt.get_attribute("value") or "", (opt.text or "").strip())
                    for opt in Select(elem).options]
            self.log(f"--- Opções de #{select_id} ({len(opts)}) ---")
            for v, t in opts[:50]:
                self.log(f"  [{v}] {t}")
            if len(opts) > 50:
                self.log(f"  ... (+{len(opts)-50} mais)")
            return opts
        except NoSuchElementException:
            self.log(f"#{select_id} não encontrado.", nivel="WARN")
            return []

    def preencher_descricao(self, descricao: str):
        if not descricao:
            return
        try:
            campo = self.driver.find_element(By.ID, "txtDescricao")
            campo.clear()
            campo.send_keys(descricao)
            self.log(f"Descrição: {descricao}")
        except NoSuchElementException:
            self.log("txtDescricao não encontrado.", nivel="WARN")

    def selecionar_assinante(self, assinante: str):
        self._selecionar_dropdown("selAssinante", assinante, "Assinante")

    def selecionar_assinante_criador(self) -> bool:
        """Seleciona o assinante = 'Usuário criador da minuta' (option value='1')
        de forma robusta: primeiro por value, depois por texto. Retorna True se
        conseguiu — o eProc exige um assinante indicado para prosseguir."""
        try:
            sel = self._aguardar_elemento(By.ID, "selAssinante", timeout=8)
            select = Select(sel)
            try:
                select.select_by_value("1")
                self.log("Assinante: Usuário criador da minuta (value=1).")
                return True
            except Exception:
                pass
            for opt in select.options:
                if "criador da minuta" in self._normalizar(opt.text):
                    select.select_by_visible_text(opt.text)
                    self.log(f"Assinante: {opt.text}")
                    return True
        except Exception as e:
            self.log(f"Não consegui selecionar o assinante criador: {e}", nivel="WARN")
        return False

    # Mapa de tratamentos por value do select
    _TRATAMENTOS = {
        "Desembargador":    "37",
        "Desembargadora":   "38",
        "Desembargador Relator":  "41",
        "Desembargadora Relatora":"42",
        "Desembargador Revisor":  "45",
        "Desembargadora Revisora":"46",
        "Juiz de Direito":        "12",
        "Juíza de Direito":       "13",
        "Juiz Relator":           "1",
        "Juíza Relatora":         "2",
        "Juiz Substituto":        "14",
        "Juíza Substituta":       "15",
        "Relator":                "39",
        "Relatora":               "40",
        "Revisor":                "43",
        "Revisora":               "44",
        "Presidente":             "47",
        "Presidente, em exercício":"48",
    }

    @staticmethod
    def inferir_tratamento(nome_magistrado: str) -> str:
        """
        Infere o tratamento pelo nome do magistrado.
        Heurística: nomes femininos terminam em 'a' ou têm partículas femininas.
        Retorna o texto do tratamento para selecionar no dropdown.
        """
        if not nome_magistrado:
            return ""
        nome = nome_magistrado.strip().upper()
        # Primeiro nome para detectar gênero
        primeiro = nome.split()[0] if nome.split() else ""
        feminino = primeiro.endswith("A") or primeiro in ("MARIA", "ANA", "LUCIA", "JULIA")
        # Contexto: 2º grau → Desembargador/a, 1º grau → Juiz/Juíza de Direito
        if "DESEMBARGADOR" in nome or "DES." in nome:
            return "Desembargadora" if feminino else "Desembargador"
        if "JUIZ" in nome or "JUÍZA" in nome:
            return "Juíza de Direito" if feminino else "Juiz de Direito"
        # Sem indicação explícita — inferir só pelo nome
        return "Desembargadora" if feminino else "Desembargador"

    def selecionar_tratamento(self, tratamento: str):
        if not tratamento:
            return
        # Aguarda o campo estar presente e visível no DOM
        try:
            self._aguardar_elemento(By.ID, "selTratamento", timeout=10)
        except TimeoutException:
            self.log("selTratamento não encontrado na tela.", nivel="WARN")
            return
        self._selecionar_dropdown("selTratamento", tratamento, "Tratamento")

    def selecionar_sigilo(self, sigilo: str):
        self._selecionar_dropdown("selSigilo", sigilo, "Sigilo")

    def selecionar_status_minuta(self, status: str):
        """Master: selStatusMinuta (não selStatusDestino como no v3)."""
        self._selecionar_dropdown("selStatusMinuta", status, "Status Minuta")

    def marcar_cabecalho(self, opcoes: dict):
        """opcoes: dict de checkboxes a marcar (chkIncluirAdvogados, chkIncluirMPF, etc.)."""
        mapping = {
            "advogados": "chkIncluirAdvogados",
            "mpf": "chkIncluirMPF",
            "interessados": "chkIncluirInteressados",
            "outras_partes": "chkIncluirOutrasPartes",
            "apenas_principais": "chkIncluirApenasPartesPrincipais",
            "originario": "chkIncluirProcessoOriginario",
            "apensos_lef28": "chkIncluirApensosArt28LEF",
        }
        for chave, chk_id in mapping.items():
            valor = opcoes.get(chave)
            if valor is None or str(valor).strip() == "":
                continue
            quer_marcar = str(valor).strip().upper() in ("S", "SIM", "TRUE", "1", "X")
            try:
                chk = self.driver.find_element(By.ID, chk_id)
                marcado = chk.is_selected()
                if quer_marcar and not marcado:
                    chk.click()
                    self.log(f"Cabeçalho: {chave} marcado")
                elif not quer_marcar and marcado:
                    chk.click()
                    self.log(f"Cabeçalho: {chave} desmarcado")
            except NoSuchElementException:
                self.log(f"Cabeçalho {chk_id} não encontrado.", nivel="WARN")

    def marcar_precedente_relevante(self, valor: str):
        if not valor:
            return
        quer = str(valor).strip().upper() in ("S", "SIM", "TRUE", "1")
        try:
            chk = self.driver.find_element(By.ID, "chkPrecedenteRelevante")
            if chk.is_selected() != quer:
                chk.click()
                self.log(f"Precedente relevante: {'marcado' if quer else 'desmarcado'}")
        except NoSuchElementException:
            pass

    # ──────────────────────────────────────────
    # PASSO 7 — Agendamento de evento
    # ──────────────────────────────────────────
    def marcar_agendamento(self, marcar: bool = True):
        """Marca/desmarca chkEventoAgendamento (controla div divEventoAgendamento)."""
        try:
            chk = self.driver.find_element(By.ID, "chkEventoAgendamento")
            if chk.is_selected() != marcar:
                chk.click()
                # marcarAgendamento() é o handler JS do master
                time.sleep(1)
                self.log(f"Agendamento {'marcado' if marcar else 'desmarcado'}.")
            # garante que o div está visível
            time.sleep(0.5)
        except NoSuchElementException:
            self.log("chkEventoAgendamento não encontrado.", nivel="WARN")

    def preencher_evento_agendamento(self, evento: str):
        """Preenche txtEvento (autocomplete) — captura hdnEvento."""
        if not evento:
            return ""
        return self._preencher_autocomplete("txtEvento", evento, "Evento Agendamento")

    def marcar_encadeamento_remessa(self):
        """
        Marca o checkbox chkEncadeamentoRemessa ('Remeter processo')
        que aparece após a seleção do evento de agendamento.
        """
        try:
            chk = self._aguardar_elemento(By.ID, "chkEncadeamentoRemessa", timeout=6)
            if not chk.is_selected():
                chk.click()
                self.log("chkEncadeamentoRemessa marcado (Remeter processo).")
            else:
                self.log("chkEncadeamentoRemessa já estava marcado.")
        except TimeoutException:
            self.log("chkEncadeamentoRemessa não apareceu após o evento — pulando.", nivel="WARN")

    def selecionar_evento_remessa(self, evento_remessa: str):
        """Seleciona o evento de encadeamento de remessa (selEventoEncadeadoRemessa)."""
        if not evento_remessa:
            return
        try:
            self._aguardar_elemento(By.ID, "selEventoEncadeadoRemessa", timeout=6)
            self._selecionar_dropdown("selEventoEncadeadoRemessa", evento_remessa, "Evento Remessa")
        except TimeoutException:
            self.log("selEventoEncadeadoRemessa não apareceu — pulando.", nivel="WARN")

    def selecionar_comportamento_localizador(self, opcao: str):
        """selOpcaoLocalizador — comportamento de remoção dos localizadores atuais."""
        self._selecionar_dropdown("selOpcaoLocalizador", opcao, "Comportamento Localizador")

    def selecionar_novo_localizador(self, localizador: str):
        """selNovoLocalizador — localizador destino. Pode ser <select> ou autocomplete dependendo do contexto."""
        if not localizador:
            return
        try:
            elem = self.driver.find_element(By.ID, "selNovoLocalizador")
            tag = elem.tag_name.lower()
            if tag == "select":
                self._selecionar_dropdown("selNovoLocalizador", localizador, "Novo Localizador")
            else:
                # campo texto (autocomplete) — alguns gabinetes
                elem.click()
                elem.clear()
                for ch in localizador:
                    elem.send_keys(ch)
                    time.sleep(0.05)
                time.sleep(2)
                elem.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.4)
                elem.send_keys(Keys.RETURN)
                self.log(f"Novo localizador (texto): {localizador}")
        except NoSuchElementException:
            self.log("selNovoLocalizador não encontrado.", nivel="WARN")

    def selecionar_localizadores_secundarios(self, lista: list):
        """selLocalizadorSecundario aceita múltiplos. Espera lista de strings (nomes)."""
        if not lista:
            return
        try:
            chk = self.driver.find_element(By.ID, "chkLocalizadoresSecundarios")
            if not chk.is_selected():
                chk.click()
                time.sleep(0.5)
        except NoSuchElementException:
            pass
        try:
            sel = self.driver.find_element(By.ID, "selLocalizadorSecundario")
            select = Select(sel)
            for nome in lista:
                marcado = False
                for opt in select.options:
                    if nome.lower() in (opt.text or "").lower():
                        select.select_by_visible_text(opt.text)
                        self.log(f"Localizador secundário: {opt.text}")
                        marcado = True
                        break
                if not marcado:
                    self.log(f"Localizador secundário não encontrado: {nome}", nivel="WARN")
        except NoSuchElementException:
            self.log("selLocalizadorSecundario não encontrado.", nivel="WARN")

    def selecionar_localizadores_desativar(self, lista: list):
        """selLocalizadorDesativar[] — multiselect dos localizadores atuais a serem removidos."""
        if not lista:
            return
        try:
            sel = self.driver.find_element(By.ID, "selLocalizadorDesativar")
            select = Select(sel)
            for nome in lista:
                for opt in select.options:
                    if nome.lower() in (opt.text or "").lower():
                        select.select_by_visible_text(opt.text)
                        self.log(f"Desativar localizador: {opt.text}")
                        break
        except NoSuchElementException:
            self.log("selLocalizadorDesativar não encontrado.", nivel="WARN")

    def marcar_todos_localizadores_atuais(self):
        """
        Marca TODAS as opções do selLocalizadorDesativar (equivalente ao link 'Marcar todos').
        Master (minuta_cadastrar.js:3050): marcarTodos('') faz exatamente isso.
        Padrão pedido: ao agendar, remover TODOS os localizadores atuais (exceto fixos)
        e adicionar somente o Novo Localizador.
        """
        try:
            # Caminho 1: chamar a função JS oficial do eproc
            ok = self.driver.execute_script("""
                if (typeof marcarTodos === 'function') {
                    marcarTodos('');
                    return true;
                }
                return false;
            """)
            if ok:
                time.sleep(0.5)
                try:
                    sel = self.driver.find_element(By.ID, "selLocalizadorDesativar")
                    select = Select(sel)
                    marcados = len(select.all_selected_options)
                    total = len(select.options)
                    self.log(f"Marcar todos localizadores atuais: {marcados}/{total} marcados (JS).")
                except NoSuchElementException:
                    self.log("Marcar todos disparado por JS (selLocalizadorDesativar não inspecionável).")
                return
        except Exception as e:
            self.log(f"marcarTodos JS falhou: {str(e)[:120]}", nivel="WARN")
        # Caminho 2: clicar no link visual
        try:
            link = self.driver.find_element(By.ID, "lblLocDesMarcarTodos")
            link.click()
            time.sleep(0.5)
            self.log("Marcar todos via #lblLocDesMarcarTodos.")
            return
        except NoSuchElementException:
            pass
        # Caminho 3: marcar manualmente todas as options (último recurso)
        try:
            sel = self.driver.find_element(By.ID, "selLocalizadorDesativar")
            select = Select(sel)
            for opt in select.options:
                if not opt.is_selected():
                    select.select_by_visible_text(opt.text)
            self.log(f"Marcar todos manualmente: {len(select.options)} opções.")
        except NoSuchElementException:
            self.log("Painel Gerenciar Localizadores não disponível para Marcar Todos.", nivel="WARN")

    def marcar_intimar_automatico(self, valor: str):
        if not valor:
            return
        quer = str(valor).strip().upper() in ("S", "SIM", "TRUE", "1")
        try:
            chk = self.driver.find_element(By.ID, "chkIntimarAutomatico")
            if chk.is_selected() != quer:
                chk.click()
                self.log(f"Intimar Automático: {'marcado' if quer else 'desmarcado'}")
        except NoSuchElementException:
            pass

    # ──────────────────────────────────────────
    # PASSO 8 — Salvar e Editar (Alt+A REAL)
    # ──────────────────────────────────────────
    def salvar_e_editar(self):
        """Master: accesskey="A" em sbmCadastrarEditarMinuta. Não Alt+E."""
        try:
            self._atalho("alt", "a", "Salvar e Editar")
            time.sleep(2)
            self._tratar_alert()
            return
        except Exception as e:
            self.log(f"Alt+A não disparou: {e}", nivel="WARN")
        # Fallback: clicar pelo nome
        try:
            btn = self.driver.find_element(By.NAME, "sbmCadastrarEditarMinuta")
            btn.click()
            time.sleep(2)
            self._tratar_alert()
        except NoSuchElementException:
            btn = self.driver.find_element(
                By.XPATH, "//button[contains(@name,'sbmCadastrarEditarMinuta') or contains(text(),'Salvar e Editar')]")
            btn.click()
            time.sleep(2)
            self._tratar_alert()

    def apenas_salvar(self):
        """accesskey="S" em sbmCadastrarMinuta."""
        try:
            self._atalho("alt", "s", "Apenas Salvar")
            time.sleep(2)
            self._tratar_alert()
            return
        except Exception:
            pass
        btn = self.driver.find_element(By.NAME, "sbmCadastrarMinuta")
        btn.click()
        time.sleep(2)
        self._tratar_alert()

    def cancelar_minuta(self):
        try:
            self._atalho("alt", "c", "Cancelar")
            time.sleep(1)
            self._tratar_alert(aceitar=True)
        except Exception:
            try:
                btn = self.driver.find_element(By.ID, "btnCancelar")
                btn.click()
                self._tratar_alert(aceitar=True)
            except Exception:
                pass

    # ──────────────────────────────────────────
    # PASSO 9 — Inserir texto no editor
    # ──────────────────────────────────────────
    def inserir_texto_editor(self, texto: str):
        """
        Versão MÍNIMA: espera 8s, digita no foco atual (o eproc já posiciona o
        cursor no editor após abrir). Sem iframe, sem switch, sem nada.
        """
        if not texto:
            self.log("Sem texto para inserir.")
            return

        self.log(f"  Aguardando 12s para o editor abrir...")
        time.sleep(12)
        self._fechar_popups_erro_eproc()

        # Texto puro, sem tags HTML
        texto_puro = re.sub(r"<[^>]+>", "", texto).strip()
        if not texto_puro:
            self.log("  Texto vazio após limpar tags HTML.")
            return

        # Ctrl+A para selecionar todo o conteúdo atual, Delete para apagar, depois digita o novo
        try:
            actions = ActionChains(self.driver)
            actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL)
            actions.perform()
            time.sleep(0.4)
            actions = ActionChains(self.driver)
            actions.send_keys(Keys.DELETE)
            actions.perform()
            time.sleep(0.4)
            self.log(f"  Conteúdo anterior limpo (Ctrl+A + Delete).")
            actions = ActionChains(self.driver)
            actions.send_keys(texto_puro)
            actions.perform()
            self.log(f"Texto digitado no foco atual ({len(texto_puro)} chars).")
            time.sleep(1)
        except Exception as e:
            self.log(f"Falha ao digitar: {str(e)[:120]}", nivel="WARN")
        self._fechar_popups_erro_eproc()
        return

        # Bloco desativado (mantido só para referência)
        if False and self._aguardar_ckeditor_pronto(timeout=30):
            # Espera adicional para garantir que TODAS as instâncias terminaram de inicializar
            self.log("  Aguardando 8s extras para a UI do editor finalizar (TODAS as instâncias)...")
            time.sleep(8)
            self._fechar_popups_erro_eproc()

            # Lista todas as instâncias com diagnóstico antes de escolher
            try:
                inventario = self.driver.execute_script("""
                    if (typeof CKEDITOR === 'undefined' || !CKEDITOR.instances) return [];
                    var out = [];
                    Object.keys(CKEDITOR.instances).forEach(function(nome) {
                        var ed = CKEDITOR.instances[nome];
                        var info = {nome: nome, status: ed.status, dados: 0, area: 0, visivel: false};
                        try { info.dados = (ed.getData() || '').length; } catch(e) {}
                        try {
                            var container = ed.container && ed.container.$;
                            if (container) {
                                var iframe = container.querySelector('iframe.cke_wysiwyg_frame, iframe[id*="cke_"]');
                                if (iframe) {
                                    var rect = iframe.getBoundingClientRect();
                                    info.area = Math.round(rect.width * rect.height);
                                    info.visivel = rect.width > 50 && rect.height > 50;
                                }
                            }
                        } catch(e) {}
                        out.push(info);
                    });
                    return out;
                """) or []
                self.log(f"  Inventário de instâncias CKEditor ({len(inventario)} total):")
                for inst in inventario:
                    self.log(f"    '{inst['nome']}': status={inst['status']}, "
                             f"dados={inst['dados']}c, área={inst['area']}px², "
                             f"visível={inst['visivel']}")
            except Exception as e:
                self.log(f"  Falha ao inventariar instâncias: {str(e)[:120]}", nivel="WARN")

            # Substitui o PLACEHOLDER "(insira aqui a decisão)" do template — não
            # substitui o template inteiro. Preserva @TAGS@ do cabeçalho/rodapé.
            for tentativa in range(3):
                try:
                    resultado = self.driver.execute_script("""
                        if (typeof CKEDITOR === 'undefined' || !CKEDITOR.instances) return {ok:false, motivo:'sem_ckeditor'};
                        var nomes = Object.keys(CKEDITOR.instances);
                        if (nomes.length === 0) return {ok:false, motivo:'sem_instancia'};

                        // Coleta candidatas 'ready' com diagnóstico
                        var candidatas = [];
                        for (var i=0; i<nomes.length; i++) {
                            var nome = nomes[i];
                            var ed = CKEDITOR.instances[nome];
                            if (ed.status !== 'ready') continue;
                            var dados = '';
                            var area = 0;
                            var visivel = false;
                            try { dados = ed.getData() || ''; } catch(e) {}
                            try {
                                var iframe = ed.container.$.querySelector('iframe.cke_wysiwyg_frame, iframe[id*="cke_"]');
                                if (iframe) {
                                    var rect = iframe.getBoundingClientRect();
                                    area = rect.width * rect.height;
                                    visivel = rect.width > 50 && rect.height > 50;
                                }
                            } catch(e) {}
                            candidatas.push({nome: nome, ed: ed, dados: dados, area: area, visivel: visivel});
                        }
                        if (candidatas.length === 0) return {ok:false, motivo:'nenhuma_pronta'};

                        // Critério: visível, mais dados, maior área
                        candidatas.sort(function(a, b) {
                            if (a.visivel !== b.visivel) return b.visivel - a.visivel;
                            if (b.dados.length !== a.dados.length) return b.dados.length - a.dados.length;
                            return b.area - a.area;
                        });
                        var escolhida = candidatas[0];

                        var conteudoNovo = arguments[0];
                        var atual = escolhida.dados || '';
                        var novo = atual;
                        var substituiu = false;
                        var marcadorEncontrado = '';

                        // Padrões de placeholder do template (em ordem de prioridade)
                        var padroes = [
                            /\\(\\s*insira\\s+aqui\\s+a\\s+decis[ãaáà]o\\s*\\)/gi,
                            /\\(\\s*insira\\s+aqui\\s+o\\s+seu\\s+texto\\s*\\)/gi,
                            /\\(\\s*insira\\s+aqui\\s+o\\s+texto\\s*\\)/gi,
                            /\\(\\s*insira\\s+aqui\\s+a\\s+ementa\\s*\\)/gi,
                            /\\(\\s*insira\\s+aqui\\s+o\\s+ac[óo]rd[ãa]o\\s*\\)/gi,
                            /\\(\\s*insira\\s+aqui[^)]*\\)/gi,
                            /\\(\\s*digite\\s+aqui[^)]*\\)/gi,
                        ];
                        for (var p=0; p<padroes.length; p++) {
                            if (padroes[p].test(novo)) {
                                marcadorEncontrado = padroes[p].toString();
                                novo = novo.replace(padroes[p], conteudoNovo);
                                substituiu = true;
                                break;
                            }
                        }

                        if (!substituiu) {
                            // Não achou placeholder: anexa ao final
                            novo = atual + conteudoNovo;
                        }

                        try { escolhida.ed.focus(); } catch(e) {}
                        escolhida.ed.setData(novo);
                        return {ok:true,
                                nome:escolhida.nome,
                                area:Math.round(escolhida.area),
                                dados_antes:atual.length,
                                dados_depois:novo.length,
                                visivel:escolhida.visivel,
                                substituiu_placeholder:substituiu,
                                marcador:marcadorEncontrado,
                                total:candidatas.length};
                    """, html)
                    if resultado and resultado.get("ok"):
                        time.sleep(2)  # setData é assíncrono
                        check = self.driver.execute_script("""
                            var ed = CKEDITOR.instances[arguments[0]];
                            if (!ed) return null;
                            return (ed.getData() || '').length;
                        """, resultado.get("nome"))
                        self.log(f"  → Instância escolhida: '{resultado.get('nome')}' "
                                 f"(visível={resultado.get('visivel')}, "
                                 f"área={resultado.get('area')}px²)")
                        if resultado.get("substituiu_placeholder"):
                            self.log(f"  Placeholder substituído (marcador: {resultado.get('marcador')[:60]})")
                        else:
                            self.log("  Nenhum placeholder '(insira aqui...)' encontrado — conteúdo anexado ao final.",
                                     nivel="WARN")
                        self.log(f"  Template: {resultado.get('dados_antes')}c → "
                                 f"{resultado.get('dados_depois')}c (confirmado: {check}c).")
                        self._fechar_popups_erro_eproc()
                        return
                    motivo = (resultado or {}).get("motivo", "?")
                    self.log(f"  Tentativa {tentativa+1}/3 falhou: motivo={motivo}")
                    time.sleep(2)
                except Exception as e:
                    self.log(f"setData CKEditor erro tentativa {tentativa+1}: {str(e)[:120]}", nivel="WARN")
                    time.sleep(2)

        # 2ª tentativa: fallback via iframe + innerHTML
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        if not iframes:
            self.log("Nenhum iframe — editor pode não ter aberto.", nivel="WARN")
            return
        iframe_editor = None
        for iframe in iframes:
            ifid = iframe.get_attribute("id") or ""
            ifclass = iframe.get_attribute("class") or ""
            if "cke_" in ifid or "editor" in ifid.lower() or "cke_" in ifclass:
                iframe_editor = iframe
                break
        if not iframe_editor:
            iframe_editor = iframes[-1]
        self.driver.switch_to.frame(iframe_editor)
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.click()
            time.sleep(0.5)
            self.driver.execute_script(
                "arguments[0].innerHTML = arguments[1];", body, html)
            time.sleep(0.5)
            self.log(f"Texto inserido via innerHTML fallback ({len(texto)} chars).")
        finally:
            self.driver.switch_to.default_content()
        time.sleep(0.5)
        self._fechar_popups_erro_eproc()

    def salvar_e_sair_editor(self) -> bool:
        """
        Salva e fecha o editor do eproc. Versão SIMPLES:
          1. Volta ao default_content e fecha popups
          2. Tenta clicar no botão visível "Salvar e Sair" (se houver)
          3. Tenta Alt+Z DENTRO do iframe do editor (foco no body) — caminho que costuma funcionar
          4. Fallback: Alt+Z no default_content
        Considera sucesso após qualquer uma — NÃO verifica se "saiu" da página.
        """
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        self._fechar_popups_erro_eproc()
        time.sleep(0.5)

        # 1) Botão visível
        for seletor in [
            (By.XPATH, "//button[contains(@title,'Salvar Minuta e Sair') or contains(@title,'Alt+Z')]"),
            (By.XPATH, "//a[contains(@title,'Salvar Minuta e Sair') or contains(@title,'Alt+Z')]"),
            (By.XPATH, "//button[normalize-space(.)='Salvar Minuta e Sair']"),
            (By.XPATH, "//button[normalize-space(.)='Salvar e Sair']"),
            (By.CSS_SELECTOR, "button[accesskey='z'], a[accesskey='z']"),
        ]:
            try:
                btn = self._aguardar_clicavel(*seletor, timeout=2)
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.2)
                try:
                    btn.click()
                except ElementClickInterceptedException:
                    self.driver.execute_script("arguments[0].click();", btn)
                self.log(f"  Botão 'Salvar e Sair' clicado.")
                time.sleep(2)
                self._tratar_alert(aceitar=True)
                return True
            except (TimeoutException, NoSuchElementException):
                continue

        # 2) Alt+Z dentro do iframe do CKEditor (caminho que costuma funcionar)
        try:
            iframes = self.driver.find_elements(
                By.CSS_SELECTOR, "iframe.cke_wysiwyg_frame, iframe[id*='cke_']")
            if iframes:
                self.driver.switch_to.frame(iframes[0])
                body = self.driver.find_element(By.TAG_NAME, "body")
                body.click()
                time.sleep(0.3)
                ActionChains(self.driver).key_down(Keys.ALT).send_keys("z").key_up(Keys.ALT).perform()
                self.driver.switch_to.default_content()
                self.log("  Alt+Z disparado dentro do iframe do editor.")
                time.sleep(2)
                self._tratar_alert(aceitar=True)
                return True
        except Exception as e:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            self.log(f"  Alt+Z no iframe falhou: {str(e)[:120]}", nivel="WARN")

        # 3) Fallback: Alt+Z no default
        try:
            self._atalho("alt", "z", "Salvar e Sair (default)")
            time.sleep(2)
            self._tratar_alert(aceitar=True)
            self.log("  Alt+Z disparado (default).")
            return True
        except Exception:
            pass

        self.log("  Não consegui disparar Alt+Z — talvez precise salvar manualmente.", nivel="WARN")
        return False

    def _aguardar_ckeditor_pronto(self, timeout: int = 20) -> bool:
        """
        Espera o CKEditor estar com status='ready'. Retorna True se ficou pronto a tempo.
        Loga progressivamente o status para debug.
        """
        inicio = time.time()
        ultimo_status_logado = ""
        while time.time() - inicio < timeout:
            try:
                info = self.driver.execute_script("""
                    if (typeof CKEDITOR === 'undefined') return {existe:false, motivo:'CKEDITOR_undefined'};
                    if (!CKEDITOR.instances) return {existe:false, motivo:'sem_instances'};
                    var nomes = Object.keys(CKEDITOR.instances);
                    if (nomes.length === 0) return {existe:false, motivo:'instances_vazio'};
                    var ed = CKEDITOR.instances[nomes[0]];
                    return {
                        existe: true,
                        nome: nomes[0],
                        status: ed.status,
                        ready: ed.status === 'ready',
                        total: nomes.length
                    };
                """) or {}
            except Exception as e:
                info = {"existe": False, "motivo": f"exception: {str(e)[:60]}"}

            if info.get("ready"):
                self.log(f"  CKEditor pronto: instância '{info.get('nome')}', "
                         f"total={info.get('total')}, em {time.time()-inicio:.1f}s.")
                return True

            status_atual = f"existe={info.get('existe')} status={info.get('status', info.get('motivo','?'))}"
            if status_atual != ultimo_status_logado:
                self.log(f"  Aguardando CKEditor: {status_atual}")
                ultimo_status_logado = status_atual
            time.sleep(1)
        self.log(f"  Timeout ({timeout}s) aguardando CKEditor ficar pronto.", nivel="WARN")
        return False

    def _fechar_popups_erro_eproc(self):
        """Fecha popups vermelhos de erro do eproc (Toast/alert/swal etc.)."""
        fechados = 0
        try:
            for seletor in [
                "button.toast-close-button",
                ".toast-error .toast-close-button",
                ".toast .toast-close-button",
                ".alert-danger button.close",
                ".alert button.close",
                ".swal2-close",
                "div[role='alert'] button[aria-label*='ec' i]",
                "div[role='alert'] button.close",
            ]:
                for btn in self.driver.find_elements(By.CSS_SELECTOR, seletor):
                    try:
                        if btn.is_displayed():
                            btn.click()
                            fechados += 1
                            time.sleep(0.1)
                    except Exception:
                        continue
            # Limpa via JS qualquer toast/alert restante (não-bloqueante)
            self.driver.execute_script("""
                var sels = ['.toast.toast-error', '.alert-danger',
                            '[role=alert][class*=erro]', '.toast-container .toast'];
                sels.forEach(function(s){
                    document.querySelectorAll(s).forEach(function(el){
                        try { el.remove(); } catch(e){}
                    });
                });
            """)
        except Exception:
            pass
        if fechados:
            self.log(f"  Popups de erro fechados: {fechados}")

    # ──────────────────────────────────────────
    # PASSO 10 — Validar tags pendentes
    # ──────────────────────────────────────────
    def validar_tags_pendentes(self) -> bool:
        """
        O endpoint url_verifica_se_existem_tag_formulario só existe na tela
        minuta_cadastrar (formulário inicial). Após Alt+A, o usuário está em
        editorweb_minuta — aí valida-se varrendo o iframe do editor.
        """
        # 1) Endpoint AJAX (só na tela do form, não no editor)
        try:
            elem = self.driver.find_element(By.ID, "url_verifica_se_existem_tag_formulario")
            url_endpoint = elem.get_attribute("value")
            if url_endpoint:
                resultado = self.driver.execute_script(
                    f"return $.ajax({{url: '{url_endpoint}', async: false, type: 'POST'}}).responseText;")
                if resultado and "true" in (resultado or "").lower():
                    self.log("ATENÇÃO: Tags @ pendentes detectadas pelo servidor.", nivel="WARN")
                    return False
                self.log("Servidor: sem tags @ pendentes.")
                return True
        except NoSuchElementException:
            self.log("(Tela do editor — endpoint de tags não disponível, validando via iframe.)")
        except Exception as e:
            self.log(f"Validação por endpoint falhou: {str(e)[:120]}", nivel="WARN")

        # 2) Fallback — varre iframes do editor
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            achou_tag = False
            for iframe in iframes:
                try:
                    self.driver.switch_to.frame(iframe)
                    texto = self.driver.find_element(By.TAG_NAME, "body").text
                    if re.search(r"@[A-Z_][A-Z_0-9]*@", texto):
                        self.log("Tags @ encontradas no editor (iframe).", nivel="WARN")
                        achou_tag = True
                finally:
                    self.driver.switch_to.default_content()
            if not achou_tag:
                self.log("Editor: sem tags @ pendentes.")
            return not achou_tag
        except Exception as e:
            self.driver.switch_to.default_content()
            self.log(f"Falha ao varrer iframe: {str(e)[:120]}", nivel="WARN")
        return True

    # ──────────────────────────────────────────
    # PASSO 11/12 — Salvar Minuta e Sair (Alt+Z)
    # ──────────────────────────────────────────
    def salvar_minuta_e_sair(self):
        """
        Clica no botão 'Salvar Minuta e Sair' do toolbar CKEditor.
        Fallback: Alt+Z na página principal.
        """
        janela_minuta = self.driver.current_window_handle
        disparou = False

        # 1) Clique direto no botão do CKEditor (método principal)
        try:
            self.driver.switch_to.default_content()
            btn = self._aguardar_clicavel(
                By.CSS_SELECTOR,
                "a.cke_button__salvarminutaesair",
                timeout=6)
            self.driver.execute_script("arguments[0].click();", btn)
            self._tratar_alert(aceitar=True)
            self.log("Botão CKEditor 'Salvar Minuta e Sair' clicado.")
            disparou = True
        except Exception as e:
            self.log(f"Clique CKEditor falhou: {e} — tentando Alt+Z.", nivel="WARN")

        # 2) Fallback: Alt+Z
        if not disparou:
            try:
                self.driver.switch_to.default_content()
                self._atalho("alt", "z", "Salvar Minuta e Sair")
                self._tratar_alert(aceitar=True)
                self.log("Alt+Z disparado.")
                disparou = True
            except Exception as e:
                self.log(f"Alt+Z também falhou: {e}", nivel="WARN")
                return

        # Espera uma confirmação de verdade de que o salvamento terminou no
        # servidor antes de fechar/trocar de aba -- um sleep fixo curto
        # (o que este método fazia antes) corre o risco de matar a aba no
        # meio do request de salvar, e o eproc não recebe o sinal de
        # conclusão: a minuta fica com o lock de edição preso ("bloqueada"),
        # mesmo o clique tendo disparado certinho. Considera concluído
        # quando a aba fecha sozinha (padrão já visto na assinatura do
        # COTRI) OU a URL sai da tela do editor (minuta_editar).
        deadline = time.time() + 15
        confirmado = False
        while time.time() < deadline:
            try:
                if janela_minuta not in self.driver.window_handles:
                    confirmado = True
                    break
                if "minuta_editar" not in self.driver.current_url:
                    confirmado = True
                    break
            except Exception:
                # Qualquer erro consultando o driver aqui (ex: janela já
                # sumiu no meio da checagem) já é sinal de que terminou.
                confirmado = True
                break
            time.sleep(0.5)
        if not confirmado:
            self.log("Timeout esperando confirmação de 'Salvar Minuta e Sair' "
                      "-- seguindo mesmo assim.", nivel="WARN")

        # A aba da minuta costuma fechar sozinha (mesmo comportamento visto
        # na assinatura do COTRI) -- garante voltar pra aba principal antes
        # de qualquer passo seguinte (ex: encaminhar_para_assinatura), senão
        # o driver fica preso numa janela que não existe mais.
        self._voltar_para_aba_principal()

        # 3) Fallback: XPath genérico
        for seletor in [
            (By.XPATH, "//a[contains(@class,'cke_button__salvarminutaesair')]"),
            (By.XPATH, "//*[@title='Salvar Minuta e Sair (Alt+Z)']"),
            (By.XPATH, "//*[contains(text(),'Salvar Minuta e Sair')]"),
        ]:
            try:
                btn = self._aguardar_clicavel(*seletor, timeout=3)
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                self._tratar_alert(aceitar=True)
                self.log("Botão 'Salvar Minuta e Sair' clicado via XPath.")
                return
            except Exception:
                continue

        self.log("Não foi possível salvar e sair.", nivel="WARN")

    def ler_assinante_indicado_minuta_atual(self) -> str:
        """Lê a sigla do magistrado (ex: "T0011585") na coluna 'Assinante
        indicado' da mesma LINHA da tabela de Minutas onde está o ícone
        'Encaminhar minuta para assinatura' (img[acao='minuta_para_assinar'])
        -- ou seja, a minuta que acabou de ser criada por este bot, não uma
        minuta antiga qualquer. Existe pra que o Passo 3 (assinatura) saiba
        com qual conta de magistrado logar sem pedir isso manualmente ao
        usuário: a sigla já está na própria tela do eproc. Nunca lança
        exceção -- retorna string vazia se não conseguir ler."""
        try:
            try:
                self._aguardar_elemento(By.CSS_SELECTOR, "img[acao='minuta_para_assinar']", timeout=8)
            except TimeoutException:
                pass
            img = self.driver.find_element(By.CSS_SELECTOR, "img[acao='minuta_para_assinar']")
            linha = img.find_element(By.XPATH, "./ancestor::tr[1]")
            for celula in linha.find_elements(By.TAG_NAME, "td"):
                texto = (celula.text or "").strip()
                if re.fullmatch(r"[A-Za-z]\d{6,}", texto):
                    return texto
            self.log("Coluna 'Assinante indicado' não encontrada na linha da minuta.", nivel="WARN")
        except Exception as e:
            self.log(f"Não foi possível ler o Assinante indicado: {e}", nivel="WARN")
        return ""

    def encaminhar_para_assinatura(self):
        """
        Clica no ícone 'Encaminhar minuta para assinatura' na capa do processo.
        Aguarda a página voltar para a capa após o salvar e sair.
        """
        # Aguarda a capa do processo carregar (sai do editor)
        try:
            self._aguardar_elemento(
                By.CSS_SELECTOR,
                "img[acao='minuta_para_assinar']",
                timeout=5)
        except TimeoutException:
            # Tenta aguardar qualquer elemento da capa como sinal de carregamento
            try:
                self._aguardar_elemento(By.ID, "divInfraAreaTabela", timeout=4)
                time.sleep(1)
            except Exception:
                time.sleep(2)

        try:
            btn = self.driver.find_element(
                By.CSS_SELECTOR, "img[acao='minuta_para_assinar']")
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(1.5)
            self._tratar_alert(aceitar=True)
            self.log("Minuta encaminhada para assinatura.")
            return
        except Exception as e:
            self.log(f"Clique img[acao] falhou: {e}", nivel="WARN")

        # Fallback: urlajax
        try:
            el = self.driver.find_element(
                By.CSS_SELECTOR, "img[acao='minuta_para_assinar']")
            url = el.get_attribute("urlajax")
            if url:
                self.driver.execute_script(f"infraAjaxRequest('{url}', null, null);")
                time.sleep(1.5)
                self._tratar_alert(aceitar=True)
                self.log("Minuta encaminhada para assinatura via urlajax.")
                return
        except Exception as e2:
            self.log(f"urlajax também falhou: {e2}", nivel="WARN")

        self.log("Não foi possível encaminhar para assinatura.", nivel="WARN")

    def salvar_e_editar_com_julgamento_relacionado(self):
        """Chama salvar_e_editar(); se o processo já teve Julgamento antes,
        o eproc exige 'Julgamento Relacionado' e mostra um alert() nativo
        'Selecione um julgamento relacionado' -- salvar_e_editar() já aceita
        esse alert sozinho (via _tratar_alert interno), mas isso só FECHA o
        popup, não resolve nada: o formulário continua na mesma tela, nada
        foi salvo. Detecta isso conferindo se o CKEditor apareceu depois; se
        não, marca o primeiro radio de 'Julgamento Relacionado' disponível e
        tenta salvar de novo. Confirmado ao vivo em 2026-08-24 -- só ocorre
        se o processo já teve sessão/julgamento antes (processo virgem não
        exige esse campo)."""
        self.salvar_e_editar()
        if self._aguardar_ckeditor_pronto(timeout=6):
            return
        self.log("CKEditor não apareceu após Salvar e Editar -- "
                 "tentando resolver 'Julgamento Relacionado'.", nivel="WARN")
        radios = self.driver.find_elements(
            By.CSS_SELECTOR,
            "input[type='radio'][name*='Julgamento' i], input[type='radio'][id*='Julgamento' i]")
        if not radios:
            raise RuntimeError(
                "Salvar e Editar não abriu o CKEditor e não achei radios de "
                "'Julgamento Relacionado' -- causa desconhecida.")
        self.driver.execute_script("arguments[0].click();", radios[0])
        self.log("Julgamento Relacionado: marcado o primeiro disponível.")
        self.salvar_e_editar()
        if not self._aguardar_ckeditor_pronto(timeout=10):
            raise RuntimeError("CKEditor ainda não abriu depois de marcar Julgamento Relacionado.")

    def _editar_minuta_por_titulo(self, titulo_contendo: str, timeout: float = 10.0) -> bool:
        """Volta pra capa do processo e abre o editor da minuta cuja linha
        contém `titulo_contendo` (ex: 'VOTO', 'ACÓRDÃO') na tabela de
        Minutas. PONTO NÃO CONFIRMADO POR DOM REAL (marcado, não escondido):
        assume o ícone 'Editar minuta' como acao='minuta_editar', por
        analogia com o padrão já confirmado de outros ícones de linha
        (img[acao='minuta_para_assinar'], ver encaminhar_para_assinatura) --
        NUNCA validado ao vivo especificamente pra esse ícone. Ajustar aqui
        se o acao real for outro."""
        self._voltar_para_aba_principal()
        deadline = time.time() + timeout
        while time.time() < deadline:
            for linha in self.driver.find_elements(By.CSS_SELECTOR, "table tr"):
                try:
                    if titulo_contendo.upper() not in (linha.text or "").upper():
                        continue
                    icone = linha.find_element(
                        By.CSS_SELECTOR, "img[acao='minuta_editar'], a[acao='minuta_editar']")
                    self.driver.execute_script("arguments[0].click();", icone)
                    time.sleep(1.5)
                    if self._aguardar_ckeditor_pronto(timeout=15):
                        return True
                except NoSuchElementException:
                    continue
                except Exception as exc:
                    self.log(f"Falha ao abrir editor de '{titulo_contendo}': {exc}", nivel="WARN")
            time.sleep(0.5)
        self.log(f"Não encontrei linha/ícone editável pra '{titulo_contendo}'.", nivel="ERROR")
        return False

    def executar_criar_minutas_julgamento(self, dados: dict) -> tuple:
        """Cria as 3 minutas do Julgamento (RELATÓRIO + VOTO + ACÓRDÃO) na
        capa do processo e preenche o conteúdo -- Passo 7 do pipeline de
        regressão de homologação (ver [[project_aura_sessao_julgamento]]
        na memória do projeto). Mapeado ao vivo ponta a ponta em
        2026-08-24 (fluxo até a anexação), mas esta função NUNCA rodou via
        Selenium antes de escrita aqui em 2026-08-26 -- primeira execução
        real precisa de acompanhamento visual antes de confiar.

        `dados`: num_processo, texto_relatorio, texto_voto, texto_ementa
        (só a Ementa do Acórdão -- o CORPO do Acórdão fica vazio até o
        Passo 9, quando o lançamento de resultado do Passo 8 o preenche
        sozinho; confirmado pelo usuário "Você só faz a ementa"),
        encaminhar_assinatura ("S"/"N", default "S" -- encaminha só o
        RELATÓRIO pra assinatura no final, Voto/Acórdão ficam Rascunho).

        NÃO INCLUÍDO AQUI (pendência real, próximo incremento): incluir o
        processo em Pauta/Mesa da sessão do Passo 6 (já existe
        `executar_incluir_pauta_mesa`, mas ainda não encadeado com isto) e
        agendar o evento 'Juntada de Relatório/Voto/Acórdão (581)' na
        Relação de Minutas do Relatório (modal ainda não portado pro
        código)."""
        passos_ok = []
        try:
            self.pesquisar_processo(dados["num_processo"])
            self.abrir_nova_minuta()
            self.preencher_tipo_modelo("*** RELATÓRIO ***")
            self._preencher_autocomplete("TXTINI2_txtModelo", "*** VOTO ***", "Texto Inicial 2 (Voto)")
            self._preencher_autocomplete("TXTINI3_txtModelo", "*** ACÓRDÃO ***", "Texto Inicial 3 (Acórdão)")
            self.salvar_e_editar_com_julgamento_relacionado()
            passos_ok.append("criar_3_minutas")

            self.inserir_texto_editor(dados.get("texto_relatorio", ""))
            self.salvar_minuta_e_sair()
            passos_ok.append("preencher_relatorio")

            if not self._editar_minuta_por_titulo("VOTO"):
                return False, f"Falha ao abrir o editor do VOTO (passos ok: {','.join(passos_ok)})."
            self.inserir_texto_editor(dados.get("texto_voto", ""))
            self.salvar_minuta_e_sair()
            passos_ok.append("preencher_voto")

            if not self._editar_minuta_por_titulo("ACÓRDÃO"):
                return False, f"Falha ao abrir o editor do ACÓRDÃO (passos ok: {','.join(passos_ok)})."
            self.inserir_texto_editor(dados.get("texto_ementa", ""))
            self.salvar_minuta_e_sair()
            passos_ok.append("preencher_ementa_acordao")

            if str(dados.get("encaminhar_assinatura", "S")).strip().upper() in ("S", "SIM", "TRUE", "1"):
                self.encaminhar_para_assinatura()
                passos_ok.append("encaminhar_relatorio_assinatura")

            return True, f"OK — minutas de julgamento criadas (passos: {','.join(passos_ok)})"
        except Exception as e:
            return False, f"Falha após '{passos_ok[-1] if passos_ok else 'início'}': {e}"


    def assinar_com_senha(self, senha: str):
        """Tela de assinatura: txtSenha + btnAssinarSenha (accesskey S)."""
        if not senha:
            self.log("Senha vazia — pulando assinatura.")
            return
        # Alt+G no editor abre o painel de assinar (manual §14.5)
        try:
            self._atalho("alt", "g", "Assinar minuta")
            time.sleep(2)
        except Exception:
            pass
        try:
            campo = self._aguardar_elemento(By.ID, "txtSenha", timeout=8)
            campo.clear()
            campo.send_keys(senha)
            btn = self._aguardar_clicavel(By.ID, "btnAssinarSenha", timeout=5)
            btn.click()
            time.sleep(2)
            self._tratar_alert()
            self.log("Assinatura com senha enviada.")
        except (TimeoutException, NoSuchElementException):
            self.log("Tela de assinatura com senha não apareceu.", nivel="WARN")

    # ══════════════════════════════════════════
    # FLUXO TESTE DE EVENTO — isolado, sem dependências
    # ══════════════════════════════════════════
    def abrir_tela_eventos_comunicacao(self):
        """
        Abre a tela oficial 'Eventos de Comunicação' do eproc via menu textual.
        URL: acao=eventos_comunicacao_listar
        Tem filtros 'Comunica apenas 1º grau' (rdoComunica1Grau) e botão 'Gerar Planilha' (Alt+G).
        """
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa.")
        for termo, alvo in [
            ("Eventos de Comunicação", "Eventos de Comunicação"),
            ("Eventos Comunicação", "Comunicação"),
            ("Eventos de comunicacao", "comunicacao"),
        ]:
            if self._navegar_via_menu_textual(termo, alvo):
                try:
                    # Aguarda algum elemento típico da tela aparecer
                    for sid in ["txtClasseOrigem", "txtEventoOrigem", "rdoComunica1GrauSim"]:
                        try:
                            self._aguardar_elemento(By.ID, sid, timeout=5)
                            self.log("✓ Tela 'Eventos de Comunicação' aberta.")
                            return
                        except TimeoutException:
                            continue
                except TimeoutException:
                    continue
        raise RuntimeError(
            "Não foi possível chegar em 'Eventos de Comunicação'. Verifique permissão.")

    def filtrar_eventos_comunica_1g(self, marcar_sim: bool = True):
        """Marca o radio 'Comunica apenas 1º grau = Sim' e filtra."""
        try:
            sid = "rdoComunica1GrauSim" if marcar_sim else "rdoComunica1GrauNao"
            rdo = self._aguardar_clicavel(By.ID, sid, timeout=8)
            if not rdo.is_selected():
                rdo.click()
                time.sleep(0.3)
            self.log(f"Filtro 'Comunica 1º grau' = {'Sim' if marcar_sim else 'Não'}")
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"Radio rdoComunica1Grau não encontrado: {e}", nivel="WARN")
        # Marca também 'Informar Processo = Não' e 'Relacionado Principal = Não' (defaults razoáveis)
        for sid in ["rdoInformarProcessoNao", "rdoRelacionadoPrincipalNao", "rdoProcessoMovimentoNao"]:
            try:
                rdo = self.driver.find_element(By.ID, sid)
                if not rdo.is_selected():
                    rdo.click()
                    time.sleep(0.2)
            except NoSuchElementException:
                continue
        try:
            btn = self._aguardar_clicavel(By.ID, "sbmFiltrar", timeout=5)
            btn.click()
            time.sleep(2)
            self.log("Filtro aplicado.")
        except (TimeoutException, NoSuchElementException):
            self.log("sbmFiltrar indisponível.", nivel="WARN")


    def executar_teste_eventos_em_lote(self, num_processo: str, lista_eventos: list,
                                        comp_loc: str = "Não remover o processo de localizador algum"
                                        ) -> tuple:
        """
        Loopa por uma lista de eventos no MESMO processo, lançando um por um.
        Útil para testar várias 'Comunicações entre Graus' de uma vez.
        Retorna (sucessos, falhas) — lista de tuplas (evento, ok, motivo).
        """
        if not num_processo:
            return False, "Nº Processo obrigatório."
        if not lista_eventos:
            return False, "Nenhum evento marcado para enviar."
        resultados = []
        for i, evento in enumerate(lista_eventos, 1):
            self.log(f"━━━ Evento {i}/{len(lista_eventos)}: {evento}")
            dados = {
                "num_processo": num_processo,
                "evento": evento,
                "comportamento_localizador": comp_loc,
            }
            try:
                ok, motivo = self.executar_teste_evento(dados)
                resultados.append((evento, ok, motivo))
                if not ok:
                    self.log(f"  ✗ Falhou: {motivo}", nivel="WARN")
                else:
                    self.log(f"  ✓ Evento '{evento}' lançado.")
                # Pausa entre eventos para o eproc estabilizar
                time.sleep(2)
            except Exception as e:
                resultados.append((evento, False, str(e)[:120]))
                self.log(f"  ✗ Exceção: {str(e)[:120]}", nivel="WARN")
        sucessos = sum(1 for _, ok, _ in resultados if ok)
        falhas = len(resultados) - sucessos
        resumo = f"Eventos disparados: {len(resultados)} | OK: {sucessos} | Erro: {falhas}"
        self.log(f"━━━ Resumo: {resumo}")
        # Detalha falhas
        for evento, ok, motivo in resultados:
            if not ok:
                self.log(f"  - '{evento}': {motivo}", nivel="WARN")
        return (sucessos > 0, resumo)

    def executar_teste_evento(self, dados: dict) -> tuple:
        """
        Teste isolado: dado um nº processo e um evento, abre Movimentar,
        preenche o evento e submete. Não interage com upload, localizador,
        intimação ou remessa — só lança o evento puro.
        Útil para testar 'Comunicação entre graus' (basta o evento ter o atributo).
        """
        num = dados.get("num_processo", "").strip()
        evento = dados.get("evento", "").strip()
        if not num:
            return False, "Nº Processo obrigatório."
        if not evento:
            return False, "Evento obrigatório."
        passos = [
            ("Pesquisar processo", lambda: self.pesquisar_processo(num)),
            ("Abrir Movimentar (Alt+O)", lambda: self.clicar_movimentar()),
            ("Lidar com lembretes", lambda: self.lidar_lembrete_popup()),
            ("Preencher Evento", lambda: self.preencher_evento_movimentar(evento)),
        ]
        # Comportamento "Não remover" (mantém localizador atual)
        # No teste isolado de comunicação, o localizador é IRRELEVANTE — se o
        # select não estiver visível, segue direto pro submit (best-effort).
        comp = dados.get("comportamento_localizador", "Não remover")
        def _manter_loc_best_effort():
            try:
                el = self.driver.find_element(By.ID, "selOpcaoLocalizador")
                if el.is_displayed():
                    self.selecionar_comportamento_localizador(comp)
                else:
                    self.log("Sub-painel localizador não visível — segue.", nivel="WARN")
            except NoSuchElementException:
                self.log("selOpcaoLocalizador inexistente nesta tela — segue.", nivel="WARN")
            except Exception as e:
                self.log(f"Falha leve em Manter Localizador (ignorado): {e}", nivel="WARN")
        if comp:
            passos.append(("Manter Localizador (best-effort)", _manter_loc_best_effort))
        passos.append(("Submeter Movimentação (Alt+O)",
            lambda: self.submeter_movimentacao()))

        for nome, fn in passos:
            try:
                self.log(f"━ Passo: {nome}")
                fn()
                self._tratar_alert()
                if not self.verificar_sessao_ativa():
                    return False, f"Sessão expirou em '{nome}'"
            except Exception as e:
                self._tratar_alert()
                return False, f"Falha em '{nome}': {str(e)[:200]}"
        return True, "OK"

    # ══════════════════════════════════════════
    # FLUXO ÁRVORE — consulta (acao=arvore_documentos, atalho Alt+Y)
    # ══════════════════════════════════════════
    def abrir_arvore_processo(self):
        """Abre a árvore de documentos do processo (já na capa). Tenta Alt+Y → link textual.
        Árvore costuma abrir em NOVA janela/aba, então detectamos por window_handles
        (não pela URL da janela atual).
        """
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        handles_antes = set(self.driver.window_handles)
        url_antes = self.driver.current_url or ""

        def _abriu():
            handles_agora = set(self.driver.window_handles)
            return (len(handles_agora) > len(handles_antes)) or \
                   ((self.driver.current_url or "") != url_antes)

        # Alt+Y (atalho oficial da capa, manual p.501)
        try:
            ActionChains(self.driver).key_down(Keys.ALT).send_keys("y").key_up(Keys.ALT).perform()
            time.sleep(1.5)
            if _abriu():
                self.log("✓ Árvore aberta via Alt+Y (provavelmente em nova janela).")
                return
        except Exception:
            pass
        # Fallback: link textual
        for txt in ["Árvore", "Arvore"]:
            try:
                link = self.driver.find_element(By.PARTIAL_LINK_TEXT, txt)
                link.click()
                time.sleep(1.5)
                if _abriu():
                    self.log(f"✓ Árvore aberta via link '{txt}'.")
                    return
            except NoSuchElementException:
                continue
        raise RuntimeError("Não consegui abrir a Árvore. Confira se está na capa do processo.")

    def consultar_arvore(self, num_processo: str) -> tuple:
        """Pesquisa + abre árvore + reporta quantidade de documentos visíveis."""
        if not num_processo:
            return False, "Nº Processo obrigatório."
        try:
            self.pesquisar_processo(num_processo)
            self.abrir_arvore_processo()
            # Conta documentos: linha por evento na árvore (heurístico, vários temas usam <a>)
            n = 0
            for sel in ["a[id^='lnkDoc']", "tr.infraTrClara, tr.infraTrEscura", "a.linkSemSublinhado"]:
                try:
                    found = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if found:
                        n = max(n, len(found))
                except Exception:
                    continue
            self.log(f"Árvore aberta — ~{n} linhas/documentos visíveis.")
            return True, f"OK — ~{n} itens"
        except Exception as e:
            return False, f"Falha: {str(e)[:200]}"

    # ══════════════════════════════════════════
    # FLUXO ASSOCIAR PROCURADOR (acao=associacao_procurador_parte, Alt+U)
    # ══════════════════════════════════════════
    def abrir_tela_associar_procurador(self):
        """Abre a tela 'Associar Procurador a Parte' (Alt+U na capa)."""
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        try:
            ActionChains(self.driver).key_down(Keys.ALT).send_keys("u").key_up(Keys.ALT).perform()
            time.sleep(1.5)
            url = (self.driver.current_url or "").lower()
            if "associacao_procurador" in url or "procurador_parte" in url:
                self.log("✓ Tela 'Associar Procurador' aberta via Alt+U.")
                return
        except Exception:
            pass
        for txt in ["Associar Procurador", "Procurador Parte", "Procurador"]:
            try:
                link = self.driver.find_element(By.PARTIAL_LINK_TEXT, txt)
                link.click()
                time.sleep(1.5)
                self.log(f"✓ Tela aberta via link '{txt}'.")
                return
            except NoSuchElementException:
                continue
        raise RuntimeError("Não consegui abrir 'Associar Procurador a Parte'. Confira que está na capa do processo.")

    def executar_associar_procurador(self, dados: dict) -> tuple:
        """
        Fluxo TJMG eproc 2G — dois passos:
          1) Tela 'Partes do processo': marca checkbox da parte → 'Adicionar'
          2) Tela 'Gerenciamento de Procuradores de Partes': OAB → 'Incluir'
        """
        num = dados.get("num_processo", "").strip()
        parte = dados.get("parte", "").strip()
        procurador = dados.get("procurador", "").strip()  # OAB no formato MG123456
        acao = (dados.get("tipo_acao", "ASSOCIAR") or "ASSOCIAR").upper()
        if not num:
            return False, "Nº Processo obrigatório."
        try:
            self.pesquisar_processo(num)
            self.abrir_tela_associar_procurador()
        except Exception as e:
            return False, f"Falha ao abrir tela: {str(e)[:200]}"
        if acao == "LISTAR":
            return True, "Tela aberta — listagem visível."
        if not parte:
            return False, "Coluna 'Parte' obrigatória (nome ou trecho)."
        if not procurador:
            return False, "Coluna 'Procurador (OAB/Nome)' obrigatória — informe a OAB (ex: MG123456)."

        # PASSO 1: marcar a parte na tabela "Partes do processo"
        parte_norm = self._normalizar(parte)
        marcou = False
        try:
            for row in self.driver.find_elements(By.TAG_NAME, "tr"):
                try:
                    txt = self._normalizar(row.text or "")
                except Exception:
                    continue
                if parte_norm in txt:
                    try:
                        chk = row.find_element(By.CSS_SELECTOR, "input[type=checkbox]")
                        if not chk.is_selected():
                            chk.click()
                            time.sleep(0.3)
                        marcou = True
                        self.log(f"✓ Parte marcada: {parte}")
                        break
                    except NoSuchElementException:
                        continue
        except Exception as e:
            return False, f"Erro varrendo lista de partes: {str(e)[:200]}"
        if not marcou:
            return False, f"Parte '{parte}' não encontrada na lista de partes do processo."

        # Clica botão 'Adicionar' (topo da tabela de partes)
        try:
            btn_add = self.driver.find_element(
                By.XPATH, "//input[@value='Adicionar'] | //button[contains(., 'Adicionar')]")
            btn_add.click()
            time.sleep(1.5)
        except NoSuchElementException:
            return False, "Botão 'Adicionar' (Partes do processo) não encontrado."

        # PASSO 2: tela 'Gerenciamento de Procuradores de Partes' — OAB
        # Confirma que estamos na tela certa (procura o campo OAB ou o label)
        # selBuscarPor: dropdown 'Buscar por' (default OAB)
        # txtNumeroOAB / txtOAB: input da OAB
        # Tenta vários IDs prováveis
        campo_oab = None
        for cid in ["txtNumeroOAB", "txtOAB", "txtIdentificacao", "txtNumIdentificacao"]:
            try:
                campo_oab = self.driver.find_element(By.ID, cid)
                break
            except NoSuchElementException:
                continue
        # Fallback: pega o primeiro input visível depois do label OAB
        if not campo_oab:
            try:
                campo_oab = self.driver.find_element(
                    By.XPATH, "//label[contains(., 'OAB')]/following::input[@type='text'][1]")
            except NoSuchElementException:
                return False, "Campo OAB não encontrado na tela de Gerenciamento de Procuradores."
        try:
            campo_oab.click()
            campo_oab.clear()
            for ch in procurador:
                campo_oab.send_keys(ch)
                time.sleep(0.06)
            # Espera o autocomplete renderizar a sugestão (eproc faz chamada AJAX)
            time.sleep(2.0)
            # Seleciona a primeira sugestão (ARROW_DOWN + ENTER)
            campo_oab.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.4)
            campo_oab.send_keys(Keys.RETURN)
            time.sleep(0.8)
            self.log(f"✓ OAB '{procurador}' selecionada no autocomplete.")
        except Exception as e:
            return False, f"Falha ao digitar/selecionar OAB: {str(e)[:200]}"

        # Clica 'Incluir' (Alt+I) — joga o advogado na tabela "pendentes de associação"
        clicou_incluir = False
        for val in ["Incluir", "Adicionar"]:
            try:
                btn = self.driver.find_element(
                    By.XPATH, f"//input[@value='{val}'] | //button[contains(., '{val}')]")
                btn.click()
                time.sleep(1.5)
                self._tratar_alert()
                clicou_incluir = True
                self.log(f"✓ '{val}' clicado — advogado nos pendentes.")
                break
            except NoSuchElementException:
                continue
        if not clicou_incluir:
            return False, "Botão 'Incluir' não encontrado na tela de Gerenciamento de Procuradores."

        # PASSO 3: 'Confirmar Associação' (Alt+C) — finaliza o vínculo
        for val in ["Confirmar Associação", "Confirmar Associacao", "Confirmar"]:
            try:
                btn = self.driver.find_element(
                    By.XPATH, f"//input[@value='{val}'] | //button[contains(., '{val}')]")
                btn.click()
                time.sleep(2.0)
                self._tratar_alert()
                return True, f"OK — OAB {procurador} associada à parte '{parte}' (Incluir + Confirmar Associação)"
            except NoSuchElementException:
                continue
        # Fallback: tenta Alt+C
        try:
            ActionChains(self.driver).key_down(Keys.ALT).send_keys("c").key_up(Keys.ALT).perform()
            time.sleep(2.0)
            self._tratar_alert()
            return True, f"OK — OAB {procurador} associada à parte '{parte}' (Incluir + Alt+C)"
        except Exception as e:
            return False, f"Incluir OK, mas 'Confirmar Associação' não encontrado: {str(e)[:120]}"

    # ══════════════════════════════════════════
    # FLUXO CANCELAR MOVIMENTAÇÃO
    # acao=processo_movimento_desativar_consulta
    # ══════════════════════════════════════════
    def abrir_tela_cancelar_movimentacao(self):
        """Abre a tela 'Cancelar Movimentação' (link na capa)."""
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        for txt in ["Cancelar Movimentação", "Cancelar Movimentacao", "Cancelar Movimento"]:
            try:
                link = self.driver.find_element(By.PARTIAL_LINK_TEXT, txt)
                link.click()
                time.sleep(1.5)
                url = (self.driver.current_url or "").lower()
                if "movimento_desativar" in url or "cancelar" in url:
                    self.log(f"✓ Tela aberta via link '{txt}'.")
                    return
            except NoSuchElementException:
                continue
        raise RuntimeError("Não consegui abrir 'Cancelar Movimentação'. Confira que está na capa.")

    def executar_cancelar_movimentacao(self, dados: dict) -> tuple:
        """
        Pesquisa processo → abre tela → acha a linha do evento (1ª coluna = Nº) →
        clica no ícone 'Desativar Evento' (coluna Ações) → aceita o alert de confirmação
        → se houver formulário de motivo, preenche e confirma.
        """
        num = dados.get("num_processo", "").strip()
        evento_id = str(dados.get("evento_id", "") or "").strip()
        motivo = dados.get("motivo", "").strip()
        if not num:
            return False, "Nº Processo obrigatório."
        if not evento_id:
            return False, "Número do Evento (coluna 'Evento Nº') obrigatório."
        try:
            self.pesquisar_processo(num)
            self.abrir_tela_cancelar_movimentacao()
        except Exception as e:
            return False, f"Falha ao abrir tela: {str(e)[:200]}"

        # Localiza a <tr> cuja PRIMEIRA célula <td> seja exatamente o evento_id
        target_row = None
        try:
            for row in self.driver.find_elements(By.TAG_NAME, "tr"):
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                except Exception:
                    continue
                if not cells:
                    continue
                primeira = (cells[0].text or "").strip()
                if primeira == evento_id:
                    target_row = row
                    break
        except Exception as e:
            return False, f"Falha varrendo lista: {str(e)[:200]}"
        if not target_row:
            return False, f"Evento nº {evento_id} não encontrado na lista de movimentações."

        # Procura ícone 'Desativar Evento' na coluna Ações da linha
        acao = None
        for sel in [
            "a[title*='Desativar']",
            "a[onclick*='desativar']",
            "a[onclick*='Desativar']",
            "img[title*='Desativar']",
            "img[alt*='Desativar']",
        ]:
            try:
                acao = target_row.find_element(By.CSS_SELECTOR, sel)
                break
            except NoSuchElementException:
                continue
        # Se achou <img>, sobe ao <a> pai para clicar
        if acao and acao.tag_name.lower() == "img":
            try:
                acao = acao.find_element(By.XPATH, "./ancestor::a[1]")
            except Exception:
                pass
        if not acao:
            return False, (f"Ícone 'Desativar Evento' não encontrado na linha do evento {evento_id}. "
                           "Talvez você não tenha permissão para cancelar este evento.")
        try:
            acao.click()
        except Exception as e:
            return False, f"Falha ao clicar 'Desativar': {str(e)[:200]}"
        time.sleep(0.8)

        # Trata o alert JS de confirmação (geralmente "Confirma a desativação?")
        try:
            alert = self.driver.switch_to.alert
            self.log(f"Confirmação do navegador: {alert.text[:120]}")
            alert.accept()
            time.sleep(1.2)
        except Exception:
            pass

        # Pode abrir um formulário de motivo. Se houver, preenche e confirma.
        # Senão, considera concluído.
        campo_motivo = None
        for cid in ["txtMotivo", "txtJustificativa", "txtObservacao", "txaMotivo", "txaMotivoCancelamento"]:
            try:
                campo_motivo = self.driver.find_element(By.ID, cid)
                break
            except NoSuchElementException:
                continue
        if campo_motivo and motivo:
            try:
                campo_motivo.clear()
                campo_motivo.send_keys(motivo)
                time.sleep(0.3)
            except Exception as e:
                self.log(f"Aviso preenchendo motivo: {e}", nivel="WARN")
        if campo_motivo:
            for val in ["Salvar", "Confirmar", "Desativar", "OK"]:
                try:
                    btn = self.driver.find_element(
                        By.XPATH, f"//input[@value='{val}'] | //button[contains(.,'{val}')]")
                    btn.click()
                    time.sleep(1.5)
                    self._tratar_alert()
                    return True, f"OK — evento {evento_id} desativado (motivo informado, via '{val}')"
                except NoSuchElementException:
                    continue
            return False, f"Formulário de motivo apareceu mas o botão de confirmação não foi encontrado."
        return True, f"OK — evento {evento_id} desativado"

    # ══════════════════════════════════════════
    # FLUXO PREFERÊNCIAS — widget por listagem
    # IDs (master): selPreferencia, selPreferencia-save, selPreferencia-listAll,
    #               txtPreferencia, hdnPreferencia
    # ══════════════════════════════════════════
    def _abrir_tela_para_preferencia(self, tela_alvo: str):
        """Navega até a listagem onde o widget de Preferências existe.
        Cada destino é um par (termo_busca, texto_link) — o termo digita no searchbox
        e o texto_link é o LEAF clicado (evita parar no header do submenu)."""
        rotas = {
            "Minutas - Área de Trabalho": ("Minutas", "Área de Trabalho"),
            "Minutas - Lista":             ("Minutas", "Lista de Minutas"),
            # Compatibilidade com versão antiga da planilha
            "Lista de Minutas":            ("Minutas", "Área de Trabalho"),
            "Localizadores":               ("Localizadores", "Meus Localizadores"),
            "Lista de Documentos":         ("Documentos", "Lista de Documentos"),
            "Lista de Movimentações":      ("Movimentações", "Lista de Movimentações"),
            "Eventos":                     ("Eventos", "Lista de Eventos"),
        }
        termo, alvo = rotas.get(tela_alvo, (tela_alvo, tela_alvo))
        if self._navegar_via_menu_textual(termo, alvo):
            time.sleep(1.2)
            self.log(f"✓ Tela '{tela_alvo}' aberta para Preferências.")
            return
        # Fallback: tenta com o termo igual ao alvo
        if self._navegar_via_menu_textual(alvo, alvo):
            time.sleep(1.2)
            self.log(f"✓ Tela '{tela_alvo}' aberta (fallback).")
            return
        raise RuntimeError(f"Não consegui chegar em '{tela_alvo}'. Confira que essa tela existe no seu perfil.")

    def aplicar_preferencia(self, tela_alvo: str, nome: str) -> tuple:
        """APLICAR: navega → seleciona pelo selPreferencia (<select>) OU
        txtPreferencia (autocomplete) dependendo da tela."""
        if not nome:
            return False, "Nome da preferência obrigatório."
        try:
            self._abrir_tela_para_preferencia(tela_alvo)
        except Exception as e:
            return False, str(e)
        # PADRÃO A: <select id="selPreferencia"> — eproc auto-aplica
        try:
            elem = self.driver.find_element(By.ID, "selPreferencia")
            if elem.tag_name.lower() == "select":
                self._selecionar_dropdown("selPreferencia", nome, "Preferência")
                time.sleep(1.5)
                return True, f"OK — preferência '{nome}' aplicada (select) em '{tela_alvo}'"
        except NoSuchElementException:
            pass
        except Exception as e:
            self.log(f"selPreferencia falhou ({e}) — tentando txtPreferencia.", nivel="WARN")
        # PADRÃO B: <input id="txtPreferencia"> + autocomplete
        try:
            campo = self.driver.find_element(By.ID, "txtPreferencia")
            campo.click()
            campo.clear()
            for ch in nome:
                campo.send_keys(ch)
                time.sleep(0.06)
            time.sleep(2.0)  # aguarda AJAX
            campo.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.4)
            campo.send_keys(Keys.RETURN)
            time.sleep(1.5)
            return True, f"OK — preferência '{nome}' aplicada (autocomplete) em '{tela_alvo}'"
        except NoSuchElementException:
            return False, ("Nenhum widget de preferência (selPreferencia/txtPreferencia) "
                           "encontrado nesta tela.")
        except Exception as e:
            return False, f"Falha no autocomplete txtPreferencia: {str(e)[:200]}"

    # Presets — filtros que o robô aplica AUTOMATICAMENTE antes de salvar
    # IDs validados no master eproc (minuta_area_trabalho.php)
    def _PRESETS_FILTROS(self):
        from datetime import datetime, timedelta
        hoje = datetime.now().strftime("%d/%m/%Y")
        semana = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
        return {
            "Para Assinar": [
                ("select_multi", "selStatusMinuta", ["Para assinar"]),
            ],
            "Pendentes Gabinete": [
                ("select_multi", "selStatusMinuta", ["Para conferir", "Para assinar"]),
            ],
            "Decisões 7 dias": [
                ("select_multi", "selTipoDocumento",
                    ["Despacho/Decisão", "Decisão Monocrática"]),
                ("text", "txtDataCriacaoInicio", semana),
                ("text", "txtDataCriacaoFim", hoje),
            ],
            "Localizadores Ativos": [],   # tela default já mostra ativos
            "Sigilo nivel 2+": [
                ("select", "selSigiloProcesso", "Restrito Procuradorias"),
            ],
            "Hoje": [
                ("text", "txtDataCriacaoInicio", hoje),
                ("text", "txtDataCriacaoFim", hoje),
            ],
        }

    def _aplicar_preset_filtros(self, nome_preset: str) -> tuple:
        """Aplica os filtros do preset. Retorna (aplicados, falhados, total)."""
        filtros = self._PRESETS_FILTROS().get(nome_preset, [])
        if not filtros:
            return (0, 0, 0)
        ok = falhou = 0
        for tipo_campo, fid, valor in filtros:
            try:
                if tipo_campo == "text":
                    el = self.driver.find_element(By.ID, fid)
                    el.clear()
                    el.send_keys(valor)
                    self.log(f"  filtro: {fid} = {valor}")
                    ok += 1
                elif tipo_campo == "select":
                    self._selecionar_dropdown(fid, valor, fid)
                    ok += 1
                elif tipo_campo == "select_multi":
                    # <select multiple> escondido por bootstrap-select — setar via JS
                    # e disparar change para o picker refletir
                    valores_json = "[" + ",".join(
                        '"' + v.replace('"', '\\"') + '"' for v in valor) + "]"
                    script = f"""
                    var sel = document.getElementById('{fid}');
                    if (!sel) return 'sem_elem';
                    var alvos = {valores_json};
                    var marcados = 0;
                    for (var i = 0; i < sel.options.length; i++) {{
                        var t = (sel.options[i].text || '').trim();
                        if (alvos.some(function(a) {{ return t.toLowerCase().indexOf(a.toLowerCase()) >= 0; }})) {{
                            sel.options[i].selected = true;
                            marcados++;
                        }}
                    }}
                    if (typeof $ === 'function' && $('#{fid}').selectpicker) {{
                        $('#{fid}').selectpicker('refresh');
                    }}
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return marcados;
                    """
                    res = self.driver.execute_script(script)
                    if res == "sem_elem":
                        raise NoSuchElementException(fid)
                    self.log(f"  filtro: {fid} = {valor} ({res} opção(s) marcada(s) via JS)")
                    ok += 1
                elif tipo_campo == "autocomplete":
                    v = valor
                    if v == "<self>":
                        v = self._nome_usuario_ativo() or ""
                    if v:
                        self._preencher_autocomplete(fid, v, fid)
                        ok += 1
                    else:
                        self.log(f"  filtro {fid}: sem valor de usuário — pulado", nivel="WARN")
                        falhou += 1
            except NoSuchElementException:
                self.log(f"  campo '{fid}' não existe nesta tela — pulado", nivel="WARN")
                falhou += 1
            except Exception as e:
                self.log(f"  falha no filtro {fid}: {str(e)[:120]}", nivel="WARN")
                falhou += 1
        return (ok, falhou, len(filtros))

    def _nome_usuario_ativo(self) -> str:
        """Tenta extrair o nome/login do usuário ativo na sessão."""
        try:
            # No header: badge com 'T0075903 - Nome' ou só o login
            for sel in ["#user-info", ".user-name", "[id*='lblUsuario']"]:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, sel)
                    txt = (el.text or "").strip()
                    if txt:
                        return txt
                except NoSuchElementException:
                    continue
        except Exception:
            pass
        return ""

    def salvar_preferencia(self, tela_alvo: str, nome: str,
                            padrao: str = "N", painel: str = "N",
                            tipo: str = "Individual") -> tuple:
        """SALVAR (automático):
        1) Navega para a tela
        2) Aplica filtros do preset (lookup pelo nome)
        3) Clica 'Consultar' (executa busca — necessário pro botão Salvar aparecer)
        4) Clica 'Salvar nova preferência' (botão do topo, aparece após consultar)
           OU '#selPreferencia-add' (widget) — depende da tela
        5) Preenche modal: Descricao + SinValorPadrao + SinPainelInicial + rdPrefTipo
        6) Clica '#btnSalvar'
        """
        if not nome:
            return False, "Nome da preferência obrigatório."
        try:
            self._abrir_tela_para_preferencia(tela_alvo)
        except Exception as e:
            return False, str(e)
        # Aplica filtros do preset automaticamente
        ok_f, fail_f, tot_f = self._aplicar_preset_filtros(nome)
        if tot_f:
            self.log(f"Preset '{nome}': {ok_f}/{tot_f} filtros aplicados ({fail_f} pulados).")
        else:
            self.log(f"Preset '{nome}' sem filtros pré-definidos — segue.")
        time.sleep(0.8)

        # PASSO: Consultar — executa a busca para o botão 'Salvar nova preferência' aparecer
        consultou = False
        for sel in [(By.ID, "btnConsultar"),
                    (By.NAME, "btnConsultar"),
                    (By.CSS_SELECTOR, "input[value='Consultar']"),
                    (By.XPATH, "//button[contains(., 'Consultar')]")]:
            try:
                btn = self.driver.find_element(*sel)
                btn.click()
                consultou = True
                self.log("✓ Consultar clicado — aguardando resultados…")
                break
            except NoSuchElementException:
                continue
        if not consultou:
            self.log("Botão 'Consultar' não encontrado — seguindo direto pra Salvar.", nivel="WARN")
        time.sleep(2.5)  # aguarda resultados/AJAX

        # PASSO: clicar 'Salvar nova preferência' OU '#selPreferencia-add'
        clicou = False
        candidatos = [
            (By.CSS_SELECTOR, "input[value='Salvar nova preferência']"),
            (By.CSS_SELECTOR, "input[value='Salvar nova preferencia']"),
            (By.XPATH, "//button[contains(., 'Salvar nova preferência')]"),
            (By.XPATH, "//button[contains(., 'Salvar nova preferencia')]"),
            (By.XPATH, "//a[contains(., 'Salvar nova preferência')]"),
            (By.CSS_SELECTOR, "#selPreferencia-add"),
            (By.CSS_SELECTOR, "button[title*='Adicionar pref']"),
            (By.CSS_SELECTOR, "a[title*='Adicionar pref']"),
        ]
        for sel in candidatos:
            try:
                btn = self.driver.find_element(*sel)
                btn.click()
                clicou = True
                self.log(f"✓ Botão de salvar preferência clicado ({sel[1]!r}).")
                break
            except NoSuchElementException:
                continue
        if not clicou:
            return False, ("Botão 'Salvar nova preferência' não encontrado. "
                           "Verifique se a Consulta retornou resultados.")
        time.sleep(2.0)

        # PASSO: entrar no iframe '#ifrSubFrm' (subframe overlay 700x450)
        entrou_iframe = False
        try:
            iframe = self._aguardar_elemento(By.ID, "ifrSubFrm", timeout=6)
            self.driver.switch_to.frame(iframe)
            entrou_iframe = True
            self.log("✓ Entrou no iframe '#ifrSubFrm'.")
        except Exception:
            self.log("Sem iframe ifrSubFrm — tentando preencher no contexto principal (Twig moderno).",
                     nivel="WARN")

        # Detecta se é form legado (txtDescricao + button[name=btnSalvar]) ou Twig (Descricao + #btnSalvar)
        # Pega o que existir.
        def _achar(cands):
            for tipo_el, sel in cands:
                try:
                    return self.driver.find_element(tipo_el, sel)
                except NoSuchElementException:
                    continue
            return None

        # Campo descrição
        campo = _achar([
            (By.ID, "txtDescricao"),         # legado
            (By.NAME, "txtDescricao"),
            (By.ID, "Descricao"),             # Twig moderno
            (By.NAME, "Descricao"),
        ])
        if not campo:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return False, ("Campo de descrição não encontrado (txtDescricao/Descricao). "
                           "Subframe pode não ter carregado.")
        try:
            campo.clear()
            campo.send_keys(nome)
        except Exception as e:
            return False, f"Falha digitando nome: {str(e)[:120]}"

        # Marcar como padrão
        if (padrao or "N").upper() == "S":
            chk = _achar([(By.ID, "chkValorPadrao"), (By.ID, "SinValorPadrao"),
                          (By.NAME, "SinValorPadrao")])
            if chk:
                try:
                    if not chk.is_selected():
                        chk.click()
                except Exception:
                    pass
            else:
                self.log("Checkbox 'Marcar como padrão' não encontrado — segue.", nivel="WARN")

        # Painel Inicial
        if (painel or "N").upper() == "S":
            chk = _achar([(By.ID, "chkPainelInicial"), (By.ID, "SinPainelInicial"),
                          (By.NAME, "SinPainelInicial")])
            if chk:
                try:
                    if chk.is_enabled() and not chk.is_selected():
                        chk.click()
                    elif not chk.is_enabled():
                        self.log("'Painel Inicial' desabilitado (limite esgotado).", nivel="WARN")
                except Exception:
                    pass
            else:
                self.log("'Painel Inicial' não disponível nesta tela.", nivel="WARN")

        # Tipo: rdIndividual (I) / rdUnidade (U)
        tipo_upper = (tipo or "Individual").strip().lower()
        rd_id = "rdUnidade" if tipo_upper.startswith("unid") else "rdIndividual"
        rd = _achar([(By.ID, rd_id)])
        if rd:
            try:
                if rd.is_enabled() and not rd.is_selected():
                    rd.click()
                elif not rd.is_enabled():
                    self.log(f"Radio '{rd_id}' desabilitado (precisa ser gerente da unidade).",
                             nivel="WARN")
            except Exception:
                pass
        else:
            self.log(f"Radio '{rd_id}' não encontrado — segue com default.", nivel="WARN")

        # Clicar Salvar — legado usa button[name=btnSalvar], Twig usa #btnSalvar
        salvou = False
        for tipo_el, sel in [
                (By.CSS_SELECTOR, "button[name='btnSalvar']"),
                (By.ID, "btnSalvar"),
                (By.XPATH, "//button[contains(., 'Salvar')]"),
                (By.XPATH, "//input[@value='Salvar']")]:
            try:
                btn = self.driver.find_element(tipo_el, sel)
                btn.click()
                salvou = True
                self.log(f"✓ Salvar clicado ({sel!r}).")
                break
            except NoSuchElementException:
                continue
        time.sleep(2.5)
        self._tratar_alert()

        # Sai do iframe pra não bagunçar próximas operações
        if entrou_iframe:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

        if salvou:
            return True, (f"OK — preferência '{nome}' salva "
                          f"(padrão={padrao}, painel={painel}, tipo={tipo})")
        return False, "Botão Salvar não encontrado no subframe."

    def listar_preferencias(self, tela_alvo: str) -> tuple:
        """LISTAR: navega + abre o gerenciador (selPreferencia-listAll)."""
        try:
            self._abrir_tela_para_preferencia(tela_alvo)
        except Exception as e:
            return False, str(e)
        for sel in ["#selPreferencia-listAll", "[id='selPreferencia-listAll']",
                    "#selPreferencia-list", "a[title*='Listar']"]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                btn.click()
                time.sleep(1.5)
                self.log("✓ Gerenciador de Preferências aberto.")
                return True, "OK — gerenciador aberto"
            except NoSuchElementException:
                continue
        return False, "Botão 'Listar Preferências' não encontrado."

    def executar_preferencia(self, dados: dict) -> tuple:
        """Despacha pela ação."""
        acao = (dados.get("tipo_acao", "APLICAR") or "APLICAR").upper()
        tela = dados.get("tela_alvo", "Minutas - Área de Trabalho").strip()
        nome = dados.get("nome", "").strip()
        if acao == "APLICAR":
            return self.aplicar_preferencia(tela, nome)
        if acao == "SALVAR":
            return self.salvar_preferencia(
                tela, nome,
                padrao=dados.get("padrao", "N"),
                painel=dados.get("painel", "N"),
                tipo=dados.get("tipo", "Individual"))
        if acao == "LISTAR":
            return self.listar_preferencias(tela)
        return False, f"Tipo de Ação '{acao}' inválido. Use APLICAR / SALVAR / LISTAR."

    # ══════════════════════════════════════════
    # FLUXO SESSÃO DE JULGAMENTO
    # • INCLUIR_PAUTA / INCLUIR_MESA: capa → 'Incluir em Pauta/Mesa' →
    #   frmSessaoJulgamentoItemCadastro → btn_salvar
    # • DISPONIBILIZAR_MINUTAS: lista → marca chkInfraModalMinutaDisp* →
    #   #btnAcaoDisponibilizar
    # ══════════════════════════════════════════
    def _garantir_iframe(self, iframe_id: str = "ifrSubFrm") -> bool:
        """Garante que estamos no iframe especificado (sai pra default + re-entra).
        Útil entre passos quando AJAX pode ter recarregado o iframe."""
        try:
            self.driver.switch_to.default_content()
            iframe = self.driver.find_element(By.ID, iframe_id)
            self.driver.switch_to.frame(iframe)
            return True
        except NoSuchElementException:
            # iframe sumiu — modal pode estar no contexto principal agora
            return False
        except Exception:
            return False

    def _selecionar_dropdown_ou_primeiro(self, select_id: str, valor_texto: str,
                                          descricao: str = "",
                                          iframe_id: str = "") -> bool:
        """Seleciona valor_texto (match parcial); se vazio, pega a 1ª opção válida.
        Retry automático em StaleElementReferenceException + re-entrada no iframe.
        Retorna True se conseguiu, False caso contrário."""
        label = descricao or select_id
        for attempt in range(3):
            try:
                elem = self.driver.find_element(By.ID, select_id)
                sel = Select(elem)
                if valor_texto:
                    # Match parcial pelo texto
                    alvo_norm = self._normalizar(valor_texto)
                    achou = False
                    for opt in sel.options:
                        txt = (opt.text or "").strip()
                        val = (opt.get_attribute("value") or "").strip()
                        if val and alvo_norm in self._normalizar(txt):
                            sel.select_by_visible_text(txt)
                            self.log(f"✓ {label}: {txt}")
                            return True
                    if not achou:
                        self.log(f"{label}: '{valor_texto}' não encontrado, "
                                 "pegando 1ª opção válida…", nivel="WARN")
                # Vazio OU não achou: pega 1ª opção válida (pula placeholder)
                for opt in sel.options:
                    val = (opt.get_attribute("value") or "").strip()
                    txt = (opt.text or "").strip()
                    if val and val not in ("0", "null") and txt and "selecionado" not in txt.lower():
                        sel.select_by_value(val)
                        self.log(f"✓ {label} (auto): {txt}")
                        return True
                self.log(f"{label}: nenhuma opção válida no dropdown.", nivel="WARN")
                return False
            except NoSuchElementException:
                if attempt < 2 and iframe_id:
                    self.log(f"  {label}: campo não encontrado — re-entrando no iframe…",
                             nivel="WARN")
                    self._garantir_iframe(iframe_id)
                    time.sleep(0.6)
                    continue
                self.log(f"{label}: campo '{select_id}' não encontrado.", nivel="WARN")
                return False
            except StaleElementReferenceException:
                if attempt < 2:
                    self.log(f"  {label}: stale — re-entrando no iframe + retry…",
                             nivel="WARN")
                    if iframe_id:
                        self._garantir_iframe(iframe_id)
                    time.sleep(0.6)
                    continue
                self.log(f"{label}: stale persistente após 3 tentativas.", nivel="WARN")
                return False
            except Exception as e:
                self.log(f"{label}: {str(e)[:120]}", nivel="WARN")
                return False
        return False

    def _selecionar_select2(self, field_id: str, valor_texto: str, descricao: str = "") -> bool:
        """Seleciona opção em <select> sob bootstrap-select/Select2.
        - Match parcial pelo texto da option
        - Atualiza UI via selectpicker('val') (não dispara change)
        - Dispara change nativo ENCAPSULADO em try/catch (suprime handlers quebrados da página)"""
        label = descricao or field_id
        try:
            elem = self.driver.find_element(By.ID, field_id)
        except NoSuchElementException:
            self.log(f"{label}: campo '{field_id}' não existe nesta tela.", nivel="WARN")
            return False
        try:
            sel = Select(elem)
            alvo_norm = self._normalizar(valor_texto)
            value_alvo = None
            texto_match = None
            for opt in sel.options:
                val = (opt.get_attribute("value") or "").strip()
                txt = (opt.text or "").strip()
                if not val or not txt:
                    continue
                if alvo_norm in self._normalizar(txt):
                    value_alvo = val
                    texto_match = txt
                    break
            if not value_alvo:
                self.log(f"{label}: nenhuma opção contém '{valor_texto}'.", nivel="WARN")
                return False
            # JS único, tolerante a erros do handler da página
            script = """
            var fid = arguments[0];
            var val = arguments[1];
            var s = document.getElementById(fid);
            if (!s) return 'no_elem';
            // 1) seta value no <select> nativo
            s.value = val;
            // 2) atualiza UI do bootstrap-select se existir (não dispara change)
            try {
                if (typeof $ === 'function' && $('#' + fid).selectpicker) {
                    $('#' + fid).selectpicker('val', val);
                }
            } catch (e) { /* widget pode falhar — segue */ }
            // 3) dispara change nativo encapsulado (handler da página pode quebrar)
            try {
                s.dispatchEvent(new Event('change', {bubbles: true}));
            } catch (e) { /* handler da página quebrado — ignora */ }
            return 'ok';
            """
            res = self.driver.execute_script(script, field_id, value_alvo)
            if res == 'no_elem':
                self.log(f"{label}: elemento sumiu durante seleção.", nivel="WARN")
                return False
            self.log(f"✓ {label}: {texto_match}")
            return True
        except Exception as e:
            self.log(f"{label}: falha ao selecionar — {str(e)[:120]}", nivel="WARN")
            return False

    def abrir_tela_incluir_pauta_mesa(self):
        """Da capa do processo, clica 'Incluir em Pauta/Mesa'."""
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        for txt in ["Incluir em Pauta/Mesa", "Incluir em Pauta", "Incluir em Mesa",
                    "Pauta/Mesa", "Pauta"]:
            try:
                link = self.driver.find_element(By.PARTIAL_LINK_TEXT, txt)
                link.click()
                time.sleep(2.0)
                self.log(f"✓ Link '{txt}' clicado na capa.")
                return
            except NoSuchElementException:
                continue
        raise RuntimeError("Link 'Incluir em Pauta/Mesa' não encontrado na capa.")

    def executar_incluir_pauta_mesa(self, dados: dict, tipo_inclusao: str) -> tuple:
        """tipo_inclusao = 'PAUTA' ou 'MESA'."""
        num = dados.get("num_processo", "").strip()
        sessao = dados.get("sessao", "").strip()
        orgao = dados.get("orgao_julgador", "").strip()
        magistrado = dados.get("magistrado", "").strip()
        tipo_julg = dados.get("tipo_julgamento", "").strip()
        if not num:
            return False, "Nº Processo obrigatório para INCLUIR_PAUTA/MESA."
        try:
            self.pesquisar_processo(num)
            self.abrir_tela_incluir_pauta_mesa()
        except Exception as e:
            return False, f"Falha ao abrir tela: {str(e)[:200]}"
        # O modal abre — pode estar em iframe ifrSubFrm (legado) ou Bootstrap (Twig)
        entrou_iframe = False
        try:
            iframe = self.driver.find_element(By.ID, "ifrSubFrm")
            self.driver.switch_to.frame(iframe)
            entrou_iframe = True
            self.log("✓ Entrou no iframe ifrSubFrm.")
        except NoSuchElementException:
            pass
        try:
            self._aguardar_elemento(By.NAME, "frmSessaoJulgamentoItemCadastro", timeout=4)
        except Exception:
            # tenta achar por algum campo do form
            try:
                self._aguardar_elemento(By.ID, "id_sessao_julgamento", timeout=4)
            except Exception as e:
                if entrou_iframe:
                    self.driver.switch_to.default_content()
                return False, f"Form de inclusão não carregou: {str(e)[:120]}"
        iframe_id_modal = "ifrSubFrm" if entrou_iframe else ""
        # cod_tipo_inclusao — escolhe PAUTA ou MESA
        ok_passos = []
        try:
            self._selecionar_dropdown("cod_tipo_inclusao", tipo_inclusao, "Tipo de Inclusão")
            ok_passos.append("tipo_inclusao")
        except Exception as e:
            self.log(f"Tipo de Inclusão: {e}", nivel="WARN")
        time.sleep(1.0)  # AJAX pode disparar
        # id_orgao_julgador — preenchido ou 1ª opção
        if self._selecionar_dropdown_ou_primeiro(
                "id_orgao_julgador", orgao, "Órgão Julgador",
                iframe_id=iframe_id_modal):
            ok_passos.append("orgao")
        # Mudar Órgão geralmente recarrega Sessão+Magistrado via AJAX
        time.sleep(1.5)
        # id_sessao_julgamento — depende do Órgão (recarregado por AJAX).
        # Garante iframe + espera ATÉ o dropdown ter opções válidas (até 6s).
        if iframe_id_modal:
            self._garantir_iframe(iframe_id_modal)
        time.sleep(0.5)  # tempo mínimo pra AJAX disparar
        elem_sess = None
        # Tenta vários IDs/seletores possíveis
        candidatos_sess = [
            (By.ID, "id_sessao_julgamento"),
            (By.NAME, "id_sessao_julgamento"),
            (By.ID, "cod_sessao_julgamento"),
            (By.ID, "id_sessao"),
            (By.CSS_SELECTOR, "select[id*='sessao_julgamento']"),
            (By.CSS_SELECTOR, "select[name*='sessao_julgamento']"),
            (By.CSS_SELECTOR, "select[id*='sessao']"),
            # via label "Sessão de julgamento"
            (By.XPATH, "//label[contains(translate(., 'ÃÊÉ', 'AEE'), 'Sessao')]"
                      "/following::select[1]"),
        ]
        # Espera ativa: até 6s pelo elemento + opções válidas
        deadline = time.time() + 6.0
        while time.time() < deadline:
            for tipo_el, sel in candidatos_sess:
                try:
                    e = self.driver.find_element(tipo_el, sel)
                    # confirma que é um <select> com opções carregadas
                    if e.tag_name.lower() == "select":
                        opts = e.find_elements(By.TAG_NAME, "option")
                        # >1 opção (placeholder + pelo menos uma sessão)
                        if len(opts) > 1:
                            elem_sess = e
                            self.log(f"  campo Sessão localizado via {tipo_el}={sel!r} ({len(opts)} opções)")
                            break
                except NoSuchElementException:
                    continue
                except Exception:
                    continue
            if elem_sess:
                break
            time.sleep(0.5)

        if not elem_sess:
            self.log("Campo de Sessão não encontrado ou sem opções (após 6s).", nivel="WARN")
            self._dump_diagnostico("sessao_nao_encontrada",
                                   f"sessao={sessao!r} orgao={orgao!r}")
        else:
            # Re-find pra evitar stale entre busca e Select() — o elem_sess pode ter
            # virado stale durante a espera ativa
            for tentativa in range(3):
                try:
                    elem_sess = self.driver.find_element(By.ID, elem_sess.get_attribute("id") or "id_sessao_julgamento")
                    break
                except (StaleElementReferenceException, NoSuchElementException):
                    if iframe_id_modal:
                        self._garantir_iframe(iframe_id_modal)
                    time.sleep(0.5)
                    elem_sess = None
                    try:
                        elem_sess = self.driver.find_element(By.ID, "id_sessao_julgamento")
                    except Exception:
                        continue
                    break
            try:
                sel_sess = Select(elem_sess)
                escolheu = False
                texto_escolhido = ""
                if sessao:
                    alvo_norm = self._normalizar(sessao)
                    for opt in sel_sess.options:
                        txt = (opt.text or "").strip()
                        val = (opt.get_attribute("value") or "").strip()
                        if val and alvo_norm in self._normalizar(txt):
                            sel_sess.select_by_visible_text(txt)
                            texto_escolhido = txt
                            escolheu = True
                            break
                    if not escolheu:
                        self.log(f"Sessão '{sessao}' não encontrada no dropdown.", nivel="WARN")
                else:
                    # 1ª opção válida (próxima sessão disponível)
                    for opt in sel_sess.options:
                        val = (opt.get_attribute("value") or "").strip()
                        txt = (opt.text or "").strip()
                        if val and val not in ("0", "null") and txt and "selecionado" not in txt.lower():
                            sel_sess.select_by_value(val)
                            texto_escolhido = txt
                            escolheu = True
                            break
                    if not escolheu:
                        self.log("Sem sessão disponível no dropdown.", nivel="WARN")
                if escolheu:
                    fid = elem_sess.get_attribute("id") or "id_sessao_julgamento"
                    try:
                        self.driver.execute_script(
                            "try{"
                            f"  if(typeof $==='function' && $('#{fid}').selectpicker){{"
                            f"    $('#{fid}').selectpicker('refresh');"
                            "  }"
                            "}catch(e){}")
                    except Exception:
                        pass
                    self.log(f"✓ Sessão: {texto_escolhido}")
                    ok_passos.append(f"sessao({texto_escolhido[:40]})")
            except Exception as e:
                self.log(f"Sessão: {str(e)[:120]}", nivel="WARN")
        # Garante iframe antes do próximo select (Sessão pode ter disparado AJAX)
        if iframe_id_modal:
            self._garantir_iframe(iframe_id_modal)
        time.sleep(0.8)
        # cod_magistrado — preenchido ou 1ª opção
        if self._selecionar_dropdown_ou_primeiro(
                "cod_magistrado", magistrado, "Magistrado",
                iframe_id=iframe_id_modal):
            ok_passos.append("magistrado")
        time.sleep(0.5)
        # Re-garante iframe antes do checkbox Novo julgamento + Tipo Julgamento
        if iframe_id_modal:
            self._garantir_iframe(iframe_id_modal)
        # Tipo Julgamento — marca 'Novo julgamento' e seleciona tipo (ou 1ª opção)
        chk_novo = None
        # Tenta vários seletores (CSS com [] precisa escape, XPath é mais robusto)
        for tipo_el, sel in [
                (By.XPATH, "//input[@name='chkJulgamento[]']"),
                (By.XPATH, "//label[contains(.,'Novo julgamento')]//input[@type='checkbox']"),
                (By.XPATH, "//label[contains(.,'Novo julgamento')]/preceding-sibling::input[@type='checkbox']"),
                (By.XPATH, "//*[contains(text(),'Novo julgamento')]/preceding::input[@type='checkbox'][1]"),
                (By.CSS_SELECTOR, r"input[name='chkJulgamento\[\]']"),
        ]:
            try:
                chk_novo = self.driver.find_element(tipo_el, sel)
                break
            except NoSuchElementException:
                continue
        if chk_novo:
            try:
                if chk_novo.is_displayed() and not chk_novo.is_selected():
                    chk_novo.click()
                    time.sleep(0.4)
                    self.log("✓ 'Novo julgamento' marcado.")
                elif chk_novo.is_selected():
                    self.log("'Novo julgamento' já estava marcado.")
            except Exception as e:
                # fallback via JS — útil quando o click é interceptado
                try:
                    self.driver.execute_script("arguments[0].click();", chk_novo)
                    self.log("✓ 'Novo julgamento' marcado via JS.")
                    time.sleep(0.4)
                except Exception:
                    self.log(f"Novo julgamento: {str(e)[:120]}", nivel="WARN")
        else:
            self.log("Checkbox 'Novo julgamento' não encontrado — segue.", nivel="WARN")
            self._dump_diagnostico("novo_julgamento_nao_achado")
        if self._selecionar_dropdown_ou_primeiro(
                "cod_tipo_julgamento", tipo_julg, "Tipo Julgamento",
                iframe_id=iframe_id_modal):
            ok_passos.append("tipo_julg")
        else:
            self._dump_diagnostico("tipo_julgamento_falhou", f"tipo={tipo_julg!r}")
        # btn_salvar — pode estar coberto por dropdown aberto ou autocomplete em foco.
        # Primeiro clica área neutra pra fechar qualquer overlay/dropdown.
        try:
            self.driver.execute_script(
                "document.querySelectorAll('.modal-body, .modal-content')[0]"
                ".click();")
            time.sleep(0.3)
        except Exception:
            pass
        salvou = False
        # Tenta achar o botão visível (modal pode ter Salvar no topo E no rodapé)
        candidatos_salvar = [
            (By.NAME, "btn_salvar"),
            (By.CSS_SELECTOR, "button[name='btn_salvar']"),
            (By.ID, "btn_salvar"),
            (By.XPATH, "//button[normalize-space(.)='Salvar']"),
            (By.XPATH, "//button[contains(., 'Salvar')]"),
        ]
        for tipo_el, sel in candidatos_salvar:
            try:
                elements = self.driver.find_elements(tipo_el, sel)
                for btn in elements:
                    if btn.is_displayed() and btn.is_enabled():
                        try:
                            btn.click()
                        except Exception:
                            # Click interceptado — tenta via JS
                            self.driver.execute_script("arguments[0].click();", btn)
                        salvou = True
                        self.log(f"✓ Salvar clicado ({sel}).")
                        break
                if salvou:
                    break
            except NoSuchElementException:
                continue
        # Fallback final: Tab+Tab+Enter (técnica do usuário) — útil se Salvar
        # estiver fora da view ou bloqueado por foco em autocomplete
        if not salvou:
            try:
                self.log("Salvar não clicou — tentando Tab+Tab+Enter…", nivel="WARN")
                ActionChains(self.driver).send_keys(Keys.TAB).pause(0.2)\
                    .send_keys(Keys.TAB).pause(0.2)\
                    .send_keys(Keys.RETURN).perform()
                time.sleep(1.5)
                salvou = True
                self.log("✓ Salvar via Tab+Tab+Enter.")
            except Exception as e:
                self.log(f"Tab+Tab+Enter falhou: {e}", nivel="WARN")
                self._dump_diagnostico("salvar_nao_clicado")
        time.sleep(2.5)
        self._tratar_alert()

        # Tela intermediária de confirmação — validada ao vivo em 2026-08-23:
        # "Os processos abaixo não foram incluídos por conterem avisos.
        # Selecione os processos que deseja incluir." Aparece quando alguma
        # parte está sem procurador (o sub-item já vem MARCADO por padrão) —
        # precisa clicar Salvar de novo pra efetivar a inclusão.
        aviso_confirmacao = False
        try:
            texto_pagina = (self.driver.find_element(By.TAG_NAME, "body").text or "")
            if "não foram incluídos por conterem avisos" in texto_pagina or \
               "nao foram incluidos por conterem avisos" in self._normalizar(texto_pagina):
                aviso_confirmacao = True
        except Exception:
            pass
        if aviso_confirmacao:
            self.log("Tela de confirmação (processos com avisos) detectada — "
                     "clicando Salvar novamente pra efetivar.", nivel="WARN")
            time.sleep(0.5)
            confirmou = False
            for tipo_el, sel in candidatos_salvar:
                try:
                    for btn in self.driver.find_elements(tipo_el, sel):
                        if btn.is_displayed() and btn.is_enabled():
                            try:
                                btn.click()
                            except Exception:
                                self.driver.execute_script("arguments[0].click();", btn)
                            confirmou = True
                            break
                    if confirmou:
                        break
                except NoSuchElementException:
                    continue
            time.sleep(2.0)
            self._tratar_alert()
            if confirmou:
                self.log("✓ Confirmação da tela de avisos enviada.")
                ok_passos.append("confirmacao_avisos")
            else:
                self.log("Não achei o botão Salvar na tela de confirmação de avisos.",
                         nivel="ERROR")
                if entrou_iframe:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass
                return False, ("Tela de confirmação de avisos apareceu, mas o botão "
                              "'Salvar' de confirmação não foi encontrado/clicado.")

        if entrou_iframe:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
        if not salvou:
            return False, "Botão 'Salvar' não encontrado no form de inclusão."
        return True, f"OK — processo {num} incluído em {tipo_inclusao} (passos: {','.join(ok_passos) or 'nenhum extra'})"

    def _clicar_botao_visivel_por_texto(self, textos, timeout: float = 6.0) -> bool:
        """
        Clica no primeiro botão VISÍVEL cujo texto bate com um dos textos dados.
        Útil pra telas do eproc que duplicam o mesmo botão no topo e no rodapé
        (ex: 'Abrir Pauta', 'Consultar') — pega sempre o que está visível/clicável.
        """
        deadline = time.time() + timeout
        normalizados = [self._normalizar(t) for t in textos]
        while time.time() < deadline:
            candidatos = self.driver.find_elements(
                By.CSS_SELECTOR,
                "button, a.infraButton, input[type='button'], input[type='submit']")
            for el in candidatos:
                try:
                    if not el.is_displayed():
                        continue
                    txt = self._normalizar(
                        (el.text or el.get_attribute("value") or "").strip())
                    if any(alvo and alvo in txt for alvo in normalizados):
                        try:
                            el.click()
                        except ElementClickInterceptedException:
                            self.driver.execute_script("arguments[0].click();", el)
                        return True
                except Exception:
                    continue
            time.sleep(0.3)
        return False

    def abrir_pauta_sessao_julgamento(self, filtro_sessao: str) -> bool:
        """
        Abre a pauta de uma Sessão de Julgamento já cadastrada.
        Fluxo validado ao vivo em 2026-08-20 (perfil CARTÓRIO, ex.
        '19CACIV/GERENTE GABINETE/SECRETARIA'): na tela 'Sessões de
        Julgamento', marcar o checkbox da LINHA da sessão (chkInfraItemN,
        achado pelo texto da linha — ex. a data 'dd/mm/aaaa' — não hardcodar
        N) e clicar 'Abrir Pauta' (botão duplicado topo/rodapé). Resultado
        esperado: toast 'Sucesso' e status muda de 'Cadastrada/Prevista' pra
        'Pauta aberta' (a célula não atualiza sozinha via AJAX — precisa
        re-clicar 'Consultar' pra conferir).

        IMPORTANTE: só o perfil CARTÓRIO tem os botões de gestão de sessão
        (Nova/Gerar/Alterar/Abrir Pauta/...) — testado no perfil GABINETE,
        esses botões não aparecem lá.

        filtro_sessao: texto que identifica a linha de forma única (ex. a
        data da sessão '24/09/2026' — use algo específico o bastante pra
        casar 1 linha só).
        """
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa. Faça login novamente.")
        if not self._navegar_via_menu_textual("Sessões de Julgamento", "Sessões de Julgamento"):
            raise RuntimeError(
                "Não foi possível chegar em 'Sessões de Julgamento'. Verifique se o "
                "perfil atual é o CARTÓRIO (só ele tem os botões de gestão de sessão).")
        time.sleep(1.5)

        alvo_norm = self._normalizar(filtro_sessao)

        def _achar_linha():
            for linha in self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr"):
                try:
                    if alvo_norm in self._normalizar(linha.text or ""):
                        return linha
                except Exception:
                    continue
            return None

        linha_alvo = _achar_linha()
        if linha_alvo is None:
            self.log(f"Nenhuma linha de sessão contém '{filtro_sessao}'.", nivel="ERROR")
            return False
        try:
            chk = linha_alvo.find_element(By.CSS_SELECTOR, "input[id^='chkInfraItem']")
            if not chk.is_selected():
                try:
                    chk.click()
                except ElementClickInterceptedException:
                    self.driver.execute_script("arguments[0].click();", chk)
            self.log(f"✓ Linha da sessão marcada ('{filtro_sessao}').")
        except NoSuchElementException:
            self.log("Checkbox da linha da sessão não encontrado.", nivel="ERROR")
            return False

        if not self._clicar_botao_visivel_por_texto(["Abrir Pauta"]):
            self.log("Botão 'Abrir Pauta' não encontrado/clicável — "
                     "confira se o perfil atual é o CARTÓRIO.", nivel="ERROR")
            return False
        time.sleep(1.5)
        self._tratar_alert()
        self._fechar_popups_erro_eproc()

        # Célula de status não atualiza sozinha via AJAX — precisa reconsultar.
        if not self._clicar_botao_visivel_por_texto(["Consultar"], timeout=3.0):
            self.log("Botão 'Consultar' não encontrado pra reconferir status "
                     "(ação foi disparada, mas confirmação ficou pendente).", nivel="WARN")
            return True
        time.sleep(1.5)

        linha_alvo = _achar_linha()
        if linha_alvo is None:
            self.log("Linha da sessão não reencontrada após reconsulta.", nivel="WARN")
            return False
        txt_norm = self._normalizar(linha_alvo.text or "")
        if "pauta aberta" in txt_norm:
            self.log(f"✓ Pauta aberta com sucesso ('{filtro_sessao}').")
            return True
        self.log(f"Status pós-clique não confirma 'Pauta aberta': "
                 f"{(linha_alvo.text or '')[:120]!r}", nivel="WARN")
        return False

    def abrir_tela_disponibilizar_minutas(self):
        """Navega para a tela de disponibilização de minutas via menu textual."""
        for termo, alvo in [
                ("Disponibilizar", "Disponibilizar"),
                ("Disponibilização", "Disponibilização"),
                ("Minutas", "Disponibilizar"),
                ("Colegiado", "Disponibilizar"),
        ]:
            if self._navegar_via_menu_textual(termo, alvo):
                time.sleep(1.2)
                self.log(f"✓ Tela de Disponibilização aberta ({termo} → {alvo}).")
                return
        raise RuntimeError("Não consegui abrir a tela de 'Disponibilizar minutas para colegiado'.")

    def executar_disponibilizar_minutas(self, dados: dict) -> tuple:
        """Filtra (opcional) → Consultar → marca chkInfraModalMinutaDisp* → #btnAcaoDisponibilizar."""
        filtro = dados.get("filtro_minutas", "").strip()
        try:
            self.abrir_tela_disponibilizar_minutas()
        except Exception as e:
            return False, str(e)
        # Filtro opcional (campo de texto comum em listas)
        if filtro:
            for cid in ["txtTermoPesquisa", "txtDescricaoMinuta", "txtSiglaDescricaoLocalizador"]:
                try:
                    el = self.driver.find_element(By.ID, cid)
                    el.clear()
                    el.send_keys(filtro)
                    self.log(f"  filtro '{filtro}' aplicado em #{cid}")
                    break
                except NoSuchElementException:
                    continue
        # Consultar
        for tipo_el, sel in [(By.ID, "btnConsultar"),
                             (By.NAME, "btnConsultar"),
                             (By.CSS_SELECTOR, "input[value='Consultar']"),
                             (By.XPATH, "//button[contains(.,'Consultar')]")]:
            try:
                btn = self.driver.find_element(tipo_el, sel)
                btn.click()
                self.log("✓ Consultar clicado.")
                break
            except NoSuchElementException:
                continue
        time.sleep(2.5)
        # Marca todos os chkInfraModalMinutaDisp*
        marcados = 0
        try:
            chks = self.driver.find_elements(
                By.CSS_SELECTOR, "input[id^='chkInfraModalMinutaDisp'][type='checkbox']")
            for chk in chks:
                if chk.is_displayed() and not chk.is_selected():
                    chk.click()
                    marcados += 1
        except Exception as e:
            self.log(f"Falha marcando minutas: {e}", nivel="WARN")
        if marcados == 0:
            return False, "Nenhuma minuta para disponibilizar (lista vazia ou checkboxes não encontrados)."
        self.log(f"✓ {marcados} minuta(s) marcada(s).")
        # Clica btnAcaoDisponibilizar
        for tipo_el, sel in [(By.ID, "btnAcaoDisponibilizar"),
                             (By.ID, "btnAcaoDisponibilizarLista"),
                             (By.CSS_SELECTOR, "#btnAcaoDisponibilizar"),
                             (By.XPATH, "//button[contains(.,'Disponibilizar')]")]:
            try:
                btn = self.driver.find_element(tipo_el, sel)
                btn.click()
                time.sleep(2.0)
                self._tratar_alert()
                return True, f"OK — {marcados} minuta(s) disponibilizada(s) ao colegiado"
            except NoSuchElementException:
                continue
        return False, "Botão 'Disponibilizar' não encontrado depois de marcar."

    def executar_sessao(self, dados: dict) -> tuple:
        """Despacha pela Tipo de Ação."""
        acao = (dados.get("tipo_acao", "INCLUIR_PAUTA") or "INCLUIR_PAUTA").upper()
        if acao == "INCLUIR_PAUTA":
            return self.executar_incluir_pauta_mesa(dados, "PAUTA")
        if acao == "INCLUIR_MESA":
            return self.executar_incluir_pauta_mesa(dados, "MESA")
        if acao == "DISPONIBILIZAR_MINUTAS":
            return self.executar_disponibilizar_minutas(dados)
        if acao == "ABRIR_PAUTA":
            filtro = dados.get("filtro_sessao", "").strip()
            if not filtro:
                return False, "'filtro_sessao' obrigatório pra ABRIR_PAUTA (ex: a data da sessão)."
            ok = self.abrir_pauta_sessao_julgamento(filtro)
            return ok, (f"OK — pauta aberta ({filtro})" if ok
                        else f"Falha ao abrir pauta ({filtro}) — ver log.")
        return (False, f"Tipo de Ação '{acao}' inválido. Use INCLUIR_PAUTA / INCLUIR_MESA / "
                       "DISPONIBILIZAR_MINUTAS / ABRIR_PAUTA.")

    # ══════════════════════════════════════════
    # FLUXO TEXTO PADRÃO — cadastro/edição
    # URLs: texto_padrao_lista / texto_padrao_cadastrar / editorweb_texto_padrao
    # ══════════════════════════════════════════
    def abrir_lista_textos_padrao(self):
        """Abre a tela 'Textos Padrão' via menu textual."""
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa.")
        for termo, alvo in [
            ("Textos Padrão", "Textos Padrão"),
            ("Texto Padrão", "Texto Padrão"),
            ("Textos Padrao", "Texto"),
        ]:
            if self._navegar_via_menu_textual(termo, alvo):
                try:
                    self._aguardar_elemento(By.ID, "txtTermoPesquisa", timeout=8)
                    self.log("✓ Lista de Textos Padrão aberta.")
                    return
                except TimeoutException:
                    continue
        raise RuntimeError(
            "Não foi possível chegar em 'Textos Padrão'. Verifique seu perfil.")

    def abrir_cadastro_novo_texto_padrao(self):
        """Abre o cadastro a partir da lista (preserva hash)."""
        try:
            self.driver.find_element(By.ID, "btnNovo")
        except NoSuchElementException:
            self.abrir_lista_textos_padrao()
        try:
            btn = self._aguardar_clicavel(By.ID, "btnNovo", timeout=8)
            btn.click()
            time.sleep(1.5)
            self._aguardar_elemento(By.ID, "txtDesTextoPadrao", timeout=10)
            self.log("✓ Cadastro de Texto Padrão aberto.")
        except (TimeoutException, NoSuchElementException) as e:
            raise RuntimeError(f"Não consegui abrir o cadastro de texto padrão: {e}")

    def cadastrar_novo_texto_padrao(self, descricao: str, sigla: str = "",
                                     publico: str = "N", conteudo: str = "") -> bool:
        """
        Cadastra texto padrão. Master: txtDesTextoPadrao + txtSiglaAutoTexto + chkSinPublico.
        Submit: name=sbmCadastrarTextoPadrao (Alt+S).
        Após salvar, eproc abre o editor (editorweb_texto_padrao) — insere conteúdo + Alt+Z.
        """
        if not descricao:
            self.log("Descrição obrigatória.", nivel="ERROR")
            return False
        try:
            self.driver.find_element(By.ID, "txtDesTextoPadrao")
        except NoSuchElementException:
            self.abrir_cadastro_novo_texto_padrao()
        # Descrição
        try:
            campo = self._aguardar_elemento(By.ID, "txtDesTextoPadrao")
            campo.clear()
            campo.send_keys(descricao)
            self.log(f"Descrição: {descricao}")
        except Exception as e:
            self.log(f"Falha ao preencher descrição: {e}", nivel="ERROR")
            return False
        # Sigla (opcional)
        if sigla:
            try:
                campo = self.driver.find_element(By.ID, "txtSiglaAutoTexto")
                campo.clear()
                campo.send_keys(sigla)
                self.log(f"Sigla: {sigla}")
            except NoSuchElementException:
                pass
        # Público
        quer = str(publico).strip().upper() in ("S", "SIM", "TRUE", "1")
        try:
            chk = self.driver.find_element(By.ID, "chkSinPublico")
            if chk.is_selected() != quer:
                chk.click()
            self.log(f"Público: {'S' if quer else 'N'}")
        except NoSuchElementException:
            pass
        # Submit
        try:
            self._atalho("alt", "s", "Salvar Texto Padrão")
            time.sleep(2)
            self._tratar_alert(aceitar=True)
        except Exception:
            try:
                btn = self.driver.find_element(By.NAME, "sbmCadastrarTextoPadrao")
                btn.click()
                time.sleep(2)
                self._tratar_alert(aceitar=True)
            except Exception as e:
                self.log(f"Falha ao submeter: {e}", nivel="ERROR")
                return False
        # Editor abre — esperar 12s + Ctrl+A + Delete + digitar + Alt+Z
        self.log(f"  Aguardando o editor abrir após salvar o cadastro...")
        time.sleep(2)
        self._aguardar_ckeditor_pronto(timeout=30)
        self._fechar_popups_erro_eproc()
        if conteudo:
            self.inserir_texto_editor(conteudo)
            time.sleep(2)
            self._fechar_popups_erro_eproc()
        else:
            self.log("  Sem conteúdo na coluna J — editor ficará só com o template.")
        self.salvar_e_sair_editor()
        self.log(f"✓ Texto Padrão '{descricao}' cadastrado, conteúdo inserido, Alt+Z disparado.")
        return True

    def filtrar_texto_por_descricao(self, descricao: str) -> bool:
        if not descricao:
            return False
        try:
            self.driver.find_element(By.ID, "txtDescricaoTexto")
        except NoSuchElementException:
            self.abrir_lista_textos_padrao()
        try:
            campo = self._aguardar_elemento(By.ID, "txtDescricaoTexto")
            campo.clear()
            campo.send_keys(descricao)
            time.sleep(0.5)
            btn = self._aguardar_clicavel(By.ID, "btnConsultar", timeout=5)
            btn.click()
            time.sleep(2)
            self.log(f"Filtrado por descrição: {descricao}")
            return True
        except Exception as e:
            self.log(f"Falha ao filtrar: {e}", nivel="WARN")
            return False

    def filtrar_texto_por_codigo(self, codigo: str) -> bool:
        if not codigo:
            return False
        try:
            self.driver.find_element(By.ID, "txtCodigoTexto")
        except NoSuchElementException:
            self.abrir_lista_textos_padrao()
        try:
            campo = self._aguardar_elemento(By.ID, "txtCodigoTexto")
            campo.clear()
            campo.send_keys(str(codigo))
            time.sleep(0.5)
            btn = self._aguardar_clicavel(By.ID, "btnConsultar", timeout=5)
            btn.click()
            time.sleep(2)
            self.log(f"Filtrado por código: {codigo}")
            return True
        except Exception as e:
            self.log(f"Falha ao filtrar: {e}", nivel="WARN")
            return False

    def filtrar_texto_por_sigla(self, sigla: str) -> bool:
        if not sigla:
            return False
        try:
            self.driver.find_element(By.ID, "txtSiglaTexto")
        except NoSuchElementException:
            self.abrir_lista_textos_padrao()
        try:
            campo = self._aguardar_elemento(By.ID, "txtSiglaTexto")
            campo.clear()
            campo.send_keys(sigla)
            time.sleep(0.5)
            btn = self._aguardar_clicavel(By.ID, "btnConsultar", timeout=5)
            btn.click()
            time.sleep(2)
            self.log(f"Filtrado por sigla: {sigla}")
            return True
        except Exception as e:
            self.log(f"Falha ao filtrar: {e}", nivel="WARN")
            return False

    def _filtrar_texto(self, descricao: str, codigo: str, sigla: str) -> bool:
        if codigo:
            return self.filtrar_texto_por_codigo(codigo)
        if sigla:
            return self.filtrar_texto_por_sigla(sigla)
        if descricao:
            return self.filtrar_texto_por_descricao(descricao)
        return False

    def desativar_texto_padrao(self, descricao: str = "", codigo: str = "", sigla: str = "") -> bool:
        if not self._filtrar_texto(descricao, codigo, sigla):
            self.log("Forneça descrição, código OU sigla para desativar.", nivel="ERROR")
            return False
        if not self._marcar_primeiro_resultado_lista():
            self.log("Nenhum texto padrão encontrado para desativar.", nivel="WARN")
            return False
        try:
            btn = self._aguardar_clicavel(By.ID, "btnDesativar", timeout=5)
            btn.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log("✓ Desativação enviada.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"btnDesativar indisponível: {e}", nivel="ERROR")
            return False

    def publicar_texto_padrao(self, descricao: str = "", codigo: str = "", sigla: str = "") -> bool:
        if not self._filtrar_texto(descricao, codigo, sigla):
            return False
        if not self._marcar_primeiro_resultado_lista():
            return False
        try:
            btn = self._aguardar_clicavel(By.ID, "btnPublicar", timeout=5)
            btn.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log("✓ Texto Padrão publicado.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"btnPublicar indisponível: {e}", nivel="ERROR")
            return False

    def retirar_publicacao_texto_padrao(self, descricao: str = "", codigo: str = "", sigla: str = "") -> bool:
        if not self._filtrar_texto(descricao, codigo, sigla):
            return False
        if not self._marcar_primeiro_resultado_lista():
            return False
        try:
            btn = self._aguardar_clicavel(By.ID, "btnRetirarPublicacao", timeout=5)
            btn.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log("✓ Publicação retirada.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"btnRetirarPublicacao indisponível: {e}", nivel="ERROR")
            return False

    def editar_conteudo_texto_padrao(self, descricao: str = "", codigo: str = "",
                                      sigla: str = "", conteudo: str = "") -> bool:
        """
        Edita conteúdo de Texto Padrão: filtra → clica 'Editar texto padrão' →
        editor abre → espera 12s + Ctrl+A + Delete + digitar → Alt+Z.
        """
        if not self._filtrar_texto(descricao, codigo, sigla):
            self.log("Forneça descrição, código OU sigla para editar.", nivel="ERROR")
            return False
        time.sleep(1)
        janelas_antes = len(self.driver.window_handles)
        clicou = self._clicar_acao_texto_padrao_lista(descricao, codigo, sigla, "editar")
        if not clicou:
            self.log("Nenhuma forma de chegar ao editor — texto não encontrado.", nivel="ERROR")
            return False
        if len(self.driver.window_handles) > janelas_antes:
            self._trocar_para_nova_aba()
            self.log("Editor aberto em nova aba.")
        else:
            self.log("Editor abriu na mesma aba.")
        self.log("  Aguardando o documento abrir...")
        if not self._aguardar_ckeditor_pronto(timeout=30):
            self.log("AVISO: editor não ficou pronto em 30s.", nivel="WARN")
            return False
        self._fechar_popups_erro_eproc()
        if conteudo:
            self.inserir_texto_editor(conteudo)
            time.sleep(2)
            self._fechar_popups_erro_eproc()
        else:
            self.log("Coluna K vazia — só abrindo editor.")
        self.salvar_e_sair_editor()
        self.log(f"✓ Texto Padrão editado e Alt+Z disparado.")
        return True

    def _clicar_acao_texto_padrao_lista(self, descricao: str, codigo: str,
                                         sigla: str, acao: str) -> bool:
        """Procura na linha do texto pelo ícone da ação especificada (editar, etc.)."""
        try:
            linhas = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for linha in linhas:
                try:
                    txt = (linha.text or "").lower()
                    if not txt:
                        continue
                    casa = False
                    if descricao and descricao.lower() in txt:
                        casa = True
                    elif codigo and str(codigo) in txt:
                        casa = True
                    elif sigla and sigla.lower() in txt:
                        casa = True
                    if not casa:
                        continue
                    # Procura ícone preferencialmente 'editar texto padrão'
                    for prioridade in ["editar texto padrão", "editar texto padrao",
                                       "editar texto", "editar"]:
                        for elem in linha.find_elements(
                            By.CSS_SELECTOR, "a[title], img[title], button[title]"):
                            title = (elem.get_attribute("title") or "").lower()
                            if prioridade in title:
                                try:
                                    elem.click()
                                    self.log(f"  Clique na ação '{acao}' (title='{title}').")
                                    return True
                                except ElementClickInterceptedException:
                                    self.driver.execute_script("arguments[0].click();", elem)
                                    return True
                except Exception:
                    continue
        except Exception as e:
            self.log(f"Falha ao procurar ação na lista: {str(e)[:120]}", nivel="WARN")
        return False

    def executar_texto_padrao(self, dados: dict) -> tuple:
        """Despachador conforme 'Tipo de Ação' da aba Texto Padrão."""
        acao = (dados.get("tipo_acao") or "").strip().upper()
        try:
            if acao in ("CRIAR", "CRIAR NOVO", "CADASTRAR", "NOVO"):
                ok = self.cadastrar_novo_texto_padrao(
                    dados.get("descricao", ""),
                    dados.get("sigla", ""),
                    dados.get("publico", "N"),
                    dados.get("conteudo", ""))
                return (ok, "OK" if ok else "Falha ao cadastrar texto padrão")
            if acao in ("EDITAR", "ALTERAR"):
                ok = self.editar_conteudo_texto_padrao(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""),
                    sigla=dados.get("sigla", ""),
                    conteudo=dados.get("conteudo_edicao", ""))
                return (ok, "OK" if ok else "Falha ao editar texto padrão")
            if acao in ("DESATIVAR", "REMOVER"):
                ok = self.desativar_texto_padrao(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""),
                    sigla=dados.get("sigla", ""))
                return (ok, "OK" if ok else "Falha ao desativar")
            if acao in ("PUBLICAR",):
                ok = self.publicar_texto_padrao(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""),
                    sigla=dados.get("sigla", ""))
                return (ok, "OK" if ok else "Falha ao publicar")
            if acao in ("RETIRAR PUBLICACAO", "RETIRAR PUBLICAÇÃO", "DESPUBLICAR"):
                ok = self.retirar_publicacao_texto_padrao(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""),
                    sigla=dados.get("sigla", ""))
                return (ok, "OK" if ok else "Falha ao retirar publicação")
            if acao in ("LISTAR", "ABRIR LISTA"):
                self.abrir_lista_textos_padrao()
                return (True, "Lista aberta")
            return (False, f"Tipo de Ação desconhecido: '{acao}'")
        except Exception as e:
            return (False, f"Exceção em '{acao}': {str(e)[:200]}")

    # ══════════════════════════════════════════
    # FLUXO LOTE DE MINUTAS — criação em massa
    # URLs: localizador_processos_lista → minuta_cadastrar_lote
    # ══════════════════════════════════════════
    def abrir_lista_processos_localizador(self):
        """Navega para 'Lista de Processos por Localizador' via menu textual."""
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa.")
        for termo, alvo in [
            ("Lista de Processos por Localizador", "Lista de Processos por Localizador"),
            ("Processos por Localizador", "Processos por Localizador"),
            ("Lista de Processos", "Lista de Processos"),
        ]:
            if self._navegar_via_menu_textual(termo, alvo):
                try:
                    self._aguardar_elemento(By.ID, "selLocalizador", timeout=8)
                    self.log("✓ Lista de Processos por Localizador aberta.")
                    return
                except TimeoutException:
                    continue
        raise RuntimeError("Não foi possível chegar em 'Lista de Processos por Localizador'.")

    def filtrar_lista_por_localizador(self, nome_localizador: str) -> bool:
        """Marca o localizador no selLocalizador (multi-select bootstrap) e clica Consultar."""
        if not nome_localizador:
            self.log("Localizador vazio.", nivel="ERROR")
            return False
        try:
            self.driver.find_element(By.ID, "selLocalizador")
        except NoSuchElementException:
            self.abrir_lista_processos_localizador()
        # selLocalizador é multi-select bootstrap-select. Usa JS para marcar a opção certa.
        try:
            ok = self.driver.execute_script("""
                var alvo = arguments[0].toLowerCase().trim();
                var sel = document.getElementById('selLocalizador');
                if (!sel) return {ok:false, motivo:'sel_nao_encontrado'};
                var matches = [];
                for (var i=0; i<sel.options.length; i++) {
                    var t = (sel.options[i].text || '').toLowerCase().trim();
                    if (t === alvo || t.indexOf(alvo) !== -1) {
                        sel.options[i].selected = true;
                        matches.push(sel.options[i].text);
                    }
                }
                if (window.jQuery) {
                    try { jQuery(sel).trigger('change'); } catch(e){}
                    try { jQuery(sel).selectpicker('refresh'); } catch(e){}
                }
                return {ok: matches.length > 0, matches: matches, total: sel.options.length};
            """, nome_localizador)
            if not (ok and ok.get("ok")):
                self.log(f"Localizador '{nome_localizador}' não encontrado ({ok}).", nivel="ERROR")
                return False
            self.log(f"Localizador marcado: {ok.get('matches')}")
            time.sleep(0.5)
        except Exception as e:
            self.log(f"Falha ao marcar localizador: {str(e)[:120]}", nivel="ERROR")
            return False
        # Clica Consultar
        try:
            btn = self._aguardar_clicavel(By.ID, "btnConsultar", timeout=8)
            try:
                btn.click()
            except ElementClickInterceptedException:
                self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(2)
            self.log("✓ Filtro aplicado, lista carregada.")
            return True
        except (TimeoutException, NoSuchElementException):
            try:
                self.driver.execute_script("validarSelecaoForm(); document.getElementById('frmProcessoLista').submit();")
                time.sleep(2)
                self.log("✓ Filtro submetido via JS fallback.")
                return True
            except Exception as e:
                self.log(f"btnConsultar indisponível: {str(e)[:120]}", nivel="ERROR")
                return False

    def marcar_todos_processos_lista(self) -> int:
        """Marca TODOS os checkboxes chkInfraItem da lista de resultados. Retorna quantos marcou."""
        try:
            # 1) Tenta clicar no 'Marcar Todos' (lnkInfraCheck / imgInfraCheck)
            for sid in ["lnkInfraCheck", "imgInfraCheck"]:
                try:
                    el = self.driver.find_element(By.ID, sid)
                    if el.is_displayed():
                        el.click()
                        time.sleep(0.5)
                        break
                except NoSuchElementException:
                    continue
            # 2) Conta quantos foram marcados (independente do método)
            chks = self.driver.find_elements(By.CSS_SELECTOR, "input[id^='chkInfraItem'][type='checkbox']")
            marcados = 0
            for chk in chks:
                try:
                    if chk.is_displayed():
                        if not chk.is_selected():
                            chk.click()
                            time.sleep(0.05)
                        marcados += 1
                except Exception:
                    continue
            self.log(f"Marcados {marcados}/{len(chks)} processos da lista.")
            return marcados
        except Exception as e:
            self.log(f"Falha ao marcar processos: {str(e)[:120]}", nivel="ERROR")
            return 0

    def marcar_processos_por_numero(self, lista_numeros: list) -> int:
        """Marca apenas os chkInfraItem cujas linhas contêm os números informados."""
        if not lista_numeros:
            return 0
        nums_norm = [re.sub(r"[^\d]", "", n) for n in lista_numeros if n]
        marcados = 0
        try:
            linhas = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for linha in linhas:
                try:
                    txt = (linha.text or "")
                    txt_norm = re.sub(r"[^\d]", "", txt)
                    if any(n and n in txt_norm for n in nums_norm):
                        chk = linha.find_element(By.CSS_SELECTOR, "input[id^='chkInfraItem']")
                        if not chk.is_selected():
                            chk.click()
                            marcados += 1
                            time.sleep(0.05)
                except Exception:
                    continue
            self.log(f"Marcados {marcados} processo(s) pelos números informados.")
            return marcados
        except Exception as e:
            self.log(f"Falha ao marcar por número: {str(e)[:120]}", nivel="WARN")
            return marcados

    def acionar_criar_lote_minutas(self):
        """Dispara a função JS gerarLoteMinutas() que abre nova aba com minuta_cadastrar_lote."""
        janelas_antes = len(self.driver.window_handles)
        try:
            self.driver.execute_script("gerarLoteMinutas();")
            time.sleep(2)
            self._tratar_alert(aceitar=True)
            self.log("gerarLoteMinutas() disparado.")
        except Exception as e:
            self.log(f"Falha ao disparar gerarLoteMinutas(): {str(e)[:120]}", nivel="ERROR")
            raise
        # Aguarda nova aba ou navegação na mesma
        time.sleep(2)
        if len(self.driver.window_handles) > janelas_antes:
            self._trocar_para_nova_aba()
            self.log("Nova aba 'Criar Lote de Minutas' aberta.")
        # Confirma com o ID da descrição do lote
        try:
            self._aguardar_elemento(By.ID, "txtDescricaoLoteMinuta", timeout=5)
            self.log("✓ Formulário de Lote de Minutas pronto.")
        except TimeoutException:
            self.log("txtDescricaoLoteMinuta não apareceu — verifique no navegador.", nivel="WARN")

    def preencher_descricao_lote(self, descricao: str):
        if not descricao:
            return
        try:
            campo = self._aguardar_elemento(By.ID, "txtDescricaoLoteMinuta", timeout=8)
            campo.clear()
            campo.send_keys(descricao)
            self.log(f"Descrição do lote: {descricao}")
        except (TimeoutException, NoSuchElementException):
            self.log("txtDescricaoLoteMinuta não encontrado.", nivel="WARN")

    def submeter_lote_minutas(self):
        """Clica sbmCadastrarMinutaLote (Alt+S) para criar todas as minutas em lote."""
        try:
            self._atalho("alt", "s", "Salvar Lote de Minutas")
            time.sleep(2)
            self._tratar_alert(aceitar=True)
            self.log("Alt+S disparado (submit do lote).")
            return
        except Exception:
            pass
        try:
            btn = self._aguardar_clicavel(By.ID, "sbmCadastrarMinutaLote", timeout=5)
            btn.click()
            time.sleep(2)
            self._tratar_alert(aceitar=True)
            self.log("sbmCadastrarMinutaLote clicado.")
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"sbmCadastrarMinutaLote indisponível: {str(e)[:120]}", nivel="ERROR")
            raise

    def executar_lote_minutas(self, dados: dict) -> tuple:
        """
        Fluxo completo de Lote de Minutas:
          1. Abre Lista de Processos por Localizador (via menu textual)
          2. Filtra por localizador
          3. Marca processos (todos OU por número da planilha)
          4. Dispara gerarLoteMinutas()
          5. Preenche descrição do lote + dados da minuta (reusa formulário de minuta)
          6. Submete (Alt+S em sbmCadastrarMinutaLote)
        """
        localizador = dados.get("localizador_origem", "")
        if not localizador:
            return False, "Localizador de Origem obrigatório."
        descricao_lote = dados.get("descricao_lote", "Lote criado pelo robô v4")
        # processos: "todos" ou lista separada por ; ,
        proc_raw = dados.get("processos", "").strip()
        passos = [
            ("Abrir Lista de Processos por Localizador",
                lambda: self.abrir_lista_processos_localizador()),
            ("Filtrar por localizador",
                lambda: self.filtrar_lista_por_localizador(localizador)),
        ]
        if proc_raw and proc_raw.lower() not in ("todos", "all", "*"):
            lista_proc = _lista_de(proc_raw)
            passos.append(("Marcar processos por número",
                lambda: self.marcar_processos_por_numero(lista_proc)))
        else:
            passos.append(("Marcar TODOS os processos da lista",
                lambda: self.marcar_todos_processos_lista()))
        passos += [
            ("Acionar Criar Lote", lambda: self.acionar_criar_lote_minutas()),
            ("Descrição do Lote", lambda: self.preencher_descricao_lote(descricao_lote)),
            ("Tipo/Modelo", lambda: self.preencher_tipo_modelo(dados.get("tipo_modelo", "DESPACHO"))),
            ("Descrição da minuta", lambda: self.preencher_descricao(dados.get("descricao_minuta", ""))),
            ("Assinante", lambda: self.selecionar_assinante(dados.get("assinante", ""))),
            ("Tratamento", lambda: self.selecionar_tratamento(dados.get("tratamento", ""))),
            ("Sigilo", lambda: self.selecionar_sigilo(dados.get("sigilo", ""))),
            ("Status Minuta", lambda: self.selecionar_status_minuta(dados.get("status_minuta", ""))),
        ]
        if str(dados.get("agendar", "")).strip().upper() in ("S", "SIM", "TRUE", "1"):
            passos += [
                ("Marcar Agendamento", lambda: self.marcar_agendamento(True)),
                ("Evento Agendamento", lambda: self.preencher_evento_agendamento(dados.get("evento", ""))),
                ("Comportamento Localizador",
                    lambda: self.selecionar_comportamento_localizador(dados.get("comportamento_localizador", ""))),
            ]
            if str(dados.get("marcar_todos_atuais", "S")).upper() in ("S", "SIM", "TRUE", "1"):
                passos.append(("Marcar TODOS atuais",
                    lambda: self.marcar_todos_localizadores_atuais()))
            passos.append(("Novo Localizador",
                lambda: self.selecionar_novo_localizador(dados.get("novo_localizador", ""))))
        passos.append(("Submeter Lote (Alt+S)", lambda: self.submeter_lote_minutas()))

        for nome, fn in passos:
            try:
                self.log(f"━ Passo: {nome}")
                fn()
                self._tratar_alert()
                if not self.verificar_sessao_ativa():
                    return False, f"Sessão expirou em '{nome}'"
            except Exception as e:
                self._tratar_alert()
                return False, f"Falha em '{nome}': {str(e)[:200]}"
        return True, "OK"

    # ══════════════════════════════════════════
    # FLUXO MODELOS PADRÃO — cadastro/edição
    # URLs: modelo_padrao_lista / modelo_padrao_cadastrar / editorweb_modelo_padrao
    # ══════════════════════════════════════════
    def abrir_lista_modelos_padrao(self):
        """Abre a tela 'Modelos' via menu textual (preserva hash da sessão)."""
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa.")
        # Tenta vários termos comuns
        for termo, alvo in [
            ("Modelos", "Modelos"),
            ("Modelos Padrão", "Modelos"),
            ("Modelo padrão", "Modelo"),
        ]:
            if self._navegar_via_menu_textual(termo, alvo):
                try:
                    self._aguardar_elemento(By.ID, "txtTermoPesquisa", timeout=8)
                    self.log("✓ Lista de Modelos aberta.")
                    return
                except TimeoutException:
                    continue
        raise RuntimeError(
            "Não foi possível chegar em 'Modelos'. Verifique se o seu perfil tem permissão.")

    def abrir_cadastro_novo_modelo(self):
        """Abre a tela de cadastro a partir da lista (preserva hash)."""
        try:
            self.driver.find_element(By.ID, "btnNovo")
        except NoSuchElementException:
            self.abrir_lista_modelos_padrao()
        try:
            btn = self._aguardar_clicavel(By.ID, "btnNovo", timeout=8)
            btn.click()
            time.sleep(1.5)
            self._aguardar_elemento(By.ID, "txtDesModeloPadrao", timeout=10)
            self.log("✓ Cadastro de Modelo aberto.")
        except (TimeoutException, NoSuchElementException) as e:
            raise RuntimeError(f"Não consegui abrir o cadastro de modelo: {e}")

    def cadastrar_novo_modelo(self, tipo_documento: str, descricao: str,
                              classificacao: str = "", publico: str = "N",
                              conteudo: str = "") -> bool:
        """
        Cadastra novo modelo padrão.
        Master: selModeloMatriz (Tipo), txtDesModeloPadrao (Descrição),
                selClassificacaoConteudoIds (Classificação), chkSinPublico (Público).
        Submit: name=sbmCadastrarModeloPadrao (Alt+S).
        Após salvar, o eproc abre o CKEditor automaticamente; se 'conteudo' foi passado,
        insere via CKEDITOR.setData e fecha com Alt+Z.
        """
        if not tipo_documento or not descricao:
            self.log("Tipo de documento e Descrição são obrigatórios.", nivel="ERROR")
            return False
        try:
            self.driver.find_element(By.ID, "txtDesModeloPadrao")
        except NoSuchElementException:
            self.abrir_cadastro_novo_modelo()
        # Tipo de documento (Modelo Matriz)
        self._selecionar_dropdown("selModeloMatriz", tipo_documento, "Tipo de Documento")
        time.sleep(0.5)
        # Descrição
        try:
            campo = self._aguardar_elemento(By.ID, "txtDesModeloPadrao")
            campo.clear()
            campo.send_keys(descricao)
            self.log(f"Descrição: {descricao}")
        except Exception as e:
            self.log(f"Falha ao preencher descrição: {e}", nivel="ERROR")
            return False
        # Classificação (opcional, multi-select)
        if classificacao:
            try:
                # Tenta selectpicker / multi-select
                for sid in ["selClassificacaoConteudoIds", "selClassificacaoConteudo"]:
                    try:
                        self.driver.find_element(By.ID, sid)
                        ok_js = self.driver.execute_script("""
                            var alvo = arguments[1].toLowerCase();
                            var sel = document.getElementById(arguments[0]);
                            if (!sel) return false;
                            for (var i=0; i<sel.options.length; i++) {
                                if ((sel.options[i].text || '').toLowerCase().indexOf(alvo) !== -1) {
                                    sel.options[i].selected = true;
                                }
                            }
                            if (window.jQuery) {
                                try { jQuery(sel).trigger('change'); } catch(e){}
                                try { jQuery(sel).selectpicker('refresh'); } catch(e){}
                            }
                            return true;
                        """, sid, classificacao)
                        if ok_js:
                            self.log(f"Classificação: {classificacao}")
                            break
                    except NoSuchElementException:
                        continue
            except Exception:
                self.log("Não consegui marcar classificação (pode ignorar).", nivel="WARN")
        # Público
        quer_publico = str(publico).strip().upper() in ("S", "SIM", "TRUE", "1")
        try:
            chk = self.driver.find_element(By.ID, "chkSinPublico")
            if chk.is_selected() != quer_publico:
                chk.click()
            self.log(f"Público: {'S' if quer_publico else 'N'}")
        except NoSuchElementException:
            pass
        # Submit (Alt+S em sbmCadastrarModeloPadrao)
        try:
            self._atalho("alt", "s", "Salvar Modelo")
            time.sleep(2)
            self._tratar_alert(aceitar=True)
        except Exception:
            try:
                btn = self.driver.find_element(By.NAME, "sbmCadastrarModeloPadrao")
                btn.click()
                time.sleep(2)
                self._tratar_alert(aceitar=True)
            except Exception as e:
                self.log(f"Falha ao submeter: {e}", nivel="ERROR")
                return False
        # Após Alt+S, o eproc abre o editor. Esperar, colar coluna J, Alt+Z. Pronto.
        self.log(f"  Aguardando o editor abrir após salvar o cadastro...")
        if not self._aguardar_ckeditor_pronto(timeout=30):
            self.log(f"AVISO: editor não ficou pronto em 30s. Cadastro talvez não tenha aberto o editor.",
                     nivel="WARN")
            # Mesmo assim consideramos OK (modelo foi criado)
            return True
        self._fechar_popups_erro_eproc()
        if conteudo:
            self.inserir_texto_editor(conteudo)
            time.sleep(2)  # Espera mais para o setData ser totalmente refletido
            self._fechar_popups_erro_eproc()
        else:
            self.log("  Sem conteúdo na coluna J — editor ficará só com o template padrão.")
        self.salvar_e_sair_editor()
        self.log(f"✓ Modelo '{descricao}' cadastrado, conteúdo inserido, Alt+Z disparado.")
        return True

    def _editor_ckeditor_disponivel(self) -> bool:
        """Verifica se há um CKEditor inicializado na página atual."""
        try:
            return bool(self.driver.execute_script(
                "return (typeof CKEDITOR !== 'undefined') && CKEDITOR.instances && "
                "Object.keys(CKEDITOR.instances).length > 0;"))
        except Exception:
            return False

    def filtrar_modelo_por_descricao(self, descricao: str) -> bool:
        """Na lista de modelos, filtra por descrição e clica Consultar."""
        if not descricao:
            return False
        try:
            self.driver.find_element(By.ID, "txtDescricaoModelo")
        except NoSuchElementException:
            self.abrir_lista_modelos_padrao()
        try:
            campo = self._aguardar_elemento(By.ID, "txtDescricaoModelo")
            campo.clear()
            campo.send_keys(descricao)
            time.sleep(0.5)
            btn = self._aguardar_clicavel(By.ID, "btnConsultar", timeout=5)
            btn.click()
            time.sleep(2)
            self.log(f"Filtrado por descrição: {descricao}")
            return True
        except Exception as e:
            self.log(f"Falha ao filtrar: {e}", nivel="WARN")
            return False

    def filtrar_modelo_por_codigo(self, codigo: str) -> bool:
        """Filtra por código do modelo."""
        if not codigo:
            return False
        try:
            self.driver.find_element(By.ID, "txtCodigoModelo")
        except NoSuchElementException:
            self.abrir_lista_modelos_padrao()
        try:
            campo = self._aguardar_elemento(By.ID, "txtCodigoModelo")
            campo.clear()
            campo.send_keys(str(codigo))
            time.sleep(0.5)
            btn = self._aguardar_clicavel(By.ID, "btnConsultar", timeout=5)
            btn.click()
            time.sleep(2)
            self.log(f"Filtrado por código: {codigo}")
            return True
        except Exception as e:
            self.log(f"Falha ao filtrar por código: {e}", nivel="WARN")
            return False

    def _marcar_primeiro_resultado_lista(self) -> bool:
        """Marca o primeiro chkInfraItem da lista de resultados."""
        try:
            chks = self.driver.find_elements(
                By.CSS_SELECTOR, "input[id^='chkInfraItem'][type='checkbox']")
            for chk in chks:
                if chk.is_displayed():
                    if not chk.is_selected():
                        chk.click()
                    return True
        except Exception:
            pass
        return False

    def desativar_modelo(self, descricao: str = "", codigo: str = "") -> bool:
        """Desativa modelo: filtra (por código se houver, senão descrição) → marca → btnDesativar."""
        if codigo:
            self.filtrar_modelo_por_codigo(codigo)
        elif descricao:
            self.filtrar_modelo_por_descricao(descricao)
        else:
            self.log("Forneça código OU descrição para desativar.", nivel="ERROR")
            return False
        if not self._marcar_primeiro_resultado_lista():
            self.log("Nenhum modelo encontrado para desativar.", nivel="WARN")
            return False
        try:
            btn = self._aguardar_clicavel(By.ID, "btnDesativar", timeout=5)
            btn.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log(f"✓ Desativação enviada.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"btnDesativar indisponível: {e}", nivel="ERROR")
            return False

    def publicar_modelo(self, descricao: str = "", codigo: str = "") -> bool:
        """Publica modelo: filtra → marca → btnPublicar."""
        if codigo:
            self.filtrar_modelo_por_codigo(codigo)
        elif descricao:
            self.filtrar_modelo_por_descricao(descricao)
        else:
            return False
        if not self._marcar_primeiro_resultado_lista():
            self.log("Nenhum modelo encontrado para publicar.", nivel="WARN")
            return False
        try:
            btn = self._aguardar_clicavel(By.ID, "btnPublicar", timeout=5)
            btn.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log(f"✓ Modelo publicado.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"btnPublicar indisponível: {e}", nivel="ERROR")
            return False

    def retirar_publicacao_modelo(self, descricao: str = "", codigo: str = "") -> bool:
        """Retira publicação: filtra → marca → btnRetirarPublicacao."""
        if codigo:
            self.filtrar_modelo_por_codigo(codigo)
        elif descricao:
            self.filtrar_modelo_por_descricao(descricao)
        else:
            return False
        if not self._marcar_primeiro_resultado_lista():
            return False
        try:
            btn = self._aguardar_clicavel(By.ID, "btnRetirarPublicacao", timeout=5)
            btn.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log(f"✓ Publicação retirada.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"btnRetirarPublicacao indisponível: {e}", nivel="ERROR")
            return False

    def editar_conteudo_modelo(self, descricao: str = "", codigo: str = "",
                                conteudo: str = "") -> bool:
        """
        Edita conteúdo de modelo padrão (versão simples):
          1. Filtrar na lista por descrição/código
          2. Clicar no ícone "Editar modelo padrão" (lápis amarelo da linha)
          3. Esperar o editor abrir (até 30s)
          4. Colar conteúdo da coluna K (via CKEDITOR.setData)
          5. Alt+Z — pronto, considera ok
        """
        if codigo:
            self.filtrar_modelo_por_codigo(codigo)
        elif descricao:
            self.filtrar_modelo_por_descricao(descricao)
        else:
            self.log("Forneça código OU descrição para editar.", nivel="ERROR")
            return False
        time.sleep(1)

        # 1) Procurar link/ícone de "Editar" na linha do resultado (preferencial)
        janelas_antes = len(self.driver.window_handles)
        clicou = self._clicar_acao_modelo_lista(descricao, codigo, "editar")
        if not clicou:
            # 2) Fallback: clicar no link da descrição (abre tela de detalhes)
            clicou = self._clicar_link_modelo_lista(descricao, codigo)
            if clicou:
                time.sleep(1.5)
                # Na tela de detalhes, procurar botão Editar
                try:
                    btn = self._aguardar_clicavel(By.NAME, "btnEditar", timeout=5)
                    btn.click()
                    time.sleep(2)
                except (TimeoutException, NoSuchElementException):
                    # Tenta variações
                    achou_botao = False
                    for seletor in [
                        (By.XPATH, "//button[normalize-space(.)='Editar']"),
                        (By.XPATH, "//a[normalize-space(.)='Editar' or @title='Editar']"),
                        (By.XPATH, "//img[@title='Editar']"),
                        (By.CSS_SELECTOR, "button[onclick*='editar' i]"),
                    ]:
                        try:
                            b = self._aguardar_clicavel(*seletor, timeout=3)
                            b.click()
                            time.sleep(2)
                            achou_botao = True
                            break
                        except (TimeoutException, NoSuchElementException):
                            continue
                    if not achou_botao:
                        self.log("Botão 'Editar' não encontrado na tela de detalhes do modelo.", nivel="ERROR")
                        return False
        if not clicou:
            self.log("Nenhuma forma de chegar ao editor — modelo não encontrado ou sem ação editar.", nivel="ERROR")
            return False

        # 3) Detectar se abriu nova aba
        if len(self.driver.window_handles) > janelas_antes:
            self._trocar_para_nova_aba()
            self.log("Editor aberto em nova aba.")
        else:
            self.log("Editor abriu na mesma aba.")

        # 4) Esperar o editor abrir
        self.log("  Aguardando o documento abrir...")
        if not self._aguardar_ckeditor_pronto(timeout=30):
            self.log(f"AVISO: editor não ficou pronto em 30s.", nivel="WARN")
            return False
        self._fechar_popups_erro_eproc()

        # 5) Colar conteúdo da coluna K
        if conteudo:
            self.inserir_texto_editor(conteudo)
            time.sleep(2)  # Espera o setData refletir totalmente
            self._fechar_popups_erro_eproc()
        else:
            self.log("Coluna K vazia — só abrindo editor sem alterar.")

        # 6) Alt+Z (considera pronto)
        self.salvar_e_sair_editor()
        self.log(f"✓ Modelo editado e Alt+Z disparado.")
        return True

    def _clicar_editar_primeira_linha_lista(self) -> bool:
        """
        Clica no ícone 'Editar modelo padrão' (lápis amarelo) da PRIMEIRA linha
        visível da lista de modelos. Usado no encadeamento CADASTRAR → EDITAR,
        quando o modelo recém-criado fica como primeira linha (ordenação default
        do eproc é por data de inclusão desc).
        """
        try:
            linhas = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for linha in linhas:
                if not linha.is_displayed():
                    continue
                # Procura ícones com title contendo 'editar modelo padrão' nesta linha
                for elem in linha.find_elements(
                    By.CSS_SELECTOR, "a[title], img[title], button[title]"):
                    title = (elem.get_attribute("title") or "").lower()
                    if ("editar modelo padrão" in title
                            or "editar modelo padrao" in title
                            or "editar modelo" in title):
                        try:
                            elem.click()
                            self.log(f"  Clique no ícone editar (1ª linha, title='{title}').")
                            return True
                        except ElementClickInterceptedException:
                            self.driver.execute_script("arguments[0].click();", elem)
                            return True
                # Se não achou por title específico, tenta clicar no PRIMEIRO ícone
                # com title contendo apenas 'editar' (não 'alterar')
                for elem in linha.find_elements(
                    By.CSS_SELECTOR, "a[title], img[title], button[title]"):
                    title = (elem.get_attribute("title") or "").lower()
                    if "editar" in title and "alterar" not in title:
                        try:
                            elem.click()
                            self.log(f"  Clique no ícone editar (fallback, title='{title}').")
                            return True
                        except Exception:
                            continue
                # Se chegou aqui, esta linha não tinha ícone editar — passa para a próxima
                break  # só tenta a primeira linha visível
        except Exception as e:
            self.log(f"  Falha ao buscar ícone editar: {str(e)[:120]}", nivel="WARN")
        return False

    def _clicar_acao_modelo_lista(self, descricao: str, codigo: str, acao: str) -> bool:
        """
        Procura na linha do modelo (filtrado) pelo ícone/link da ação especificada.
        Para 'editar': prioriza title contendo 'editar modelo' (CKEditor) sobre
        'alterar dados' (volta ao cadastro). Manual p.200 distingue os dois.
        """
        # Para 'editar', define ordem de preferência por match específico
        preferencias = []
        if acao == "editar":
            preferencias = [
                "editar modelo padrão", "editar modelo padrao",
                "editar modelo", "editar conteudo", "editar conteúdo",
                "editar"  # último fallback
            ]
        elif acao == "alterar":
            preferencias = ["alterar dados", "alterar"]
        elif acao == "visualizar":
            preferencias = ["consultar modelo", "consultar", "visualizar"]
        elif acao == "desativar":
            preferencias = ["desativar"]
        else:
            preferencias = [acao]

        try:
            # Procura linhas com a descrição/código
            linhas = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            linha_alvo = None
            for linha in linhas:
                try:
                    txt = (linha.text or "").lower()
                    if not txt:
                        continue
                    if descricao and descricao.lower() in txt:
                        linha_alvo = linha
                        break
                    if codigo and str(codigo) in txt:
                        linha_alvo = linha
                        break
                except Exception:
                    continue
            if not linha_alvo:
                return False

            # Coleta TODOS os elementos com title na linha alvo
            elementos = linha_alvo.find_elements(
                By.CSS_SELECTOR, "a[title], img[title], button[title], i[title]")
            # Loga para debug
            titles = [(e.get_attribute("title") or "")[:60] for e in elementos]
            self.log(f"  Ícones disponíveis na linha: {titles}")

            # Tenta cada preferência em ordem
            for pref in preferencias:
                for elem in elementos:
                    title = (elem.get_attribute("title") or "").lower()
                    if pref in title:
                        try:
                            # Se for IMG, clica no <a> pai
                            tag = elem.tag_name.lower()
                            if tag == "img":
                                pai = elem.find_element(By.XPATH, "./ancestor::a[1]")
                                pai.click()
                            else:
                                elem.click()
                            self.log(f"  Clique na ação '{pref}' (title='{title[:80]}').")
                            return True
                        except ElementClickInterceptedException:
                            self.driver.execute_script("arguments[0].click();", elem)
                            self.log(f"  Clique JS na ação '{pref}'.")
                            return True
                        except Exception as e:
                            self.log(f"  Falha ao clicar '{pref}': {str(e)[:80]}", nivel="WARN")
                            continue
        except Exception as e:
            self.log(f"Falha ao procurar ação '{acao}' na lista: {str(e)[:120]}", nivel="WARN")
        return False

    def _clicar_link_modelo_lista(self, descricao: str, codigo: str) -> bool:
        """Clica no link cuja célula contém a descrição/código."""
        try:
            linhas = self.driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for linha in linhas:
                try:
                    txt = (linha.text or "").lower()
                    if not txt:
                        continue
                    casa = False
                    if descricao and descricao.lower() in txt:
                        casa = True
                    elif codigo and str(codigo) in txt:
                        casa = True
                    if not casa:
                        continue
                    # Pega o primeiro link clicável da linha (não chk, não controle)
                    for a in linha.find_elements(By.TAG_NAME, "a"):
                        try:
                            if a.is_displayed() and (a.text or "").strip():
                                a.click()
                                self.log(f"  Clique no link: {(a.text or '')[:60]}")
                                return True
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception as e:
            self.log(f"Falha ao clicar link: {str(e)[:120]}", nivel="WARN")
        return False

    def executar_modelo(self, dados: dict) -> tuple:
        """Despachador conforme 'Tipo de Ação' da aba Modelos."""
        acao = (dados.get("tipo_acao") or "").strip().upper()
        try:
            if acao in ("CRIAR", "CRIAR NOVO", "CADASTRAR", "NOVO"):
                ok = self.cadastrar_novo_modelo(
                    dados.get("tipo_documento", ""),
                    dados.get("descricao", ""),
                    dados.get("classificacao", ""),
                    dados.get("publico", "N"),
                    dados.get("conteudo", ""))  # coluna J → editor após Alt+S
                return (ok, "OK" if ok else "Falha ao cadastrar modelo")
            if acao in ("EDITAR", "ALTERAR"):
                ok = self.editar_conteudo_modelo(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""),
                    conteudo=dados.get("conteudo_edicao", ""))  # coluna K
                return (ok, "OK" if ok else "Falha ao editar modelo")
            if acao in ("DESATIVAR", "REMOVER"):
                ok = self.desativar_modelo(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""))
                return (ok, "OK" if ok else "Falha ao desativar modelo")
            if acao in ("PUBLICAR",):
                ok = self.publicar_modelo(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""))
                return (ok, "OK" if ok else "Falha ao publicar")
            if acao in ("RETIRAR PUBLICACAO", "RETIRAR PUBLICAÇÃO", "DESPUBLICAR"):
                ok = self.retirar_publicacao_modelo(
                    descricao=dados.get("descricao", ""),
                    codigo=dados.get("codigo", ""))
                return (ok, "OK" if ok else "Falha ao retirar publicação")
            if acao in ("LISTAR", "ABRIR LISTA"):
                self.abrir_lista_modelos_padrao()
                return (True, "Lista aberta")
            return (False, f"Tipo de Ação desconhecido: '{acao}'")
        except Exception as e:
            return (False, f"Exceção em '{acao}': {str(e)[:200]}")

    # ══════════════════════════════════════════
    # FLUXO LOCALIZADORES — gerenciamento da unidade
    # URLs: localizador_orgao_listar / localizador_orgao_cadastrar
    # ══════════════════════════════════════════
    # ──────────────────────────────────────────
    # Navegação via menu textual (preserva o hash da sessão)
    # ──────────────────────────────────────────
    def _garantir_sidebar_aberto(self):
        """Tenta garantir que o menu lateral está aberto (searchbox visível)."""
        # Se já está visível, ok
        try:
            sb = self.driver.find_element(By.ID, "sidebar-searchbox")
            if sb.is_displayed():
                return
        except NoSuchElementException:
            pass
        # Tenta clicar no botão de menu (hambúrguer / icone que toggle o menuList)
        for seletor in [
            (By.ID, "btn-menu-toggler"),
            (By.CSS_SELECTOR, "button.menu-toggler, button[onclick*='toggleMenu']"),
            (By.CSS_SELECTOR, "i.material-icons:not([class*='close'])"),
        ]:
            try:
                btns = self.driver.find_elements(*seletor)
                for b in btns:
                    if b.is_displayed():
                        try:
                            txt = (b.get_attribute("textContent") or b.text or "").strip().lower()
                            if "menu" in txt or "≡" in txt:
                                b.click()
                                time.sleep(0.5)
                                return
                        except Exception:
                            continue
            except NoSuchElementException:
                continue
        # Último recurso: Alt+M
        try:
            self._atalho("alt", "m", "Abrir menu textual")
            time.sleep(0.8)
        except Exception:
            pass

    def _achar_searchbox_visivel(self):
        """Procura sidebar-searchbox visível, com várias tentativas."""
        for tentativa in range(3):
            for sid in ["sidebar-searchbox", "txtBuscaMenu", "txtBusca"]:
                try:
                    elementos = self.driver.find_elements(By.ID, sid)
                    for el in elementos:
                        try:
                            if el.is_displayed() and el.is_enabled():
                                return el
                        except Exception:
                            continue
                except NoSuchElementException:
                    continue
            # Não achou visível — abre sidebar e tenta de novo
            if tentativa < 2:
                self._garantir_sidebar_aberto()
                time.sleep(0.6)
        return None

    def _digitar_no_searchbox(self, campo, texto: str):
        """Digita no searchbox lidando com casos onde o input não recebe foco direto."""
        # Tenta foco via JS primeiro (driblar element_not_interactable)
        try:
            self.driver.execute_script("arguments[0].focus();", campo)
            time.sleep(0.2)
        except Exception:
            pass
        try:
            campo.click()
            time.sleep(0.2)
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", campo)
            time.sleep(0.2)
        except Exception:
            pass
        # Limpa
        try:
            campo.clear()
        except Exception:
            try:
                self.driver.execute_script("arguments[0].value = '';", campo)
            except Exception:
                pass
        # Digita caractere por caractere; se send_keys falhar, usa JS para setar value
        try:
            for ch in texto:
                campo.send_keys(ch)
                time.sleep(0.04)
        except Exception:
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('keyup', {bubbles:true}));",
                campo, texto)

    def _navegar_via_menu_textual(self, termo_busca: str,
                                   texto_link_alvo: str = None,
                                   timeout_sugestoes: float = 2.0) -> bool:
        """
        Usa o campo de busca do menu (sidebar-searchbox) para chegar a uma tela.
        IMPORTANTE: o eproc assina cada link com um hash da sessão. Ir por driver.get
        em URLs sem hash desloga o usuário. Esta função sempre clica em links
        renderizados pelo próprio eproc, preservando o hash.
        """
        if not texto_link_alvo:
            texto_link_alvo = termo_busca

        # 1) Garantir que o sidebar está aberto antes de procurar o searchbox
        self._garantir_sidebar_aberto()
        # 2) Localiza o searchbox
        campo = self._achar_searchbox_visivel()
        if not campo:
            self.log("Campo sidebar-searchbox não encontrado.", nivel="ERROR")
            return False

        self.log(f"Buscando no menu textual: '{termo_busca}'")
        try:
            self._digitar_no_searchbox(campo, termo_busca)
            time.sleep(timeout_sugestoes)
        except Exception as e:
            self.log(f"Falha ao digitar no searchbox: {str(e)[:200]}", nivel="WARN")
            return False

        # 2) Encontra o link de destino — varre <a> visíveis que contenham o texto-alvo
        alvo_norm = self._normalizar(texto_link_alvo)
        links = self.driver.find_elements(By.CSS_SELECTOR, "a")
        candidatos = []
        for link in links:
            try:
                if not link.is_displayed():
                    continue
                txt = (link.text or "").strip()
                if not txt:
                    continue
                if alvo_norm in self._normalizar(txt):
                    href = link.get_attribute("href") or ""
                    score = 1000 if self._normalizar(txt) == alvo_norm else 100
                    score += len(href) // 10  # links internos do eproc são longos (têm hash)
                    candidatos.append((score, txt, link))
            except Exception:
                continue

        if not candidatos:
            self.log(f"Nenhum link com '{texto_link_alvo}' no menu.", nivel="WARN")
            return False

        candidatos.sort(reverse=True, key=lambda x: x[0])
        score, txt, link = candidatos[0]
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            time.sleep(0.2)
            try:
                link.click()
            except ElementClickInterceptedException:
                self.driver.execute_script("arguments[0].click();", link)
            time.sleep(2)
            self.log(f"  → Navegado para: {txt[:80]}")
            if not self.verificar_sessao_ativa():
                self.log("Sessão expirou após navegação pelo menu.", nivel="ERROR")
                return False
            return True
        except Exception as e:
            self.log(f"Falha ao clicar no link '{txt}': {e}", nivel="ERROR")
            return False

    def abrir_lista_localizadores_orgao(self):
        """
        Abre a tela 'Localizadores do Órgão' SEM perder a sessão — via menu textual.
        Master URL: acao=localizador_orgao_listar
        """
        if not self.driver:
            raise RuntimeError("Navegador não aberto.")
        if not self.verificar_sessao_ativa():
            raise RuntimeError("Sessão inativa. Faça login novamente.")
        ok = self._navegar_via_menu_textual("Localizadores do Órgão",
                                             "Localizadores do Órgão")
        if not ok:
            raise RuntimeError(
                "Não foi possível chegar em 'Localizadores do Órgão'. "
                "Verifique se o seu perfil tem permissão (Gerente, em geral).")
        # Confirma que carregou
        try:
            self._aguardar_elemento(By.ID, "frmLocalizadorOrgaoLista", timeout=10)
            self.log("✓ Lista de Localizadores aberta.")
        except TimeoutException:
            self.log("frmLocalizadorOrgaoLista não apareceu — verifique no navegador.",
                     nivel="WARN")

    def abrir_cadastro_novo_localizador(self):
        """
        Abre o cadastro de novo localizador A PARTIR da lista (clicando no btnNovo
        renderizado pelo eproc, que já vem com o hash da sessão).
        """
        # Garante estar na lista
        try:
            self.driver.find_element(By.ID, "btnNovo")
        except NoSuchElementException:
            self.abrir_lista_localizadores_orgao()
        # Clica em "Novo"
        try:
            btn = self._aguardar_clicavel(By.ID, "btnNovo", timeout=8)
            btn.click()
            time.sleep(1.5)
            self._aguardar_elemento(By.ID, "txtNomeLocalizador", timeout=10)
            self.log("✓ Cadastro de Localizador aberto.")
        except (TimeoutException, NoSuchElementException) as e:
            raise RuntimeError(
                f"Botão 'Novo' não encontrado na lista de localizadores. {str(e)[:120]}")

    def cadastrar_novo_localizador(self, nome: str, sigla: str,
                                   fixo: str = "N", descricao: str = "") -> bool:
        """
        Preenche e salva o formulário de cadastro de localizador do órgão.
        Master: txtNomeLocalizador, txtSigLocalizador, selSinLocalizadorFixo, txtDesLocalizador
        Submit: button[name=sbmCadastrarLocalizadorOrgao] (accesskey=S → Alt+S).
        """
        if not nome:
            self.log("Nome do localizador vazio.", nivel="ERROR")
            return False
        if not sigla:
            self.log("Sigla do localizador vazia.", nivel="ERROR")
            return False
        # Garante que está na tela certa
        try:
            self.driver.find_element(By.ID, "txtNomeLocalizador")
        except NoSuchElementException:
            self.abrir_cadastro_novo_localizador()
        # Preencher campos
        try:
            campo_nome = self._aguardar_elemento(By.ID, "txtNomeLocalizador")
            campo_nome.clear()
            campo_nome.send_keys(nome)
            self.log(f"Nome: {nome}")

            campo_sig = self.driver.find_element(By.ID, "txtSigLocalizador")
            campo_sig.clear()
            campo_sig.send_keys(sigla)
            self.log(f"Sigla: {sigla}")

            valor_fixo = "S" if str(fixo).strip().upper() in ("S", "SIM", "TRUE", "1") else "N"
            try:
                Select(self.driver.find_element(By.ID, "selSinLocalizadorFixo")).select_by_value(valor_fixo)
            except Exception:
                # tenta por texto
                texto_alvo = "Sim" if valor_fixo == "S" else "Não"
                self._selecionar_dropdown("selSinLocalizadorFixo", texto_alvo, "Localizador Fixo")
            self.log(f"Fixo: {valor_fixo}")

            if descricao:
                campo_desc = self.driver.find_element(By.ID, "txtDesLocalizador")
                campo_desc.clear()
                campo_desc.send_keys(descricao)
                self.log(f"Descrição: {descricao[:60]}...")
        except Exception as e:
            self.log(f"Falha ao preencher cadastro: {e}", nivel="ERROR")
            return False

        # Submeter (Alt+S ou click)
        try:
            self._atalho("alt", "s", "Salvar Localizador")
            time.sleep(2)
            self._tratar_alert(aceitar=True)
        except Exception:
            try:
                btn = self.driver.find_element(By.NAME, "sbmCadastrarLocalizadorOrgao")
                btn.click()
                time.sleep(2)
                self._tratar_alert(aceitar=True)
            except Exception as e:
                self.log(f"Não foi possível submeter: {e}", nivel="ERROR")
                return False
        # Verifica se voltou para a lista (sucesso)
        time.sleep(1.5)
        url = self.driver.current_url
        if "localizador_orgao_listar" in url or "acao_origem=localizador_orgao_cadastrar" in url:
            self.log(f"✓ Localizador '{nome}' ({sigla}) cadastrado.")
            return True
        # Verifica mensagem de erro
        try:
            msg = self.driver.find_element(By.CSS_SELECTOR, ".infraMensagem, .alert-danger").text
            if msg:
                self.log(f"Servidor retornou: {msg[:200]}", nivel="ERROR")
                return False
        except NoSuchElementException:
            pass
        self.log(f"Cadastro retornou status incerto (URL: {url[:120]}).", nivel="WARN")
        return False

    def desativar_localizador_por_sigla(self, sigla: str) -> bool:
        """
        Desativa um localizador filtrando por sigla na lista do órgão.
        Master: txtSiglaDescricaoLocalizador + btnFiltro + chkInfraItemN + btnDesativar.
        """
        if not sigla:
            return False
        self.abrir_lista_localizadores_orgao()
        try:
            campo = self._aguardar_elemento(By.ID, "txtSiglaDescricaoLocalizador")
            campo.clear()
            campo.send_keys(sigla)
            time.sleep(0.5)
            btn_filtrar = self.driver.find_element(By.ID, "btnFiltro")
            btn_filtrar.click()
            time.sleep(1.5)
        except NoSuchElementException as e:
            self.log(f"Filtro indisponível: {e}", nivel="WARN")
            return False
        # Marca todos os checkboxes que aparecem (deve ser 1 só se a sigla é única)
        checkboxes = self.driver.find_elements(By.CSS_SELECTOR, "input[id^='chkInfraItem'][type='checkbox']")
        if not checkboxes:
            self.log(f"Nenhum localizador com sigla '{sigla}' encontrado.", nivel="WARN")
            return False
        for chk in checkboxes:
            try:
                if not chk.is_selected():
                    chk.click()
            except Exception:
                continue
        self.log(f"{len(checkboxes)} item(ns) marcado(s).")
        try:
            btn_des = self._aguardar_clicavel(By.ID, "btnDesativar", timeout=5)
            btn_des.click()
            time.sleep(1)
            self._tratar_alert(aceitar=True)
            time.sleep(2)
            self.log(f"✓ Desativação de '{sigla}' enviada.")
            return True
        except (TimeoutException, NoSuchElementException) as e:
            self.log(f"Botão Desativar indisponível: {e}", nivel="ERROR")
            return False

    def adicionar_localizador_no_processo(self, num_processo: str, nome_localizador: str) -> bool:
        """
        Adiciona um localizador no processo via capa (interface inline com tags).
        Fluxo real (validado em screenshots da homologação 2026-05-10):
          1. Pesquisar processo
          2. Clicar no ícone amarelo (lápis) com title 'Abrir edição de localizadores'
          3. O modo de edição mostra tags com X + um input + botões Salvar/Cancelar
          4. Digitar a sigla/nome no input → dropdown de sugestões aparece
          5. Clicar na sugestão (linha em destaque)
          6. Clicar 'Salvar'
        """
        if not num_processo or not nome_localizador:
            self.log("Processo ou nome do localizador vazios.", nivel="ERROR")
            return False
        self.pesquisar_processo(num_processo)
        time.sleep(1)

        # Passo 1: abrir o modo de edição clicando no ícone "Abrir edição de localizadores"
        if not self._abrir_edicao_localizadores_capa():
            self.log("Não foi possível abrir o modo de edição de localizadores.",
                     nivel="ERROR")
            return False

        # Passo 2: localizar o input visível e digitar
        input_loc = self._achar_input_localizador_capa()
        if not input_loc:
            self.log("Input de adicionar localizador não encontrado após abrir edição.",
                     nivel="ERROR")
            return False

        self.log(f"Digitando '{nome_localizador}' no input da capa...")
        # Limpa qualquer texto residual (ex: 'k' que vazou de Alt+K)
        self._limpar_input_completamente(input_loc)
        valor_residual = input_loc.get_attribute("value") or ""
        if valor_residual:
            self.log(f"  AVISO: input ainda tem '{valor_residual}' após limpeza.", nivel="WARN")
        for ch in nome_localizador:
            input_loc.send_keys(ch)
            time.sleep(0.05)
        time.sleep(1.5)

        # Passo 3: clicar na sugestão do autocomplete
        if not self._clicar_sugestao_localizador(nome_localizador, input_loc):
            self.log(f"Sugestão '{nome_localizador}' não apareceu no autocomplete.",
                     nivel="ERROR")
            return False
        time.sleep(0.5)

        # Passo 4: salvar
        return self._salvar_localizadores_capa(nome_localizador)

    def _abrir_edicao_localizadores_capa(self) -> bool:
        """
        Clica no ícone/link que abre a edição de localizadores na capa.
        IMPORTANTE: NÃO usa Alt+K como primeira opção, porque o atalho com modificador
        pode "vazar" a tecla 'k' no input que ganha foco logo em seguida.
        Estratégia: clicar primeiro no ícone com title 'Abrir edição de localizadores'.
        """
        if self._modo_edicao_localizadores_aberto():
            return True
        # 1) Clique no ícone (caminho preferido — não polui o input)
        for seletor in [
            (By.CSS_SELECTOR, "a[title*='dição de localizadores' i]"),
            (By.CSS_SELECTOR, "a[title*='ditar localizad' i]"),
            (By.CSS_SELECTOR, "img[title*='dição de localizadores' i]"),
            (By.CSS_SELECTOR, "#dvLocalizadoresOrgao a img"),
            (By.ID, "AbreLocalizadores"),
        ]:
            try:
                elem = self.driver.find_element(*seletor)
                if elem.is_displayed():
                    try:
                        elem.click()
                    except ElementClickInterceptedException:
                        self.driver.execute_script("arguments[0].click();", elem)
                    time.sleep(1)
                    if self._modo_edicao_localizadores_aberto():
                        self.log("  Modo de edição aberto via clique no ícone.")
                        return True
            except NoSuchElementException:
                continue
        # 2) Clique no próprio nome do localizador (na capa, isso também abre)
        try:
            for link in self.driver.find_elements(
                By.CSS_SELECTOR, "#dvLocalizadoresOrgao a:not([id='AbreLocalizadores'])"):
                if link.is_displayed():
                    link.click()
                    time.sleep(1)
                    if self._modo_edicao_localizadores_aberto():
                        self.log("  Modo de edição aberto (clique no nome do localizador).")
                        return True
        except NoSuchElementException:
            pass
        # 3) ÚLTIMO recurso: Alt+K (perigoso — pode vazar 'k' no input)
        try:
            self._atalho("alt", "k", "Abrir edição localizadores (último recurso)")
            time.sleep(1)
            if self._modo_edicao_localizadores_aberto():
                self.log("  Modo de edição aberto (Alt+K). Atenção: pode ter digitado 'k' no input.")
                return True
        except Exception:
            pass
        return False

    def _modo_edicao_localizadores_aberto(self) -> bool:
        """
        Verifica se o modo de edição inline está visível.
        Sinais (qualquer um basta):
         - Botão 'Salvar' VISÍVEL em qualquer lugar
         - Tag com X (botão 'remover') visível dentro de container de localizadores
         - Input de texto visível dentro de container que mencione 'localizador'
        """
        # 1) Botão Salvar visível
        try:
            for btn in self.driver.find_elements(By.XPATH,
                "//button[normalize-space(.)='Salvar' and not(@disabled)]"
                " | //input[@type='button' and @value='Salvar' and not(@disabled)]"
                " | //input[@type='submit' and @value='Salvar' and not(@disabled)]"):
                if btn.is_displayed():
                    return True
        except Exception:
            pass
        # 2) Tag com X (sinal de modo de edição: cápsulas com botão remover)
        try:
            for x in self.driver.find_elements(
                By.CSS_SELECTOR,
                ".tag-delete, [class*='tag-delete'], button.tag-close, span.tag-x"):
                if x.is_displayed():
                    return True
        except Exception:
            pass
        # 3) Input visível em containers relacionados a localizadores
        for sel in [
            "#dvLocalizadoresOrgao input[type='text']",
            "[id*='ocalizador' i] input[type='text']",
            "fieldset[id*='ocaliz' i] input[type='text']",
            "div[class*='ocaliz' i] input[type='text']",
        ]:
            try:
                for inp in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if inp.is_displayed() and inp.is_enabled() and not inp.get_attribute("readonly"):
                        return True
            except Exception:
                continue
        return False

    def _achar_input_localizador_capa(self):
        """Encontra o input de texto visível e EDITÁVEL no painel de edição."""
        seletores = [
            "#dvLocalizadoresOrgao input[type='text']:not([readonly])",
            "[id*='ocalizador' i] input[type='text']:not([readonly])",
            "fieldset[id*='ocaliz' i] input[type='text']:not([readonly])",
            "div[class*='ocaliz' i] input[type='text']:not([readonly])",
            "#fldCapa input[type='text'][name*='ocaliz' i]",
            "input[placeholder*='ocaliz' i]",
            ".select2-search__field",
        ]
        for sel in seletores:
            try:
                for inp in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if inp.is_displayed() and inp.is_enabled():
                        return inp
            except Exception:
                continue
        return None

    def _limpar_input_completamente(self, input_elem):
        """Limpa input mesmo que tenha texto residual (de Alt+K vazado, p.ex.)."""
        try:
            input_elem.click()
            time.sleep(0.2)
        except Exception:
            pass
        try:
            input_elem.send_keys(Keys.CONTROL, "a")
            time.sleep(0.1)
            input_elem.send_keys(Keys.DELETE)
            time.sleep(0.1)
        except Exception:
            pass
        try:
            input_elem.clear()
        except Exception:
            pass
        # Confirma
        try:
            valor = input_elem.get_attribute("value") or ""
            if valor:
                # último recurso: backspace por caractere
                for _ in range(len(valor) + 2):
                    input_elem.send_keys(Keys.BACKSPACE)
                    time.sleep(0.02)
        except Exception:
            pass

    def _clicar_sugestao_localizador(self, alvo: str, input_elem) -> bool:
        """Clica na sugestão do dropdown que casa com 'alvo'."""
        alvo_norm = self._normalizar(alvo)
        # Tenta várias possibilidades de containers de sugestão
        seletores = [
            ".ui-autocomplete .ui-menu-item",
            ".select2-results__option",
            "li[role='option']",
            "div[id^='divInfraAjax'] li",
            ".dropdown-menu li:not(.hidden) a",
            ".dropdown-menu .dropdown-item",
            "table[id^='tabela'] tr:hover",
            # Fallback: qualquer elemento clicável visível com o texto
        ]
        for sel in seletores:
            try:
                items = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for item in items:
                    try:
                        if not item.is_displayed():
                            continue
                        txt = (item.text or "").strip()
                        if not txt:
                            continue
                        if alvo_norm in self._normalizar(txt):
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block:'center'});", item)
                            time.sleep(0.2)
                            try:
                                item.click()
                            except ElementClickInterceptedException:
                                self.driver.execute_script("arguments[0].click();", item)
                            self.log(f"  Sugestão clicada: {txt[:80]}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        # Último recurso: ARROW_DOWN + ENTER
        try:
            input_elem.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.3)
            input_elem.send_keys(Keys.RETURN)
            time.sleep(0.5)
            self.log(f"  Selecionado via ARROW_DOWN+ENTER (verifique no navegador).")
            return True
        except Exception as e:
            self.log(f"  Falha no ARROW_DOWN+ENTER: {e}", nivel="WARN")
        return False

    def _capa_localizadores_aberto(self) -> bool:
        """Verifica se o painel de edição de localizadores da capa está visível."""
        try:
            sel = self.driver.find_element(By.ID, "selLocalizadoresProcesso")
            return True  # se o select existe, o painel está montado
        except NoSuchElementException:
            pass
        try:
            btn = self.driver.find_element(By.ID, "salvar")
            return btn.is_displayed()
        except NoSuchElementException:
            return False

    def _adicionar_localizador_via_js(self, nome_localizador: str) -> bool:
        """
        Adiciona uma option ao <select#selLocalizadoresProcesso> via JS,
        depois aciona change + selectpicker('refresh'). Funciona com Bootstrap-Select.
        """
        js = """
        var alvoNorm = arguments[0].toLowerCase().trim();
        var seletores = ['selLocalizadoresProcesso', 'selLocalizadores'];
        var sel = null;
        for (var i=0; i<seletores.length; i++) {
            var e = document.getElementById(seletores[i]);
            if (e && e.tagName === 'SELECT') { sel = e; break; }
        }
        if (!sel) {
            // tenta CSS broader
            sel = document.querySelector('select[name*="LocalizadoresProcesso"]');
        }
        if (!sel) return {ok:false, motivo:'select_nao_encontrado'};
        var matches = [];
        var totalOpts = sel.options.length;
        for (var i=0; i<sel.options.length; i++) {
            var txt = (sel.options[i].text || '').toLowerCase().trim();
            if (txt && txt.indexOf(alvoNorm) !== -1) {
                if (!sel.options[i].selected) {
                    sel.options[i].selected = true;
                }
                matches.push(sel.options[i].text);
            }
        }
        if (window.jQuery) {
            try { jQuery(sel).trigger('change'); } catch(e){}
            try { jQuery(sel).selectpicker('refresh'); } catch(e){}
        }
        return {ok: matches.length > 0, matches: matches, total: totalOpts};
        """
        try:
            res = self.driver.execute_script(js, nome_localizador) or {}
        except Exception as e:
            self.log(f"  JS lançou exceção: {str(e)[:120]}", nivel="WARN")
            return False
        if res.get("ok"):
            self.log(f"  Localizador marcado via JS: {res.get('matches')} (total opções: {res.get('total')})")
            time.sleep(0.5)
            return True
        self.log(f"  JS não achou option para '{nome_localizador}': {res}", nivel="WARN")
        return False

    def _adicionar_localizador_via_click(self, nome_localizador: str) -> bool:
        """Fallback: abre o dropdown bootstrap-select e clica na opção."""
        # Botão visual do bootstrap-select (geralmente <button class='dropdown-toggle'>)
        try:
            wrapper = self.driver.find_element(
                By.CSS_SELECTOR,
                "div.bootstrap-select > button.dropdown-toggle, "
                "[data-id='selLocalizadoresProcesso'], "
                "button[data-id='selLocalizadoresProcesso']")
            wrapper.click()
            time.sleep(0.5)
        except NoSuchElementException:
            self.log("  Botão bootstrap-select não encontrado.", nivel="WARN")
            return False
        # Campo de busca interno do bootstrap-select
        try:
            search = self.driver.find_element(
                By.CSS_SELECTOR,
                "div.bootstrap-select.show .bs-searchbox input, "
                ".bs-searchbox input")
            search.clear()
            search.send_keys(nome_localizador)
            time.sleep(1)
        except NoSuchElementException:
            pass
        # Clica na primeira opção visível que casa
        try:
            options = self.driver.find_elements(
                By.CSS_SELECTOR,
                "div.bootstrap-select .dropdown-menu li:not(.hidden) a, "
                "div.bootstrap-select.show li a")
            alvo_norm = self._normalizar(nome_localizador)
            for opt in options:
                try:
                    if not opt.is_displayed():
                        continue
                    txt = (opt.text or "").strip()
                    if alvo_norm in self._normalizar(txt):
                        opt.click()
                        self.log(f"  Clicado no dropdown: {txt[:80]}")
                        time.sleep(0.5)
                        return True
                except Exception:
                    continue
        except Exception as e:
            self.log(f"  Falha ao listar opções: {e}", nivel="WARN")
        return False

    def _salvar_localizadores_capa(self, nome_localizador: str) -> bool:
        """Clica no botão 'salvar' do painel de edição da capa."""
        for seletor in [
            (By.ID, "salvar"),
            (By.XPATH, "//button[@id='salvar']"),
            (By.XPATH, "//button[normalize-space(.)='Salvar' and not(@disabled)]"),
            (By.CSS_SELECTOR, "#dvLocalizadoresOrgao button[type='submit']"),
        ]:
            try:
                btn = self._aguardar_clicavel(*seletor, timeout=3)
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.2)
                try:
                    btn.click()
                except ElementClickInterceptedException:
                    self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.5)
                self._tratar_alert(aceitar=True)
                self.log(f"✓ Localizador '{nome_localizador}' adicionado e salvo na capa.")
                return True
            except (TimeoutException, NoSuchElementException):
                continue
        # Último recurso: Alt+Enter (atalho mencionado no manual)
        try:
            actions = ActionChains(self.driver)
            actions.key_down(Keys.ALT).send_keys(Keys.RETURN).key_up(Keys.ALT).perform()
            time.sleep(1.5)
            self._tratar_alert(aceitar=True)
            self.log(f"✓ Localizador '{nome_localizador}' salvo (Alt+Enter).")
            return True
        except Exception:
            pass
        self.log("Botão 'salvar' do painel de localizadores da capa não encontrado.", nivel="ERROR")
        return False

    def executar_localizador(self, dados: dict) -> tuple:
        """Despachador conforme 'Tipo de Ação'."""
        acao = (dados.get("tipo_acao") or "").strip().upper()
        try:
            if acao in ("CRIAR", "CRIAR NOVO", "CADASTRAR", "NOVO"):
                ok = self.cadastrar_novo_localizador(
                    dados.get("nome", ""), dados.get("sigla", ""),
                    dados.get("fixo", "N"), dados.get("descricao", ""))
                return (ok, "OK" if ok else "Falha ao cadastrar localizador")
            if acao in ("ADICIONAR NO PROCESSO", "ADICIONAR PROCESSO", "ADICIONAR"):
                # Para adicionar na capa, o autocomplete usa a SIGLA (preferencial).
                # Cai no nome longo só se sigla estiver vazia.
                termo = dados.get("sigla", "") or dados.get("nome", "")
                ok = self.adicionar_localizador_no_processo(
                    dados.get("num_processo", ""), termo)
                return (ok, "OK" if ok else "Falha ao adicionar no processo")
            if acao in ("DESATIVAR", "REMOVER"):
                ok = self.desativar_localizador_por_sigla(dados.get("sigla", ""))
                return (ok, "OK" if ok else "Falha ao desativar")
            if acao in ("LISTAR", "ABRIR LISTA"):
                self.abrir_lista_localizadores_orgao()
                return (True, "Lista aberta")
            return (False, f"Tipo de Ação desconhecido: '{acao}' (use CRIAR / ADICIONAR NO PROCESSO / DESATIVAR / LISTAR)")
        except Exception as e:
            return (False, f"Exceção em '{acao}': {str(e)[:200]}")

    # ══════════════════════════════════════════
    # FLUXO MOVIMENTAR — PASSOS
    # URL: processo_movimento_consultar
    # ══════════════════════════════════════════
    def clicar_movimentar(self):
        """
        Abre Movimentar a partir da capa.
        Master: btn-movimentar com accesskey="o" → URL processo_movimento_consultar.
        """
        janelas_antes = len(self.driver.window_handles)
        try:
            self._atalho("alt", "o", "Movimentar processo")
            time.sleep(2)
            if len(self.driver.window_handles) > janelas_antes:
                self._trocar_para_nova_aba()
                self.log("Movimentar aberto em nova aba (Alt+O).")
                self._aguardar_url_conter("processo_movimento_consultar", timeout=10)
                return
            try:
                self._aguardar_url_conter("processo_movimento_consultar", timeout=3)
                self.log("Movimentar aberto na mesma aba (Alt+O).")
                return
            except TimeoutException:
                pass
        except Exception as e:
            self.log(f"Alt+O não disparou: {e}", nivel="WARN")

        self.log("Tentando fallback: clicar #btn-movimentar...")
        try:
            btn = self._aguardar_clicavel(By.ID, "btn-movimentar", timeout=5)
            btn.click()
        except (TimeoutException, NoSuchElementException):
            self._tratar_alert()
            raise NoSuchElementException("Botão 'Movimentar' não encontrado na capa.")
        time.sleep(2)
        if len(self.driver.window_handles) > janelas_antes:
            self._trocar_para_nova_aba()
        self._aguardar_url_conter("processo_movimento_consultar", timeout=10)
        self.log("Movimentar aberto.")

    def preencher_evento_movimentar(self, evento: str):
        """txtEvento + hdnEvento — autocomplete (reusa lógica inteligente)."""
        if not evento:
            return ""
        return self._preencher_autocomplete("txtEvento", evento, "Evento Movimentar")

    def fazer_upload_pdf(self, caminho_arquivo: str):
        """
        Upload de PDF. Master: input[type=file] dinâmico (fleArquivo_N), e o eproc
        em cima de cada arquivo cria um par txtTipo_N + selIdSigilo_N.
        """
        if not caminho_arquivo:
            return
        if not os.path.exists(caminho_arquivo):
            raise FileNotFoundError(f"Arquivo PDF não encontrado: {caminho_arquivo}")
        try:
            input_file = self.driver.find_element(
                By.CSS_SELECTOR, "input[type='file'][name^='fleArquivo'], input[type='file'][name='file']")
        except NoSuchElementException:
            # último recurso: qualquer input file na página
            inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if not inputs:
                raise NoSuchElementException("Nenhum input[type=file] encontrado.")
            input_file = inputs[0]
        input_file.send_keys(caminho_arquivo)
        time.sleep(2.5)
        self.log(f"Arquivo enviado: {os.path.basename(caminho_arquivo)}")

    def preencher_tipo_documento(self, tipo: str):
        """
        Após upload, preenche txtTipo_1 (autocomplete) — primeiro documento.
        Se tipo for vazio, tenta usar txtTipo_Padrao (aplica a todos).
        """
        if not tipo:
            return
        for campo_id in ["txtTipo_1", "txtTipo_Padrao", "txtTipo_2", "txtTipo_3"]:
            try:
                self.driver.find_element(By.ID, campo_id)
                return self._preencher_autocomplete(campo_id, tipo, f"Tipo Documento ({campo_id})")
            except NoSuchElementException:
                continue
        self.log("Nenhum campo de Tipo Documento encontrado (txtTipo_1/Padrao).", nivel="WARN")

    def selecionar_sigilo_documento(self, sigilo: str):
        """Master: selIdSigilo_1 (por documento) ou selIdSigilo_Padrao."""
        if not sigilo:
            return
        for sel_id in ["selIdSigilo_1", "selIdSigilo_Padrao", "selIdSigilo_2"]:
            try:
                self.driver.find_element(By.ID, sel_id)
                self._selecionar_dropdown(sel_id, sigilo, "Sigilo Documento")
                return
            except NoSuchElementException:
                continue
        # Fallback v3: selSigilo
        try:
            self._selecionar_dropdown("selSigilo", sigilo, "Sigilo Documento")
        except Exception:
            self.log("Nenhum select de Sigilo do documento encontrado.", nivel="WARN")

    def confirmar_documentos(self):
        """Clica btnEnviarArquivos para anexar os arquivos selecionados (acaoAnexar JS)."""
        try:
            btn = self._aguardar_clicavel(By.ID, "btnEnviarArquivos", timeout=5)
            btn.click()
            time.sleep(2.5)
            self._tratar_alert()
            self.log("Documentos confirmados (#btnEnviarArquivos).")
            return
        except (TimeoutException, NoSuchElementException):
            pass
        # Fallback: botão pelo texto
        for seletor in [
            (By.XPATH, "//button[contains(text(),'Confirmar') and contains(text(),'documento')]"),
            (By.XPATH, "//button[contains(@onclick,'acaoAnexar')]"),
        ]:
            try:
                btn = self._aguardar_clicavel(*seletor, timeout=3)
                btn.click()
                time.sleep(2.5)
                self.log("Documentos confirmados (fallback).")
                return
            except Exception:
                continue
        self.log("Nenhum botão de Confirmar Documentos encontrado.", nivel="WARN")

    def marcar_intimar_partes_inline(self, valor: str):
        """
        Após escolher o evento, alguns eventos exibem o painel "Intimar/Citar Partes".
        Master: o checkbox principal varia (chkIntimarPartes / chkIntimar...).
        """
        if not valor:
            return
        quer = str(valor).strip().upper() in ("S", "SIM", "TRUE", "1")
        for chk_id in ["chkIntimarPartes", "chkCitarIntimar", "chkIntimar"]:
            try:
                chk = self.driver.find_element(By.ID, chk_id)
                if chk.is_selected() != quer:
                    chk.click()
                    self.log(f"Intimar partes inline ({chk_id}): {'marcado' if quer else 'desmarcado'}")
                return
            except NoSuchElementException:
                continue
        self.log("Painel Intimar partes não disponível (depende do evento).", nivel="WARN")

    def selecionar_orgao_destino_remessa(self, nome_orgao: str):
        """selOrgao (Select2 quando habilitado pelo evento de remessa)."""
        if not nome_orgao:
            return
        # Tenta select2 primeiro
        try:
            self._selecionar_select2("selOrgao", nome_orgao, "Órgão Destino")
            return
        except Exception:
            pass
        try:
            self._selecionar_dropdown("selOrgao", nome_orgao, "Órgão Destino")
        except Exception as e:
            self.log(f"Falha ao escolher órgão destino: {str(e)[:120]}", nivel="WARN")

    def _selecionar_select2(self, hidden_id: str, texto: str, descricao: str = ""):
        """Helper p/ Select2 wrapper (s2id_*) usado pelo eproc em alguns selects."""
        label = descricao or hidden_id
        try:
            self.driver.execute_script(f"$('#{hidden_id}').select2('open');")
            time.sleep(0.5)
            search = self.driver.find_element(By.CSS_SELECTOR, ".select2-search__field, .select2-input")
            search.send_keys(texto)
            time.sleep(0.8)
            search.send_keys(Keys.RETURN)
            time.sleep(0.5)
            self.log(f"{label} selecionado via Select2: {texto}")
        except Exception as e:
            raise RuntimeError(f"Select2 falhou em {label}: {e}")

    def submeter_movimentacao(self):
        """sbmMovimentar (accesskey 'o')."""
        try:
            self._atalho("alt", "o", "Submeter Movimentação")
            time.sleep(2)
            self._tratar_alert()
            self.log("Movimentação submetida (Alt+O).")
            return
        except Exception:
            pass
        try:
            btn = self._aguardar_clicavel(By.ID, "sbmMovimentar", timeout=5)
            btn.click()
            time.sleep(2)
            self._tratar_alert()
            self.log("Movimentação submetida (#sbmMovimentar).")
        except (TimeoutException, NoSuchElementException):
            try:
                btn = self.driver.find_element(By.NAME, "sbmMovimentar")
                btn.click()
                time.sleep(2)
                self._tratar_alert()
            except Exception:
                self.log("Botão 'Movimentar' final não encontrado.", nivel="ERROR")
                raise

    def lidar_lembrete_popup(self):
        """
        Master: se existem lembretes não tratados, eproc impede submit até confirmar.
        Aceita o pop-up clicando OK (controleLembrete=t).
        """
        # O eproc usa um div modal; ou simplesmente um alert. Tenta aceitar alert.
        self._tratar_alert(aceitar=True)
        # Alternativa: setar controleLembrete=t via JS para liberar o submit
        try:
            self.driver.execute_script(
                "var el = document.getElementById('controleLembrete');"
                "if (el) el.value = 't';")
        except Exception:
            pass

    def executar_movimentar(self, dados: dict) -> tuple:
        """Fluxo completo Movimentar."""
        agendar_localizador = str(dados.get("comportamento_localizador", "")).strip() != ""
        marcar_todos = str(dados.get("marcar_todos_atuais", "S")).strip().upper() in ("S", "SIM", "TRUE", "1")
        passos = [
            ("Pesquisar processo", lambda: self.pesquisar_processo(dados["num_processo"])),
            ("Abrir Movimentar (Alt+O)", lambda: self.clicar_movimentar()),
            ("Lidar com lembretes", lambda: self.lidar_lembrete_popup()),
            ("Preencher Evento", lambda: self.preencher_evento_movimentar(dados.get("evento", ""))),
        ]
        if dados.get("caminho_arquivo"):
            passos += [
                ("Upload PDF", lambda: self.fazer_upload_pdf(dados.get("caminho_arquivo", ""))),
                ("Tipo Documento", lambda: self.preencher_tipo_documento(dados.get("tipo_documento", ""))),
                ("Sigilo Documento", lambda: self.selecionar_sigilo_documento(dados.get("sigilo_documento", ""))),
                ("Confirmar Documentos", lambda: self.confirmar_documentos()),
            ]
        if agendar_localizador:
            passos += [
                ("Comportamento Localizador", lambda: self.selecionar_comportamento_localizador(dados.get("comportamento_localizador", ""))),
            ]
            if marcar_todos:
                passos.append(("Marcar TODOS localizadores atuais", lambda: self.marcar_todos_localizadores_atuais()))
            passos += [
                ("Novo Localizador", lambda: self.selecionar_novo_localizador(dados.get("novo_localizador", ""))),
                ("Localizadores Secundários", lambda: self.selecionar_localizadores_secundarios(_lista_de(dados.get("localizadores_secundarios", "")))),
            ]
        if dados.get("intimar_inline"):
            passos.append(("Intimar partes inline", lambda: self.marcar_intimar_partes_inline(dados.get("intimar_inline", ""))))
        if dados.get("remeter_para"):
            passos.append(("Órgão Destino (remessa)", lambda: self.selecionar_orgao_destino_remessa(dados.get("remeter_para", ""))))
        passos.append(("Submeter Movimentação", lambda: self.submeter_movimentacao()))

        for nome, fn in passos:
            try:
                self.log(f"━ Passo: {nome}")
                fn()
                self._tratar_alert()
                if not self.verificar_sessao_ativa():
                    return False, f"Sessão expirou em '{nome}'"
            except FileNotFoundError as e:
                return False, f"Arquivo PDF: {e}"
            except UnexpectedAlertPresentException as e:
                texto = self._tratar_alert()
                return False, f"Alert em '{nome}': {texto or str(e)[:120]}"
            except Exception as e:
                self._tratar_alert()
                return False, f"Falha em '{nome}': {str(e)[:200]}"
        return True, "OK"

    # ──────────────────────────────────────────
    # FLUXO completo MINUTAR (chamado pelo botão "Executar Tudo")
    # ──────────────────────────────────────────
    def executar_minutar_com_agendamento(self, dados: dict) -> tuple:
        agendar = str(dados.get("agendar", "S")).upper() in ("S", "SIM", "TRUE", "1")
        passos = [
            ("Pesquisar processo",          lambda: self.pesquisar_processo(dados["num_processo"])),
            ("Abrir Nova Minuta (Ctrl+M)",  lambda: self.abrir_nova_minuta()),
            ("Tipo/Modelo",                 lambda: self.preencher_tipo_modelo(dados.get("tipo_modelo", "DESPACHO"))),
            ("Descrição",                   lambda: self.preencher_descricao(dados.get("descricao", ""))),
            ("Assinante",                   lambda: self.selecionar_assinante(dados.get("assinante", ""))),
            ("Tratamento",                  lambda: self.selecionar_tratamento(dados.get("tratamento", ""))),
            ("Sigilo",                      lambda: self.selecionar_sigilo(dados.get("sigilo", ""))),
            ("Status Minuta",               lambda: self.selecionar_status_minuta(dados.get("status_minuta", ""))),
            ("Cabeçalho",                   lambda: self.marcar_cabecalho(dados.get("cabecalho", {}))),
            ("Precedente Relevante",        lambda: self.marcar_precedente_relevante(dados.get("precedente_relevante", ""))),
        ]
        if agendar:
            marcar_todos = str(dados.get("marcar_todos_atuais", "S")).strip().upper() in ("S", "SIM", "TRUE", "1")
            passos += [
                ("Marcar Agendamento",          lambda: self.marcar_agendamento(True)),
                ("Evento (txtEvento)",          lambda: self.preencher_evento_agendamento(dados.get("evento", ""))),
                ("Remeter processo",             lambda: self.marcar_encadeamento_remessa()),
                ("Evento de Remessa",            lambda: self.selecionar_evento_remessa(dados.get("evento_remessa", ""))),
                ("Comportamento Localizador",   lambda: self.selecionar_comportamento_localizador(dados.get("comportamento_localizador", ""))),
            ]
            if marcar_todos:
                passos.append(
                    ("Marcar TODOS localizadores atuais", lambda: self.marcar_todos_localizadores_atuais())
                )
            passos += [
                ("Novo Localizador",            lambda: self.selecionar_novo_localizador(dados.get("novo_localizador", ""))),
                ("Localizadores Secundários",   lambda: self.selecionar_localizadores_secundarios(_lista_de(dados.get("localizadores_secundarios", "")))),
                ("Localizadores a Desativar",   lambda: self.selecionar_localizadores_desativar(_lista_de(dados.get("localizadores_desativar", "")))),
                ("Intimar Automático",          lambda: self.marcar_intimar_automatico(dados.get("intimar_automatico", ""))),
            ]
        else:
            self.log("Agendamento desativado — pulando bloco de evento/localizador.")
        passos += [
            ("Salvar e Editar (Alt+A)",     lambda: self.salvar_e_editar()),
            ("Inserir texto no editor",     lambda: self.inserir_texto_editor(dados.get("texto_minuta", ""))),
            ("Validar tags @ pendentes",    lambda: self.validar_tags_pendentes()),
        ]
        if str(dados.get("assinar", "")).strip().upper() not in ("S", "SIM", "TRUE", "1"):
            if str(dados.get("salvar_e_sair", "S")).strip().upper() in ("S", "SIM", "TRUE", "1"):
                passos.append(("Salvar Minuta e Sair (Alt+Z)", lambda: self.salvar_minuta_e_sair()))
                # "encaminhar_assinatura" (padrão "S", igual sempre foi)
                # deixa o pipeline de teste (shared/aura_regressao_homologacao.py)
                # pular esse passo aqui e chamar encaminhar_para_assinatura()
                # por conta própria, depois de ler o Assinante Indicado --
                # mantém essa função só com o que já usava em produção.
                if str(dados.get("encaminhar_assinatura", "S")).strip().upper() in ("S", "SIM", "TRUE", "1"):
                    passos.append(("Encaminhar para Assinatura", lambda: self.encaminhar_para_assinatura()))
        for nome, fn in passos:
            try:
                self.log(f"━ Passo: {nome}")
                fn()
                self._tratar_alert()
                if not self.verificar_sessao_ativa():
                    return False, f"Sessão expirou em '{nome}'"
            except UnexpectedAlertPresentException as e:
                texto = self._tratar_alert()
                return False, f"Alert em '{nome}': {texto or str(e)[:120]}"
            except Exception as e:
                self._tratar_alert()
                return False, f"Falha em '{nome}': {str(e)[:200]}"
        if str(dados.get("assinar", "")).strip().upper() in ("S", "SIM", "TRUE", "1") and dados.get("senha"):
            try:
                self.assinar_com_senha(dados["senha"])
            except Exception as e:
                return False, f"Falha ao assinar: {str(e)[:200]}"
            # A minuta abre em nova aba; após assinar, a aba costuma fechar. Volta
            # à aba principal para o próximo processo da fila não pesquisar numa
            # aba inválida.
            try:
                self._voltar_para_aba_principal()
            except Exception:
                pass
        return True, "OK"

class AppGUI(ctk.CTkToplevel):

    def __init__(self, master=None):
        super().__init__(master)

        # ── Janela ──────────────────────────────────────────────────────────
        self.title("AURA GABINETE")
        self.geometry("1200x860")
        self.minsize(1000, 700)
        self.configure(fg_color=COR_BG)

        # ── Estado ──────────────────────────────────────────────────────────
        self.bot = EprocBotV4(log_callback=self._log)
        self.perfil_ativo     = ""
        self.processos_gabinete = []

        # Garante a chave da IA mesmo se o Gabinete for aberto sem passar pelo
        # login do AURA principal (ex.: execução standalone).
        _agente_mod.init(_carregar_groq_key())

        self.notificar_avisos  = tk.BooleanVar(value=True)
        self.current_action    = ""
        self.warnings_buffer   = []

        # ── Relatório ───────────────────────────────────────────────────────
        self.relatorio_path = os.path.join(
            PASTA_SCRIPT, f"relatorio_gabinete_{datetime.now().strftime('%Y%m%d')}.html")
        self._inicializar_relatorio()
        self._build_ui()
        # Abre seleção de gabinete automaticamente ao iniciar
        self.after(400, self._popup_escolher_gabinete)

    # ─────────────────────────────────────────────────────────────────────────
    # Logo
    # ─────────────────────────────────────────────────────────────────────────
    def _logo(self, size=(32, 29)):
        try:
            img = Image.open(_base_path("aura_logo.png")).convert("RGBA")
            img = img.crop((0, 0, img.width, 104))
            dados = img.getdata()
            img.putdata([(r, g, b, 0) if r > 220 and g > 220 and b > 220
                         else (r, g, b, a) for r, g, b, a in dados])
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Relatório HTML
    # ─────────────────────────────────────────────────────────────────────────
    def _inicializar_relatorio(self):
        if os.path.exists(self.relatorio_path):
            return
        with open(self.relatorio_path, "w", encoding="utf-8") as f:
            f.write(f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<title>Relatório AURA Gabinete</title>
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
<h1>AURA GABINETE — Relatório de Execução</h1>
<p style="color:#8b949e">Iniciado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
<table><thead><tr>
<th style="width:90px">Hora</th>
<th style="width:180px">Processo</th>
<th style="width:220px">Ação</th>
<th style="width:80px">Status</th>
<th>Detalhe</th>
</tr></thead><tbody>
""")

    def _registrar_relatorio(self, processo: str, acao: str, status: str, detalhe: str = ""):
        try:
            hora   = datetime.now().strftime("%H:%M:%S")
            classe = status.lower()
            det    = (detalhe or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            linha  = (f'<tr class="{classe}"><td>{hora}</td><td>{processo or "-"}</td>'
                      f'<td>{acao}</td><td class="status {classe}">{status}</td>'
                      f'<td class="detalhe">{det}</td></tr>\n')
            with open(self.relatorio_path, "a", encoding="utf-8") as f:
                f.write(linha)
        except Exception:
            pass

    def _abrir_relatorio(self):
        try:
            if not os.path.exists(self.relatorio_path):
                self._inicializar_relatorio()
            os.startfile(self.relatorio_path)
        except Exception as e:
            messagebox.showerror("Relatório", str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Log
    # ─────────────────────────────────────────────────────────────────────────
    def _log(self, mensagem: str):
        ts = datetime.now().strftime("%H:%M:%S")
        tl = mensagem.lower()
        if mensagem.startswith("[ERROR]") or "erro" in tl or "falha" in tl or "fail" in tl:
            tag = "erro"
        elif mensagem.startswith("[WARN]") or "⚠" in mensagem or "aviso" in tl or "warn" in tl:
            tag = "aviso"
        elif "✓" in mensagem or "sucesso" in tl or "concluí" in tl or "finaliz" in tl or "ok" in tl:
            tag = "ok"
        elif mensagem.startswith("━"):
            tag = "passo"
        else:
            tag = "info"

        def _ins():
            try:
                self.txt_log.configure(state="normal")
                self.txt_log.insert("end", f"[{ts}] {mensagem}\n", tag)
                self.txt_log.see("end")
                self.txt_log.configure(state="disabled")
            except Exception:
                pass
        try:
            self.after(0, _ins)
        except Exception:
            pass

        m = re.match(r"^━ Passo: (.+?)\.{0,3}$", mensagem.strip())
        if m:
            self._flush_action_warnings()
            self.current_action  = m.group(1).strip()
            self.warnings_buffer = []
            return

        if mensagem.startswith("[WARN]") or mensagem.startswith("[ERROR]"):
            self.warnings_buffer.append(mensagem)

    def _pulsar_dot(self):
        if not self._dot_label:
            return
        self._dot_on = not self._dot_on
        cor = COR_SUCESSO if self._dot_on else "#1a4a2a"
        try:
            self._dot_label.configure(text_color=cor)
            self.after(700, self._pulsar_dot)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Notificações por etapa
    # ─────────────────────────────────────────────────────────────────────────
    def _start_action(self, nome: str):
        self._flush_action_warnings()
        self.current_action  = nome
        self.warnings_buffer = []

    def _flush_action_warnings(self):
        if not self.warnings_buffer:
            if self.current_action:
                self._registrar_relatorio(self._processo_atual(), self.current_action, "OK")
            return
        nome  = self.current_action or "ação"
        msgs  = self.warnings_buffer[:8]
        sobra = len(self.warnings_buffer) - len(msgs)
        corpo = "\n\n".join(msgs)
        if sobra > 0:
            corpo += f"\n\n(+{sobra} aviso(s) — veja o log)"
        eh_erro = any(m.startswith("[ERROR]") for m in self.warnings_buffer)
        self._registrar_relatorio(self._processo_atual(), nome,
                                  "ERROR" if eh_erro else "WARN",
                                  "\n".join(self.warnings_buffer))
        self.warnings_buffer = []
        if not eh_erro or not self.notificar_avisos.get():
            return
        try:
            self.after(0, lambda: messagebox.showerror(f"Erro em '{nome}'", corpo))
        except Exception:
            pass

    def _processo_atual(self) -> str:
        try:
            return self.processos_gabinete[0]["num_processo"] if self.processos_gabinete else ""
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # Thread runner
    # ─────────────────────────────────────────────────────────────────────────
    def _run_thread(self, fn, *args, action_name: str = None):
        if action_name:
            self._start_action(action_name)
        threading.Thread(
            target=lambda: self._run_safe(fn, *args, action_name=action_name),
            daemon=True).start()

    def _run_safe(self, fn, *args, action_name: str = None):
        try:
            fn(*args)
            if action_name:
                self._flush_action_warnings()
        except Exception as e:
            msg = str(e)
            # Navegador fechado externamente
            if "invalid session id" in msg or "no such window" in msg.lower():
                msg_limpa = "Navegador foi fechado. Clique em '▶ Executar' para reiniciar."
                self._log(f"[ERROR] {msg_limpa}")
                self._set_passo("Navegador fechado.", 0)
                self.bot.driver = None
                if action_name:
                    self.warnings_buffer.append(f"[ERROR] {msg_limpa}")
                    self._flush_action_warnings()
                else:
                    self.after(0, lambda: messagebox.showerror("Navegador fechado", msg_limpa))
                return
            if action_name:
                self.warnings_buffer.append(f"[ERROR] {e}")
                self._flush_action_warnings()
            else:
                self._log(f"ERRO: {e}")
                if self.notificar_avisos.get():
                    self.after(0, lambda: messagebox.showerror("Erro", str(e)[:1200]))


    # ─────────────────────────────────────────────────────────────────────────
    # Filtro por perfil — integração AURA
    # ─────────────────────────────────────────────────────────────────────────
    def _filtrar_processos_gabinete(self, linhas=None):
        """Filtra processos pelo perfil ativo. Aceita dados já carregados ou busca do Sheets."""
        if linhas is None:
            try:
                linhas = ler_processos_ajuizados()
            except Exception as e:
                self._log(f"[WARN] Não foi possível carregar processos do Sheets: {e}")
                linhas = []

        if not linhas:
            self._log("[WARN] Nenhum processo encontrado no Google Sheets.")
            self.processos_gabinete = []
            self._atualizar_painel_fila()
            return

        nome_perfil = self.perfil_ativo.split(" - ")[0].strip()
        filtrados = []
        for r in linhas:
            mag = str(r.get("Magistrado", "") or "").strip()
            nome_mag = mag.split(" - ")[0].strip()
            if _normalizar_texto(nome_mag) == _normalizar_texto(nome_perfil):
                filtrados.append({
                    "num_processo": str(r.get("Processo", "") or "").strip(),
                    "classe":       str(r.get("Classe", "") or "").strip(),
                    "magistrado":   str(r.get("Magistrado", "") or "").strip(),
                    "data":         str(r.get("Data", "") or "").strip(),
                    "chave":        str(r.get("Chave", "") or "").strip(),
                })

        self.processos_gabinete = filtrados
        self._log(f"Perfil '{self.perfil_ativo}': {len(filtrados)} processo(s) na fila.")
        self._atualizar_painel_fila()

    def _atualizar_painel_fila(self):
        """Atualiza o label da fila na topbar."""
        n = len(self.processos_gabinete)
        cor = COR_SUCESSO if n > 0 else COR_SUBTEXTO
        texto = f"Fila: {n} processo(s)"
        try:
            self.lbl_fila.configure(text=texto, text_color=cor)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    # BUILD UI — Homologação
    # ─────────────────────────────────────────────────────────────────────────
    def _popup_escolher_gabinete(self):
        """Popup AURA para o usuário escolher qual gabinete vai trabalhar.
        Busca dados em background para não bloquear a thread do Tkinter."""
        self._log("Carregando processos do Google Sheets...")

        resultado = {"linhas": None, "erro": None}
        evento = threading.Event()

        def _fetch():
            try:
                resultado["linhas"] = ler_processos_ajuizados()
            except Exception as e:
                resultado["erro"] = e
            evento.set()
            self.after(0, _abrir_popup)

        def _abrir_popup():
            if resultado["erro"]:
                messagebox.showerror("Erro ao carregar processos",
                                     f"Não foi possível ler os processos do Google Sheets:\n\n{resultado['erro']}")
                return

            linhas = resultado["linhas"] or []
            gabinetes = sorted(set(
                str(r.get("Magistrado", "") or "").strip()
                for r in linhas
                if str(r.get("Magistrado", "") or "").strip()
            ))

            if not gabinetes:
                messagebox.showwarning("Sem dados",
                                       "Nenhum processo encontrado no Google Sheets.\n"
                                       "Verifique se há registros na aba 'processos_ajuizados'.")
                return

            self._log(f"✓ {len(linhas)} processo(s) carregado(s) — {len(gabinetes)} gabinete(s).")

            # ── Janela popup ──────────────────────────────────────────────────
            popup = tk.Toplevel(self)
            popup.title("AURA — Escolher Gabinete")
            popup.configure(bg=COR_BG)
            popup.resizable(False, False)
            popup.lift()
            popup.focus_force()
            popup.grab_set()

            # Ícone da janela (barra de título + barra de tarefas)
            try:
                popup.iconbitmap(_base_path("aura_logo.ico"))
            except Exception:
                pass

            # Cabeçalho com logo
            hdr = tk.Frame(popup, bg=COR_PAINEL)
            hdr.pack(fill="x")

            _logo_img = None
            try:
                _pil = Image.open(_base_path("aura_logo.png")).convert("RGBA")
                _pil = _pil.crop((0, 0, _pil.width, 104))
                _dados = _pil.getdata()
                _pil.putdata([(r, g, b, 0) if r > 220 and g > 220 and b > 220
                               else (r, g, b, a) for r, g, b, a in _dados])
                _pil = _pil.resize((28, 26), Image.LANCZOS)
                _logo_img = ImageTk.PhotoImage(_pil)
            except Exception:
                pass

            if _logo_img:
                lbl_ico = tk.Label(hdr, image=_logo_img, bg=COR_PAINEL)
                lbl_ico.image = _logo_img  # manter referência
                lbl_ico.pack(side="left", padx=(14, 6), pady=12)

            tk.Label(hdr, text="Escolher Gabinete",
                     bg=COR_PAINEL, fg=COR_PRIMARIA,
                     font=("Segoe UI", 13, "bold"),
                     anchor="w").pack(side="left", pady=12)

            # Instrução
            tk.Label(popup,
                     text="Selecione o gabinete para esta sessão.\n"
                          "O robô irá minutar apenas os processos deste gabinete.",
                     bg=COR_BG, fg=COR_SUBTEXTO,
                     font=("Segoe UI", 10), justify="left").pack(anchor="w", padx=20, pady=(12, 6))

            # Listbox + scrollbar
            frame_lista = tk.Frame(popup, bg="#0d1117",
                                   highlightbackground=COR_BORDA, highlightthickness=1)
            frame_lista.pack(fill="both", expand=True, padx=20, pady=(0, 8))

            scrollbar = tk.Scrollbar(frame_lista)
            scrollbar.pack(side="right", fill="y")

            listbox = tk.Listbox(
                frame_lista,
                yscrollcommand=scrollbar.set,
                bg="#0d1117", fg=COR_TEXTO,
                selectbackground=COR_PRIMARIA, selectforeground="#ffffff",
                font=("Segoe UI", 10),
                borderwidth=0, highlightthickness=0,
                activestyle="none", relief="flat",
            )
            listbox.pack(fill="both", expand=True, padx=4, pady=4)
            scrollbar.config(command=listbox.yview)

            for g in gabinetes:
                listbox.insert("end", f"  {g}")

            if len(gabinetes) == 1:
                listbox.selection_set(0)

            # Forçar renderização antes de exibir
            popup.update_idletasks()
            popup.geometry(f"560x500+{self.winfo_x() + (self.winfo_width()-560)//2}"
                           f"+{self.winfo_y() + (self.winfo_height()-500)//2}")
            popup.update()

            gabinete_selecionado = tk.StringVar(value="")

            def _confirmar():
                sel = listbox.curselection()
                if not sel:
                    messagebox.showwarning("Atenção", "Selecione um gabinete.", parent=popup)
                    return
                gabinete_selecionado.set(gabinetes[sel[0]])
                popup.destroy()

            listbox.bind("<Double-Button-1>", lambda _e: _confirmar())

            # Botão confirmar
            tk.Button(popup, text="✓  Confirmar Gabinete",
                      bg=COR_SUCESSO, fg="#ffffff",
                      font=("Segoe UI", 11, "bold"),
                      relief="flat", cursor="hand2",
                      command=_confirmar).pack(fill="x", padx=20, pady=(0, 16), ipady=8)

            # Aguardar fechamento do popup
            self.wait_window(popup)

            escolha = gabinete_selecionado.get()
            if not escolha:
                self._log("Nenhum gabinete escolhido.")
                return

            # Aplicar escolha e filtrar (reutiliza linhas já carregadas)
            self.perfil_ativo = escolha
            nome_curto = escolha.split(" - ")[0].strip()[:30]
            self.lbl_perfil.configure(text=f"  {nome_curto}  ", text_color=COR_SUCESSO)
            try:
                self._chip_perfil.configure(fg_color="#0d1f12", border_color="#2ea043")
            except Exception:
                pass
            self._log(f"Gabinete selecionado: {escolha}")
            self._filtrar_processos_gabinete(linhas)
            self._atualizar_txt_fila()

        threading.Thread(target=_fetch, daemon=True).start()



    def _build_ui(self):
        self._dot_label = None
        self._dot_on = True

        # ── Topbar ──────────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0,
                              border_width=0, height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        # accent line no fundo da topbar
        ctk.CTkFrame(self, fg_color=COR_BORDA, height=1, corner_radius=0).pack(fill="x")

        logo_img = self._logo((28, 26))
        if logo_img:
            ctk.CTkLabel(topbar, image=logo_img, text="",
                         fg_color="transparent").pack(side="left", padx=(14, 6), pady=10)
        ctk.CTkLabel(topbar, text="AURA GABINETE",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_PRIMARIA).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(topbar, text="Minutar · Movimentar · TJMG",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO).pack(side="left")

        # Badge versão pill
        badge = ctk.CTkFrame(topbar, fg_color="#1a2a45",
                             corner_radius=10, border_width=1, border_color="#2a4a7f")
        badge.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(badge, text=f"  v{VERSAO_GABINETE}  ",
                     font=ctk.CTkFont("Segoe UI", 8, "bold"),
                     text_color=COR_PRIMARIA).pack(padx=2, pady=1)

        # Dot pulsante de status
        self._dot_label = ctk.CTkLabel(topbar, text="●",
                                       font=ctk.CTkFont("Segoe UI", 10),
                                       text_color=COR_SUCESSO)
        self._dot_label.pack(side="right", padx=(0, 10))
        self.after(700, self._pulsar_dot)

        # Fila (badge chip)
        self.lbl_fila = ctk.CTkLabel(topbar, text="Fila: —",
                                     font=ctk.CTkFont("Segoe UI", 9, "bold"),
                                     text_color=COR_SUBTEXTO)
        self.lbl_fila.pack(side="right", padx=(0, 6))

        # Chip de perfil
        self._chip_perfil = ctk.CTkFrame(topbar, fg_color="#1a2a1a",
                                          corner_radius=10, border_width=1,
                                          border_color="#2a4a2a")
        self._chip_perfil.pack(side="right", padx=(0, 8))
        self.lbl_perfil = ctk.CTkLabel(self._chip_perfil, text="  — sem perfil —  ",
                                       font=ctk.CTkFont("Segoe UI", 9, "bold"),
                                       text_color=COR_SUBTEXTO)
        self.lbl_perfil.pack(padx=4, pady=3)

        # ── Session strip ────────────────────────────────────────────────────
        strip = ctk.CTkFrame(self, fg_color="#0c1020", corner_radius=0, height=26)
        strip.pack(fill="x")
        strip.pack_propagate(False)
        self.lbl_strip_processo = ctk.CTkLabel(
            strip, text="⚙  Processo: —",
            font=ctk.CTkFont("Segoe UI", 8),
            text_color=COR_SUBTEXTO, anchor="w")
        self.lbl_strip_processo.pack(side="left", padx=14)
        self.lbl_strip_acao = ctk.CTkLabel(
            strip, text="🔄  Aguardando",
            font=ctk.CTkFont("Segoe UI", 8),
            text_color=COR_SUBTEXTO, anchor="e")
        self.lbl_strip_acao.pack(side="right", padx=14)

        # ── Corpo com PanedWindow para ser responsivo ─────────────────────
        paned = tk.PanedWindow(self, orient="horizontal",
                               bg=COR_BG, sashwidth=4,
                               sashrelief="flat", bd=0)
        paned.pack(fill="both", expand=True, padx=10, pady=8)

        # Coluna esquerda — scrollable
        esq_outer = ctk.CTkFrame(paned, fg_color=COR_BG, corner_radius=0)
        self._scroll_esq = ctk.CTkScrollableFrame(
            esq_outer, fg_color=COR_BG, corner_radius=0,
            scrollbar_button_color=COR_BORDA,
            scrollbar_button_hover_color=COR_PRIMARIA)
        self._scroll_esq.pack(fill="both", expand=True)
        paned.add(esq_outer, minsize=280, width=340)

        # Coluna direita — log
        dir_outer = ctk.CTkFrame(paned, fg_color=COR_BG, corner_radius=0)
        paned.add(dir_outer, minsize=300)

        self._build_esquerda(self._scroll_esq)
        self._build_direita(dir_outer)

    # ─────────────────────────────────────────────────────────────────────────
    # Coluna esquerda
    # ─────────────────────────────────────────────────────────────────────────
    def _build_esquerda(self, parent):
        def painel(titulo, cor_accent=COR_PRIMARIA):
            f = ctk.CTkFrame(parent, fg_color=COR_PAINEL, corner_radius=8,
                             border_width=1, border_color=COR_BORDA)
            f.pack(fill="x", pady=(0, 8))
            ctk.CTkFrame(f, fg_color=cor_accent, height=3, corner_radius=0).pack(fill="x")
            ctk.CTkLabel(f, text=titulo,
                         font=ctk.CTkFont("Segoe UI", 9, "bold"),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkFrame(f, fg_color=COR_BORDA, height=1).pack(fill="x", padx=12, pady=(0, 6))
            return f

        def btn(parent, texto, cmd, cor=COR_PRIMARIA, h=34):
            ctk.CTkButton(parent, text=texto, command=cmd,
                          fg_color=cor, hover_color=_cor_hover(cor),
                          font=ctk.CTkFont("Segoe UI", 10, "bold"),
                          height=h, corner_radius=6).pack(fill="x", padx=12, pady=3)

        def label(parent, texto):
            ctk.CTkLabel(parent, text=texto,
                         font=ctk.CTkFont("Segoe UI", 9),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=12, pady=(4, 0))

        def entry(parent, var):
            e = ctk.CTkEntry(parent, textvariable=var,
                             font=ctk.CTkFont("Segoe UI", 10),
                             fg_color="#21262d", border_color=COR_BORDA,
                             height=30, corner_radius=5)
            e.pack(fill="x", padx=12, pady=(2, 6))
            return e

        def combo(parent, var, values):
            c = ctk.CTkComboBox(
                parent, variable=var, values=values,
                font=ctk.CTkFont("Segoe UI", 10),
                fg_color="#21262d", border_color=COR_BORDA,
                button_color=COR_PRIMARIA, button_hover_color=COR_HOVER,
                dropdown_fg_color=COR_PAINEL, dropdown_text_color=COR_TEXTO,
                dropdown_hover_color=COR_BORDA,
                height=30, corner_radius=5,
                command=lambda v: var.set(v))
            c.pack(fill="x", padx=12, pady=(2, 6))
            return c

        # ── Gabinete ──────────────────────────────────────────────────────
        p_gab = painel("GABINETE", cor_accent=COR_AVISO)
        btn(p_gab, "👤  Escolher Gabinete", self._popup_escolher_gabinete, COR_AVISO)

        # ── Navegador ─────────────────────────────────────────────────────
        p_nav = painel("NAVEGADOR")
        btn(p_nav, "▶  Executar", self._abrir_site, COR_PRIMARIA, h=40)
        btn(p_nav, "Fechar Navegador", self._fechar_navegador, "#30363d")

        # ── Fila ──────────────────────────────────────────────────────────
        p_fila = painel("FILA DO GABINETE")
        self.txt_fila = ctk.CTkTextbox(p_fila, height=90,
                                       font=ctk.CTkFont("Consolas", 9),
                                       fg_color="#0d1117", text_color=COR_TEXTO,
                                       border_width=0, corner_radius=4)
        self.txt_fila.pack(fill="x", padx=12, pady=(0, 8))
        self.txt_fila.configure(state="disabled")

        # ── Parâmetros ────────────────────────────────────────────────────
        p_min = painel("PARÂMETROS DA MINUTA")

        label(p_min, "Tipo / Modelo")
        self.var_modelo = tk.StringVar(value="DESPACHO")
        entry(p_min, self.var_modelo)

        label(p_min, "Descrição")
        self.var_descricao = tk.StringVar()
        entry(p_min, self.var_descricao)

        label(p_min, "Evento (agendamento)")
        self.var_evento = tk.StringVar()
        self.cmb_evento = combo(p_min, self.var_evento, EVENTOS_CIVEIS)

        label(p_min, "Evento de Remessa (opcional)")
        self.var_evento_remessa = tk.StringVar()
        self.cmb_remessa = combo(p_min, self.var_evento_remessa, [""] + EVENTOS_REMESSA)

        label(p_min, "Texto da Minuta (opcional)")
        self.var_texto = tk.StringVar()
        entry(p_min, self.var_texto)

        # Checkboxes em grid 2x2
        ck_frame = ctk.CTkFrame(p_min, fg_color="transparent")
        ck_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.var_agendar     = tk.BooleanVar(value=True)
        self.var_salvar_sair = tk.BooleanVar(value=True)
        self.var_para_assinar = tk.BooleanVar(value=True)

        def ck(parent, texto, var, cor=COR_PRIMARIA, row=0, col=0):
            ctk.CTkCheckBox(parent, text=texto, variable=var,
                            font=ctk.CTkFont("Segoe UI", 10),
                            fg_color=cor, hover_color=_cor_hover(cor),
                            checkmark_color="#fff").grid(row=row, column=col,
                                                         sticky="w", padx=(0, 12), pady=2)

        ck(ck_frame, "Agendar evento",  self.var_agendar,     row=0, col=0)
        ck(ck_frame, "Salvar e Sair",   self.var_salvar_sair, row=0, col=1)
        ck(ck_frame, "Para assinar",    self.var_para_assinar,
           cor=COR_SUCESSO, row=1, col=0)

        # ── Execução ──────────────────────────────────────────────────────
        p_exec = painel("EXECUÇÃO", cor_accent=COR_SUCESSO)
        btn(p_exec, "▶  Minutar processo da fila",  self._executar_proximo,       COR_PRIMARIA, h=38)
        btn(p_exec, "▶▶ Minutar FILA INTEIRA",      self._executar_fila_gabinete, COR_SUCESSO,  h=38)
        btn(p_exec, "📄 Relatório do dia",           self._abrir_relatorio,        "#21262d")
        btn(p_exec, "🤖 AURA AGENT",                 self._abrir_agente,           "#6c63ff")

    # ─────────────────────────────────────────────────────────────────────────
    # Coluna direita — Log
    # ─────────────────────────────────────────────────────────────────────────
    def _build_direita(self, parent):
        # Card de progresso com accent bar
        passo_card = ctk.CTkFrame(parent, fg_color=COR_PAINEL, corner_radius=8,
                                   border_width=1, border_color=COR_BORDA)
        passo_card.pack(fill="x", pady=(0, 8))
        ctk.CTkFrame(passo_card, fg_color=COR_PRIMARIA, height=3,
                     corner_radius=0).pack(fill="x")
        passo_row = ctk.CTkFrame(passo_card, fg_color="transparent")
        passo_row.pack(fill="x", padx=10, pady=(6, 2))
        self.lbl_passo = ctk.CTkLabel(passo_row,
                                      text="Aguardando...",
                                      font=ctk.CTkFont("Segoe UI", 9, "bold"),
                                      text_color=COR_SUBTEXTO, anchor="w")
        self.lbl_passo.pack(side="left", fill="x", expand=True)
        self._lbl_pct = ctk.CTkLabel(passo_row, text="0%",
                                      font=ctk.CTkFont("Segoe UI", 8, "bold"),
                                      text_color=COR_PRIMARIA)
        self._lbl_pct.pack(side="right")
        self.progress = ctk.CTkProgressBar(passo_card, height=5,
                                           fg_color=COR_BORDA,
                                           progress_color=COR_PRIMARIA,
                                           corner_radius=0)
        self.progress.pack(fill="x", pady=(4, 0))
        self.progress.set(0)

        # Card de log colorido
        log_frame = ctk.CTkFrame(parent, fg_color=COR_PAINEL, corner_radius=8,
                                 border_width=1, border_color=COR_BORDA)
        log_frame.pack(fill="both", expand=True)
        ctk.CTkFrame(log_frame, fg_color=COR_AVISO, height=3,
                     corner_radius=0).pack(fill="x")

        topo = ctk.CTkFrame(log_frame, fg_color="transparent")
        topo.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(topo, text="LOG DE EXECUÇÃO",
                     font=ctk.CTkFont("Segoe UI", 8, "bold"),
                     text_color=COR_SUBTEXTO).pack(side="left")
        ctk.CTkButton(topo, text="Limpar",
                      font=ctk.CTkFont("Segoe UI", 8),
                      fg_color="#21262d", hover_color=COR_BORDA,
                      width=55, height=22, corner_radius=4,
                      command=self._limpar_log).pack(side="right")

        ctk.CTkFrame(log_frame, fg_color=COR_BORDA, height=1).pack(fill="x", padx=12, pady=(0, 4))

        self.txt_log = _st.ScrolledText(
            log_frame, font=("Consolas", 9),
            bg="#080b10", fg=COR_TEXTO, relief="flat",
            wrap="word", state="disabled", padx=10, pady=8,
            insertbackground=COR_TEXTO,
        )
        self.txt_log.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        for tag, cor in (("ok", COR_SUCESSO), ("erro", COR_ERRO),
                         ("aviso", COR_AVISO), ("info", COR_SUBTEXTO),
                         ("passo", COR_PRIMARIA)):
            self.txt_log.tag_configure(tag, foreground=cor)

        self._log("AURA GABINETE — pronto.")
        self._log("① Escolha o gabinete  ② Executar  ③ Login no eProc  ④ Minutar")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de UI
    # ─────────────────────────────────────────────────────────────────────────
    def _filtrar_eventos(self, *args):
        busca = _normalizar_texto(self.var_busca_evento.get())
        filtrados = [e for e in EVENTOS_CIVEIS if busca in _normalizar_texto(e)] if busca else EVENTOS_CIVEIS
        try:
            self.cmb_evento.configure(values=filtrados if filtrados else EVENTOS_CIVEIS)
        except Exception:
            pass

    def _filtrar_remessa(self, *args):
        busca = _normalizar_texto(self.var_busca_remessa.get())
        filtrados = [e for e in EVENTOS_REMESSA if busca in _normalizar_texto(e)] if busca else EVENTOS_REMESSA
        try:
            self.cmb_remessa.configure(values=filtrados if filtrados else EVENTOS_REMESSA)
        except Exception:
            pass

    def _limpar_log(self):
        try:
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.configure(state="disabled")
        except Exception:
            try:
                self.txt_log["state"] = "normal"
                self.txt_log.delete("1.0", "end")
                self.txt_log["state"] = "disabled"
            except Exception:
                pass

    def _set_passo(self, texto: str, progresso: float = None):
        def _ins():
            try:
                self.lbl_passo.configure(text=texto)
                self.lbl_strip_acao.configure(text=f"🔄  {texto}")
                if progresso is not None:
                    v = max(0.0, min(1.0, progresso))
                    self.progress.set(v)
                    self._lbl_pct.configure(text=f"{int(v * 100)}%")
            except Exception:
                pass
        self.after(0, _ins)

    def _atualizar_txt_fila(self):
        def _ins():
            try:
                self.txt_fila.configure(state="normal")
                self.txt_fila.delete("1.0", "end")
                if not self.processos_gabinete:
                    self.txt_fila.insert("end", "Nenhum processo na fila.")
                else:
                    for p in self.processos_gabinete:
                        self.txt_fila.insert(
                            "end",
                            f"• {p['num_processo']}  [{p['data']}]\n"
                            f"  {p['classe'][:50]}\n\n")
                self.txt_fila.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _ins)

    def _atualizar_info_linha(self):
        pass  # não usada na UI de homologação

    # ─────────────────────────────────────────────────────────────────────────
    # Handlers de Setup
    # ─────────────────────────────────────────────────────────────────────────
    def _abrir_site(self):
        if not self.perfil_ativo:
            messagebox.showwarning("Atenção", "Escolha o gabinete antes de executar.")
            return

        def _go():
            # Herda endereço e usuário da tela inicial (aura_config.json). Os
            # planos B *_PADRAO só valem se o Gabinete rodar avulso, sem config.
            cfg = carregar_config()
            url     = (cfg.get("url")     or URL_EPROC_GABINETE_PADRAO).strip()
            usuario = (cfg.get("usuario") or USUARIO_EPROC_PADRAO).strip()
            senha   = (cfg.get("senha")   or SENHA_EPROC_PADRAO)
            self._set_passo("Abrindo navegador...", 0.05)
            self.bot.abrir_navegador(url)
            self._set_passo("Realizando login...", 0.2)
            self.bot.fazer_login(usuario, senha)

            # Seleciona o perfil automaticamente (como o AURA Distribuição), em
            # vez de parar na tela "Seleção de perfil". O gabinete escolhido
            # (self.perfil_ativo) vem como "MAGISTRADO - Câmara - Assento"; o que
            # identifica o perfil no eProc é a parte da câmara/assento (após o
            # nome do magistrado).
            partes = [p.strip() for p in (self.perfil_ativo or "").split(" - ")]
            alvo_perfil = " - ".join(partes[1:]).strip() if len(partes) > 1 else (self.perfil_ativo or "").strip()
            self._set_passo(f"Selecionando perfil do gabinete ({alvo_perfil})...", 0.3)
            if alvo_perfil and self.bot.selecionar_perfil(alvo_perfil):
                # NÃO sobrescreve self.perfil_ativo: ele guarda o MAGISTRADO, usado
                # para filtrar a fila. Aqui só confirmamos/logamos o perfil eProc.
                try:
                    ativo = self.bot.confirmar_login().get("ativo", "")
                    if ativo:
                        self._log(f"Perfil eProc ativo: {ativo}")
                except Exception as e:
                    self._log(f"(perfil selecionado; confirmação do combobox falhou: {e})", nivel="WARN")
                self._set_passo("Pronto — perfil selecionado", 0.4)
                self._log(f"✓ Perfil do gabinete selecionado automaticamente ({alvo_perfil}). Clique em Minutar.")
            else:
                self._set_passo("Selecione o perfil manualmente e clique em '② Confirmar Login'.", 0.35)
                self._log(
                    "⚠ Não consegui achar o perfil do gabinete automaticamente para "
                    f"'{alvo_perfil}'. Escolha o perfil na tela do eProc e clique em "
                    "'② Confirmar Login'.", nivel="WARN")

        self._run_thread(_go, action_name="Abrir e Logar")

    def _confirmar_login(self):
        def _go():
            self._set_passo("Confirmando login...", 0.1)
            info = self.bot.confirmar_login()
            self.perfil_ativo = info.get("ativo", "")
            _perfil = self.perfil_ativo
            def _atualizar_chip():
                nome_curto = _perfil.split(" - ")[0].strip()[:30] if _perfil else "—"
                self.lbl_perfil.configure(
                    text=f"  {nome_curto}  ",
                    text_color=COR_SUCESSO if _perfil else COR_AVISO)
                try:
                    self._chip_perfil.configure(
                        fg_color="#0d1f12" if _perfil else "#1a2a1a",
                        border_color="#2ea043" if _perfil else "#2a4a2a")
                except Exception:
                    pass
            self.after(0, _atualizar_chip)
            self._log(f"Login confirmado. Perfil eProc: {self.perfil_ativo or '—'}")
            self.after(0, self._popup_escolher_gabinete)
        self._run_thread(_go, action_name="Confirmar Login")

    def _fechar_navegador(self):
        self.bot.fechar_navegador()
        self._set_passo("Navegador fechado.", 0)

    # ─────────────────────────────────────────────────────────────────────────
    # Montar dados para o bot a partir dos campos da UI
    # ─────────────────────────────────────────────────────────────────────────
    def _montar_dados_minuta(self, num_processo: str) -> dict:
        # Busca o magistrado do processo na fila para inferir tratamento
        magistrado = ""
        for p in self.processos_gabinete:
            if p["num_processo"] == num_processo:
                magistrado = p.get("magistrado", "")
                break
        if not magistrado:
            magistrado = self.perfil_ativo

        tratamento = EprocBotV4.inferir_tratamento(magistrado)
        self._log(f"Tratamento inferido: '{tratamento}' (magistrado: {magistrado})")
        return {
            "num_processo":              num_processo,
            "tipo_modelo":               self.var_modelo.get().strip() or "DESPACHO",
            "descricao":                 self.var_descricao.get().strip(),
            "assinante":                 "",
            "tratamento":                tratamento,
            "sigilo":                    "",
            "status_minuta":             "Para assinar" if self.var_para_assinar.get() else "Rascunho",
            "cabecalho":                 {},
            "precedente_relevante":      "",
            "agendar":                   "S" if self.var_agendar.get() else "N",
            "evento":                    self.var_evento.get().strip(),
            "evento_remessa":            self.var_evento_remessa.get().strip(),
            "comportamento_localizador": "",
            "marcar_todos_atuais":       "N",
            "novo_localizador":          "",
            "localizadores_secundarios": "",
            "localizadores_desativar":   "",
            "intimar_automatico":        "",
            "texto_minuta":              self.var_texto.get().strip(),
            "salvar_e_sair":             "S" if self.var_salvar_sair.get() else "N",
            "assinar":                   "",
            "senha":                     "",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Executar próximo processo da fila
    # ─────────────────────────────────────────────────────────────────────────
    def _executar_proximo(self):
        if not self.perfil_ativo:
            self._popup_escolher_gabinete()
        if not self.perfil_ativo:
            return  # usuário cancelou o popup
        if not self.processos_gabinete:
            messagebox.showwarning("Fila vazia", f"Nenhum processo encontrado para o gabinete:\n\n'{self.perfil_ativo}'")
            return
        proc_info = self.processos_gabinete[0]
        num       = proc_info["num_processo"]
        dados     = self._montar_dados_minuta(num)

        def _go():
            self.after(0, lambda: self.lbl_strip_processo.configure(text=f"⚙  Processo: {num}"))
            self._set_passo(f"Minutando: {num}", 0.2)
            self._registrar_relatorio(num, "INICIADO", "INFO", proc_info.get("classe", ""))
            ok, motivo = self.bot.executar_minutar_com_agendamento(dados)
            if ok:
                self._set_passo(f"✓ Concluído: {num}", 1.0)
                self._registrar_relatorio(num, "MINUTAR", "OK", "Concluído")
                self._log(f"✓ {num}: OK")
                self.after(0, lambda: self.lbl_strip_processo.configure(text="⚙  Processo: —"))
                # Remove da fila
                self.processos_gabinete.pop(0)
                self._atualizar_painel_fila()
                self._atualizar_txt_fila()
            else:
                self._set_passo(f"✗ Erro: {num}", 0)
                self._registrar_relatorio(num, "MINUTAR", "ERROR", motivo)
                self._log(f"✗ {num}: {motivo}")
                if self.notificar_avisos.get():
                    self.after(0, lambda: messagebox.showerror("Erro", f"{num}\n\n{motivo}"))

        self._run_thread(_go)

    # ─────────────────────────────────────────────────────────────────────────
    # Executar fila inteira
    # ─────────────────────────────────────────────────────────────────────────
    def _executar_fila_gabinete(self):
        if not self.perfil_ativo:
            self._popup_escolher_gabinete()
        if not self.perfil_ativo:
            return  # usuário cancelou
        if not self.processos_gabinete:
            messagebox.showwarning("Fila vazia", f"Nenhum processo encontrado para o gabinete:\n\n'{self.perfil_ativo}'")
            return
        if not messagebox.askyesno("Confirmar",
            f"Minutar {len(self.processos_gabinete)} processo(s) do gabinete:\n\n"
            f"'{self.perfil_ativo}'\n\nConfirma?"):
            return

        def _go():
            total = len(self.processos_gabinete)
            ok_n = err_n = 0
            # Copia a lista para iterar — a fila vai sendo drenada
            fila = list(self.processos_gabinete)
            for idx, proc_info in enumerate(fila, 1):
                num   = proc_info["num_processo"]
                dados = self._montar_dados_minuta(num)
                self._set_passo(f"[{idx}/{total}] {num}", idx / total)
                self._log(f"═══ [{idx}/{total}] {num} ═══")
                self._registrar_relatorio(num, "FILA INICIADO", "INFO", proc_info.get("classe", ""))
                try:
                    ok, motivo = self.bot.executar_minutar_com_agendamento(dados)
                    if ok:
                        ok_n += 1
                        self._registrar_relatorio(num, "FILA OK", "OK", "Concluído")
                        self._log(f"✓ {num}")
                        # Remove da fila
                        if self.processos_gabinete and self.processos_gabinete[0]["num_processo"] == num:
                            self.processos_gabinete.pop(0)
                        self._atualizar_painel_fila()
                        self._atualizar_txt_fila()
                    else:
                        err_n += 1
                        self._registrar_relatorio(num, "FILA ERRO", "ERROR", motivo)
                        self._log(f"✗ {num}: {motivo}")
                except Exception as e:
                    err_n += 1
                    self._registrar_relatorio(num, "FILA EXCEÇÃO", "ERROR", str(e)[:200])
                    self._log(f"✗ {num}: {e}")

            resumo = f"Fila concluída. ✓ {ok_n}  ✗ {err_n}"
            self._set_passo(resumo, 1.0)
            self._log(resumo)
            if self.notificar_avisos.get():
                self.after(0, lambda: messagebox.showinfo("Fila concluída", resumo))

        self._run_thread(_go)

    def _abrir_relatorio(self):
        try:
            if not os.path.exists(self.relatorio_path):
                self._inicializar_relatorio()
            os.startfile(self.relatorio_path)
        except Exception as e:
            messagebox.showerror("Relatório", str(e))

    def _abrir_agente(self):
        def _get_ctx():
            return {
                "pdf": None,
                "competencia": self.lbl_strip_processo.cget("text").replace("⚙  Processo: ", "").strip() or None,
                "usuario": self.perfil_ativo or None,
            }
        _agente_mod.abrir_chat_agente(self, _get_ctx)

    def _dbg_dump_tela(self):
        def _go():
            self.bot._dump_diagnostico("manual", "via debug")
        self._run_thread(_go)

    def executar(self):
        # Standalone: cria seu próprio loop. Integrado ao aura.py: mainloop já está rodando.
        if not self.master:
            self.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
def _cor_hover(cor: str) -> str:
    try:
        r, g, b = int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)
        f = 0.85
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"
    except Exception:
        return cor


if __name__ == "__main__":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _root = ctk.CTk()
    _root.withdraw()
    app = AppGUI(_root)
    app.protocol("WM_DELETE_WINDOW", _root.destroy)
    _root.mainloop()