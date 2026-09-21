"""AURA Eventos Câmara Cível — arquivo único.

Verifica quais eventos aparecem no autocomplete de "Evento a ser lançado" em
cada gabinete/cartório de uma câmara cível no eproc2g-hml (TJMG), remetendo
um processo de teste em cadeia por todos os órgãos e, no modo "cadeia
completa", por todas as câmaras cíveis em sequência (1CACIV..21CACIV +
4CACIVEsp/8CACIVEsp/16CACIVEsp/21CACIVEsp).

Reaproveita login, seleção de perfil e criação resiliente do chromedriver do
AURA COTRI (run_aura_cotri.py) em vez de duplicar automação já validada em
produção. Roda embutido no AURA Principal (AuraEventosApp) ou standalone:

    python run_aura_eventoscamaracivel.py
"""

import csv
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

# Modulos compartilhados vivem em shared/ (pasta irma desta, integrations/)
# -- necessario ao rodar este arquivo standalone (import de sibling nao acha
# shared/ sozinho). Quando importado pelo aura.py, ja esta no sys.path, mas
# nao ha problema em inserir de novo.
_caminho_shared = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared")
if _caminho_shared not in sys.path:
    sys.path.insert(0, _caminho_shared)

import aura_db

from selenium.common.exceptions import (
    NoAlertPresentException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

import run_aura_cotri as _cotri

logger = logging.getLogger("aura_eventoscamaracivel")

VERSAO_ATUAL = "1.0"

OUTPUT_DIR = Path.home() / ".aura_eventoscamaracivel"
ARQUIVO_CONFIG = OUTPUT_DIR / "config.json"
PASTA_RELATORIOS = OUTPUT_DIR / "relatorios"
PASTA_DUMPS = OUTPUT_DIR / "dumps"

# Esta automacao usa uma conta propria (diferente da conta padrao do AURA
# Principal/AURA COTRI): o processo de teste e as lotacoes ja incluidas em
# execucoes anteriores estao todos sob essa conta. NAO fica hardcoded aqui --
# fica apenas no config local (~/.aura_eventoscamaracivel/config.json, fora do
# repositorio git), o mesmo padrao usado por _cotri para ~/.aura_cotri/config.json.
# carregar_config() e a unica fonte; sem config salvo, o app pede login na tela.
USUARIO_PADRAO = ""
SENHA_PADRAO = ""
URL_PADRAO = "https://eproc2g-hml.tjmg.jus.br/eproc/"

ORGAOS_JSON_PATH = _cotri.base_path("orgaos_caciv.json")

PERFIL_GERENTE_USUARIOS = "GERENTE DE USUÁRIOS"
TIPO_USUARIO_GERENTE_SECRETARIA = "D|10|1|S|S|N"
UF_PADRAO = "MG"

EVENTOS_ALVO = [
    "Remetidos os Autos para Secretaria de Recursos 1° CAROT",
    "Remetidos os Autos para Secretaria de Recursos 2° CAROT",
    "Remetidos os Autos para Secretaria de Recursos 3° CAROT",
    "Remetidos os Autos para Secretaria de Recursos 4° CAROT",
]

# Ordem combinada: 1..21CACIV primeiro (exceto 4 e 8, que o tribunal
# reorganizou como "Especializada" -- nao existem mais como camara comum),
# depois as 4 camaras "Esp".
CAMARA_SEQUENCIA = [f"{i}CACIV" for i in range(1, 22) if i not in (4, 8)] + [
    "4CACIVEsp", "8CACIVEsp", "16CACIVEsp", "21CACIVEsp",
]

TIMEOUT = 60


class FalhaCritica(Exception):
    """Falha que impede seguir a cadeia com seguranca (posse do processo fica ambigua)."""


# ===========================================================================
# Configuracao (mesmo padrao do run_aura_cotri.py)
# ===========================================================================

def salvar_config(usuario, senha, url):
    try:
        os.makedirs(ARQUIVO_CONFIG.parent, exist_ok=True)
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump({"usuario": usuario, "senha": senha, "url": url}, f)
    except Exception:
        pass


def carregar_config():
    try:
        if ARQUIVO_CONFIG.exists():
            with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


# ===========================================================================
# Cadeia de orgaos de uma ou mais camaras (a partir de orgaos_caciv.json)
# ===========================================================================

def carregar_camara(camara_sigla, log=None):
    with open(ORGAOS_JSON_PATH, encoding="utf-8") as f:
        camaras = json.load(f)

    camara = next((c for c in camaras if c["camara"] == camara_sigla), None)
    if camara is None:
        raise ValueError(f"Camara '{camara_sigla}' nao encontrada em {ORGAOS_JSON_PATH}")

    if not camara["gabinetes"] and log is not None:
        log(f"  [AVISO] Camara '{camara_sigla}' sem gabinetes cadastrados em "
            f"orgaos_caciv.json -- verificando apenas o cartorio.")

    cadeia = [
        {"sigla": g["orgao"], "descricao": g["descricao"]}
        for g in sorted(camara["gabinetes"], key=lambda g: g["assento"])
    ]
    cadeia.append({"sigla": camara["cartorio"]["orgao"], "descricao": camara["cartorio"]["descricao"]})
    return cadeia


def carregar_cadeia_completa(camaras_siglas, log=None):
    """Concatena a cadeia de cada camara da lista (na ordem dada) numa unica
    lista, marcando cada no com a camara de origem (usado so no relatorio)."""
    cadeia = []
    for camara_sigla in camaras_siglas:
        for no in carregar_camara(camara_sigla, log=log):
            no = dict(no)
            no["camara"] = camara_sigla
            cadeia.append(no)
    return cadeia


# ===========================================================================
# Driver / login (reaproveita run_aura_cotri para login, perfil e chromedriver)
# ===========================================================================

def criar_driver(timeout=TIMEOUT, headless=True):
    chrome_options = Options()
    # "eager" libera o controle assim que o DOM esta pronto (DOMContentLoaded),
    # sem esperar recursos secundarios (analytics/trackers) que o eproc2g-hml
    # as vezes trava carregando bem depois da pagina ja estar usavel -- sem
    # isso, QUALQUER navegacao (busca de processo, Movimentar Processo, etc.)
    # pode travar ate o page_load_timeout inteiro (60s) e estourar
    # "Timed out receiving message from renderer".
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_experimental_option("detach", not headless)
    # --window-size vale tambem fora do headless: sem ele, a janela abre no
    # tamanho padrao do Chrome, que pode ficar estreito o bastante pra
    # disparar o layout responsivo/mobile do eproc (menu recolhido, sem o
    # indicador de perfil visivel) -- selInfraUnidades e outros elementos que
    # o codigo espera visiveis ficam escondidos, e is_displayed() falha.
    chrome_options.add_argument("--window-size=1920,1080")
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
    driver = _cotri.criar_chrome_driver(chrome_options)
    if not headless:
        try:
            driver.set_window_size(1920, 1080)
        except Exception:
            pass
    driver.set_page_load_timeout(timeout)
    wait = WebDriverWait(driver, timeout)
    return driver, wait


def _matar_processo_arvore(pid, log=print):
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=10,
        )
    except Exception as exc:
        log(f"  [AVISO] Falha ao encerrar arvore de processos do navegador (pid {pid}): {exc}")


def _fechar_driver(driver, log=print):
    """Fecha o driver com um timeout curto e, independente do resultado, mata
    a arvore de processos do chromedriver/chrome na forca. driver.quit()
    sozinho pode travar (ou simplesmente nao rodar, se a execucao abortar de
    um jeito que pule o finally) deixando chrome.exe orfaos, ainda logados na
    mesma conta -- na proxima execucao, o eproc detecta duas sessoes ativas
    da mesma conta e cancela uma ("mudanca no perfil do usuario" / "sessao
    encerrada"), derrubando a automacao no meio do caminho."""
    pid = None
    try:
        pid = driver.service.process.pid
    except Exception:
        pass

    def _quit():
        try:
            driver.quit()
        except Exception:
            pass

    t = threading.Thread(target=_quit, daemon=True)
    t.start()
    t.join(timeout=8)

    if pid:
        _matar_processo_arvore(pid, log=log)


def _get_resiliente(driver, url, log=print):
    """driver.get() com timeout curto: o eproc2g-hml as vezes fica preso
    carregando recursos secundarios (analytics/trackers) bem depois do
    formulario de login ja estar pronto. Em vez de travar minutos esperando
    o evento 'load' que pode nunca vir, corta o carregamento e segue --
    o conteudo essencial da pagina ja esta no DOM nesse ponto."""
    try:
        driver.get(url)
    except TimeoutException:
        log(f"  [AVISO] Carregamento de {url} nao terminou em 45s -- interrompendo e seguindo.")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass


