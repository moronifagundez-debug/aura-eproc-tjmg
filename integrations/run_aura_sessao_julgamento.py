"""AURA Sessão de Julgamento — launcher headless da extensão de Chrome.

O acompanhamento em si (extração do painel, diff de estado, detecção de
divergência/votos, notificação) roda dentro da extensão de Chrome em
extension/ (content.js + background.js) -- ela funciona sozinha em qualquer
Chrome normal onde o consultor abra a tela de "Painel da Sessão de
Julgamento" no eproc.

Este script é só o *launcher* para o modo headless/automatizado: faz login,
navega até a listagem de Sessões de Julgamento, filtra por órgão/data,
localiza a sessão com status "aberta" e abre o painel -- tudo via Selenium,
reaproveitando login/perfil/chromedriver do AURA COTRI (run_aura_cotri.py).
O Chrome é aberto com `--headless=new --load-extension=<extension/>`, e a
extensão passa a rodar sozinha na aba, sem mais nenhuma ação do Python.

Como não há popup acessível em modo headless, os eventos que a extensão
gera (console.log com prefixo "[AURA-EVENTO]"/"[AURA-CICLO]") são lidos via
`driver.get_log('browser')` e repassados para o log da GUI -- por isso é
necessário habilitar `goog:loggingPrefs` no Chrome (feito em criar_driver).

Roda embutido no AURA Principal (AuraSessaoJulgamentoApp) ou standalone:

    python run_aura_sessao_julgamento.py
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

# Modulos compartilhados vivem em shared/ (pasta irma desta, integrations/)
# -- necessario ao rodar este arquivo standalone (import de sibling nao acha
# shared/ sozinho). Quando importado pelo aura.py, ja esta no sys.path, mas
# nao ha problema em inserir de novo.
_DIR_INTEGRATIONS = os.path.dirname(os.path.abspath(__file__))
_DIR_PROJETO = os.path.dirname(_DIR_INTEGRATIONS)
_caminho_shared = os.path.join(_DIR_PROJETO, "shared")
if _caminho_shared not in sys.path:
    sys.path.insert(0, _caminho_shared)

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

import run_aura_cotri as _cotri

logger = logging.getLogger("aura_sessao_julgamento")

VERSAO_ATUAL = "1.0"

OUTPUT_DIR = Path.home() / ".aura_sessao_julgamento"
ARQUIVO_CONFIG = OUTPUT_DIR / "config.json"
PASTA_DUMPS = OUTPUT_DIR / "dumps"

CAMINHO_EXTENSAO = os.path.join(_DIR_PROJETO, "extension")
PASTA_PERFIL_CHROME = OUTPUT_DIR / "chrome_profile"
CAMINHO_CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Este acompanhamento roda contra dados reais de sessao em andamento --
# diferente do AURA COTRI/Eventos (testados em eproc2g-hml), aqui o padrao e
# producao. Usuario/senha/perfil ficam so no config local (fora do git),
# mesmo padrao usado pelos outros modulos (~/.aura_cotri/config.json etc.).
USUARIO_PADRAO = ""
SENHA_PADRAO = ""
URL_PADRAO = "https://eproc2g.tjmg.jus.br/eproc/"

TIMEOUT = 60

# Prefixos que o content.js da extensao usa no console.log -- tem que bater
# com PREFIXO_EVENTO/PREFIXO_CICLO em extension/content.js.
PREFIXO_EVENTO = "[AURA-EVENTO]"
PREFIXO_CICLO = "[AURA-CICLO]"

INTERVALO_LEITURA_LOG_SEGUNDOS = 5


# ===========================================================================
# Configuracao (mesmo padrao dos outros modulos de integrations/)
# ===========================================================================

def salvar_config(usuario, senha, url, perfil=""):
    try:
        os.makedirs(ARQUIVO_CONFIG.parent, exist_ok=True)
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump({"usuario": usuario, "senha": senha, "url": url, "perfil": perfil}, f)
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
# Driver / login -- Chrome com a extensao carregada (funciona headless=new)
# ===========================================================================

def abrir_chrome_para_instalar_extensao():
    """Abre um Chrome NORMAL (fora do Selenium, nao automatizado) apontando
    pro perfil persistente (PASTA_PERFIL_CHROME) direto em
    chrome://extensions/, pra facilitar o passo manual de instalacao unica.

    Confirmado ao vivo que `--load-extension` NUNCA grava a extensao de
    forma persistente no perfil (nao cria entrada em Preferences/Secure
    Preferences) -- e' sempre efemero, mesmo lancado fora de automacao. A
    UNICA forma real de deixar a extensao permanentemente instalada num
    perfil e' pela propria UI do Chrome: "Modo do desenvolvedor" ligado +
    "Carregar sem compactacao" apontando pra pasta -- e isso passa por um
    dialogo nativo do Windows, que nao da pra automatizar via Selenium/CDP
    (dialogos de arquivo do SO ficam fora do processo renderizado do
    Chrome). Por isso esse passo e' manual, uma vez por PC -- exatamente o
    modelo de implantacao real do projeto."""
    os.makedirs(PASTA_PERFIL_CHROME, exist_ok=True)
    subprocess.Popen([
        CAMINHO_CHROME_EXE,
        f"--user-data-dir={PASTA_PERFIL_CHROME}",
        "--no-first-run",
        "--no-default-browser-check",
        "chrome://extensions/",
    ])


def criar_driver(timeout=TIMEOUT, headless=True, carregar_extensao=True, log=print):
    chrome_options = Options()
    chrome_options.add_experimental_option("detach", not headless)
    # Captura console.log da pagina (onde o content.js escreve os eventos)
    # via Selenium 4 -- necessario tanto headless quanto com janela visivel.
    chrome_options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-gpu")
    if carregar_extensao:
        if not os.path.isdir(CAMINHO_EXTENSAO):
            raise FileNotFoundError(
                f"Pasta da extensao nao encontrada em {CAMINHO_EXTENSAO} -- "
                "verifique se extension/ existe na raiz do projeto."
            )
        # --user-data-dir fixo e' o que faz a extensao carregar de verdade
        # em modo automatizado/headless -- ela precisa ja estar instalada
        # NESSE perfil via passo manual (ver abrir_chrome_para_instalar_extensao).
        # `--load-extension` continua incluido como fallback inofensivo (nunca
        # funciona sob automacao, confirmado ao vivo, mas nao atrapalha).
        chrome_options.add_argument(f"--user-data-dir={PASTA_PERFIL_CHROME}")
        chrome_options.add_argument(f"--load-extension={CAMINHO_EXTENSAO}")
        chrome_options.add_argument(f"--disable-extensions-except={CAMINHO_EXTENSAO}")
    driver = _cotri.criar_chrome_driver(chrome_options)
    driver.set_page_load_timeout(timeout)
    wait = WebDriverWait(driver, timeout)
    return driver, wait


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


class FalhaDeLogin(Exception):
    """Login nao autenticou de verdade -- credenciais invalidas/expiradas,
    conta exige certificado digital em vez de usuario/senha, ou bloqueio
    anti-automacao. Melhor abortar cedo e com clareza do que deixar a
    execucao seguir e falhar de forma confusa varios passos depois."""


def login(driver, wait, usuario, senha, url, perfil="", log=print):
    driver.get(url)
    try:
        _cotri.fazer_login(driver, wait, usuario, senha)
    except TimeoutException:
        log("  [AVISO] Formulario de login nao apareceu -- salvando diagnostico e tentando recarregar 1x.")
        _dump_diagnostico(driver, "falha_login_1a_tentativa", log=log)
        driver.get(url)
        _cotri.fazer_login(driver, wait, usuario, senha)
    time.sleep(1)

    # Confere se o login realmente autenticou -- checar so' a URL nao e'
    # confiavel aqui: a tela de "Selecao de perfil" (esperada apos um login
    # bem-sucedido, quando o usuario tem mais de um perfil) e' servida pela
    # MESMA URL-base (externo_controlador.php) da tela de login, entao um
    # check por URL sozinho da falso positivo. O sinal real de falha e' o
    # FORMULARIO de login (campos usuario/senha) continuar presente e
    # visivel na tela -- isso so' acontece se a autenticacao nao passou.
    login_ainda_visivel = bool(
        driver.find_elements(By.ID, "txtUsuario") and driver.find_elements(By.ID, "pwdSenha")
    ) and any(el.is_displayed() for el in driver.find_elements(By.ID, "txtUsuario"))
    if login_ainda_visivel:
        _dump_diagnostico(driver, "falha_autenticacao", log=log)
        raise FalhaDeLogin(
            f"Login nao autenticou -- formulario de usuario/senha ainda visivel ({driver.current_url}). "
            "Confira usuario/senha, ou se essa conta exige Certificado Digital em vez "
            "de usuario/senha para este ambiente."
        )

    if perfil:
        if _selecionar_perfil_por_fragmentos(driver, perfil, log=log):
            log(f"  [OK] Perfil '{perfil}' selecionado apos login (match exato por fragmentos).")
        elif _cotri.selecionar_perfil(driver, perfil):
            log(f"  [OK] Perfil '{perfil}' selecionado apos login (tela de selecao, match por substring).")
        else:
            log(f"  [AVISO] Tela de selecao de perfil nao apresentou opcao compativel com '{perfil}' "
                f"-- tentando trocar via combobox #selInfraUnidades (usuario ja esta logado em algum perfil).")
            if _trocar_perfil_via_combobox(driver, wait, perfil, log=log):
                log(f"  [OK] Perfil '{perfil}' selecionado via combobox.")
            else:
                log(f"  [AVISO] Nao foi possivel trocar para o perfil '{perfil}' por nenhum metodo -- "
                    f"seguindo com o perfil atual (pode faltar acesso a 'Sessão de Julgamento > Consultar').")
    else:
        log("  [INFO] Nenhum perfil especifico informado -- seguindo com o perfil padrao pos-login.")


def _normalizar_fragmento(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", (valor or "").strip().lower())
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


def _fragmentos_perfil(texto: str) -> set:
    """Quebra um texto de perfil em fragmentos separados por '/' (ordem
    ignorada). Necessario porque a tela real de "Selecao de perfil" do eproc
    mostra 'Descricao / Lotacao' (ex: 'GERENTE GABINETE/SECRETARIA / 10CACIV'),
    enquanto o config.json guarda o formato 'Lotacao/Descricao'
    (ex: '10CACIV/GERENTE GABINETE/SECRETARIA') -- comparar por substring
    direta (ordem-dependente) nunca bate. Comparar como conjunto de fragmentos
    resolve a ordem E evita falso-positivo com sufixos tipo '10CACIV-A1'
    (fragmento '10caciv' != '10caciv-a1' quando comparado por igualdade, ao
    contrario de uma checagem de substring)."""
    return {_normalizar_fragmento(f) for f in texto.split("/") if f.strip()}


def _selecionar_perfil_por_fragmentos(driver, perfil: str, log=print) -> bool:
    """Tenta casar o perfil configurado com um botao de 'data-descricao' da
    tela de Selecao de Perfil por igualdade de conjunto de fragmentos
    (ver _fragmentos_perfil). Mais preciso que o matching por substring de
    run_aura_cotri.selecionar_perfil para este caso especifico."""
    alvo = _fragmentos_perfil(perfil)
    if not alvo:
        return False
    try:
        botoes = driver.find_elements(By.XPATH, "//button[@data-descricao]")
        for botao in botoes:
            descricao = botao.get_attribute("data-descricao") or ""
            if _fragmentos_perfil(descricao) == alvo:
                onclick_attr = botao.get_attribute("onclick") or ""
                match = re.search(r"acaoLogar\(['\"](\d+)['\"]\)", onclick_attr)
                if match:
                    driver.execute_script(f"acaoLogar('{match.group(1)}');")
                else:
                    _clicar_nativo(driver, botao)
                time.sleep(3)
                return True
    except Exception as exc:
        log(f"  [AVISO] Match por fragmentos de perfil falhou: {exc}")
    return False


def _trocar_perfil_via_combobox(driver, wait, texto_visivel_opcao, log=print):
    """Troca o perfil/lotacao ativo usando o combobox #selInfraUnidades --
    mesmo padrao usado em run_aura_eventoscamaracivel.py (trocar_perfil).
    Mais confiavel que a tela de selecao pos-login, que pode nao aparecer
    dependendo do usuario/estado da sessao anterior."""
    try:
        select_el = WebDriverWait(driver, 8).until(lambda d: _primeiro_visivel(d, By.ID, "selInfraUnidades"))
        Select(select_el).select_by_visible_text(texto_visivel_opcao)
        time.sleep(2)
        return True
    except Exception as exc:
        log(f"  [AVISO] Falha ao trocar perfil via combobox: {exc}")
        return False


def _primeiro_visivel(driver, by, value):
    for el in driver.find_elements(by, value):
        if el.is_displayed():
            return el
    raise NoSuchElementException(f"Nenhum elemento visivel para {by}={value}")


def _clicar(driver, elemento):
    """Clique resiliente: espera o overlay de carregamento (divInfraAvisoFundo)
    sumir e clica via JS -- mesmo padrao usado em run_aura_eventoscamaracivel.py."""
    try:
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.ID, "divInfraAvisoFundo"))
        )
    except TimeoutException:
        pass
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
    driver.execute_script("arguments[0].click();", elemento)


# ===========================================================================
# Navegacao ate a listagem de Sessoes de Julgamento e abertura do painel
# ===========================================================================

def navegar_para_listagem_sessoes(driver, wait, log=print):
    """Abre o menu lateral, clica em 'Sessão de Julgamento' e depois em
    'Cronograma de Sessões de Julgamento' -- confirmado ao vivo (dump real
    do submenu em homologacao) que e' esse o rotulo do item que leva pra
    `acao=sessao_julgamento_listar`, a mesma tela/action usada na validacao
    manual em producao na Fase 0. (Rotulos anteriormente assumidos,
    'Consultar'/'Sessões de Hoje', nunca existiram nesse submenu -- eram um
    chute nao validado.) O submenu tem so' 4 itens pra este perfil
    (Calendário, Cronograma de Sessões de Julgamento, Cronograma Padrão,
    Solicitações de Sustentação ou Preferência) -- o filtro real de
    Órgão/datas com o botão "Consultar" fica DENTRO dessa tela de listagem,
    nao no menu (ver `filtrar_orgao_e_datas`).

    Usa clique NATIVO (_clicar_nativo) em vez do clique via JS (_clicar) --
    o toggle do menu lateral e os itens dele so respondem a clique
    confiavel, mesmo padrao ja confirmado em varios outros widgets do eproc
    (abas do painel, sub-abas internas).

    IMPORTANTE: o container `#wrapper` do eproc ja vem com a classe
    `abre-automaticamente` -- ou seja, a sidebar normalmente JA esta aberta
    em viewport desktop. Por isso tentamos clicar direto no item "Sessão de
    Julgamento" PRIMEIRO; so' clicamos no `menu-btn` (hamburguer) se isso
    falhar. Clicar no `menu-btn` incondicionalmente (comportamento antigo)
    tende a FECHAR a sidebar ja aberta, deixando o item seguinte fora da
    area interativa (`ElementNotInteractableException` confirmado ao vivo)."""

    def _achar_e_clicar_item_sessao(timeout):
        item = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(normalize-space(.), 'Sessão de Julgamento')]"))
        )
        _clicar_nativo(driver, item)

    try:
        _achar_e_clicar_item_sessao(5)
    except Exception:
        log("  [INFO] Item 'Sessão de Julgamento' nao interativel de primeira -- abrindo menu lateral via menu-btn.")
        menu_btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//a[@id='menu-btn' or @aria-label='Abrir menu' or @title='Abrir menu']"
        )))
        _clicar_nativo(driver, menu_btn)
        time.sleep(0.5)
        _achar_e_clicar_item_sessao(10)
    time.sleep(0.5)

    link_cronograma = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//a[contains(@href, 'acao=sessao_julgamento_listar') "
            "or contains(normalize-space(.), 'Cronograma de Sessões de Julgamento')]"
        ))
    )
    _clicar_nativo(driver, link_cronograma)
    time.sleep(1.5)


def filtrar_orgao_e_datas(driver, wait, orgao_descricao, data_inicial=None, data_final=None, log=print):
    """Preenche o filtro de Órgão e o intervalo de datas na tela de listagem
    de sessoes, e clica em Consultar.

    O campo Órgão (`#selOrgao`) e' um `<select>` real por baixo de um
    widget bootstrap-select (confirmado via dump real da tela em
    homologacao) -- NAO um `<input>` de autocomplete como o codigo antigo
    assumia (por isso o XPath `label/following::input` nunca achava o
    campo certo). O bootstrap-select deixa o `<select>` original oculto
    visualmente, entao um clique nativo num `<option>` (via
    `Select.select_by_visible_text`) e' rejeitado como
    ElementNotInteractable -- mesma familia de problema ja vista no
    combobox `#selInfraUnidades`. Resolvido setando o valor via JS e
    disparando 'change' manualmente (evento 'change' de formulario, ao
    contrario de clique em widget, e' respeitado por handlers JS/jQuery
    mesmo quando disparado via `dispatchEvent`)."""
    if not orgao_descricao:
        log("  [INFO] Nenhum Órgão especifico informado -- seguindo sem filtrar (todas as sessões visiveis no perfil).")
    else:
        try:
            select_el = wait.until(EC.presence_of_element_located((By.ID, "selOrgao")))
            opcoes = Select(select_el).options
            alvo_normalizado = _normalizar_fragmento(orgao_descricao)
            opcao_valor = None
            for opcao in opcoes:
                if alvo_normalizado in _normalizar_fragmento(opcao.text):
                    opcao_valor = opcao.get_attribute("value")
                    break
            if opcao_valor:
                driver.execute_script(
                    "arguments[0].value = arguments[1];"
                    "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                    select_el, opcao_valor,
                )
                time.sleep(1)
            else:
                log(f"  [AVISO] Órgão '{orgao_descricao}' nao encontrado nas opcoes de #selOrgao "
                    f"-- perfil provavelmente ja e' restrito a um unico orgao; seguindo sem filtrar.")
        except Exception as exc:
            log(f"  [AVISO] Falha ao filtrar por Órgão: {exc}")

    if data_inicial:
        campo_data_ini = driver.find_element(By.XPATH, "//label[contains(., 'Data Inicial')]/following::input[1]")
        campo_data_ini.clear()
        campo_data_ini.send_keys(data_inicial)
    if data_final:
        campo_data_fim = driver.find_element(By.XPATH, "//label[contains(., 'Data Final')]/following::input[1]")
        campo_data_fim.clear()
        campo_data_fim.send_keys(data_final)

    botao_consultar = driver.find_element(By.XPATH, "//button[contains(normalize-space(.), 'Consultar')]")
    _clicar(driver, botao_consultar)
    time.sleep(1.5)


def localizar_e_abrir_painel(driver, wait, status_desejado_regex=r"abert[ao]", log=print):
    """Na tabela de sessoes ja filtrada, acha a primeira linha cujo status
    bate com `status_desejado_regex` (default: contem 'aberta'/'aberto' --
    ou seja, sessao ainda em andamento/pre-sessao, nunca 'encerrada') e
    navega direto para o Painel da Sessao via o href do icone -- em vez de
    clicar e lidar com nova janela, o que e mais fragil em modo headless."""
    linhas = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    for linha in linhas:
        texto = linha.text
        if not re.search(status_desejado_regex, texto, re.IGNORECASE):
            continue
        try:
            link_painel = linha.find_element(By.CSS_SELECTOR, "a[href*='acao=sessao_julgamento_exibir_painel']")
        except NoSuchElementException:
            continue
        href = link_painel.get_attribute("href")
        log(f"  [OK] Sessao encontrada (status compativel com '{status_desejado_regex}') -- abrindo painel.")
        driver.get(href)
        time.sleep(1.5)
        return True
    log(f"  [AVISO] Nenhuma sessao com status compativel com '{status_desejado_regex}' encontrada na listagem atual.")
    return False


# ===========================================================================
# AÇÕES DE GESTÃO DA SESSÃO (perfil CARTÓRIO) -- fechar pauta, quórum,
# composição, gerar pauta (publica+intima), abrir sessão.
#
# Mapeadas 100% ao vivo em 2026-08-24 (ver memória do projeto,
# project_aura_sessao_julgamento.md) inspecionando o DOM real em
# homologação, mas NUNCA rodadas via Selenium antes de escritas aqui em
# 2026-08-26 -- tratar como PRIMEIRA EXECUÇÃO em qualquer teste real,
# acompanhar visualmente (headless=False) antes de confiar. Continuam
# faltando (pendência real, não escondida): votação dos vogais, fechamento
# da sessão e lançamento do resultado do julgamento -- exigem login como
# um dos magistrados vogais, e a senha de login é sempre digitada pelo
# usuário manualmente, nunca por automação.
# ===========================================================================

def _achar_linha_sessao(driver, filtro_sessao):
    alvo_norm = _normalizar_fragmento(filtro_sessao)
    for linha in driver.find_elements(By.CSS_SELECTOR, "table tbody tr"):
        try:
            if alvo_norm in _normalizar_fragmento(linha.text or ""):
                return linha
        except Exception:
            continue
    return None


def _clicar_por_texto(driver, textos, tags="a, button", timeout=6.0):
    """Clica no primeiro elemento VISÍVEL cujo texto bate com um dos
    textos dados (substring normalizada sem acento/maiúsculas). Necessário
    porque os wizards de Sessão de Julgamento usam <a class="btn ..."> em
    vez de <button> pros botões de ação ('Validar', 'Gravar', 'Gerar
    pauta') -- confirmado por inspeção de DOM ao vivo."""
    deadline = time.time() + timeout
    normalizados = [_normalizar_fragmento(t) for t in textos]
    while time.time() < deadline:
        for el in driver.find_elements(By.CSS_SELECTOR, tags):
            try:
                if not el.is_displayed():
                    continue
                txt = _normalizar_fragmento((el.text or el.get_attribute("value") or "").strip())
                if any(alvo and alvo in txt for alvo in normalizados):
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    return True
            except Exception:
                continue
        time.sleep(0.3)
    return False


def _abrir_menu_linha(driver, linha, log=print):
    """Abre o dropdown '⋮' (mais ações) de uma linha da listagem. Seletor
    NÃO confirmado por inspeção exata de DOM (só descrito visualmente no
    mapeamento ao vivo) -- tenta o padrão Bootstrap (data-toggle=dropdown)
    e, como fallback, o ícone Material 'more_vert' (glifo do '⋮'). Se
    falhar na primeira execução real, inspecionar o DOM da linha e
    ajustar aqui."""
    candidatos = linha.find_elements(
        By.CSS_SELECTOR,
        "a[data-toggle='dropdown'], button[data-toggle='dropdown'], .dropdown-toggle")
    if not candidatos:
        for el in linha.find_elements(By.CSS_SELECTOR, "a, button"):
            if (el.text or "").strip() == "more_vert":
                candidatos = [el]
                break
    if not candidatos:
        log("  [ERRO] Menu '⋮' (mais ações) não encontrado na linha.")
        return False
    _clicar_nativo(driver, candidatos[0])
    time.sleep(0.5)
    return True


def fechar_pauta(driver, filtro_sessao, log=print):
    """Fecha a pauta de uma sessão com status 'Pauta aberta' -> 'Pauta
    fechada'. O ícone fica na coluna 'Ações' de cada linha
    (a[acao="sessao_julgamento_fechar_pauta"]) e dispara um
    window.confirm() nativo -- sobrescrever window.confirm ANTES do
    clique é mais confiável que interceptar o alert nativo depois
    (interceptação falhou repetidas vezes no mapeamento ao vivo).
    Pressupõe que a listagem já está na tela (navegar_para_listagem_sessoes)."""
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is None:
        log(f"  [ERRO] Nenhuma linha de sessão contém '{filtro_sessao}'.")
        return False
    try:
        icone = linha.find_element(By.CSS_SELECTOR, 'a[acao="sessao_julgamento_fechar_pauta"]')
    except NoSuchElementException:
        log("  [ERRO] Ícone 'Fechar Pauta' não encontrado na linha -- sessão pode não estar com pauta aberta.")
        return False
    driver.execute_script("window.confirm = function(){return true;};")
    _clicar_nativo(driver, icone)
    time.sleep(1.5)

    if not _clicar_por_texto(driver, ["Consultar"], tags="button, a", timeout=3.0):
        log("  [AVISO] Botão 'Consultar' não encontrado pra reconferir status.")
        return True
    time.sleep(1.5)
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is None:
        log("  [AVISO] Linha da sessão não reencontrada após reconsulta.")
        return False
    if "pauta fechada" in _normalizar_fragmento(linha.text or ""):
        log(f"  [OK] Pauta fechada com sucesso ('{filtro_sessao}').")
        return True
    log(f"  [AVISO] Status pós-clique não confirma 'Pauta fechada': {(linha.text or '')[:120]!r}")
    return False


def abrir_modal_participantes(driver, filtro_sessao, log=print):
    """Abre o modal 'Sessão Telepresencial - <Câmara> - <Data>' (abas
    Quórum/Composição) pelo menu '⋮' da linha -- opção 'Alterar os
    magistrados participantes da sessão de julgamento'."""
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is None:
        log(f"  [ERRO] Nenhuma linha de sessão contém '{filtro_sessao}'.")
        return False
    if not _abrir_menu_linha(driver, linha, log=log):
        return False
    if not _clicar_por_texto(driver, ["Alterar os magistrados participantes"],
                              tags="a, li, button", timeout=4.0):
        log("  [ERRO] Item 'Alterar os magistrados participantes da sessão de julgamento' não encontrado no menu.")
        return False
    time.sleep(1.0)
    return True


def incluir_magistrado_quorum(driver, nome_magistrado, presidente=False, log=print):
    """Aba QUÓRUM do modal (ver abrir_modal_participantes): inclui um
    magistrado da tabela 'Magistrados não cadastrados' clicando na seta
    de 'Incluir'. CUIDADO: magistrados com a badge 'Com processos'
    (relator) têm 2 <a> na linha -- o botão de incluir é sempre o ÚLTIMO
    <a>. Depois de incluído, marca o checkbox 'Presidente' (2º checkbox
    da linha, índice 1 -- o 1º é 'Participante Eventual') se
    presidente=True."""
    alvo_norm = _normalizar_fragmento(nome_magistrado)
    botao_incluir = None
    for linha in driver.find_elements(By.CSS_SELECTOR, "table tr"):
        if not linha.is_displayed():
            continue
        if alvo_norm in _normalizar_fragmento(linha.text or ""):
            links = linha.find_elements(By.TAG_NAME, "a")
            if links:
                botao_incluir = links[-1]
                break
    if botao_incluir is None:
        log(f"  [ERRO] Magistrado '{nome_magistrado}' não encontrado na tabela de não cadastrados.")
        return False
    _clicar_nativo(driver, botao_incluir)
    time.sleep(1.0)

    if not presidente:
        log(f"  [OK] '{nome_magistrado}' incluído no quórum.")
        return True

    for linha in driver.find_elements(By.CSS_SELECTOR, "table tr"):
        if not linha.is_displayed():
            continue
        if alvo_norm in _normalizar_fragmento(linha.text or ""):
            checkboxes = linha.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            if len(checkboxes) >= 2:
                if not checkboxes[1].is_selected():
                    _clicar_nativo(driver, checkboxes[1])
                log(f"  [OK] '{nome_magistrado}' incluído no quórum como Presidente.")
                return True
    log(f"  [AVISO] '{nome_magistrado}' incluído, mas checkbox 'Presidente' não encontrado pra marcar.")
    return True


def mudar_aba_modal(driver, nome_aba, log=print):
    """Troca de aba dentro do modal Quórum/Composição ('Quórum' ou
    'Composição')."""
    if not _clicar_por_texto(driver, [nome_aba], tags="a, li, button", timeout=4.0):
        log(f"  [ERRO] Aba '{nome_aba}' não encontrada no modal.")
        return False
    time.sleep(0.5)
    return True


def definir_papel_composicao(driver, nome_magistrado, papel, log=print):
    """Aba COMPOSIÇÃO do modal: define o papel de um magistrado clicando
    no span da célula até chegar no estado certo. ACHADO TÉCNICO: a
    tabela de composição NÃO usa <tbody> (as <tr> são inseridas via JS
    como filhas diretas de <table>) -- 'table tbody tr' sempre pega a
    linha errada (vazia, da aba Quórum escondida). Usa
    querySelectorAll('tr') genérico + filtra por
    getBoundingClientRect().width>0 pra achar só linhas visíveis da aba
    ativa. Cada clique CICLA o estado: indefinido(-1) -> 1 clique =
    votante -> 2 cliques = presidente -> (3 cliques = presidente-sem-voto,
    NÃO TESTADO) -> volta pro início. `papel`: 'votante' ou 'presidente'."""
    cliques_necessarios = {"votante": 1, "presidente": 2}.get(papel)
    if cliques_necessarios is None:
        log(f"  [ERRO] Papel '{papel}' inválido -- use 'votante' ou 'presidente'.")
        return False

    linhas = driver.execute_script(
        "return Array.from(document.querySelectorAll('tr')).filter("
        "  r => r.getBoundingClientRect().width > 0);"
    )
    alvo_norm = _normalizar_fragmento(nome_magistrado)
    linha_alvo = None
    for linha in linhas:
        if alvo_norm in _normalizar_fragmento(linha.text or ""):
            linha_alvo = linha
            break
    if linha_alvo is None:
        log(f"  [ERRO] Magistrado '{nome_magistrado}' não encontrado na tabela de composição visível.")
        return False

    try:
        tds = linha_alvo.find_elements(By.TAG_NAME, "td")
        span_papel = tds[2].find_element(By.CSS_SELECTOR, "span[data-id-papel]")
    except Exception as exc:
        log(f"  [ERRO] Célula de papel (3ª coluna) não encontrada pra '{nome_magistrado}': {exc}")
        return False

    for _ in range(cliques_necessarios):
        _clicar_nativo(driver, span_papel)
        time.sleep(0.4)

    classe_final = span_papel.get_attribute("class") or ""
    if papel not in classe_final:
        log(f"  [AVISO] Depois de {cliques_necessarios} clique(s), classe do span é {classe_final!r} "
            f"-- não confirma papel '{papel}' esperado.")
        return False
    log(f"  [OK] '{nome_magistrado}' definido como '{papel}' na composição.")
    return True


def salvar_quorum_composicao(driver, log=print):
    """Salva o modal de Quórum/Composição -- botão compartilhado entre as
    2 abas (não precisa estar em nenhuma aba específica pra salvar);
    id 'btnSalvar' confirmado na aba Composição, aba Quórum documentada
    como 'botão azul Salvar' pelo texto (mesmo elemento)."""
    try:
        botao = driver.find_element(By.ID, "btnSalvar")
        if botao.is_displayed():
            _clicar_nativo(driver, botao)
            time.sleep(1.5)
            log("  [OK] Quórum/Composição salvos (#btnSalvar).")
            return True
    except NoSuchElementException:
        pass
    if _clicar_por_texto(driver, ["Salvar"], tags="a, button", timeout=3.0):
        time.sleep(1.5)
        log("  [OK] Quórum/Composição salvos (botão 'Salvar' por texto).")
        return True
    log("  [ERRO] Botão 'Salvar' do modal de Quórum/Composição não encontrado.")
    return False


def gerar_pauta_publicar_intimar(driver, wait, filtro_sessao, log=print):
    """Wizard de 3 telas aberto via '⋮' > 'Gerar Pauta da Sessão de
    Julgamento'. Tela 1 ('Registros encontrados para geração da pauta')
    -> botão 'Validar' (é <a class="btn btn-primary">, NÃO <button>).
    Tela 2 (só aparece se algum processo tiver aviso -- checkboxes já vêm
    marcados) -> botão 'Gravar' (mesmo padrão <a>). Tela 3 ('Ordenação de
    gabinetes e magistrados') -> marcar os 2 checkboxes de id FIXO
    chk_lancar_evento_S ('Lançar os eventos de inclusão em pauta e
    intimação?') e chk_publicar_S ('Publicar a pauta no próximo Diário da
    Justiça?') -- CUIDADO (erro real já cometido no mapeamento ao vivo):
    nunca usar seletor genérico tipo 'todo checkbox visível', o modal fica
    por cima da listagem cheia de filtros/checkboxes e um clique em lote
    pega os de trás e fecha o modal sem confirmar nada -- sempre usar os
    ids exatos. -> botão 'Gerar pauta' (de novo <a>, não <button>).
    Resultado esperado: status pula de 'Pauta fechada' direto pra
    'Intimação realizada'."""
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is None:
        log(f"  [ERRO] Nenhuma linha de sessão contém '{filtro_sessao}'.")
        return False
    if not _abrir_menu_linha(driver, linha, log=log):
        return False
    if not _clicar_por_texto(driver, ["Gerar Pauta da Sessão de Julgamento"],
                              tags="a, li, button", timeout=4.0):
        log("  [ERRO] Item 'Gerar Pauta da Sessão de Julgamento' não encontrado no menu.")
        return False
    time.sleep(1.0)

    if not _clicar_por_texto(driver, ["Validar"], tags="a", timeout=6.0):
        log("  [ERRO] Botão 'Validar' (Tela 1 do wizard) não encontrado.")
        return False
    time.sleep(1.0)

    if _clicar_por_texto(driver, ["Gravar"], tags="a", timeout=2.5):
        log("  [INFO] Tela 2 (avisos) apareceu -- 'Gravar' clicado (checkboxes já vinham marcados).")
        time.sleep(1.0)

    try:
        chk_evento = wait.until(EC.presence_of_element_located((By.ID, "chk_lancar_evento_S")))
        chk_publicar = driver.find_element(By.ID, "chk_publicar_S")
    except TimeoutException:
        log("  [ERRO] Tela 3 (checkboxes de evento/publicação) não apareceu -- wizard pode ter parado antes.")
        return False
    if not chk_evento.is_selected():
        _clicar_nativo(driver, chk_evento)
    if not chk_publicar.is_selected():
        _clicar_nativo(driver, chk_publicar)
    time.sleep(0.3)

    if not _clicar_por_texto(driver, ["Gerar pauta"], tags="a", timeout=6.0):
        log("  [ERRO] Botão 'Gerar pauta' (Tela 3) não encontrado.")
        return False
    time.sleep(2.0)

    if not _clicar_por_texto(driver, ["Consultar"], tags="button, a", timeout=3.0):
        log("  [AVISO] Botão 'Consultar' não encontrado pra reconferir status.")
        return True
    time.sleep(1.5)
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is not None and "intimacao realizada" in _normalizar_fragmento(linha.text or ""):
        log("  [OK] Pauta gerada, publicada e intimada -- status 'Intimação realizada' confirmado.")
        return True
    log(f"  [AVISO] Status pós-wizard não confirma 'Intimação realizada': "
        f"{(linha.text if linha is not None else '???')[:120]!r}")
    return False


def encerrar_ata(driver, filtro_sessao, log=print):
    """Encerra a Ata da Sessão de Julgamento -- ação final que fecha a
    sessão de vez (equivalente a 'fechar sessão + lançar resultado' do
    rito). ACHADO NO CÓDIGO-FONTE do eproc (controlador
    `App\\Controladores\\SessaoJulgamento\\EncerrarAta`, 2026-08-26, NÃO
    mapeado via observação de tela): o recurso que controla se essa aba
    aparece é `sessao_julgamento_encerrar_ata`, e só fica disponível
    quando TODOS os itens da sessão já têm resultado E evento lançado
    (sem isso o backend nem mostra a aba). O botão real de confirmação é
    `sbmEncerrarAtaSessaoJulgamento` -- o controlador confere
    especificamente `$hdnButton == 'sbmEncerrarAtaSessaoJulgamento'`
    antes de executar `SessaoJulgamentoRN::encerrarAtaSessaoJulgamento()`.

    PONTO NÃO CONFIRMADO (marcado, não escondido): pelo código, essa aba
    'ENCERRAMENTO DA ATA' é combinada com as abas Dados/Quórum/Composição
    no MESMO modal (`EncerrarAta::acaoModalComAbas` monta as 4 juntas) --
    ou seja, provavelmente é o MESMO modal já usado por
    `abrir_modal_participantes` (aberto pelo menu '⋮'), só que essa 4ª
    aba só aparece quando a sessão já está elegível pra encerrar. Nunca
    testado ao vivo -- se a aba não aparecer nesse modal, procurar um
    item de menu separado tipo 'Encerrar a Ata da Sessão'."""
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is None:
        log(f"  [ERRO] Nenhuma linha de sessão contém '{filtro_sessao}'.")
        return False
    if not _abrir_menu_linha(driver, linha, log=log):
        return False
    if not _clicar_por_texto(driver, ["Encerrar a Ata", "Alterar os magistrados participantes"],
                              tags="a, li, button", timeout=4.0):
        log("  [ERRO] Não encontrei item de menu que leve ao modal com a aba 'Encerramento da Ata'.")
        return False
    time.sleep(1.0)
    if not _clicar_por_texto(driver, ["ENCERRAMENTO DA ATA", "Encerramento da Ata"],
                              tags="a, li, button", timeout=4.0):
        log("  [ERRO] Aba 'ENCERRAMENTO DA ATA' não apareceu -- sessão pode ainda ter "
            "itens sem resultado/evento lançado (pré-requisito confirmado no código-fonte).")
        return False
    time.sleep(0.5)

    if not _clicar_por_texto(driver, ["Encerrar"], tags="button", timeout=6.0):
        log("  [ERRO] Botão de confirmar 'Encerrar Ata' (sbmEncerrarAtaSessaoJulgamento) não encontrado.")
        return False
    time.sleep(1.5)

    if not _clicar_por_texto(driver, ["Consultar"], tags="button, a", timeout=3.0):
        log("  [AVISO] Botão 'Consultar' não encontrado pra reconferir status.")
        return True
    time.sleep(1.5)
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is not None and "encerrad" in _normalizar_fragmento(linha.text or ""):
        log(f"  [OK] Ata encerrada com sucesso ('{filtro_sessao}').")
        return True
    log(f"  [AVISO] Status pós-clique não confirma sessão encerrada: "
        f"{(linha.text if linha is not None else '???')[:120]!r}")
    return False


def abrir_sessao(driver, filtro_sessao, log=print):
    """Abre a sessão de julgamento antes/na data marcada. O ícone da
    linha (mesma posição que antes mostrava 'Fechar Pauta') muda pra
    onclick="window.abrirRecursoSessaoModal('...acao=sessao_julgamento_
    abrir_sessao...')" com tooltip 'Abrir a Sessão de Julgamento' quando
    o status já é 'Intimação realizada'. O modal tem campo 'Data e Hora
    do Início' (pré-preenchido, não mexemos) e aviso vermelho de
    confirmação -- botão de confirmar é um <button> 'Salvar' (não <a>,
    diferente dos wizards acima)."""
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is None:
        log(f"  [ERRO] Nenhuma linha de sessão contém '{filtro_sessao}'.")
        return False
    icone = None
    for el in linha.find_elements(By.CSS_SELECTOR, "a[onclick*='abrirRecursoSessaoModal']"):
        if "sessao_julgamento_abrir_sessao" in (el.get_attribute("onclick") or ""):
            icone = el
            break
    if icone is None:
        log("  [ERRO] Ícone 'Abrir a Sessão de Julgamento' não encontrado na linha -- "
            "confira se o status já é 'Intimação realizada'.")
        return False
    driver.execute_script("window.confirm = function(){return true;};")
    _clicar_nativo(driver, icone)
    time.sleep(1.5)

    if not _clicar_por_texto(driver, ["Salvar"], tags="button", timeout=6.0):
        log("  [ERRO] Botão 'Salvar' do modal 'Abrir a Sessão de Julgamento' não encontrado.")
        return False
    time.sleep(1.5)

    if not _clicar_por_texto(driver, ["Consultar"], tags="button, a", timeout=3.0):
        log("  [AVISO] Botão 'Consultar' não encontrado pra reconferir status.")
        return True
    time.sleep(1.5)
    linha = _achar_linha_sessao(driver, filtro_sessao)
    if linha is not None and "sessao aberta" in _normalizar_fragmento(linha.text or ""):
        log(f"  [OK] Sessão aberta com sucesso ('{filtro_sessao}').")
        return True
    log(f"  [AVISO] Status pós-clique não confirma 'Sessão aberta': "
        f"{(linha.text if linha is not None else '???')[:120]!r}")
    return False


# ===========================================================================
# Navegação até o Painel da Sessão de Julgamento via Calendário (perfil
# MAGISTRADO/vogal) + voto por item da Pauta.
#
# Mapeado ao vivo em 2026-08-27 (logado como CHRISTIAN GOMES LIMA, sigla
# t0026716, processo de teste 2819955-05.2026.8.13.0000) -- ver memória do
# projeto, project_aura_sessao_julgamento.md. Caminho de navegação (Painel
# do Magistrado -> Calendário -> evento -> ícone playlist_play -> nova aba
# -> aba Pauta) confirmado só por clique manual visual, seletores das
# etapas 1-3 de `navegar_ate_painel_sessao_via_calendario` NÃO confirmados
# por inspeção exata de DOM -- tratar como primeira execução real. Os
# ícones de voto por item (`votar_item_pauta`) já foram confirmados por
# inspeção de DOM real (atributos acao=/descricao=/sin_solicitar_
# confirmacao= lidos ao vivo), mas NUNCA CLICADOS de verdade -- tratar o
# primeiro clique real como teste acompanhado (headless=False).
# ===========================================================================

def _trocar_para_nova_aba(driver, handles_antes, timeout=10, log=print) -> bool:
    """Versão livre (sem `self`) de EprocBotV4._trocar_para_nova_aba
    (integrations/auragabinete.py:716) -- espera surgir um handle que não
    estava em `handles_antes` e troca o driver pra ele. `handles_antes`
    deve ser capturado (driver.window_handles) ANTES da ação que abre a
    nova aba."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.window_handles) > len(handles_antes)
        )
    except TimeoutException:
        log("  [ERRO] Nenhuma aba nova apareceu após a ação.")
        return False
    for handle in driver.window_handles:
        if handle not in handles_antes:
            driver.switch_to.window(handle)
            return True
    return False


def navegar_ate_painel_sessao_via_calendario(driver, wait, filtro_sessao, log=print) -> bool:
    """Caminho confirmado ao vivo em 27/08 (perfil MAGISTRADO/vogal, NÃO o
    mesmo caminho por menu textual usado pro perfil cartório em
    `navegar_para_listagem_sessoes`): Painel do Magistrado -> Calendário de
    Sessões de Julgamento -> clicar no evento -> ícone Material
    'playlist_play' (1o de 9 ícones sem href, só onclick) -> abre em NOVA
    ABA -> aba Pauta. Cada etapa loga separadamente qual falhou (mesmo
    estilo 'Tela 1/2/3' de gerar_pauta_publicar_intimar) pra saber onde
    ajustar seletor sem re-mapear tudo de novo.

    `filtro_sessao`: fragmento que identifica o EVENTO no calendário (ex.
    '08/09/2026 20ª CÂMARA CÍVEL') -- diferente do filtro usado nas funções
    de listagem (essas usam texto de LINHA de tabela, aqui é texto de card/
    evento de calendário; normalizar sem sufixo de status tipo '- Sessão
    aberta', que é conceito de listagem, não de calendário)."""
    alvo_norm = _normalizar_fragmento(filtro_sessao)

    # Etapa 1 -- menu lateral "Sessão de Julgamento" > "Calendário".
    if not _clicar_por_texto(driver, ["Sessão de Julgamento"], tags="a, span", timeout=5.0):
        log("  [ERRO] Etapa 1: item de menu 'Sessão de Julgamento' não encontrado.")
        return False
    time.sleep(0.6)
    if not _clicar_por_texto(driver, ["Calendário"], tags="a, span", timeout=4.0):
        log("  [ERRO] Etapa 1: item de submenu 'Calendário' não encontrado.")
        return False
    time.sleep(1.5)

    # Etapa 2 -- achar o evento no calendário e abrir o popover.
    evento = None
    for el in driver.find_elements(By.CSS_SELECTOR, "a, div[class*='evento'], td[class*='evento']"):
        try:
            if not el.is_displayed():
                continue
            if alvo_norm in _normalizar_fragmento(el.text or el.get_attribute("title") or ""):
                evento = el
                break
        except Exception:
            continue
    if evento is None:
        log(f"  [ERRO] Etapa 2: nenhum evento do calendário contém '{filtro_sessao}'.")
        return False
    _clicar_nativo(driver, evento)
    time.sleep(1.0)

    # Etapa 3 -- ícone 'playlist_play' no popover/modal do evento -> nova aba.
    icone_painel = None
    for el in driver.find_elements(By.CSS_SELECTOR, "i.material-icons, i[class*='material']"):
        try:
            if (el.text or "").strip() == "playlist_play":
                pai = el.find_element(By.XPATH, "./..")
                icone_painel = pai if pai.tag_name.lower() in ("a", "button") else el
                break
        except Exception:
            continue
    if icone_painel is None:
        log("  [ERRO] Etapa 3: ícone 'playlist_play' (Painel da Sessão) não encontrado no evento.")
        return False
    handles_antes = driver.window_handles
    _clicar_nativo(driver, icone_painel)
    if not _trocar_para_nova_aba(driver, handles_antes, timeout=10, log=log):
        log("  [ERRO] Etapa 3: clique em 'playlist_play' não abriu nova aba.")
        return False
    time.sleep(1.0)

    # Etapa 4 -- aba Pauta do Painel da Sessão de Julgamento.
    try:
        aba_pauta = driver.find_element(By.ID, "tab-pauta")
    except NoSuchElementException:
        log("  [ERRO] Etapa 4: aba 'Pauta' (#tab-pauta) não encontrada -- "
            "confira se a nova aba é mesmo o Painel da Sessão de Julgamento.")
        return False
    _clicar_nativo(driver, aba_pauta)
    time.sleep(1.0)
    log("  [OK] Painel da Sessão de Julgamento aberto, aba Pauta ativa.")
    return True


ACOES_VOTO_ITEM_PAUTA = {
    "acompanha_relator": "sessao_julgamento_item_acompanha_relator",
    "acompanha_divergencia": "sessao_julgamento_item_acompanha_divergencia",
    "pedir_vista": "sessao_julgamento_item_pedir_vista",
}

# Ícone material esperado na coluna "Destaques" após cada tipo de voto --
# 'thumb_up' CONFIRMADO ao vivo em 27/08/2026; os outros 2 são
# extrapolados por simetria (mesmo ícone do próprio botão de voto), ainda
# não confirmados ao vivo.
_ICONE_CONFIRMACAO_POR_TIPO_VOTO = {
    "acompanha_relator": "thumb_up",
    "acompanha_divergencia": "thumb_down",
    "pedir_vista": "visibility",
}


def _achar_celula_por_cabecalho(linha, texto_cabecalho, log=print):
    """Acha a `<td>` da `linha` cuja coluna tem `<th>` contendo
    `texto_cabecalho` (case-insensitive) -- evita hardcodar um índice de
    coluna fixo, que pode variar entre telas/critérios de exibição."""
    try:
        tabela = linha.find_element(By.XPATH, "./ancestor::table[1]")
    except NoSuchElementException:
        return None
    indice = None
    for i, th in enumerate(tabela.find_elements(By.CSS_SELECTOR, "th")):
        if texto_cabecalho.strip().lower() in (th.text or "").strip().lower():
            indice = i
            break
    if indice is None:
        return None
    celulas = linha.find_elements(By.TAG_NAME, "td")
    if indice >= len(celulas):
        return None
    return celulas[indice]


def _achar_linha_item_pauta(driver, num_processo, log=print):
    """Acha a `<tr>` do item da Pauta referente a `num_processo`, casando só
    os dígitos (re.sub(r"[^\\d]", "", ...), mesmo padrão de
    EprocBotV4.pesquisar_processo em auragabinete.py:654) -- exige
    igualdade EXATA dos dígitos primeiro (evita casar com outra coluna
    numérica da linha, tipo Nro. Composição); só cai pra 'contains' com
    aviso se a igualdade exata não achar nada. NÃO escopado por container
    de aba (ex.: '#tab-pauta' é só o link da aba, não o painel de conteúdo
    -- id do painel não confirmado por inspeção de DOM ainda); na prática
    isso não deu problema no mapeamento ao vivo porque as outras abas
    (Mesa/Privados/Pesquisa) apareciam com 0 itens e não têm linhas de
    tabela renderizadas antes de serem clicadas."""
    alvo_digitos = re.sub(r"[^\d]", "", num_processo or "")
    if not alvo_digitos:
        log(f"  [ERRO] Número de processo inválido: '{num_processo}'.")
        return None
    candidatas_contains = []
    for linha in driver.find_elements(By.CSS_SELECTOR, "table tr"):
        try:
            texto = linha.text or ""
        except Exception:
            continue
        # Span numérico-com-pontuação (>=15 chars: cobre o formato CNJ
        # "NNNNNNN-DD.AAAA.J.TR.OOOO", 20 dígitos + pontuação) tratado como
        # UM candidato a "número de processo da linha" -- ao contrário de
        # um findall(r"\d+") ingênuo, que fragmentaria esse mesmo número em
        # vários pedaços curtos (por causa dos '-'/'.') e nunca bateria
        # igual a `alvo_digitos`. Igualdade exata dos dígitos desse span é
        # o match forte; só cai pra 'contains' no texto inteiro (mais
        # fraco) se nenhum span bater exatamente.
        for span in re.findall(r"[\d.\-/]{15,}", texto):
            if re.sub(r"[^\d]", "", span) == alvo_digitos:
                return linha
        if alvo_digitos in re.sub(r"[^\d]", "", texto):
            candidatas_contains.append(linha)
    if candidatas_contains:
        log(f"  [AVISO] Nenhum span numérico da linha bateu EXATAMENTE com "
            f"'{num_processo}' -- casei por 'contains' (mais fraco, confira o "
            f"resultado). Pode indicar processo formatado diferente do esperado.")
        return candidatas_contains[0]
    log(f"  [ERRO] Nenhuma linha da Pauta contém o processo '{num_processo}'.")
    return None


def votar_item_pauta(driver, num_processo, tipo_voto, log=print) -> bool:
    """Vota no item da Pauta referente a `num_processo`, clicando no ícone
    real `a[name="imgRecursoSessaoJulgamentoItemAjax"][acao="..."]` da
    linha -- MESMO padrão de atributo já usado por `fechar_pauta` pro
    ícone de nível de sessão (`a[acao="sessao_julgamento_fechar_pauta"]`),
    confirmado ao vivo em 27/08 também pros ícones de item (thumb_up=
    acompanha_relator, thumb_down=acompanha_divergencia, visibility=
    pedir_vista -- ver ACOES_VOTO_ITEM_PAUTA).

    Sempre sobrescreve `window.confirm` ANTES do clique (mesmo truque já
    usado em `fechar_pauta`/`abrir_sessao`) -- não decide com base em ler
    `sin_solicitar_confirmacao` em runtime, só loga o valor real pra
    diagnóstico (thumb_up confirmado 'N' ao vivo 27/08 -- ação AJAX direta,
    sem modal; os outros 2 tipos ainda não confirmados, o override
    incondicional cobre os dois casos sem precisar saber de antemão).

    NUNCA CLICADO DE VERDADE ainda -- tratar a primeira chamada real como
    teste acompanhado (headless=False), ver seção 'Primeiro teste ao vivo'
    do plano/handoff. Confirmação pós-clique é BEST-EFFORT (loga o texto da
    linha depois do clique pra conferência visual) até o primeiro teste
    real revelar qual é o sinal de sucesso de verdade -- mesma filosofia já
    usada em fechar_pauta/abrir_sessao quando um passo de confirmação não é
    achado (retorna True com [AVISO], nunca finge certeza silenciosa)."""
    acao = ACOES_VOTO_ITEM_PAUTA.get(tipo_voto)
    if acao is None:
        log(f"  [ERRO] tipo_voto '{tipo_voto}' inválido -- use um de {list(ACOES_VOTO_ITEM_PAUTA)}.")
        return False
    linha = _achar_linha_item_pauta(driver, num_processo, log=log)
    if linha is None:
        return False
    try:
        icone = linha.find_element(
            By.CSS_SELECTOR, f'a[name="imgRecursoSessaoJulgamentoItemAjax"][acao="{acao}"]')
    except NoSuchElementException:
        log(f"  [ERRO] Ícone de voto '{tipo_voto}' (acao={acao}) não encontrado na linha do item "
            f"'{num_processo}'.")
        return False

    sin_confirmacao = icone.get_attribute("sin_solicitar_confirmacao")
    descricao = icone.get_attribute("descricao")
    log(f"  [INFO] Votando '{descricao}' (acao={acao}, "
        f"sin_solicitar_confirmacao={sin_confirmacao!r}) no processo '{num_processo}'.")

    _dump_diagnostico(driver, f"antes_voto_{tipo_voto}", log=log)
    driver.execute_script("window.confirm = function(){return true;};")
    _clicar_nativo(driver, icone)
    time.sleep(1.5)
    _dump_diagnostico(driver, f"depois_voto_{tipo_voto}", log=log)

    # Gancho do Plano B (SÓ DETECTA, não automatiza): tela de arrastar-e-
    # soltar achada no código-fonte do eproc (item_resultado.js) -- se
    # aparecer, o clique simples não bastou pra este caso (provável
    # divergência real entre vogais). Automação de drag-and-drop NÃO
    # implementada -- ver MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md.
    if driver.find_elements(By.ID, "section-relator") or \
       driver.find_elements(By.CSS_SELECTOR, ".section-divergencia, #section-pedido-vista"):
        log("  [AVISO] Apareceu a tela de arrastar-e-soltar (item_resultado.js) -- "
            "clique simples não bastou. Automação de drag-and-drop NÃO implementada.")
        return False

    linha_depois = _achar_linha_item_pauta(driver, num_processo, log=log)
    if linha_depois is None:
        log("  [AVISO] Linha do item não reencontrada após o clique -- confira manualmente.")
        return False

    # Sinal de sucesso CONFIRMADO ao vivo em 27/08/2026 (clique real, não
    # suposição): pra tipo_voto='acompanha_relator', um ícone material
    # 'thumb_up' aparece na coluna "Destaques" da linha (ao lado do '+' de
    # destaque) imediatamente após o clique, sem modal/reload -- ação AJAX
    # síncrona confirmada. Os ícones esperados pra 'acompanha_divergencia'
    # ('thumb_down') e 'pedir_vista' ('visibility') são EXTRAPOLADOS por
    # simetria com os próprios ícones de voto -- ainda não confirmados ao
    # vivo, conferir no primeiro teste real de cada um.
    icone_esperado = _ICONE_CONFIRMACAO_POR_TIPO_VOTO.get(tipo_voto)
    celula_destaques = _achar_celula_por_cabecalho(linha_depois, "Destaques", log=log)
    if celula_destaques is not None and icone_esperado:
        icones_destaques = [
            (i.text or "").strip()
            for i in celula_destaques.find_elements(By.CSS_SELECTOR, "i.material-icons, i[class*='material']")
        ]
        if icone_esperado in icones_destaques:
            log(f"  [OK] Confirmado: ícone '{icone_esperado}' apareceu na coluna Destaques -- "
                f"voto '{tipo_voto}' registrado no processo '{num_processo}'.")
            return True
        log(f"  [AVISO] Ícone '{icone_esperado}' não apareceu na coluna Destaques após o clique "
            f"(ícones encontrados: {icones_destaques}) -- ação foi disparada mas confirmação "
            f"automática não bateu, confira manualmente.")
        return True
    log(f"  [AVISO] Coluna 'Destaques' não encontrada pra confirmar -- "
        f"texto da linha após o clique: {(linha_depois.text or '')[:200]!r}. "
        f"Confira visualmente antes de confiar neste retorno.")
    return True


# ===========================================================================
# Revelar as abas do painel (clique NATIVO -- necessario pro AJAX carregar)
# ===========================================================================

# IDs dos links das abas monitoradas -- por decisao explicita, so Pauta e
# Mesa (Sessao tem categorias/sub-abas aninhadas que poluiam o sinal,
# Privados/Internos nao entrou no escopo).
IDS_ABAS_PAINEL = [
    ("Pauta", "tab-pauta"),
    ("Mesa", "tab-mesa"),
]


def _clicar_nativo(driver, elemento):
    """Clique NATIVO do Selenium (WebElement.click(), via CDP Input) -- ao
    contrario de `_clicar` (que usa driver.execute_script para bypassar
    overlays), este e' tratado pelo Chrome como um clique confiavel
    (isTrusted=True). As abas do Painel da Sessao (e sub-abas internas como
    "Com apontamentos"/"Todos") so disparam o carregamento via AJAX com um
    clique confiavel -- um clique via JS (inclusive disparado de dentro de
    um content script de extensao) e' ignorado pelo widget. Mesmo problema
    ja documentado no AURA Eventos Câmara Cível (autocomplete que so
    responde a "clique nativo, nao JS")."""
    try:
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.ID, "divInfraAvisoFundo"))
        )
    except TimeoutException:
        pass
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
    elemento.click()


