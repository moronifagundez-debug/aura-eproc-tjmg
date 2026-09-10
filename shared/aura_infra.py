"""
Utilitarios de infraestrutura compartilhados entre aura.py, run_aura_cotri.py
e auragabinete.py: instanciacao resiliente do chromedriver, checagem de
atualizacao via GitHub, e helpers de UI (escala DPI, clarear cor).

Consolidado a partir de copias identicas que existiam nesses 3 arquivos.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import json

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# ===============================
# INSTANCIAÇÃO RESILIENTE DO CHROMEDRIVER
# ===============================
def _matar_processos_chromedriver():
    """Finaliza chromedriver.exe zumbis que podem travar o cache do webdriver_manager."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chromedriver.exe", "/T"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


def _limpar_cache_wdm():
    """Remove o cache do webdriver_manager (~/.wdm) quando fica corrompido/desatualizado."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".wdm")
    shutil.rmtree(cache_dir, ignore_errors=True)


def _erro_e_acesso_negado(e, msg):
    msg_low = msg.lower()
    return isinstance(e, PermissionError) or "winerror 5" in msg_low or "acesso negado" in msg_low or "access is denied" in msg_low


def _erro_e_versao_incompativel(msg):
    """Detecta o erro clássico quando o Chrome foi atualizado e o chromedriver em cache é de outra versão."""
    msg_low = msg.lower()
    return (
        "session not created" in msg_low
        or "only supports chrome version" in msg_low
        or "this version of chromedriver" in msg_low
    )


def obter_chromedriver_path(max_tentativas=3, forcar_atualizacao=False):
    """Instala/baixa o chromedriver via webdriver_manager com retries."""
    if forcar_atualizacao:
        _limpar_cache_wdm()
    ultimo_erro = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            return ChromeDriverManager().install()
        except Exception as e:
            ultimo_erro = e
            msg = str(e)
            if _erro_e_acesso_negado(e, msg):
                _matar_processos_chromedriver()
                time.sleep(1.5)
                if tentativa >= 2:
                    _limpar_cache_wdm()
                    time.sleep(1)
                continue
            raise
    raise RuntimeError(
        f"Não foi possível instalar o chromedriver após {max_tentativas} tentativa(s) "
        f"(último erro: {ultimo_erro})."
    )


def criar_chrome_driver(options):
    """Instancia webdriver.Chrome de forma resiliente: sobrevive a chromedriver travado
    por antivírus/zumbi E a Chrome atualizado com cache de driver desatualizado."""
    caminho = obter_chromedriver_path()
    try:
        return webdriver.Chrome(service=Service(caminho), options=options)
    except Exception as e:
        msg = str(e)
        if _erro_e_acesso_negado(e, msg) or _erro_e_versao_incompativel(msg):
            _matar_processos_chromedriver()
            time.sleep(1.5)
            caminho = obter_chromedriver_path(forcar_atualizacao=True)
            return webdriver.Chrome(service=Service(caminho), options=options)
        raise


def verificar_atualizacao(versao_atual, github_repo):
    """Verifica no GitHub se há versão mais recente. Retorna (tem_update, versao_nova, url_download)."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{github_repo}/releases/latest",
            headers={"User-Agent": "AURA"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            dados = json.loads(resp.read())
            versao_nova = dados.get("tag_name", "").lstrip("v")
            url_download = dados.get("html_url", f"https://github.com/{github_repo}/releases/latest")
            tem_update = versao_nova and versao_nova != versao_atual
            return tem_update, versao_nova, url_download
    except Exception:
        return False, None, None


# ===============================
# HELPERS DE UI
# ===============================
def _detectar_scaling():
    """Detecta DPI da tela e ajusta scaling do CTK automaticamente."""
    try:
        if sys.platform == "win32":
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            scale = round(dpi / 96, 1)  # 96 DPI = 100% = scale 1.0
            return max(1.0, min(scale, 2.0))  # limita entre 1.0 e 2.0
    except Exception:
        pass
    return 1.0


def _lighten(hex_color):
    r = min(255, int(hex_color[1:3], 16) + 20)
    g = min(255, int(hex_color[3:5], 16) + 20)
    b = min(255, int(hex_color[5:7], 16) + 20)
    return f"#{r:02x}{g:02x}{b:02x}"