def _dump_diagnostico(driver, nome, log=print):
    try:
        os.makedirs(PASTA_DUMPS, exist_ok=True)
        driver.save_screenshot(str(PASTA_DUMPS / f"{nome}.png"))
        with open(PASTA_DUMPS / f"{nome}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log(f"  [DUMP] Screenshot/HTML salvos em {PASTA_DUMPS} ({nome}.png/.html) -- "
            f"url atual: {driver.current_url}")
    except Exception as exc:
        log(f"  [AVISO] Falha ao salvar dump de diagnostico: {exc}")


def _verificar_processo_correto(driver, processo, contexto, log=print):
    """Confere se o numero do processo esperado aparece na pagina atual logo
    apos buscar_processo(). Visto em producao: a busca as vezes abre um
    processo diferente do digitado (ex: sugestao de autocomplete/historico da
    conta) -- sem essa checagem, o sintoma so aparece bem mais na frente como
    um timeout de 60s em remeter_processo, sem indicar a causa. Numero de
    processo tem 20 digitos (padrao CNJ), entao um match de substring nos
    digitos da pagina e confiavel o bastante para nao dar falso positivo."""
    numero_limpo = re.sub(r"\D", "", processo)
    if numero_limpo and numero_limpo not in re.sub(r"\D", "", driver.page_source):
        log(f"  [AVISO] Apos buscar_processo ({contexto}): processo esperado "
            f"({processo}) nao aparece na pagina -- abriu o processo errado. "
            f"Salvando dump e abortando o passo (nao pode seguir mexendo num "
            f"processo que nao e o esperado).")
        _dump_diagnostico(driver, f"processo_errado_{contexto}_{int(time.time())}", log=log)
        raise ValueError(
            f"buscar_processo ({contexto}) abriu processo diferente do esperado ({processo})"
        )


def _com_retry_uma_vez(passos, driver, nome_dump, log=print, tentativas=3, pausa=5):
    """Executa `passos` (lista de callables, em sequencia); se qualquer um
    lancar excecao, salva diagnostico e tenta a sequencia inteira de novo (ate
    `tentativas` vezes, com pausa entre elas) -- o hml tem hiccups de
    renderer/rede que podem levar mais de uma tentativa extra para passar."""
    ultimo_exc = None
    for i in range(tentativas):
        try:
            for passo in passos:
                passo()
            return
        except Exception as exc:
            ultimo_exc = exc
            log(f"  [AVISO] Falha em '{nome_dump}' (tentativa {i + 1}/{tentativas}): {exc}")
            _dump_diagnostico(driver, f"falha_{nome_dump}_tentativa{i + 1}", log=log)
            if i + 1 < tentativas:
                time.sleep(pausa)
    raise ultimo_exc


def login(driver, wait, usuario, senha, url, log=print, limpar_sessao=False):
    if limpar_sessao:
        # Limpa cookies antes de reabrir a pagina de login -- forca o
        # servidor a criar uma sessao nova em vez de reaproveitar a sessao
        # antiga (que pode estar presa num estado quebrado do lado do
        # servidor, ex: o erro de Redis visto em producao). So usado no
        # relogin de recuperacao (_com_relogin_automatico); o primeiro login
        # da execucao nao precisa disso.
        try:
            driver.delete_all_cookies()
        except Exception:
            pass
    _get_resiliente(driver, url, log=log)
    try:
        _cotri.fazer_login(driver, wait, usuario, senha)
    except TimeoutException:
        log("  [AVISO] Formulario de login nao apareceu -- salvando diagnostico e tentando recarregar 1x.")
        _dump_diagnostico(driver, "falha_login_1a_tentativa", log=log)
        _get_resiliente(driver, url, log=log)
        try:
            _cotri.fazer_login(driver, wait, usuario, senha)
        except TimeoutException:
            _dump_diagnostico(driver, "falha_login_2a_tentativa", log=log)
            raise
    time.sleep(1)
    if _cotri.selecionar_perfil(driver, PERFIL_GERENTE_USUARIOS):
        log(f"  [OK] Perfil '{PERFIL_GERENTE_USUARIOS}' selecionado apos login.")
    else:
        log("  [INFO] Tela de selecao de perfil nao apareceu (ja entrou logado num perfil).")


def trocar_perfil(driver, wait, texto_visivel_opcao):
    """Troca o perfil/lotacao ativo usando o combobox selInfraUnidades.

    Confirma que a troca realmente aconteceu antes de retornar -- visto em
    producao: select_by_visible_text() + sleep(2) pode retornar sem erro
    mesmo com a troca ainda em andamento (a pagina so recarrega depois do
    onchange disparar mudarPerfil()), e o passo seguinte (buscar processo,
    verificar eventos) acaba rodando com o perfil antigo ainda ativo, sem
    nenhuma excecao ser levantada pra acusar o problema."""
    select_el = wait.until(lambda d: _primeiro_visivel(d, By.ID, "selInfraUnidades"))
    Select(select_el).select_by_visible_text(texto_visivel_opcao)
    time.sleep(2)

    for _ in range(4):
        try:
            select_el = _primeiro_visivel(driver, By.ID, "selInfraUnidades")
            if Select(select_el).first_selected_option.text.strip() == texto_visivel_opcao:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutException(
        f"Perfil nao confirmou troca para '{texto_visivel_opcao}' apos select_by_visible_text"
    )


def _sessao_expirada(driver):
    """Detecta se a sessao caiu e voltou pra tela de login (visto em
    producao: em cadeias longas o eproc as vezes desloga sozinho no meio do
    caminho, sem aviso previo -- so aparece como falha um passo qualquer la
    na frente que nao acha nenhum elemento porque a pagina virou a tela de
    login). Confere os dois campos do formulario de login (txtUsuario/
    pwdSenha) em vez de so um, pra nao dar falso positivo com alguma outra
    tela que por acaso tenha um campo de mesmo nome."""
    try:
        return bool(driver.find_elements(By.ID, "txtUsuario")) and bool(
            driver.find_elements(By.ID, "pwdSenha")
        )
    except Exception:
        return False


def _erro_servidor_eproc(driver):
    """Detecta a pagina de erro fatal do PHP do proprio servidor do eproc
    (visto em producao: ArgumentCountError no construtor do Redis, dentro de
    CacheEproc.php/SessaoEproc -- bug de infra do ambiente hml/dsv do TJMG,
    incompatibilidade entre a extensao PHP Redis instalada e o codigo do
    eproc). Quando essa pagina aparece no lugar da tela esperada, qualquer
    elemento que o codigo procura simplesmente nao existe -- por isso os
    sintomas variados (sessao "caindo", processo "errado", etc.) as vezes sao
    na real esse erro de servidor por baixo."""
    try:
        fonte = driver.page_source
    except Exception:
        return False
    marcadores = ("Fatal error", "ArgumentCountError", "Uncaught")
    return any(m in fonte for m in marcadores)


def _parece_mudanca_perfil(exc):
    """Alerta especifico "acao cancelada devido a mudanca no perfil do
    usuario" -- a propria mensagem do eproc ja informa o perfil ativo, ou
    seja, a sessao continua valida, so o perfil ficou errado. Nao precisa de
    relogin completo, basta forcar a troca de volta pro perfil esperado."""
    return "mudanca no perfil do usuario" in _cotri._normalizar(str(exc))


def _parece_sessao_perdida(driver, exc):
    texto_exc = _cotri._normalizar(str(exc))
    if "sessao" in texto_exc:
        return True
    if _erro_servidor_eproc(driver):
        return True
    return _sessao_expirada(driver)