def revelar_todas_as_abas(driver, log=print):
    """Clica nativamente em cada aba do painel e, se houver, na sub-aba
    interna que ja vem marcada como ativa (ex: "Com apontamentos", "Todos")
    -- essa sub-aba tambem precisa de um clique confiavel proprio para
    buscar sua tabela via AJAX, mesmo ja aparecendo com a classe "active".
    So faz a extensao (content.js) enxergar dados: a extracao/diff/alerta
    continuam inteiramente do lado da extensao, que so observa o DOM."""
    for nome, id_aba in IDS_ABAS_PAINEL:
        try:
            link = driver.find_element(By.ID, id_aba)
        except NoSuchElementException:
            log(f"  [AVISO] Aba '{nome}' (id {id_aba}) nao encontrada no painel -- pulando.")
            continue
        try:
            _clicar_nativo(driver, link)
            time.sleep(0.8)
        except Exception as exc:
            log(f"  [AVISO] Falha ao clicar na aba '{nome}': {exc}")
            continue

        href = link.get_attribute("href") or ""
        id_painel = href.split("#", 1)[1] if "#" in href else None
        if not id_painel:
            continue
        try:
            painel = driver.find_element(By.ID, id_painel)
            sub_aba = painel.find_element(By.CSS_SELECTOR, ".nav-link.active, [role='tab'].active")
            _clicar_nativo(driver, sub_aba)
            time.sleep(0.8)
        except NoSuchElementException:
            pass  # aba sem sub-navegacao interna (ex: Privados/Internos) -- tudo bem
        except Exception as exc:
            log(f"  [AVISO] Falha ao revelar sub-aba interna de '{nome}': {exc}")


# ===========================================================================
# Leitura dos eventos gerados pela extensao (console do navegador)
# ===========================================================================

def ler_eventos_do_console(driver, log=print):
    """Le as entradas novas do console do navegador (driver.get_log
    consome e limpa o buffer a cada chamada) e repassa para `log` as que
    vierem da extensao (prefixo [AURA-EVENTO]/[AURA-CICLO])."""
    try:
        entradas = driver.get_log("browser")
    except Exception as exc:
        log(f"  [AVISO] Nao foi possivel ler o console do navegador: {exc}")
        return

    for entrada in entradas:
        mensagem = entrada.get("message", "")
        if PREFIXO_EVENTO in mensagem:
            corpo = mensagem.split(PREFIXO_EVENTO, 1)[1].strip()
            corpo = _extrair_json_de_mensagem_console(corpo)
            try:
                evento = json.loads(corpo)
                log(f"  [EVENTO][{evento.get('tipo_evento')}] {evento.get('mensagem')}")
            except Exception:
                log(f"  [EVENTO] {corpo}")
        elif PREFIXO_CICLO in mensagem:
            corpo = mensagem.split(PREFIXO_CICLO, 1)[1].strip()
            corpo = _extrair_json_de_mensagem_console(corpo)
            log(f"  [CICLO] {corpo}")