def _com_relogin_automatico(passo, driver, wait, usuario, senha, url, perfil_texto,
                             log=print, tentativas=4, pausa=5):
    """Roda `passo` (callable sem argumentos) com retry automatico p/
    qualquer tipo de erro -- nao so sessao perdida. A cada falha: salva dump,
    fecha alerta pendente (se houver) e trata 3 casos:
    - alerta de "mudanca no perfil do usuario": a mensagem do proprio eproc
      ja confirma que a sessao continua valida, so o perfil ativo mudou --
      forca so a troca de volta pro perfil indicado, sem relogar;
    - sessao perdida de verdade (deslogado sozinho, "sessao encerrada", ou a
      pagina de erro fatal do servidor do eproc): reloga do zero e troca de
      volta pro perfil indicado antes de tentar de novo -- da mais chance de
      recuperar de um erro intermitente do lado do servidor (ex: Redis
      reconectando) do que so re-tentar a mesma pagina quebrada;
    - falhas "normais" (timeout, elemento nao encontrado sem pagina de erro):
      so tentam de novo sem relogar, ja que a pagina pode so estar lenta.
    So propaga a excecao (deixando o chamador decidir, ex: FalhaCritica) se
    todas as `tentativas` esgotarem."""
    ultimo_exc = None
    for i in range(tentativas):
        try:
            return passo()
        except Exception as exc:
            ultimo_exc = exc
            log(f"  [AVISO] Falha (tentativa {i + 1}/{tentativas}): {exc}")
            try:
                driver.switch_to.alert.accept()
            except Exception:
                pass
            sessao_perdida = _parece_sessao_perdida(driver, exc)
            mudanca_perfil = _parece_mudanca_perfil(exc)
            _dump_diagnostico(driver, f"retry_falha_tentativa{i + 1}_{int(time.time())}", log=log)
            if mudanca_perfil and not sessao_perdida:
                log("  [AVISO] Alerta de mudanca de perfil -- forcando volta para "
                    f"'{perfil_texto}' antes de tentar de novo.")
                try:
                    trocar_perfil(driver, wait, perfil_texto)
                except Exception as exc_perfil:
                    log(f"  [AVISO] Forcar perfil falhou: {exc_perfil}")
                if i + 1 < tentativas:
                    time.sleep(pausa)
            elif sessao_perdida:
                log("  [AVISO] Sessao parece ter caido (ou erro de servidor do eproc) -- "
                    "esperando um pouco e relogando...")
                time.sleep(pausa)
                try:
                    login(driver, wait, usuario, senha, url, log=log, limpar_sessao=True)
                    trocar_perfil(driver, wait, perfil_texto)
                except Exception as exc_relogin:
                    log(f"  [AVISO] Relogin tambem falhou: {exc_relogin}")
            else:
                if i + 1 < tentativas:
                    time.sleep(pausa)
                # Mesmo sem sessao perdida, reafirma o perfil antes de tentar
                # de novo: `passo` pode ser um bloco de varios passos (ex: a
                # remessa completa, que troca pro perfil GERENTE DE USUARIOS
                # no meio pra cadastrar lotacao) -- se a falha aconteceu apos
                # essa troca, um retry que so re-roda `passo` do inicio fica
                # preso no perfil errado (visto em producao: 4 tentativas
                # seguidas travando com o perfil ainda em "GERENTE DE
                # USUARIOS" em vez do perfil do orgao).
                try:
                    select_el = _primeiro_visivel(driver, By.ID, "selInfraUnidades")
                    if Select(select_el).first_selected_option.text.strip() != perfil_texto:
                        log(f"  [AVISO] Perfil ativo nao e '{perfil_texto}' -- corrigindo antes de tentar de novo.")
                        trocar_perfil(driver, wait, perfil_texto)
                except Exception:
                    pass
    raise ultimo_exc


def _primeiro_visivel(driver, by, value):
    for el in driver.find_elements(by, value):
        if el.is_displayed():
            return el
    raise NoSuchElementException(f"Nenhum elemento visivel para {by}={value}")


def _clicar(driver, elemento):
    """Clique resiliente: espera o overlay de carregamento (divInfraAvisoFundo)
    sumir e clica via JS (bypassa ElementClickInterceptedException quando o
    overlay ainda cobre o elemento no instante do clique -- comum apos
    trocas de perfil/pagina no eproc-hml)."""
    try:
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.ID, "divInfraAvisoFundo"))
        )
    except TimeoutException:
        pass
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
    driver.execute_script("arguments[0].click();", elemento)


def _fechar_popup_lembretes_se_necessario(driver, log=print):
    """Fecha o popup "Lembretes" que a tela de Movimentar/Intimar as vezes
    abre sozinha (avisos automaticos do processo, ex: pendencia antiga de
    peticao) -- visto em producao travando o bootstrap: o popup fica por
    cima do formulario e bloqueia qualquer clique seguinte ate ser fechado."""
    try:
        botoes = driver.find_elements(
            By.XPATH,
            "//*[self::button or self::a or self::input]"
            "[contains(normalize-space(.), 'Fechar') or @value='Fechar']",
        )
        for botao in botoes:
            if botao.is_displayed():
                log("  [INFO] Fechando popup de Lembretes...")
                driver.execute_script("arguments[0].click();", botao)
                time.sleep(0.5)
    except Exception:
        pass


# ===========================================================================
# Cadastro de Usuarios: garantir/desativar lotacoes
# ===========================================================================

def abrir_cadastro_usuarios(driver, wait):
    # Absorve qualquer alerta pendente de uma acao anterior (ex: confirmacao
    # de inclusao/desativacao de lotacao) -- um alerta aberto bloqueia
    # qualquer find_element/click seguinte com UnexpectedAlertPresentException.
    _cotri.fechar_alerta_silencioso(driver, [])
    usuarios_menu = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//a[contains(normalize-space(.), 'Usuários')]"))
    )
    _clicar(driver, usuarios_menu)
    time.sleep(1)
    cadastro_link = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//a[contains(normalize-space(.), 'Cadastro de Usuários')]"))
    )
    _clicar(driver, cadastro_link)
    time.sleep(1)


def lotacoes_existentes(driver, sigla_usuario):
    # find_element sem espera aqui e uma corrida com o carregamento da tela
    # "Cadastro de Usuarios" (abrir_cadastro_usuarios so da time.sleep(1) apos
    # clicar no link, sem esperar o formulario renderizar) -- visto na
    # pratica: NoSuchElementException instantaneo quando a pagina demora um
    # pouco mais que o normal. WebDriverWait tolera essa variacao.
    sigla_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "txtSiglaOab"))
    )
    sigla_input.clear()
    sigla_input.send_keys(sigla_usuario)

    candidatos = driver.find_elements(
        By.XPATH,
        "//button[contains(normalize-space(.), 'Consultar')] "
        "| //input[@type='submit' and contains(@value, 'Consultar')] "
        "| //a[contains(normalize-space(.), 'Consultar')]",
    )
    consultar_btn = next(b for b in candidatos if b.is_displayed())
    _clicar(driver, consultar_btn)
    time.sleep(2)
    return driver.page_source


# Cache do ultimo mapa {sigla: descricao} lido de selUsuarioOrgao (todos os
# orgaos do tribunal) -- usado por buscar_camaras_renomeadas() para sugerir
# candidatos quando uma camara esperada sumiu (renomeada/reorganizada).
_ULTIMO_MAPA_DESCRICOES = {}


def resolver_valores_orgao(driver, wait, siglas, usuario, exigir_todos=True):
    """Le as options do select #selUsuarioOrgao (todos os orgaos do tribunal)
    e retorna {sigla: value}. Precisa da pagina de Cadastro de Usuarios aberta.

    O select #selUsuarioOrgao so e injetado no DOM depois de uma consulta
    (Sigla + Consultar) -- nao existe no HTML inicial da pagina. Por isso
    reaproveita lotacoes_existentes() aqui para garantir a consulta.

    Se exigir_todos=True (padrao) e algum orgao nao for encontrado, levanta
    ValueError. Se False, retorna so o mapa parcial (sem as siglas faltantes)
    -- usado quando o chamador quer decidir o que fazer com a ausencia (ex:
    pular a camara inteira em vez de travar toda a cadeia)."""
    lotacoes_existentes(driver, usuario)
    select_el = wait.until(EC.presence_of_element_located((By.ID, "selUsuarioOrgao")))
    opcoes = Select(select_el).options

    mapa = {}
    descricoes = {}
    for opcao in opcoes:
        texto = opcao.get_attribute("textContent") or ""
        if " - " not in texto:
            continue
        sigla, descricao = texto.split(" - ", 1)
        sigla = sigla.strip()
        mapa[sigla] = opcao.get_attribute("value")
        descricoes[sigla] = descricao.strip()
    _ULTIMO_MAPA_DESCRICOES.clear()
    _ULTIMO_MAPA_DESCRICOES.update(descricoes)

    faltando = [s for s in siglas if s not in mapa]
    if faltando and exigir_todos:
        raise ValueError(f"Nao encontrei o(s) orgao(s) {faltando} no select selUsuarioOrgao")
    return {sigla: mapa[sigla] for sigla in siglas if sigla in mapa}


def buscar_camaras_renomeadas(camara_sigla):
    """Quando uma camara esperada (ex: '4CACIV') nao existe mais no select
    selUsuarioOrgao, procura no mapa de descricoes (todos os orgaos do
    tribunal, cacheado por resolver_valores_orgao) por candidatos cuja
    descricao contenha 'camara civel' + o numero ordinal da camara -- ajuda a
    descobrir renomeacoes/reorganizacoes (foi assim que se descobriu que
    4CACIV/8CACIV viraram 4CACIVEsp/8CACIVEsp com assentos 'NCACIVESP-AN').
    Retorna lista de (sigla, descricao) candidatos; vazia se nada achado ou
    se resolver_valores_orgao ainda nao rodou nesta sessao."""
    m = re.match(r"(\d+)CACIV", camara_sigla, re.IGNORECASE)
    if not m:
        return []
    numero = m.group(1)
    candidatos = []
    for sigla, descricao in _ULTIMO_MAPA_DESCRICOES.items():
        desc_norm = _cotri._normalizar(descricao)
        if "camara civel" in desc_norm and re.search(rf"\b{numero}\b", desc_norm):
            candidatos.append((sigla, descricao))
    return candidatos


def garantir_lotacao(driver, wait, sigla_usuario, orgao, dry_run=False, log=print):
    """Garante lotacao GERENTE GABINETE/SECRETARIA em orgao. Retorna True se
    incluida nesta chamada, False se ja existia (ou se dry_run impediu)."""
    abrir_cadastro_usuarios(driver, wait)
    html = lotacoes_existentes(driver, sigla_usuario)

    descricao_lotacao = orgao["descricao"].split(" - ", 1)[-1]
    marcador = f"', ' - {descricao_lotacao}', 'GERENTE GABINETE/SECRETARIA'"
    if marcador in html:
        log(f"  [OK] Ja possui lotacao em {orgao['sigla']}")
        return False

    log(f"  [INCLUIR] Lotacao ausente em {orgao['sigla']} -> incluindo...")
    if dry_run:
        log("  [DRY_RUN] Inclusao nao executada.")
        return False

    Select(driver.find_element(By.ID, "selUsuarioTipo")).select_by_value(TIPO_USUARIO_GERENTE_SECRETARIA)
    time.sleep(1)

    Select(driver.find_element(By.ID, "selUsuarioUf")).select_by_value(UF_PADRAO)
    time.sleep(1)

    Select(driver.find_element(By.ID, "selUsuarioOrgao")).select_by_value(orgao["orgao_valor"])
    time.sleep(1)

    _clicar(driver, driver.find_element(By.ID, "btnMultiLotacaoAdd"))
    time.sleep(1)

    # O alerta pode vir sincronamente ja no click do Incluir (nao so depois),
    # por isso o try/except: sem isso, UnexpectedAlertPresentException
    # propagaria direto do proprio clique.
    try:
        _clicar(driver, driver.find_element(By.ID, "btnIncUsu"))
        alerta = wait.until(EC.alert_is_present())
        texto_alerta = alerta.text
    except UnexpectedAlertPresentException as exc:
        texto_alerta = exc.alert_text or str(exc)
        try:
            driver.switch_to.alert.accept()
        except Exception:
            pass
    else:
        alerta.accept()

    log(f"  [ALERT] {texto_alerta}")
    time.sleep(2)

    if "ja existe" in _cotri._normalizar(texto_alerta):
        log(f"  [OK] Lotacao em {orgao['sigla']} ja existia (alerta de duplicidade -- "
            f"provavelmente sobra de execucao antiga; nao sera desativada ao final).")
        return False

    log(f"  [INCLUIDO] Lotacao {orgao['sigla']} incluida.")
    return True


def desativar_lotacao(driver, wait, sigla_usuario, orgao, log=print):
    """Desativa a lotacao GERENTE GABINETE/SECRETARIA de orgao para sigla_usuario."""
    abrir_cadastro_usuarios(driver, wait)
    lotacoes_existentes(driver, sigla_usuario)
    _cotri.fechar_alerta_silencioso(driver, [])

    descricao_lotacao = orgao["descricao"].split(" - ", 1)[-1]
    xpath_btn = (
        f"//tr[.//td[contains(normalize-space(),'{descricao_lotacao}')]]"
        f"//img[contains(@src,'desativar_vermelho')]/.."
    )
    try:
        btn = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xpath_btn)))
    except TimeoutException:
        log(f"  [AVISO] Lotacao em {orgao['sigla']} nao encontrada para remover.")
        return False

    _clicar(driver, btn)
    _cotri.fechar_alerta_silencioso(driver, [])
    time.sleep(1)
    log(f"  [REMOVIDO] Lotacao {orgao['sigla']} removida.")
    return True


# ===========================================================================
# Processo: busca, verificacao de eventos, remessa
# ===========================================================================

def buscar_processo(driver, wait, numero_processo):
    """Reaproveita _cotri.pesquisar_processo -- ja usa o campo de busca rapida
    com foco/clear via JS e um botao de submit dedicado (btnPesquisaRapidaSubmit)
    em vez de so Enter, e confirma o resultado antes de seguir
    (_aguardar_resultado_pesquisa). Muito mais robusto que reimplementar aqui:
    o clique/Enter isolado se mostrou nao-confiavel a partir de certas
    paginas (ex: Painel do Diretor de Secretaria)."""
    base = driver.current_url.split("/controlador.php")[0].rstrip("/") + "/"
    _cotri.pesquisar_processo(driver, base, numero_processo)
    # Espera a tabela de eventos do processo aparecer de verdade em vez de um
    # sleep fixo -- visto em producao: um dump tirado logo apos a busca podia
    # pegar a pagina com o <body> ainda vazio (title certo, conteudo nao),
    # fazendo passos seguintes (ex: ler o orgao atual, _verificar_processo_correto)
    # falharem por timing, nao por a pagina estar realmente errada.
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "tblEventos")))
    except TimeoutException:
        time.sleep(1)


def _orgao_atual_do_processo(driver):
    """Le a tabela de eventos do processo (tblEventos, mesma pagina aberta
    por buscar_processo) e retorna a sigla do orgao de destino do evento mais
    recente do tipo "Remetidos os Autos ... - ORIGEM -> DESTINO" -- fonte mais
    confiavel de onde o processo esta agora do que inferir pela presenca/
    ausencia do botao "Movimentar Processo" (que pode falhar por timing/
    instabilidade de pagina em vez de refletir posse real, como visto em
    producao com paginas que carregam com o body ainda vazio). A tabela vem
    ordenada do evento mais recente pro mais antigo, entao basta pegar a
    primeira linha que for uma remessa."""
    try:
        linhas = driver.find_elements(By.CSS_SELECTOR, "#tblEventos tbody tr")
    except Exception:
        return ""
    for linha in linhas:
        try:
            desc = linha.find_element(By.CSS_SELECTOR, "td.infraEventoDescricao").text
        except NoSuchElementException:
            continue
        if "Remetidos os Autos" not in desc:
            continue
        match = re.search(r"->\s*(\S+)\s*$", desc.strip())
        return match.group(1).strip() if match else ""
    return ""


def abrir_movimentar(driver, wait):
    movimentar_btn = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//a[contains(@class, 'infraButton') and contains(normalize-space(.), 'Movimentar Processo')]",
        ))
    )
    _clicar(driver, movimentar_btn)
    time.sleep(2)
    _fechar_popup_lembretes_se_necessario(driver)


def abrir_intimar(driver, wait):
    intimar_btn = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//a[contains(@class, 'infraButton') and contains(normalize-space(.), 'Intimar')]",
        ))
    )
    _clicar(driver, intimar_btn)
    time.sleep(2)
    _fechar_popup_lembretes_se_necessario(driver)


def verificar_eventos(driver, wait, eventos_alvo):
    """Busca cada evento em eventos_alvo individualmente no autocomplete de
    "Evento a ser lancado" -- nao da pra reaproveitar uma unica busca fixa
    porque, desde que a lista de eventos ficou editavel na tela, um evento
    digitado pode nao compartilhar prefixo nenhum com os outros (uma busca
    so encontraria eventos que combinem com o texto digitado nela)."""
    resultado = {}
    for evento in eventos_alvo:
        txt_evento = wait.until(EC.presence_of_element_located((By.ID, "txtEvento")))
        _clicar(driver, txt_evento)
        txt_evento.send_keys(Keys.CONTROL + "a")
        txt_evento.send_keys(evento)
        time.sleep(1.5)

        sugestoes = []
        try:
            container = driver.find_element(By.ID, "divInfraAjaxtxtEvento")
            sugestoes = [a.text.strip() for a in container.find_elements(By.TAG_NAME, "a")]
        except NoSuchElementException:
            pass

        resultado[evento] = any(evento in s for s in sugestoes)
        txt_evento.send_keys(Keys.ESCAPE)
        time.sleep(0.3)
    return resultado