CHAVE_LOCALSTORAGE_EVENTOS = "__aura_sj_eventos__"


def ler_eventos_via_storage(driver, estado, log=print):
    """Le os eventos que o content.js espelha em localStorage da propria
    pagina do painel (chave CHAVE_LOCALSTORAGE_EVENTOS -- ver
    extension/content.js, funcao emitirEvento). Substitui a tentativa
    original de usar driver.get_log('browser'): confirmado ao vivo que o
    Selenium NAO captura console.log do content script (isolated world),
    zero entradas da extensao em 180s de teste real, so' logs da propria
    pagina do eproc. localStorage, diferente de chrome.storage, e'
    compartilhado entre o isolated world do content script e o main world
    da pagina -- da pra ler direto da aba do painel, sem trocar de aba nem
    descobrir o id da extensao (tentativas via CDP Target.getTargets e
    chrome://extensions/ nao funcionaram nesse ambiente headless). So' loga
    entradas novas desde a ultima leitura (por `recebido_em`, timestamp que
    o content script grava em cada evento), rastreado em `estado`."""
    try:
        bruto = driver.execute_script(
            f"return localStorage.getItem('{CHAVE_LOCALSTORAGE_EVENTOS}');"
        )
    except Exception as exc:
        log(f"  [AVISO] Falha ao ler localStorage da pagina: {exc}")
        return

    if not bruto:
        return
    try:
        historico = json.loads(bruto)
    except Exception as exc:
        log(f"  [AVISO] localStorage com JSON invalido: {exc}")
        return

    ultimo = estado.get("ultimo_recebido_em", 0)
    novos = [e for e in historico if e.get("recebido_em", 0) > ultimo]
    novos.sort(key=lambda e: e.get("recebido_em", 0))
    for evento in novos:
        log(f"  [EVENTO][{evento.get('tipo_evento')}] {evento.get('mensagem')}")
    if novos:
        estado["ultimo_recebido_em"] = novos[-1].get("recebido_em", ultimo)