def listar_eventos_intimar(driver, wait):
    """Le todas as <option> do select fixo #selEventoJudicial da tela de
    Intimar e retorna {evento: True} com o inventario completo disponivel
    para o orgao atual (opcao em branco excluida). Ao contrario do
    Movimentar Processo (autocomplete, exige digitar um texto-alvo), aqui
    nao ha lista pre-definida a buscar -- o campo de eventos-alvo da tela
    nao e usado para Intimar: o interesse e descobrir tudo que o orgao tem
    disponivel."""
    select_el = wait.until(EC.presence_of_element_located((By.ID, "selEventoJudicial")))
    opcoes = [o.text.strip() for o in Select(select_el).options]
    return {opcao: True for opcao in opcoes if opcao}


def formatar_eventos(eventos):
    faltando = [e for e, achou in eventos.items() if not achou]
    total = len(eventos)
    if not faltando:
        return f"OK ({total}/{total})"
    return f"FALTAM {len(faltando)}/{total}: " + "; ".join(faltando)


def _resolver_valor_no_select(select_el, sigla_alvo):
    """Le as options de um <select> (formato 'SIGLA - descricao') e retorna o
    value cuja sigla bate com sigla_alvo. Necessario porque #selOrgao (tela de
    Movimentar processo) e #selUsuarioOrgao (Cadastro de Usuarios) sao selects
    diferentes -- nao ha garantia de que usem os mesmos IDs de value para o
    mesmo orgao (confirmado em producao: reaproveitar o value de um no outro
    ou lanca NoSuchElementException, ou -- pior -- pode bater por coincidencia
    num value de um orgao errado, selecionando o destino errado sem nenhum
    erro visivel). O valor tem que ser lido do proprio select de destino."""
    for opcao in Select(select_el).options:
        texto = opcao.get_attribute("textContent") or ""
        if " - " not in texto:
            continue
        sigla, _ = texto.split(" - ", 1)
        if sigla.strip() == sigla_alvo:
            return opcao.get_attribute("value")
    raise NoSuchElementException(f"Orgao '{sigla_alvo}' nao encontrado no select de destino (selOrgao)")


def remeter_processo(driver, wait, orgao_destino_sigla):
    txt_evento = wait.until(EC.presence_of_element_located((By.ID, "txtEvento")))
    _clicar(driver, txt_evento)
    txt_evento.send_keys(Keys.CONTROL + "a")
    txt_evento.send_keys("Remetidos os Autos")
    time.sleep(1.5)

    opcao_generica = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//div[@id='divInfraAjaxtxtEvento']//a[starts-with(normalize-space(.), 'Remetidos os Autos (')]",
        ))
    )
    # Clique NATIVO (nao _clicar/JS): esse widget de autocomplete escuta
    # mousedown, nao um evento "click" sintetico -- um clique via JS nao
    # preenche txtEvento/hdnEvento (confirmado por dump: autocomplete
    # mostrava a sugestao certa, mas o campo ficava vazio apos "clicar").
    opcao_generica.click()
    time.sleep(1)

    select_orgao = wait.until(EC.presence_of_element_located((By.ID, "selOrgao")))
    valor_destino = _resolver_valor_no_select(select_orgao, orgao_destino_sigla)
    Select(select_orgao).select_by_value(valor_destino)
    time.sleep(1)

    # Confirma que o orgao selecionado e mesmo o esperado antes de submeter --
    # select_by_value ja garante isso na pratica (o value veio do proprio
    # select), mas o custo de checar de novo aqui e minimo e evita qualquer
    # duvida antes de uma acao irreversivel (remessa real do processo).
    texto_selecionado = Select(select_orgao).first_selected_option.get_attribute("textContent") or ""
    if not texto_selecionado.strip().startswith(orgao_destino_sigla):
        raise ValueError(
            f"selOrgao ficou selecionado em '{texto_selecionado.strip()}', "
            f"esperado orgao '{orgao_destino_sigla}' -- abortando antes de remeter."
        )

    _clicar(driver, wait.until(EC.element_to_be_clickable((By.ID, "sbmMovimentar"))))
    time.sleep(2)


# ===========================================================================
# Loop principal (compartilhado entre modo camara-unica e cadeia-completa)
# ===========================================================================

def percorrer_cadeia(driver, wait, cadeia, resultados, incluidas_nesta_execucao,
                      processo, dry_run, garantir_lotacoes, usuario, senha, url,
                      log=print, eventos_alvo=None,
                      checar_movimentar=True, checar_intimar=True):
    """Percorre cadeia verificando eventos e remetendo o processo entre os
    orgaos. Falhas de verificacao viram linha de erro no relatorio (segue em
    frente); falha na remessa/lotacao do proximo orgao levanta FalhaCritica
    (posse do processo fica ambigua -- nao da pra continuar com seguranca).

    eventos_alvo: lista de eventos a verificar; None usa o padrao EVENTOS_ALVO.
    checar_movimentar/checar_intimar: qual(is) tela(s) usar para verificar
    cada evento de eventos_alvo -- pelo menos uma precisa ficar True."""
    eventos_alvo = eventos_alvo if eventos_alvo else EVENTOS_ALVO
    for i, orgao in enumerate(cadeia):
        perfil_texto = f"{orgao['sigla']}/GERENTE GABINETE/SECRETARIA"
        log(f"\n=== Verificando {orgao['sigla']} ({orgao.get('camara', '')}) ===")

        try:
            _com_relogin_automatico(
                lambda: trocar_perfil(driver, wait, perfil_texto),
                driver, wait, usuario, senha, url, perfil_texto, log=log,
            )
        except (TimeoutException, NoSuchElementException, UnexpectedAlertPresentException) as exc:
            log(f"  [ERRO] Nao foi possivel trocar para o perfil {perfil_texto}: {exc}")
            resultados.append({"orgao": orgao["sigla"], "camara": orgao.get("camara", ""),
                                "erro": f"perfil indisponivel: {exc}"})
            continue

        try:
            linha = {"orgao": orgao["sigla"], "camara": orgao.get("camara", ""), "processo": processo}

            if checar_movimentar:
                def _checar_movimentar():
                    buscar_processo(driver, wait, processo)
                    _verificar_processo_correto(driver, processo, f"verificar_movimentar_{orgao['sigla']}", log=log)
                    abrir_movimentar(driver, wait)
                    return verificar_eventos(driver, wait, eventos_alvo)

                eventos_mov = _com_relogin_automatico(
                    _checar_movimentar, driver, wait, usuario, senha, url, perfil_texto, log=log,
                )
                log(f"  Eventos (Movimentar): {formatar_eventos(eventos_mov)}")
                for evento, achou in eventos_mov.items():
                    linha[f"{evento} [Movimentar]"] = achou

            if checar_intimar:
                # Checagem de Intimar isolada: se a tela/botao nao existir
                # nesse orgao (ex: permissao), o resultado do Movimentar
                # acima nao se perde -- so fica sem as colunas de Intimar
                # nessa linha.
                def _checar_intimar():
                    buscar_processo(driver, wait, processo)
                    _verificar_processo_correto(driver, processo, f"verificar_intimar_{orgao['sigla']}", log=log)
                    abrir_intimar(driver, wait)
                    return listar_eventos_intimar(driver, wait)

                try:
                    eventos_int = _com_relogin_automatico(
                        _checar_intimar, driver, wait, usuario, senha, url, perfil_texto, log=log,
                    )
                    log(f"  Eventos (Intimar): {len(eventos_int)} evento(s) disponivel(is)")
                    for evento, achou in eventos_int.items():
                        linha[f"{evento} [Intimar]"] = achou
                except Exception as exc:
                    log(f"  [AVISO] Falha ao verificar eventos via Intimar em {orgao['sigla']}: {exc}")

            resultados.append(linha)
        except Exception as exc:
            log(f"  [ERRO] Falha nao critica ao verificar eventos em {orgao['sigla']}: {exc}")
            try:
                driver.save_screenshot(str(PASTA_DUMPS / f"falha_{orgao['sigla']}.png"))
            except Exception:
                pass
            resultados.append({"orgao": orgao["sigla"], "camara": orgao.get("camara", ""),
                                "erro": f"verificacao falhou: {exc}"})

        proximo = cadeia[i + 1] if i + 1 < len(cadeia) else None
        if not proximo:
            continue

        log(f"  Remetendo processo para {proximo['sigla']}...")
        if dry_run:
            log("  [DRY_RUN] Remessa nao executada.")
            continue

        def _fazer_remessa():
            # Reabre Movimentar explicitamente -- nao da pra confiar que a
            # tela ja esta aberta: se so "Intimar" estiver marcado na
            # verificacao, o navegador fica na tela de Intimar, nao na de
            # Movimentar, que e o que remeter_processo precisa.
            buscar_processo(driver, wait, processo)
            _verificar_processo_correto(driver, processo, f"remessa_para_{proximo['sigla']}", log=log)
            # Se um retry cair aqui (ex: apos o alerta de "mudanca no perfil
            # do usuario" durante o cadastro de lotacao abaixo), a remessa
            # deste mesmo processo pode ja ter sido feita com sucesso antes
            # do alerta -- reroda-la de novo duplicaria a movimentacao no
            # eproc. Confere pelo ultimo evento "Remetidos os Autos" da
            # propria tabela de eventos do processo -- fonte confiavel de
            # onde ele esta agora -- antes de decidir se remete de novo.
            orgao_atual = _orgao_atual_do_processo(driver)
            if orgao_atual == proximo["sigla"]:
                log(f"  [AVISO] Ultimo evento do processo mostra que ja esta em "
                    f"{proximo['sigla']} -- pulando remessa e so garantindo a lotacao.")
            else:
                # Fallback: se a tabela de eventos nao confirmar (ex: layout
                # diferente, tabela vazia), cai no sinal indireto de sempre --
                # "Movimentar Processo" exige posse do processo no perfil de
                # origem; se o processo ja saiu de orgao['sigla'], o botao
                # nao aparece mais.
                try:
                    abrir_movimentar(driver, wait)
                except TimeoutException:
                    log(f"  [AVISO] 'Movimentar Processo' nao encontrado em {orgao['sigla']} -- "
                        f"processo provavelmente ja foi remetido para {proximo['sigla']} "
                        "nesta mesma execucao; pulando remessa e so garantindo a lotacao.")
                else:
                    remeter_processo(driver, wait, proximo["sigla"])
            if garantir_lotacoes:
                log(f"  Auto-cadastrando lotacao em {proximo['sigla']} (se necessario)...")
                trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)
                if garantir_lotacao(driver, wait, USUARIO_ATUAL[0], proximo, dry_run=dry_run, log=log):
                    incluidas_nesta_execucao.append(proximo)

        try:
            _com_relogin_automatico(_fazer_remessa, driver, wait, usuario, senha, url, perfil_texto, log=log)
        except Exception as exc:
            log(f"  [FALHA CRITICA] Remessa/lotacao para {proximo['sigla']} falhou: {exc}")
            try:
                driver.save_screenshot(str(PASTA_DUMPS / "falha_critica.png"))
                with open(PASTA_DUMPS / "falha_critica.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except Exception:
                pass
            raise FalhaCritica(
                f"Parou em '{orgao['sigla']}' (camara {orgao.get('camara', '')}) "
                f"tentando remeter para '{proximo['sigla']}': {exc}"
            ) from exc


# Usado por percorrer_cadeia para saber a sigla do usuario sem mudar a
# assinatura em todo o resto da cadeia de chamadas (definido em cada execucao).
USUARIO_ATUAL = [None]


def gerar_relatorio(resultados, log=print):
    os.makedirs(PASTA_RELATORIOS, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_json = PASTA_RELATORIOS / f"relatorio_eventos_{timestamp}.json"
    nome_csv = PASTA_RELATORIOS / f"relatorio_eventos_{timestamp}.csv"

    with open(nome_json, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    campos = sorted({chave for linha in resultados for chave in linha.keys()})
    with open(nome_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for linha in resultados:
            writer.writerow(linha)

    log(f"\nRelatorio gerado: {nome_json} / {nome_csv}")
    return str(nome_json), str(nome_csv)


# ===========================================================================
# Execucao: camara unica ou cadeia completa (todas as camaras)
# ===========================================================================

def executar_camara_unica(camara_alvo, num_processo, usuario, senha, url,
                           orgao_inicial_index=0, dry_run=False, garantir_lotacoes=True,
                           limpar_lotacoes_ao_final=True, headless=True, log=print, eventos_alvo=None,
                           checar_movimentar=True, checar_intimar=True):
    USUARIO_ATUAL[0] = usuario
    driver, wait = criar_driver(headless=headless)
    resultados = []
    cadeia = carregar_camara(camara_alvo, log=log)[orgao_inicial_index:]
    for orgao in cadeia:
        orgao["camara"] = camara_alvo

    try:
        login(driver, wait, usuario, senha, url, log=log)
        _com_retry_uma_vez(
            [lambda: trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)],
            driver, "trocar_perfil_apos_login", log=log,
        )
        try:
            abrir_cadastro_usuarios(driver, wait)
            valores = resolver_valores_orgao(driver, wait, [o["sigla"] for o in cadeia], usuario)
        except TimeoutException:
            log("  [AVISO] Cadastro de Usuarios nao carregou a tempo -- salvando diagnostico e tentando 1x de novo.")
            _dump_diagnostico(driver, "falha_cadastro_usuarios_1a_tentativa", log=log)
            trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)
            abrir_cadastro_usuarios(driver, wait)
            valores = resolver_valores_orgao(driver, wait, [o["sigla"] for o in cadeia], usuario)
        for orgao in cadeia:
            orgao["orgao_valor"] = valores[orgao["sigla"]]

        incluidas_nesta_execucao = []
        if garantir_lotacoes:
            if garantir_lotacao(driver, wait, usuario, cadeia[0], dry_run=dry_run, log=log):
                incluidas_nesta_execucao.append(cadeia[0])

        try:
            percorrer_cadeia(driver, wait, cadeia, resultados, incluidas_nesta_execucao,
                              num_processo, dry_run, garantir_lotacoes, usuario, senha, url,
                              log=log, eventos_alvo=eventos_alvo,
                              checar_movimentar=checar_movimentar, checar_intimar=checar_intimar)
        except FalhaCritica as exc:
            log(f"\n[PARADO] {exc}")

        if limpar_lotacoes_ao_final and incluidas_nesta_execucao and not dry_run:
            log(f"\n=== Limpando lotacoes incluidas nesta execucao ({len(incluidas_nesta_execucao)}) ===")
            trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)
            for orgao in incluidas_nesta_execucao:
                try:
                    desativar_lotacao(driver, wait, usuario, orgao, log=log)
                except Exception as exc:
                    log(f"  [ERRO] Falha ao desativar lotacao em {orgao['sigla']}: "
                        f"{type(exc).__name__}: {exc}")
    finally:
        gerar_relatorio(resultados, log=log)
        _fechar_driver(driver, log=log)

    return resultados


def executar_cadeia_completa(resume_a_partir_de, holder_atual, num_processo,
                              usuario, senha, url,
                              dry_run=False, garantir_lotacoes=True,
                              limpar_lotacoes_ao_final=True, headless=True, log=print,
                              eventos_alvo=None, checar_movimentar=True, checar_intimar=True):
    """holder_atual: {'sigla':..., 'descricao':...} -- quem detem o processo
    HOJE (antes desta execucao). resume_a_partir_de: sigla da 1a camara da
    CAMARA_SEQUENCIA a processar agora (as anteriores ja foram validadas)."""
    USUARIO_ATUAL[0] = usuario
    sequencia = CAMARA_SEQUENCIA[CAMARA_SEQUENCIA.index(resume_a_partir_de):]
    cadeia = carregar_cadeia_completa(sequencia, log=log)

    driver, wait = criar_driver(headless=headless)
    resultados = []

    try:
        login(driver, wait, usuario, senha, url, log=log)
        _com_retry_uma_vez(
            [lambda: trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)],
            driver, "trocar_perfil_apos_login", log=log,
        )
        try:
            abrir_cadastro_usuarios(driver, wait)
            valores = resolver_valores_orgao(driver, wait, [o["sigla"] for o in cadeia], usuario,
                                              exigir_todos=False)
        except TimeoutException:
            log("  [AVISO] Cadastro de Usuarios nao carregou a tempo -- salvando diagnostico e tentando 1x de novo.")
            _dump_diagnostico(driver, "falha_cadastro_usuarios_1a_tentativa", log=log)
            trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)
            abrir_cadastro_usuarios(driver, wait)
            valores = resolver_valores_orgao(driver, wait, [o["sigla"] for o in cadeia], usuario,
                                              exigir_todos=False)

        # Camaras com algum orgao nao encontrado no tribunal (reorganizado/
        # renomeado etc.) sao puladas por inteiro -- uma cadeia parcial
        # quebraria a remessa entre os proprios orgaos da camara. O resto da
        # sequencia continua normalmente.
        camaras_com_falha = {o["camara"] for o in cadeia if o["sigla"] not in valores}
        if camaras_com_falha:
            faltando_por_camara = {
                cam: [o["sigla"] for o in cadeia if o["camara"] == cam and o["sigla"] not in valores]
                for cam in camaras_com_falha
            }
            log(f"  [AVISO] Pulando camara(s) com orgao(s) nao encontrado(s) no tribunal: {faltando_por_camara}")
            for cam in sorted(camaras_com_falha):
                candidatos = buscar_camaras_renomeadas(cam)
                if candidatos:
                    log(f"  [SUGESTAO] '{cam}' pode ter sido renomeada/reorganizada -- "
                        f"candidatos encontrados no tribunal: {candidatos}")
            cadeia = [o for o in cadeia if o["camara"] not in camaras_com_falha]
        for orgao in cadeia:
            orgao["orgao_valor"] = valores[orgao["sigla"]]

        incluidas_nesta_execucao = []

        log(f"\n=== Bootstrap: remetendo de {holder_atual['sigla']} (dono atual) "
            f"para {cadeia[0]['sigla']} ===")
        if dry_run:
            log("  [DRY_RUN] Bootstrap nao executado.")
        else:
            holder_perfil = f"{holder_atual['sigla']}/GERENTE GABINETE/SECRETARIA"
            _com_retry_uma_vez(
                [
                    lambda: trocar_perfil(driver, wait, holder_perfil),
                    lambda: buscar_processo(driver, wait, num_processo),
                    lambda: abrir_movimentar(driver, wait),
                ],
                driver, "bootstrap_busca", log=log,
            )
            try:
                remeter_processo(driver, wait, cadeia[0]["sigla"])
            except Exception as exc:
                try:
                    driver.save_screenshot(str(PASTA_DUMPS / "falha_bootstrap.png"))
                    with open(PASTA_DUMPS / "falha_bootstrap.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                except Exception:
                    pass
                raise FalhaCritica(
                    f"Bootstrap falhou remetendo de {holder_atual['sigla']} para {cadeia[0]['sigla']}: {exc}"
                ) from exc

            if garantir_lotacoes:
                trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)
                if garantir_lotacao(driver, wait, usuario, cadeia[0], dry_run=dry_run, log=log):
                    incluidas_nesta_execucao.append(cadeia[0])

        try:
            percorrer_cadeia(driver, wait, cadeia, resultados, incluidas_nesta_execucao,
                              num_processo, dry_run, garantir_lotacoes, usuario, senha, url,
                              log=log, eventos_alvo=eventos_alvo,
                              checar_movimentar=checar_movimentar, checar_intimar=checar_intimar)
        except FalhaCritica as exc:
            log(f"\n[PARADO] {exc}")

        if limpar_lotacoes_ao_final and incluidas_nesta_execucao and not dry_run:
            log(f"\n=== Limpando lotacoes incluidas nesta execucao ({len(incluidas_nesta_execucao)}) ===")
            trocar_perfil(driver, wait, PERFIL_GERENTE_USUARIOS)
            for orgao in incluidas_nesta_execucao:
                try:
                    desativar_lotacao(driver, wait, usuario, orgao, log=log)
                except Exception as exc:
                    log(f"  [ERRO] Falha ao desativar lotacao em {orgao['sigla']}: "
                        f"{type(exc).__name__}: {exc}")
    finally:
        gerar_relatorio(resultados, log=log)
        _fechar_driver(driver, log=log)

    return resultados