def _extrair_json_de_mensagem_console(corpo):
    """As mensagens de console do Chrome vem com aspas escapadas quando
    capturadas via get_log -- normaliza para tentar json.loads limpo."""
    return corpo.strip().strip('"').encode().decode("unicode_escape") if "\\" in corpo else corpo


# ===========================================================================
# Fluxo principal do launcher
# ===========================================================================

@dataclass
class ConfigAcompanhamento:
    usuario: str
    senha: str
    url: str
    perfil: str
    orgao_descricao: str
    data_inicial: str
    data_final: str
    headless: bool = True


def executar_acompanhamento(config: ConfigAcompanhamento, log=print, deve_continuar=lambda: True):
    """Faz login, localiza a sessao aberta da camara/data informadas e abre
    o painel com a extensao ja carregada -- a partir dai, a extensao
    (content.js) assume o monitoramento sozinha. Este loop so fica lendo o
    console do navegador e repassando os eventos para `log`, ate
    `deve_continuar()` retornar False."""
    driver, wait = criar_driver(headless=config.headless, carregar_extensao=True, log=log)
    try:
        log("Fazendo login...")
        login(driver, wait, config.usuario, config.senha, config.url, config.perfil, log=log)

        log("Navegando ate a listagem de Sessoes de Julgamento...")
        navegar_para_listagem_sessoes(driver, wait, log=log)

        log(f"Filtrando por orgao '{config.orgao_descricao}' "
            f"({config.data_inicial or '...'} a {config.data_final or '...'})...")
        filtrar_orgao_e_datas(driver, wait, config.orgao_descricao,
                               config.data_inicial, config.data_final, log=log)

        if not localizar_e_abrir_painel(driver, wait, log=log):
            log("Nao foi possivel localizar uma sessao aberta -- encerrando.")
            return

        log("Painel aberto. A cada ciclo: revelo as abas com clique nativo (Selenium) e a "
            "extensao (content.js) observa o DOM e extrai/compara sozinha -- ela nunca clica em nada.")

        estado_leitura = {}

        ciclo = 0
        while deve_continuar():
            ciclo += 1
            try:
                revelar_todas_as_abas(driver, log=log)
            except Exception as exc:
                log(f"  [AVISO] Falha ao revelar abas no ciclo {ciclo}: {exc}")
                _dump_diagnostico(driver, f"falha_revelar_abas_ciclo_{ciclo}", log=log)

            time.sleep(1.5)  # da tempo do debounce da extensao (1s) processar antes de ler
            ler_eventos_via_storage(driver, estado_leitura, log=log)

            for _ in range(INTERVALO_LEITURA_LOG_SEGUNDOS):
                if not deve_continuar():
                    break
                time.sleep(1)

        log("Acompanhamento encerrado.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ===========================================================================
# GUI (CustomTkinter -- mesmo padrao visual dos outros modulos)
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


class AuraSessaoJulgamentoApp(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("AURA Sessão de Julgamento")
        self.configure(fg_color=COR_BG)
        self.geometry("640x740")
        self.minsize(580, 660)

        _cfg = carregar_config()
        self.usuario = (_cfg.get("usuario") or USUARIO_PADRAO).strip()
        self.senha = (_cfg.get("senha") or SENHA_PADRAO).strip()
        self.url = (_cfg.get("url") or URL_PADRAO).strip()
        self.perfil_salvo = (_cfg.get("perfil") or "").strip()

        self._executando = False
        self._deve_continuar = True
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="AURA Sessão de Julgamento",
                     font=ctk.CTkFont("Segoe UI", 22, "bold"),
                     text_color=COR_PRIMARIA).pack(pady=(16, 0))
        ctk.CTkLabel(header, text="Launcher headless -- o monitoramento roda na extensão de Chrome (extension/)",
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

        self.entry_perfil = campo(
            "PERFIL (câmara/gabinete -- ex: 10CACIV/GERENTE GABINETE/SECRETARIA)",
            default=self.perfil_salvo,
        )
        self.entry_orgao = campo("ÓRGÃO (câmara -- ex: 10ª CÂMARA CÍVEL)")

        row_datas = ctk.CTkFrame(card, fg_color="transparent")
        row_datas.pack(fill="x", padx=20, pady=(10, 0))
        col_ini = ctk.CTkFrame(row_datas, fg_color="transparent")
        col_ini.pack(side="left", fill="x", expand=True, padx=(0, 6))
        col_fim = ctk.CTkFrame(row_datas, fg_color="transparent")
        col_fim.pack(side="left", fill="x", expand=True, padx=(6, 0))

        ctk.CTkLabel(col_ini, text="DATA INICIAL (dd/mm/aaaa)", font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO, anchor="w").pack(fill="x")
        self.entry_data_inicial = ctk.CTkEntry(col_ini, font=ctk.CTkFont("Segoe UI", 11),
                                                fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                                                border_color=COR_BORDA, border_width=1,
                                                corner_radius=6, height=34)
        self.entry_data_inicial.insert(0, datetime.now().strftime("%d/%m/%Y"))
        self.entry_data_inicial.pack(fill="x")

        ctk.CTkLabel(col_fim, text="DATA FINAL (dd/mm/aaaa)", font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO, anchor="w").pack(fill="x")
        self.entry_data_final = ctk.CTkEntry(col_fim, font=ctk.CTkFont("Segoe UI", 11),
                                              fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                                              border_color=COR_BORDA, border_width=1,
                                              corner_radius=6, height=34)
        self.entry_data_final.pack(fill="x")

        self.chk_headless = ctk.CTkCheckBox(card, text="Executar em segundo plano (sem abrir o navegador)",
                                             font=ctk.CTkFont("Segoe UI", 10), text_color=COR_TEXTO)
        self.chk_headless.select()
        self.chk_headless.pack(anchor="w", padx=20, pady=(14, 16))

        row_botoes = ctk.CTkFrame(card, fg_color="transparent")
        row_botoes.pack(fill="x", padx=20, pady=(0, 20))
        self.btn_iniciar = ctk.CTkButton(row_botoes, text="▶  INICIAR ACOMPANHAMENTO",
                                          font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                          fg_color=COR_PRIMARIA, hover_color=COR_HOVER,
                                          height=42, corner_radius=8, command=self._iniciar)
        self.btn_iniciar.pack(side="left", fill="x", expand=True)
        self.btn_parar = ctk.CTkButton(row_botoes, text="⏹ PARAR",
                                        font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                        fg_color=COR_ERRO, hover_color="#b8352a",
                                        height=42, corner_radius=8, width=100,
                                        state="disabled", command=self._parar)
        self.btn_parar.pack(side="left", padx=(8, 0))

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

    def _iniciar(self):
        if self._executando:
            return
        perfil = self.entry_perfil.get().strip()
        orgao = self.entry_orgao.get().strip()
        data_inicial = self.entry_data_inicial.get().strip()
        data_final = self.entry_data_final.get().strip()
        headless = bool(self.chk_headless.get())

        if not (perfil and orgao):
            messagebox.showerror("AURA Sessão de Julgamento", "Preencha ao menos Perfil e Órgão.")
            return

        salvar_config(self.usuario, self.senha, self.url, perfil)

        config = ConfigAcompanhamento(
            usuario=self.usuario, senha=self.senha, url=self.url, perfil=perfil,
            orgao_descricao=orgao, data_inicial=data_inicial, data_final=data_final,
            headless=headless,
        )

        self._executando = True
        self._deve_continuar = True
        self.btn_iniciar.configure(state="disabled", text="⏳  ACOMPANHANDO...")
        self.btn_parar.configure(state="normal")
        self._set_status("Executando -- acompanhamento contínuo até você clicar em Parar.", COR_AVISO)
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

        threading.Thread(target=self._executar_em_thread, args=(config,), daemon=True).start()

    def _parar(self):
        self._deve_continuar = False
        self._set_status("Parando (aguardando fim do ciclo atual)...", COR_AVISO)

    def _executar_em_thread(self, config: ConfigAcompanhamento):
        try:
            executar_acompanhamento(config, log=self._log_thread_safe,
                                     deve_continuar=lambda: self._deve_continuar)
            self._set_status("Acompanhamento encerrado.", COR_SUCESSO)
        except Exception as exc:
            logger.exception("Falha no acompanhamento da sessao de julgamento")
            self._log_thread_safe(f"\n[ERRO FATAL] {exc}")
            self._set_status(f"Erro: {exc}", COR_ERRO)
        finally:
            self.after(0, lambda: self.btn_iniciar.configure(state="normal", text="▶  INICIAR ACOMPANHAMENTO"))
            self.after(0, lambda: self.btn_parar.configure(state="disabled"))
            self._executando = False


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.withdraw()
    app = AuraSessaoJulgamentoApp(root)
    app.protocol("WM_DELETE_WINDOW", lambda: (app.destroy(), root.destroy()))
    root.mainloop()