# ===========================================================================
# GUI — embutivel no AURA Principal (mesmo padrao do AURA COTRI)
# ===========================================================================

COR_BG = _cotri.COR_BG
COR_PAINEL = _cotri.COR_PAINEL
COR_BORDA = _cotri.COR_BORDA
COR_PRIMARIA = _cotri.COR_PRIMARIA
COR_HOVER = _cotri.COR_HOVER
COR_SUCESSO = _cotri.COR_SUCESSO
COR_AVISO = _cotri.COR_AVISO
COR_ERRO = _cotri.COR_ERRO
COR_TEXTO = _cotri.COR_TEXTO
COR_SUBTEXTO = _cotri.COR_SUBTEXTO
COR_INPUT_BG = _cotri.COR_INPUT_BG


class AuraEventosApp(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("AURA Eventos Câmara Cível")
        self.configure(fg_color=COR_BG)
        self.geometry("620x760")
        self.minsize(560, 680)

        _cfg = carregar_config()
        self.usuario = (_cfg.get("usuario") or USUARIO_PADRAO).strip()
        self.senha = (_cfg.get("senha") or SENHA_PADRAO).strip()
        self.url = (_cfg.get("url") or URL_PADRAO).strip()
        salvar_config(self.usuario, self.senha, self.url)

        self._executando = False
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="AURA Eventos Câmara Cível",
                     font=ctk.CTkFont("Segoe UI", 22, "bold"),
                     text_color=COR_PRIMARIA).pack(pady=(16, 0))
        ctk.CTkLabel(header, text="Verificação de eventos por gabinete/cartório (eproc2g-hml)",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=COR_SUBTEXTO).pack(pady=(2, 14))

        card = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=10,
                             border_width=1, border_color=COR_BORDA)
        card.pack(padx=20, pady=16, fill="x")

        def campo(label, default=""):
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont("Segoe UI", 9),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=20, pady=(10, 2))
            e = ctk.CTkEntry(card, font=ctk.CTkFont("Segoe UI", 11),
                              fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                              border_color=COR_BORDA, border_width=1,
                              corner_radius=6, height=34)
            if default:
                e.insert(0, default)
            e.pack(fill="x", padx=20)
            return e

        ctk.CTkLabel(card, text="NÚMERO DO PROCESSO DE TESTE", font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        row_processo = ctk.CTkFrame(card, fg_color="transparent")
        row_processo.pack(fill="x", padx=20)
        self.entry_processo = ctk.CTkEntry(row_processo, font=ctk.CTkFont("Segoe UI", 11),
                                            fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                                            border_color=COR_BORDA, border_width=1,
                                            corner_radius=6, height=34)
        self.entry_processo.insert(0, "2811115-06.2026.8.13.0000")
        self.entry_processo.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row_processo, text="🔎", width=34, height=34, corner_radius=6,
                      fg_color=COR_INPUT_BG, hover_color=COR_BORDA, text_color=COR_TEXTO,
                      command=self._buscar_processo_do_banco).pack(side="left", padx=(6, 0))

        self.entry_resume = campo("RETOMAR A PARTIR DA CÂMARA (sequência 1..21CACIV + Esp)", default="2CACIV")
        self.entry_holder = campo("CÂMARA/ÓRGÃO QUE DETÉM O PROCESSO HOJE", default="1CACIV")

        ctk.CTkLabel(card, text="EVENTOS A VERIFICAR EM MOVIMENTAR PROCESSO (um por linha -- "
                                 "não usado por Intimar, que lista tudo automaticamente)",
                     font=ctk.CTkFont("Segoe UI", 9), text_color=COR_SUBTEXTO,
                     anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        self.txt_eventos = ctk.CTkTextbox(card, fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                                           border_color=COR_BORDA, border_width=1, corner_radius=6,
                                           font=ctk.CTkFont("Segoe UI", 10), height=100)
        self.txt_eventos.insert("1.0", "\n".join(EVENTOS_ALVO))
        self.txt_eventos.pack(fill="x", padx=20)

        ctk.CTkLabel(card, text="TELAS A VERIFICAR:",
                     font=ctk.CTkFont("Segoe UI", 9), text_color=COR_SUBTEXTO,
                     anchor="w").pack(fill="x", padx=20, pady=(10, 2))
        row_telas = ctk.CTkFrame(card, fg_color="transparent")
        row_telas.pack(fill="x", padx=20)
        self.chk_check_movimentar = ctk.CTkCheckBox(row_telas, text="Movimentar Processo",
                                                      font=ctk.CTkFont("Segoe UI", 10), text_color=COR_TEXTO)
        self.chk_check_movimentar.select()
        self.chk_check_movimentar.pack(side="left", padx=(0, 20))
        self.chk_check_intimar = ctk.CTkCheckBox(row_telas, text="Intimar",
                                                   font=ctk.CTkFont("Segoe UI", 10), text_color=COR_TEXTO)
        self.chk_check_intimar.select()
        self.chk_check_intimar.pack(side="left")

        self.chk_dry_run = ctk.CTkCheckBox(card, text="Modo dry-run (só verifica, não remete nem inclui lotação)",
                                            font=ctk.CTkFont("Segoe UI", 10), text_color=COR_TEXTO)
        self.chk_dry_run.pack(anchor="w", padx=20, pady=(14, 4))

        self.chk_headless = ctk.CTkCheckBox(card, text="Executar em segundo plano (sem abrir o navegador)",
                                             font=ctk.CTkFont("Segoe UI", 10), text_color=COR_TEXTO)
        self.chk_headless.select()
        self.chk_headless.pack(anchor="w", padx=20, pady=(4, 16))

        self.btn_iniciar = ctk.CTkButton(card, text="▶  INICIAR VERIFICAÇÃO (CADEIA COMPLETA)",
                                          font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                          fg_color=COR_PRIMARIA, hover_color=COR_HOVER,
                                          height=42, corner_radius=8, command=self._iniciar)
        self.btn_iniciar.pack(fill="x", padx=20, pady=(0, 20))

        self.label_status = ctk.CTkLabel(self, text="Pronto.", font=ctk.CTkFont("Segoe UI", 10),
                                          text_color=COR_SUBTEXTO)
        self.label_status.pack(pady=(0, 6))

        self.txt_log = ctk.CTkTextbox(self, fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                                       border_color=COR_BORDA, border_width=1, corner_radius=8,
                                       font=ctk.CTkFont("Consolas", 10))
        self.txt_log.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.txt_log.configure(state="disabled")

    def _log_thread_safe(self, msg):
        self.after(0, lambda: self._append_log(msg))

    def _append_log(self, msg):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", str(msg) + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_status(self, texto, cor=None):
        self.after(0, lambda: self.label_status.configure(text=texto, text_color=cor or COR_SUBTEXTO))

    def _buscar_processo_do_banco(self):
        """Abre uma lista dos processos ajuizados mais recentes (banco AURA,
        Google Sheets) para escolher um numero de processo em vez de digitar
        na mao. Atencao: essa base registra processos AJUIZADOS, nao onde o
        processo esta agora -- confirme que ele realmente esta no orgao
        inicial pretendido antes de usar (ex: 1CACIV-A1) para evitar falha
        logo no primeiro passo da cadeia."""
        try:
            registros = aura_db.ler_processos_ajuizados()
        except Exception as exc:
            messagebox.showerror("AURA Eventos Câmara Cível",
                                  f"Não foi possível consultar o banco AURA:\n\n{exc}")
            return
        if not registros:
            messagebox.showinfo("AURA Eventos Câmara Cível", "Nenhum processo ajuizado encontrado no banco.")
            return

        recentes = list(reversed(registros))[:30]

        jan = ctk.CTkToplevel(self)
        jan.title("Buscar processo do banco AURA")
        jan.geometry("560x420")
        jan.configure(fg_color=COR_BG)
        jan.grab_set()

        ctk.CTkLabel(jan, text="Processos ajuizados mais recentes (clique para usar)",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=COR_TEXTO).pack(pady=(14, 2), padx=16)
        ctk.CTkLabel(jan, text="Atenção: esta base não indica onde o processo está agora -- "
                               "confirme que ele está no órgão inicial pretendido.",
                     font=ctk.CTkFont("Segoe UI", 9), text_color=COR_AVISO,
                     wraplength=520, justify="left").pack(padx=16, pady=(0, 8))

        lista = ctk.CTkScrollableFrame(jan, fg_color=COR_INPUT_BG)
        lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        def escolher(numero):
            self.entry_processo.delete(0, "end")
            self.entry_processo.insert(0, numero)
            jan.destroy()

        for r in recentes:
            numero = (r.get("Processo") or "").strip()
            if not numero:
                continue
            texto = f"{numero}  ·  {r.get('Classe', '')}  ·  {r.get('Competência', '')}  ·  {r.get('Data', '')}"
            ctk.CTkButton(lista, text=texto, anchor="w",
                          font=ctk.CTkFont("Segoe UI", 10), fg_color="transparent",
                          hover_color=COR_BORDA, text_color=COR_TEXTO, height=30,
                          command=lambda n=numero: escolher(n)).pack(fill="x", pady=1)

    def _iniciar(self):
        if self._executando:
            return
        processo = self.entry_processo.get().strip()
        resume_de = self.entry_resume.get().strip()
        holder_sigla = self.entry_holder.get().strip()
        dry_run = bool(self.chk_dry_run.get())
        headless = bool(self.chk_headless.get())
        checar_movimentar = bool(self.chk_check_movimentar.get())
        checar_intimar = bool(self.chk_check_intimar.get())
        eventos_alvo = [linha.strip() for linha in self.txt_eventos.get("1.0", "end").splitlines() if linha.strip()]

        if not (processo and resume_de and holder_sigla):
            messagebox.showerror("AURA Eventos Câmara Cível", "Preencha todos os campos.")
            return
        if resume_de not in CAMARA_SEQUENCIA:
            messagebox.showerror("AURA Eventos Câmara Cível",
                                  f"'{resume_de}' não está na sequência conhecida de câmaras.")
            return
        if checar_movimentar and not eventos_alvo:
            messagebox.showerror("AURA Eventos Câmara Cível",
                                  "Informe ao menos um evento a verificar em Movimentar Processo "
                                  "(ou desmarque essa tela e deixe só Intimar).")
            return
        if not (checar_movimentar or checar_intimar):
            messagebox.showerror("AURA Eventos Câmara Cível",
                                  "Marque ao menos uma tela (Movimentar Processo e/ou Intimar).")
            return

        self._executando = True
        self.btn_iniciar.configure(state="disabled", text="⏳  EXECUTANDO...")
        self._set_status("Executando — isso pode levar horas para a cadeia completa...", COR_AVISO)
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

        threading.Thread(target=self._executar_em_thread,
                          args=(processo, resume_de, holder_sigla, dry_run, headless, eventos_alvo,
                                checar_movimentar, checar_intimar),
                          daemon=True).start()

    def _executar_em_thread(self, processo, resume_de, holder_sigla, dry_run, headless, eventos_alvo,
                             checar_movimentar=True, checar_intimar=True):
        try:
            try:
                camara_holder = next((c for c in carregar_cadeia_completa([holder_sigla])
                                       if c["sigla"] == holder_sigla), None)
            except ValueError:
                # holder_sigla nao e uma camara conhecida em orgaos_caciv.json --
                # o campo aceita tanto camara/cartorio quanto um gabinete
                # especifico (ex: "2CACIV-A2"), que carregar_camara nao acha.
                camara_holder = None
            if camara_holder is None:
                # holder pode ser um gabinete especifico, nao so a camara/cartorio
                camara_holder = {"sigla": holder_sigla, "descricao": holder_sigla}

            resultados = executar_cadeia_completa(
                resume_a_partir_de=resume_de,
                holder_atual=camara_holder,
                num_processo=processo,
                usuario=self.usuario, senha=self.senha, url=self.url,
                dry_run=dry_run, garantir_lotacoes=True,
                limpar_lotacoes_ao_final=True, headless=headless,
                log=self._log_thread_safe, eventos_alvo=eventos_alvo,
                checar_movimentar=checar_movimentar, checar_intimar=checar_intimar,
            )
            erros = [r for r in resultados if "erro" in r]
            self._set_status(f"Concluído: {len(resultados)} órgãos, {len(erros)} com erro.",
                              COR_SUCESSO if not erros else COR_AVISO)
        except Exception as exc:
            logger.exception("Falha na execucao da cadeia completa")
            self._log_thread_safe(f"\n[ERRO FATAL] {exc}")
            self._set_status(f"Erro: {exc}", COR_ERRO)
        finally:
            self.after(0, lambda: self.btn_iniciar.configure(
                state="normal", text="▶  INICIAR VERIFICAÇÃO (CADEIA COMPLETA)"))
            self._executando = False


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.withdraw()
    app = AuraEventosApp(root)
    app.protocol("WM_DELETE_WINDOW", lambda: (app.destroy(), root.destroy()))
    root.mainloop()
