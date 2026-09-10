import threading
import time
import os
import sys
import csv
import subprocess
import shutil
import traceback

# Modulos foram organizados em subpastas (integrations/, shared/) em vez de
# soltos na raiz -- adiciona ambas ao sys.path para que os imports abaixo
# (flat, sem prefixo de pacote) continuem funcionando sem alterar o resto
# do arquivo. Precisa vir antes de qualquer "import" de modulo proprio.
_DIR_BASE = os.path.dirname(os.path.abspath(__file__))
for _sub in ("shared", "integrations"):
    _caminho = os.path.join(_DIR_BASE, _sub)
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

from aura_db import (
    gravar_processo_ajuizado,
    ler_processos_ajuizados,
    gravar_historico_intermediario,
    ler_historico_intermediario,
    inicializar_planilha,
)
from aura_sheet_selector import SheetSelectorFrame
from aura_infra import (
    _matar_processos_chromedriver,
    _limpar_cache_wdm,
    _erro_e_acesso_negado,
    _erro_e_versao_incompativel,
    obter_chromedriver_path,
    criar_chrome_driver,
    verificar_atualizacao as _verificar_atualizacao_infra,
    _detectar_scaling,
    _lighten,
)
import json
import urllib.request
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext
import customtkinter as ctk
from tkinter import messagebox
from PIL import Image
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
from webdriver_manager.chrome import ChromeDriverManager


# ===============================
# CONFIGURAÇÕES E GLOBAIS
# ===============================
VERSAO_ATUAL = "9.21"
GITHUB_REPO = "marcelopenaguerra/aura_eproc"
ARQUIVO_CONFIG = "aura_config.json"
ARQUIVO_CONFIG_PADRAO = "aura_api_padrao.json"


def base_path(filename):
    """Resolve caminho do arquivo tanto em dev quanto no .exe"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


CAMINHO_PDF = None
DADOS_COMPETENCIA = []   # linhas carregadas do Google Sheets
NOME_COMPETENCIA = ""    # nome da aba selecionada
import auragabinete as _auragabinete
import run_aura_cotri as _run_cotri
import run_aura_eventoscamaracivel as _run_eventoscamaracivel
import run_aura_sessao_julgamento as _run_sessaojulgamento
import aura_regressao_homologacao as _run_regressao_homologacao

_TEXTO_MINUTA_TESTE_REGRESSAO = (
    "Vistos etc.\n\n"
    "Trata-se de pedido de antecipação de tutela recursal. "
    "Ausentes os requisitos legais para a concessão da medida "
    "(fumus boni iuris e periculum in mora), indefiro o pedido de "
    "antecipação de tutela.\n\n"
    "[TESTE DE REGRESSÃO AURA -- NÃO É UMA DECISÃO REAL]"
)

USUARIO = os.environ.get("AURA_USUARIO", "")
SENHA = os.environ.get("AURA_SENHA", "")
URL = "https://eproc2g-hml.tjmg.jus.br/eproc/"
PAUSADO = False
lbl_strip_comp = None
lbl_strip_pdf = None


def _pasta_config_externa():
    """Pasta gravável onde o config do usuário fica salvo (ao lado do .exe/script)."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def salvar_config(usuario, senha, url, groq_key=""):
    """Salva credenciais e URL no arquivo de configuração local (ao lado do executável)."""
    try:
        dados = {"usuario": usuario, "senha": senha, "url": url, "groq_key": groq_key}
        caminho = os.path.join(_pasta_config_externa(), ARQUIVO_CONFIG)
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(dados, f)
    except Exception as e:
        print(f"[aura] Aviso: falha ao salvar config em {ARQUIVO_CONFIG}: {e}")


def carregar_config():
    """Carrega configurações salvas ao lado do executável. Se ainda não houver
    chave de IA definida, usa a chave padrão embutida no próprio .exe."""
    dados = {}
    try:
        caminho = os.path.join(_pasta_config_externa(), ARQUIVO_CONFIG)
        if os.path.exists(caminho):
            with open(caminho, 'r', encoding='utf-8') as f:
                dados = json.load(f)
    except Exception as e:
        print(f"[aura] Aviso: falha ao carregar config de {ARQUIVO_CONFIG}: {e}")
    if not dados.get("groq_key"):
        try:
            with open(base_path(ARQUIVO_CONFIG_PADRAO), 'r', encoding='utf-8') as f:
                dados["groq_key"] = json.load(f).get("groq_key", "")
        except Exception as e:
            print(f"[aura] Aviso: falha ao carregar chave de IA padrao ({ARQUIVO_CONFIG_PADRAO}): {e}")
    return dados


def verificar_atualizacao():
    """Verifica no GitHub se há versão mais recente. Retorna (tem_update, versao_nova, url_download)."""
    return _verificar_atualizacao_infra(VERSAO_ATUAL, GITHUB_REPO)


import AURAAGENT as _agente_mod

GROQ_API_KEY = carregar_config().get("groq_key", "")


def salvar_no_historico(dados):
    gravar_processo_ajuizado(
        data=dados.get("Data", ""),
        classe=dados.get("Classe", ""),
        magistrado=dados.get("Magistrado", ""),
        processo=dados.get("Processo", ""),
        chave=dados.get("Chave", ""),
        aviso=dados.get("Aviso", ""),
        competencia=dados.get("Competência", ""),
    )


def salvar_historico_intermediario(dados):
    gravar_historico_intermediario(
        processo=dados.get("Processo", ""),
        evento=dados.get("Evento", ""),
        tipodocumento=dados.get("Tipodocumento", ""),
        status=dados.get("Status", ""),
        motivo=dados.get("Motivo", ""),
        data=dados.get("Data", None),
    )


def capturar_dados_finais(driver, wait, aviso=""):
    try:
        num_processo = wait.until(EC.presence_of_element_located((By.ID, "lblDesNumProcesso"))).text
        classe = driver.find_element(By.ID, "lblDesClasse").text
        juiz = driver.find_element(By.ID, "lblDesJuiz").text
        chave = driver.find_element(By.ID, "lblDesChaveConsulta").text
        dados = {
            "Data": time.strftime("%d/%m/%Y"),
            "Classe": classe.strip(),
            "Magistrado": juiz.strip(),
            "Processo": num_processo.strip(),
            "Chave": chave.strip(),
            "Aviso": aviso,
            "Competência": NOME_COMPETENCIA,
        }
        salvar_no_historico(dados)
        return dados
    except:
        return None


def clicar_seguro(driver, wait, xpath):
    try:
        elemento = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", elemento)
    except Exception as e:
        print(f"[aura] Aviso: clicar_seguro falhou em {xpath}: {e}")


def aceitar_alertas_pendentes(driver, tentativas=3):
    """Aceita alertas do navegador, como o OK dos avisos do eproc."""
    aceitou = False
    for _ in range(tentativas):
        try:
            driver.switch_to.alert.accept()
            aceitou = True
            time.sleep(0.5)
        except:
            break
    return aceitou


def abrir_peticao_inicial_menu_textual(driver, wait):
    """Volta direto para Peticao Inicial pelo menu textual do eproc."""
    driver.switch_to.default_content()
    xpaths = [
        "//a[@aria-label='Petição Inicial']",
        "//a[@aria-label='Peticao Inicial']",
        "//a[@title='Petição Inicial']",
        "//a[@title='Peticao Inicial']",
        "//a[normalize-space()='Petição Inicial']",
        "//a[normalize-space()='Peticao Inicial']",
        "//a[contains(normalize-space(.), 'Petição Inicial')]",
        "//a[contains(normalize-space(.), 'Peticao Inicial')]",
        "//*[contains(@id, 'menu') or contains(@class, 'menu')]//a[contains(normalize-space(.), 'Petição Inicial')]",
        "//*[contains(@id, 'menu') or contains(@class, 'menu')]//a[contains(normalize-space(.), 'Peticao Inicial')]",
    ]
    ultimo_erro = None
    for xpath in xpaths:
        try:
            link = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", link)
            aceitar_alertas_pendentes(driver)
            wait.until(EC.presence_of_element_located((By.XPATH, "//a[@aria-label='Petição Inicial']")))
            return True
        except Exception as e:
            ultimo_erro = e
            aceitar_alertas_pendentes(driver)

    try:
        link = driver.execute_script("""
            const normalizar = (valor) => (valor || '')
                .normalize('NFD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .toLowerCase()
                .trim();
            return Array.from(document.querySelectorAll('a'))
                .find(a => normalizar(a.innerText || a.textContent || a.getAttribute('aria-label') || a.title)
                    .includes('peticao inicial'));
        """)
        if link:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", link)
            aceitar_alertas_pendentes(driver)
            return True
    except Exception as e:
        ultimo_erro = e

    raise Exception(f"Não foi possível abrir Petição Inicial pelo menu textual: {ultimo_erro}")


def analisar_erro_com_ia(erro, contexto=""):
    """Envia o erro para o Groq e retorna uma análise amigável."""
    try:
        prompt = f"""Você é um assistente técnico do sistema AURA, um robô de peticionamento eletrônico do TJMG (Tribunal de Justiça de Minas Gerais).

O robô encontrou o seguinte erro durante o peticionamento:
ERRO: {erro}
CONTEXTO: {contexto}

Explique em português simples:
1. O que causou esse erro
2. O que o usuário pode fazer para resolver

Seja direto e objetivo. Máximo 5 linhas."""

        dados = json.dumps({
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=dados,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "AURA-TJMG/9.21",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resultado = json.loads(resp.read())
            return resultado["choices"][0]["message"]["content"]
    except:
        return None


def mostrar_erro_com_ia(erro, contexto=""):
    """Exibe janela de erro com análise da IA."""
    janela_erro = tk.Toplevel()
    janela_erro.title("❌ Erro AURA")
    janela_erro.geometry("540x400")
    janela_erro.configure(bg="#1f2933")
    janela_erro.grab_set()
    janela_erro.lift()
    janela_erro.focus_force()

    tk.Label(janela_erro, text="❌  Erro durante o peticionamento",
             font=("Segoe UI", 12, "bold"), bg="#1f2933", fg="#EF4444").pack(pady=(20, 5))

    tk.Label(janela_erro, text="Erro técnico:",
             font=("Segoe UI", 9), bg="#1f2933", fg="#9ca3af").pack(anchor="w", padx=20)

    txt_erro = scrolledtext.ScrolledText(janela_erro, height=4, font=("Courier New", 9),
                                         bg="#111827", fg="#F87171", relief="flat", wrap="word")
    txt_erro.pack(fill="x", padx=20, pady=(0, 10))
    txt_erro.insert("1.0", str(erro))
    txt_erro.configure(state="disabled")

    tk.Label(janela_erro, text="🤖  Análise do Assistente:",
             font=("Segoe UI", 9, "bold"), bg="#1f2933", fg="#10b981").pack(anchor="w", padx=20)

    txt_ia = scrolledtext.ScrolledText(janela_erro, height=6, font=("Segoe UI", 10),
                                       bg="#111827", fg="white", relief="flat", wrap="word")
    txt_ia.pack(fill="x", padx=20, pady=(0, 10))
    txt_ia.insert("1.0", "Consultando assistente...")
    txt_ia.configure(state="disabled")

    def carregar_analise():
        analise = analisar_erro_com_ia(erro, contexto)
        txt_ia.configure(state="normal")
        txt_ia.delete("1.0", "end")
        txt_ia.insert("1.0",
                      analise if analise else "Não foi possível consultar o assistente. Verifique a chave GROQ_API_KEY.")
        txt_ia.configure(state="disabled")

    threading.Thread(target=carregar_analise, daemon=True).start()
    tk.Button(janela_erro, text="Fechar", font=("Segoe UI", 10),
              bg="#374151", fg="white", relief="flat", width=15,
              command=janela_erro.destroy).pack(pady=10)
    janela_erro.wait_window()


def proxima(driver):
    driver.execute_script('var btn = document.querySelector("#btnProxima"); if(btn) btn.click();')


def verificar_pausa(status):
    """Aguarda se o sistema estiver pausado."""
    global PAUSADO
    while PAUSADO:
        status.configure(text="⏸ Pausado — clique em Retomar para continuar...")
        time.sleep(0.5)


def campo_visivel(driver, elemento_id):
    """Verifica se um campo existe e está visível na tela."""
    try:
        el = driver.find_elements(By.ID, elemento_id)
        return el and el[0].is_displayed()
    except:
        return False


def campo_existe(driver, elemento_id):
    """Verifica se um campo existe na tela, visível ou não."""
    return len(driver.find_elements(By.ID, elemento_id)) > 0


# IDs de campos de formulário que o AURA conhece e interage com.
# Qualquer ID novo detectado nas telas do eProc será registrado em
# campos_desconhecidos_eproc.json para análise posterior.
CAMPOS_CONHECIDOS_EPROC = {
    # Login
    "txtUsuario", "pwdSenha",
    # Tela 1 — dados iniciais
    "selIdGrupoCompetencia", "selIdClasseJudicial", "selTipoJustica",
    "chkNaoAplicaValor", "chkRenunciaValor", "chkValorAlcada",
    "txtProcessoOriginario", "txtDescJuizo",
    "selLocalidadeJudicial", "selIdSigilo", "selInfraUnidades",
    "selTipoJusticaProcesso", "selTipoOrigemJudicial", "selIdJuizo",
    "chkRemeterPlantao",
    "txtValorCausa", "txtSinExibeOriginario", "txtSinExigeOriginario", "txtSinVinculaOriginario",
    # Tela Assunto
    "txtFiltroPesquisa", "txtDesAssunto", "txtArtigo", "txtNorma", "txtGlossario",
    "txt-C-livre", "txt-D-livre", "txt-M-livre",
    # Tela Partes — pessoa física
    "txtCpfCnpj", "selTipoPessoa", "txtNome", "txtNumDoc",
    "chkSemCpfCnpj", "selSemCpf", "selSemCnpj", "selTipoDoc", "selTipoFiltroNome",
    "selPrincipalEnt", "selEntidade",
    # Tela Partes — juízo federal e estadual
    "txtJuizoFederal", "txtJuizoEstadual",
    # Tela Partes — entidade
    "txtEntidade",
    # Tela Partes — autoridade coatora
    "txtDesAutoridade",
    # Tela Documentos
    "txtTipo_1",
    # Pesquisa rápida (barra superior, presente em todas as telas)
    "txtNumProcessoPesquisaRapida",
}


def detectar_campos_novos(driver, tela, status, num_fila):
    """Varre a tela atual do eProc em busca de campos de formulário não mapeados.

    Campos com IDs desconhecidos são logados no status e salvos em
    campos_desconhecidos_eproc.json com timestamp, tela e número da linha.
    """
    try:
        prefixos_form = ("txt", "sel", "chk", "pwd", "rad")
        # IDs gerados dinamicamente pelo eProc (ex: selJusticaAutor1234567890...)
        prefixos_dinamicos = ("selJusticaAutor", "selJusticaReu", "divInfraAjax")
        elementos = driver.find_elements(By.CSS_SELECTOR, "input, select, textarea")
        ids_pagina = {
            e.get_attribute("id") for e in elementos
            if e.get_attribute("id")
            and e.get_attribute("id").startswith(prefixos_form)
            and not e.get_attribute("id").startswith(prefixos_dinamicos)
        }
        novos = ids_pagina - CAMPOS_CONHECIDOS_EPROC
        if not novos:
            return

        lista = ", ".join(sorted(novos))

        sugestao_ia = None
        try:
            dados_linha = DADOS_COMPETENCIA[num_fila - 1] if 0 < num_fila <= len(DADOS_COMPETENCIA) else {}
            sugestao_ia = _agente_mod.sugerir_campo_desconhecido(tela, sorted(novos), dados_linha)
        except Exception:
            sugestao_ia = None

        if sugestao_ia:
            status.configure(text=f"L{num_fila}: ⚠ Campos novos em '{tela}': {lista} | IA: {sugestao_ia[:120]}")
        else:
            status.configure(text=f"L{num_fila}: ⚠ Campos novos em '{tela}': {lista}")

        arquivo = "campos_desconhecidos_eproc.json"
        historico = []
        if os.path.exists(arquivo):
            with open(arquivo, "r", encoding="utf-8") as f:
                try:
                    historico = json.load(f)
                except Exception:
                    historico = []

        historico.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tela": tela,
            "linha": num_fila,
            "campos_novos": sorted(novos),
            "sugestao_ia": sugestao_ia,
        })

        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)

    except Exception:
        pass


def _registrar_revisao_ia(num_fila, dados, revisao):
    """Registra alertas da revisão de IA feita antes da confirmação final,
    para auditoria posterior. Nunca lança exceção nem interrompe o lote."""
    try:
        arquivo = "revisoes_ia_peticionamento.json"
        historico = []
        if os.path.exists(arquivo):
            with open(arquivo, "r", encoding="utf-8") as f:
                try:
                    historico = json.load(f)
                except Exception:
                    historico = []
        historico.append({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "linha": num_fila,
            "dados": dados,
            "revisao_ia": revisao,
        })
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def normalizar_separador_parte(texto):
    """Planilhas usam tanto '=' quanto '-' como separador entre o rótulo
    (Entidade, Juízo, Autoridade Coatora, Pessoa Jurídica) e o valor.
    Normaliza para '=' para que a classificação e a extração funcionem
    independente do separador usado na linha."""
    import re
    return re.sub(
        r"^\s*(JU[ÍI]ZO|ENTIDADE|AUTORIDADE COATORA|PESSOA JUR[ÍI]DICA)\s*-\s*",
        r"\1 = ",
        str(texto or ""),
        flags=re.IGNORECASE,
    )


def extrair_documento_parte(texto):
    """Extrai CPF/CNPJ da descricao da parte na planilha."""
    import re
    texto = str(texto or "").replace("\n", " ").replace("\r", " ").strip()
    depois_igual = texto.split("=", 1)[-1] if "=" in texto else texto
    match = re.search(r"[\d\.\-/]{8,20}", depois_igual)
    if not match:
        return ""
    return re.sub(r"\D", "", match.group(0))


def extrair_nome_parte(texto):
    """Extrai nome/descricao da parte a partir da coluna Tipoautor/Tiporeu."""
    import re
    texto = str(texto or "").replace("\n", " ").replace("\r", " ").strip()
    match_parenteses = re.search(r"\(([^)]+)\)", texto)
    if match_parenteses:
        return match_parenteses.group(1).strip()
    parte = texto.split("=", 1)[-1] if "=" in texto else texto
    parte = re.sub(r"[\d\.\-/]{8,20}", "", parte)
    parte = re.sub(r"\s+", " ", parte)
    return parte.strip()


def incluir_pessoa_fisica(driver, wait, status, num_fila, polo_nome, dados_parte):
    """Inclui pessoa fisica usando CPF/nome informado na propria planilha."""
    documento = extrair_documento_parte(dados_parte)
    nome = extrair_nome_parte(dados_parte)
    identificador = documento or nome
    if not identificador:
        status.configure(text=f"L{num_fila}: {polo_nome} sem CPF/nome na planilha.")
        return False

    try:
        status.configure(text=f"L{num_fila}: Preenchendo {polo_nome} ({identificador[:20]})...")

        # Se o eProc usar txtNumDoc em vez de txtCpfCnpj, adapta
        campo_cpf_id = "txtCpfCnpj" if campo_existe(driver, "txtCpfCnpj") else (
            "txtNumDoc" if campo_existe(driver, "txtNumDoc") else None
        )

        if documento and campo_cpf_id and campo_visivel(driver, campo_cpf_id):
            try:
                if campo_existe(driver, "selTipoPessoa"):
                    Select(wait.until(EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("PF")
                    time.sleep(0.5)
                # selTipoDoc (alternativa ao selTipoPessoa em versões novas do eproc)
                elif campo_existe(driver, "selTipoDoc"):
                    try:
                        sel_td = Select(driver.find_element(By.ID, "selTipoDoc"))
                        opcoes = [o.get_attribute("value") for o in sel_td.options]
                        if "PF" in opcoes:
                            sel_td.select_by_value("PF")
                            time.sleep(0.5)
                    except:
                        pass
            except:
                pass
            campo_doc = wait.until(EC.presence_of_element_located((By.ID, campo_cpf_id)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo_doc)
            campo_doc.clear()
            campo_doc.send_keys(documento)
            clicar_seguro(driver, wait, '//*[@id="btnConsultarNome"]')
            time.sleep(1.5)
            clicar_seguro(driver, wait, '//*[@id="btnIncluir"]')
            time.sleep(1.5)
            return True

        if not nome or not campo_existe(driver, "txtNome"):
            return False

        campo_nome = wait.until(EC.presence_of_element_located((By.ID, "txtNome")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo_nome)
        driver.execute_script("arguments[0].value = '';", campo_nome)
        time.sleep(0.3)
        campo_nome.send_keys(nome)
        time.sleep(0.5)
        clicar_seguro(driver, wait, '//*[@id="btnConsultarNome"]')
        time.sleep(2)
        clicar_seguro(driver, wait, '//*[@id="btnIncluir"]')
        time.sleep(1.5)
        return True
    except:
        return False


_ultimo_aviso = []  # lista mutável para capturar aviso fora do escopo


def erro_na_linha(num_fila, erro, status):
    """Exibe janela de erro por linha com opção de Repetir, Pular ou Parar."""
    status.configure(text=f"L{num_fila}: ERRO — aguardando decisão...")
    resultado = tk.StringVar(value="")
    janela_erro = tk.Toplevel()
    janela_erro.title(f"⚠ Erro na Linha {num_fila}")
    janela_erro.geometry("520x300")
    janela_erro.configure(bg="#1f2933")
    janela_erro.grab_set()
    janela_erro.lift()
    janela_erro.focus_force()
    tk.Label(janela_erro, text=f"Erro na Linha {num_fila}",
             font=("Segoe UI", 13, "bold"), bg="#1f2933", fg="#F59E0B").pack(pady=(18, 6))
    tk.Label(janela_erro, text=str(erro)[:300], wraplength=480,
             font=("Segoe UI", 9), bg="#1f2933", fg="#D1D5DB", justify="left").pack(padx=20)
    tk.Label(janela_erro, text="O que deseja fazer?",
             font=("Segoe UI", 10), bg="#1f2933", fg="#9CA3AF").pack(pady=(12, 4))
    tk.Label(janela_erro, text="⚠ Repetir irá cancelar o processo atual antes de tentar novamente.",
             font=("Segoe UI", 8), bg="#1f2933", fg="#6B7280", wraplength=480).pack()
    frame_btns = tk.Frame(janela_erro, bg="#1f2933")
    frame_btns.pack(pady=12)

    def repetir():
        resultado.set("repetir")
        janela_erro.destroy()

    def pular():
        resultado.set("pular")
        janela_erro.destroy()

    def parar():
        resultado.set("parar")
        janela_erro.destroy()

    tk.Button(frame_btns, text="🔄  REPETIR LINHA", font=("Segoe UI", 10, "bold"),
              bg="#2563EB", fg="white", relief="flat", width=16, command=repetir).pack(side="left", padx=6)
    tk.Button(frame_btns, text="⏭  PULAR LINHA", font=("Segoe UI", 10, "bold"),
              bg="#F59E0B", fg="white", relief="flat", width=16, command=pular).pack(side="left", padx=6)
    tk.Button(frame_btns, text="⏹  PARAR TUDO", font=("Segoe UI", 10, "bold"),
              bg="#EF4444", fg="white", relief="flat", width=16, command=parar).pack(side="left", padx=6)
    janela_erro.wait_window()
    return resultado.get()


def fechar_alerta(driver):
    """Se houver alerta, exibe janela de aviso no AURA e aguarda usuario continuar."""
    try:
        alert = driver.switch_to.alert
        mensagem = alert.text
        alert.accept()
        _ultimo_aviso.append(mensagem)
        # Exibe janela de aviso com botao Continuar
        janela_aviso = tk.Toplevel()
        janela_aviso.title("⚠ Aviso do eProc")
        janela_aviso.geometry("480x220")
        janela_aviso.configure(bg="#1f2933")
        janela_aviso.grab_set()
        janela_aviso.lift()
        janela_aviso.focus_force()
        tk.Label(janela_aviso, text="⚠  Aviso do sistema eProc",
                 font=("Segoe UI", 12, "bold"), bg="#1f2933", fg="#F59E0B").pack(pady=(20, 10))
        tk.Label(janela_aviso, text=mensagem, wraplength=420,
                 font=("Segoe UI", 10), bg="#1f2933", fg="white", justify="center").pack(padx=20)
        tk.Label(janela_aviso, text="Faça as tratativas necessárias e clique em Continuar.",
                 font=("Segoe UI", 9), bg="#1f2933", fg="#9ca3af", wraplength=420).pack(pady=(10, 0))
        continuar = tk.BooleanVar(value=False)

        def on_continuar():
            continuar.set(True)
            janela_aviso.destroy()

        tk.Button(janela_aviso, text="✔  CONTINUAR", font=("Segoe UI", 11, "bold"),
                  bg="#10b981", fg="white", relief="flat", width=20,
                  command=on_continuar).pack(pady=20)
        janela_aviso.wait_window()
    except:
        pass  # sem alerta, continua normalmente


def incluir_autocomplete(driver, wait, actions, campo_id, div_id, nome, btn_incluir_xpath):
    """Digita no campo autocomplete, aguarda sugestão, clica com ActionChains e inclui."""
    campo = wait.until(EC.presence_of_element_located((By.ID, campo_id)))
    # Clica para disparar onclick (limpa valor padrao como "Digite para selecionar...")
    driver.execute_script("arguments[0].click();", campo)
    time.sleep(0.5)
    campo.clear()
    # Limpa via JS caso ainda tenha valor residual
    driver.execute_script("arguments[0].value = '';", campo)
    campo.send_keys(nome[:30])
    time.sleep(3)
    # Aguarda o dropdown ficar visivel
    wait.until(EC.visibility_of_element_located((By.ID, div_id)))
    time.sleep(0.5)
    sugestao = driver.find_element(By.XPATH, f"//div[@id='{div_id}']//li[1]/a")
    # Move o mouse ate a sugestao e clica (simula comportamento humano)
    actions.move_to_element(sugestao).pause(0.3).click().perform()
    time.sleep(2)
    clicar_seguro(driver, wait, btn_incluir_xpath)
    time.sleep(2)


def assunto_principal_incluido(driver):
    """Retorna True quando ha ao menos um assunto principal na tabela."""
    try:
        linhas = driver.find_elements(By.CSS_SELECTOR, "#tblAssuntoPrincipal tbody tr")
        for linha in linhas:
            texto = " ".join(linha.text.split())
            if texto and "nenhum" not in texto.lower():
                return True
    except:
        pass
    return False


def selecionar_assunto_da_planilha(driver, wait, status, num_fila, assunto, tem_originario):
    """Filtra, seleciona e confirma o assunto informado na planilha."""
    assunto = str(assunto or "").strip()
    if not assunto:
        raise Exception("Assunto vazio na planilha.")

    status.configure(text=f"L{num_fila}: Selecionando Assunto ({assunto})...")
    time.sleep(2)

    if tem_originario:
        try:
            btns_remover = driver.find_elements(By.XPATH, '//*[@id="tblAssuntoPrincipal"]/tbody/tr/td[8]/img')
            for btn_remover in btns_remover:
                driver.execute_script("arguments[0].click();", btn_remover)
                time.sleep(0.8)
                try:
                    driver.switch_to.alert.accept()
                except:
                    pass
        except:
            pass

    campo_assunto = wait.until(EC.element_to_be_clickable((By.ID, "txtFiltroPesquisa")))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", campo_assunto)
    time.sleep(0.5)
    campo_assunto.clear()
    campo_assunto.click()
    campo_assunto.send_keys(assunto)
    time.sleep(1)

    btn_filtrar = wait.until(EC.element_to_be_clickable((By.ID, "btnFiltrar")))
    driver.execute_script("arguments[0].click();", btn_filtrar)
    time.sleep(2)

    xpaths_resultado = [
        f'//*[@id="{assunto}_anchor"]',
        f'//*[@id="{assunto}_anchor"]/span/span',
        f'//*[contains(@id, "_anchor") and contains(normalize-space(.), "{assunto}")]',
    ]
    ultimo_erro = None
    for xpath in xpaths_resultado:
        try:
            opcao = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", opcao)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", opcao)
            ultimo_erro = None
            break
        except Exception as e:
            ultimo_erro = e

    if ultimo_erro:
        # Nenhum resultado bateu exatamente com o texto da planilha: pede à IA
        # para escolher, entre as opções realmente exibidas na tela, a mais
        # compatível. Se a IA falhar ou não achar nada razoável, cai no
        # comportamento antigo (erro tratado por erro_na_linha).
        codigo_ia = None
        try:
            opcoes = []
            for el in driver.find_elements(By.XPATH, "//*[contains(@id, '_anchor')]"):
                try:
                    if not el.is_displayed():
                        continue
                    texto = " ".join(el.text.split())
                    id_el = (el.get_attribute("id") or "").replace("_anchor", "")
                    if texto and id_el:
                        opcoes.append((id_el, texto))
                except Exception:
                    continue
            if opcoes:
                status.configure(text=f"L{num_fila}: Assunto '{assunto}' não encontrado exato. Consultando IA...")
                codigo_ia = _agente_mod.escolher_assunto_similar(assunto, opcoes)
        except Exception:
            codigo_ia = None

        if codigo_ia:
            try:
                opcao = wait.until(EC.element_to_be_clickable((By.XPATH, f'//*[@id="{codigo_ia}_anchor"]')))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", opcao)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", opcao)
                status.configure(text=f"L{num_fila}: IA selecionou Assunto '{codigo_ia}' como equivalente a '{assunto}'.")
                ultimo_erro = None
            except Exception:
                ultimo_erro = Exception(f"Assunto {assunto} nao apareceu na pesquisa.")

    if ultimo_erro:
        raise Exception(f"Assunto {assunto} nao apareceu na pesquisa.")

    time.sleep(1)
    clicar_seguro(driver, wait, '//*[@id="btnIncluirAssunto"]')
    fechar_alerta(driver)
    try:
        wait.until(lambda d: assunto_principal_incluido(d))
    except:
        raise Exception(f"Assunto {assunto} nao foi incluido. Confira o codigo na planilha.")

    # Aguarda o AJAX de registro do assunto concluir no servidor antes de avançar.
    # assunto_principal_incluido() confirma apenas o DOM; sem esse sleep o servidor
    # ainda pode estar gravando quando sbmProcessoEtapa2 é enviado, causando
    # getStrDesAssunto() == null na tela de confirmação.
    time.sleep(2)

    clicar_seguro(driver, wait, '//*[@id="sbmProcessoEtapa2"]')
    fechar_alerta(driver)


# ===============================
# ROBÔ PRINCIPAL (AURA)
# ===============================
def executar_peticionamento_lote(status, perfil_cinprot=False):
    global CAMINHO_PDF, DADOS_COMPETENCIA

    try:
        if not CAMINHO_PDF:
            messagebox.showerror("AURA", "Selecione o PDF.")
            return
        if not DADOS_COMPETENCIA:
            messagebox.showerror("AURA", "Selecione uma competência no painel acima.")
            return

        status.configure(text="Status: Inicializando Chrome...")
        chrome_options = Options()
        chrome_options.add_experimental_option("detach", True)
        driver = criar_chrome_driver(chrome_options)
        wait = WebDriverWait(driver, 60)
        actions = ActionChains(driver)

        if not URL:
            messagebox.showerror("AURA", "Informe a URL do sistema.")
            return
        driver.get(URL)
        driver.maximize_window()

        # LOGIN
        if not USUARIO or not SENHA:
            messagebox.showerror("AURA", "Informe o usuário e a senha.")
            return
        status.configure(text="Status: Autenticando...")
        wait.until(EC.presence_of_element_located((By.ID, "txtUsuario"))).send_keys(USUARIO)
        driver.find_element(By.ID, "pwdSenha").send_keys(SENHA)
        clicar_seguro(driver, wait, '//*[@id="sbmEntrar"]')

        # PERFIL
        if perfil_cinprot:
            clicar_seguro(driver, wait, '//*[@data-descricao="DIRETOR DISTRIBUIÇÃO / CINPROT"]')
        else:
            clicar_seguro(driver, wait, '//*[@id="tr1"]')
        clicar_seguro(driver, wait, '//*[@id="action-bar"]/a[1]')

        linhas_lista = DADOS_COMPETENCIA
        idx = 0
        while idx < len(linhas_lista):
                linha = linhas_lista[idx]
                num_fila = idx + 1
                avisos_linha = []
                _ultimo_aviso.clear()
                status.configure(text=f"Processando Linha {num_fila}...")
                verificar_pausa(status)
                _erro_linha = False
                try:
                    time.sleep(2)
                    wait.until(EC.presence_of_element_located((By.XPATH, "//a[@aria-label='Petição Inicial']")))
                    clicar_seguro(driver, wait, "//a[@aria-label='Petição Inicial']")

                    id_area = int(linha['AREA'].split("POS ")[-1])
                    id_classe = int(linha['Classeprocessual'].split("POS ")[-1])
                    proc_orig = str(linha['Numero de processo originario']).strip().replace('\n', '').replace('\r', '')
                    tipo_doc = str(linha.get('Tipodocumento', 'Petição inicial')).strip()
                    tipo_justica = str(
                        linha.get('tipojustica', linha.get('Tipodejustica', linha.get('Tipojustica', '')))).strip()
                    tipo_autor = normalizar_separador_parte(
                        str(linha.get('Tipoautor', 'Pessoa física')).strip().replace("\n", "").replace("\r", ""))
                    tipo_reu = normalizar_separador_parte(
                        str(linha.get('Tiporeu', 'Pessoa física')).strip().replace("\n", "").replace("\r", ""))
                    assunto = str(linha.get('Assunto ', linha.get('Assunto', ''))).strip()

                    tem_originario = proc_orig and proc_orig.upper() != "NAO PRECISA" and proc_orig.lower() != "nan"

                    # --- Detecta tipo do autor ---
                    tipo_autor_upper = tipo_autor.upper()
                    cpf_autor = extrair_documento_parte(tipo_autor)
                    if tipo_autor_upper.startswith("JUÍZO =") or tipo_autor_upper.startswith("JUIZO ="):
                        nome_juizo_autor = extrair_nome_parte(tipo_autor)
                        modo_autor = "JUIZO"
                    elif tipo_autor_upper.startswith("ENTIDADE ="):
                        nome_entidade_autor = extrair_nome_parte(tipo_autor)
                        modo_autor = "ENTIDADE"
                    elif tipo_autor_upper.startswith("AUTORIDADE COATORA ="):
                        nome_autoridade_autor = extrair_nome_parte(tipo_autor)
                        modo_autor = "AUTORIDADE"
                    elif tipo_autor_upper.startswith("PESSOA JURÍDICA =") or tipo_autor_upper.startswith(
                            "PESSOA JURIDICA ="):
                        modo_autor = "PJ"
                    else:
                        modo_autor = "PESSOA"

                    # --- Detecta tipo do réu ---
                    tipo_reu_upper = tipo_reu.upper()
                    cpf_reu = extrair_documento_parte(tipo_reu)
                    if tipo_reu_upper.startswith("JUÍZO =") or tipo_reu_upper.startswith("JUIZO ="):
                        nome_juizo = extrair_nome_parte(tipo_reu)
                        modo_reu = "JUIZO"
                    elif tipo_reu_upper.startswith("ENTIDADE ="):
                        nome_entidade_reu = extrair_nome_parte(tipo_reu)
                        modo_reu = "ENTIDADE"
                    elif tipo_reu_upper.startswith("AUTORIDADE COATORA ="):
                        nome_autoridade_reu = extrair_nome_parte(tipo_reu)
                        modo_reu = "AUTORIDADE"
                    elif tipo_reu_upper.startswith("PESSOA JURÍDICA =") or tipo_reu_upper.startswith(
                            "PESSOA JURIDICA ="):
                        modo_reu = "PJ"
                    elif tipo_reu_upper.strip() in ("NAO PRECISA", "", "NAN"):
                        modo_reu = "NENHUM"
                    else:
                        modo_reu = "PESSOA"

                    # --- TELA 1: DADOS INICIAIS ---
                    sel_area = Select(wait.until(EC.presence_of_element_located((By.ID, "selIdGrupoCompetencia"))))
                    detectar_campos_novos(driver, "Tela 1 - Dados Iniciais", status, num_fila)
                    sel_area.select_by_index(id_area)
                    time.sleep(3)
                    wait.until(lambda d: len(Select(d.find_element(By.ID, "selIdClasseJudicial")).options) > 1)
                    Select(driver.find_element(By.ID, "selIdClasseJudicial")).select_by_index(id_classe)
                    time.sleep(1)
                    # Seleciona tipo de justica se informado na planilha
                    if tipo_justica:
                        try:
                            nth = "1" if tipo_justica == "1" else "2"
                            driver.execute_script(
                                f"document.querySelector('#selTipoJustica > option:nth-child({nth})').selected = true; verificarTipoJustica();")
                            time.sleep(1)
                        except Exception as e:
                            print(f"[aura] Aviso: L{num_fila}: falha ao selecionar Tipo de Justica: {e}")

                    # Seleciona localidade judicial se informado na planilha
                    localidade = str(linha.get('Localidade', linha.get('localidade', ''))).strip()
                    if localidade:
                        try:
                            sel_loc = driver.find_elements(By.ID, "selLocalidadeJudicial")
                            if sel_loc and sel_loc[0].is_displayed():
                                Select(sel_loc[0]).select_by_visible_text(localidade)
                                time.sleep(0.5)
                        except Exception as e:
                            print(f"[aura] Aviso: L{num_fila}: falha ao selecionar Localidade Judicial '{localidade}': {e}")

                    # Marca "Não se aplica" no valor da causa — tenta vários IDs conforme versão do eProc
                    time.sleep(1.5)
                    _chk_valor_ids = ("chkNaoAplicaValor", "chkRenunciaValor", "chkValorAlcada")
                    for _chk_id in _chk_valor_ids:
                        try:
                            chk = driver.find_elements(By.ID, _chk_id)
                            if chk and chk[0].is_displayed() and not chk[0].is_selected():
                                driver.execute_script("arguments[0].click();", chk[0])
                                time.sleep(0.5)
                                break
                        except Exception as e:
                            print(f"[aura] Aviso: L{num_fila}: falha ao marcar checkbox de valor da causa '{_chk_id}': {e}")

                    if tem_originario:
                        try:
                            sel_origem = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.ID, "selTipoOrigemJudicial")))
                            Select(sel_origem).select_by_visible_text("Sentença e Acórdão")
                            time.sleep(1)
                        except:
                            pass
                        campo_orig = wait.until(EC.presence_of_element_located((By.ID, "txtProcessoOriginario")))
                        campo_orig.clear()
                        campo_orig.send_keys(proc_orig)
                        time.sleep(1)
                        for _chk_id in _chk_valor_ids:
                            try:
                                chk = driver.find_elements(By.ID, _chk_id)
                                if chk and not chk[0].is_selected():
                                    driver.execute_script("arguments[0].click();", chk[0])
                                    break
                            except Exception as e:
                                print(f"[aura] Aviso: L{num_fila}: falha ao marcar checkbox de valor da causa (originario) '{_chk_id}': {e}")
                        try:
                            campo_juizo_orig = wait.until(EC.presence_of_element_located((By.ID, "txtDescJuizo")))
                            actions.double_click(campo_juizo_orig).perform()
                            time.sleep(1.5)
                        except Exception as e:
                            print(f"[aura] Aviso: L{num_fila}: falha ao abrir autocomplete de Juizo Originario: {e}")

                    clicar_seguro(driver, wait, '//*[@id="btnSalvar"]')

                    # --- TELA DE IMPORTAÇÃO (APENAS SE TIVER ORIGINÁRIO) ---
                    if tem_originario:
                        for polo in ["Autor", "Reu"]:
                            try:
                                time.sleep(2)
                                checkboxes = driver.find_elements(By.CSS_SELECTOR,
                                                                  "input[type='checkbox'][name^='chkInfraItem']")
                                if checkboxes:
                                    if not checkboxes[0].is_selected():
                                        driver.execute_script("arguments[0].click();", checkboxes[0])
                                    clicar_seguro(driver, wait,
                                                  f'//*[@name="sbmProcessoEtapa{1 if polo == "Autor" else 2}"]')
                            except:
                                break

                    # --- TELA DE ASSUNTO ---
                    detectar_campos_novos(driver, "Tela Assunto", status, num_fila)
                    selecionar_assunto_da_planilha(driver, wait, status, num_fila, assunto, tem_originario)

                    # --- TELAS DE PARTES ---
                    for polo_idx, polo_nome in enumerate(["Autor", "Reu"]):
                        fechar_alerta(driver)
                        time.sleep(3)
                        detectar_campos_novos(driver, f"Tela Partes - {polo_nome}", status, num_fila)

                        if tem_originario and polo_idx == 0 and modo_autor == "PESSOA":
                            # Autor importado do originário: verifica se precisa adicionar principal
                            status.configure(text=f"L{num_fila}: Verificando Autor principal...")
                            try:
                                principais = driver.find_elements(By.XPATH, "//table//td[contains(text(),'Sim')]")
                                if not principais:
                                    incluir_pessoa_fisica(driver, wait, status, num_fila, "Autor", tipo_autor)
                            except:
                                pass
                            proxima(driver)

                        elif tem_originario and polo_idx == 1 and modo_reu == "PESSOA":
                            # Verifica se ja existe reu principal importado
                            status.configure(text=f"L{num_fila}: Verificando Reu importado...")
                            try:
                                principais = driver.find_elements(By.XPATH, "//table//td[contains(text(),'Sim')]")
                                if not principais:
                                    incluir_pessoa_fisica(driver, wait, status, num_fila, "Reu", tipo_reu)
                                else:
                                    status.configure(text=f"L{num_fila}: Reu importado, avancando...")
                            except:
                                pass
                            proxima(driver)

                        elif polo_idx == 0 and modo_autor == "JUIZO":
                            # Autor = Juízo (federal ou estadual)
                            if campo_visivel(driver, "txtJuizoFederal"):
                                status.configure(text=f"L{num_fila}: Preenchendo Autor Juizo (federal)...")
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtJuizoFederal", "divInfraAjaxtxtJuizoFederal",
                                                     nome_juizo_autor, '//*[@id="btnIncluirJui"]')
                            elif campo_visivel(driver, "txtJuizoEstadual"):
                                status.configure(text=f"L{num_fila}: Preenchendo Autor Juizo (estadual)...")
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtJuizoEstadual", "divInfraAjaxtxtJuizoEstadual",
                                                     nome_juizo_autor, '//*[@id="btnIncluirJui"]')
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Autor Juizo, avancando...")
                            proxima(driver)

                        elif polo_idx == 0 and modo_autor == "PJ":
                            # Autor = Pessoa Jurídica (CNPJ)
                            if campo_visivel(driver, "txtCpfCnpj"):
                                status.configure(text=f"L{num_fila}: Preenchendo Autor PJ (CNPJ)...")
                                Select(wait.until(
                                    EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("PJ")
                                time.sleep(1)
                                input_cnpj = wait.until(EC.presence_of_element_located((By.ID, "txtCpfCnpj")))
                                input_cnpj.clear()
                                input_cnpj.send_keys(cpf_autor)
                                clicar_seguro(driver, wait, '//*[@id="btnConsultarNome"]')
                                time.sleep(1.5)
                                clicar_seguro(driver, wait, '//*[@id="btnIncluir"]')
                                time.sleep(1.5)
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Autor PJ, avancando...")
                            proxima(driver)

                        elif polo_idx == 0 and modo_autor == "ENTIDADE":
                            # Autor = Entidade (só se campo estiver visível)
                            if campo_visivel(driver, "selTipoPessoa"):
                                status.configure(text=f"L{num_fila}: Preenchendo Autor Entidade...")
                                Select(wait.until(
                                    EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("ENT")
                                time.sleep(1)
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtEntidade", "divInfraAjaxtxtEntidade",
                                                     nome_entidade_autor, '//*[@id="btnIncluirEnt"]')
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Autor, avancando...")
                            proxima(driver)

                        elif polo_idx == 0 and modo_autor == "AUTORIDADE":
                            # Autor = Autoridade Coatora (só se campo estiver visível)
                            if campo_visivel(driver, "selTipoPessoa"):
                                status.configure(text=f"L{num_fila}: Preenchendo Autor Autoridade Coatora...")
                                Select(wait.until(
                                    EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("AUT")
                                time.sleep(1)
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtDesAutoridade", "divInfraAjaxtxtDesAutoridade",
                                                     nome_autoridade_autor, '//*[@id="btnIncluirAut"]')
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Autor, avancando...")
                            proxima(driver)

                        elif polo_idx == 1 and modo_reu == "JUIZO":
                            # Réu = Juízo (federal ou estadual, só se campo estiver visível)
                            if campo_visivel(driver, "txtJuizoFederal"):
                                status.configure(text=f"L{num_fila}: Preenchendo Suscitado (Juizo federal)...")
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtJuizoFederal", "divInfraAjaxtxtJuizoFederal",
                                                     nome_juizo, '//*[@id="btnIncluirJui"]')
                            elif campo_visivel(driver, "txtJuizoEstadual"):
                                status.configure(text=f"L{num_fila}: Preenchendo Suscitado (Juizo estadual)...")
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtJuizoEstadual", "divInfraAjaxtxtJuizoEstadual",
                                                     nome_juizo, '//*[@id="btnIncluirJui"]')
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Juizo, avancando...")
                            proxima(driver)

                        elif polo_idx == 1 and modo_reu == "ENTIDADE":
                            # Réu = Entidade (só se campo estiver visível)
                            if campo_visivel(driver, "selTipoPessoa"):
                                status.configure(text=f"L{num_fila}: Preenchendo Reu Entidade...")
                                Select(wait.until(
                                    EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("ENT")
                                time.sleep(1)
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtEntidade", "divInfraAjaxtxtEntidade",
                                                     nome_entidade_reu, '//*[@id="btnIncluirEnt"]')
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Reu, avancando...")
                            proxima(driver)

                        elif polo_idx == 1 and modo_reu == "AUTORIDADE":
                            # Réu = Autoridade Coatora (só se campo estiver visível)
                            if campo_visivel(driver, "selTipoPessoa"):
                                status.configure(text=f"L{num_fila}: Preenchendo Reu Autoridade Coatora...")
                                Select(wait.until(
                                    EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("AUT")
                                time.sleep(1)
                                incluir_autocomplete(driver, wait, actions,
                                                     "txtDesAutoridade", "divInfraAjaxtxtDesAutoridade",
                                                     nome_autoridade_reu, '//*[@id="btnIncluirAut"]')
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Reu, avancando...")
                            proxima(driver)

                        elif polo_idx == 1 and modo_reu == "PJ":
                            # Réu = Pessoa Jurídica (CNPJ)
                            if campo_visivel(driver, "txtCpfCnpj"):
                                status.configure(text=f"L{num_fila}: Preenchendo Reu PJ (CNPJ)...")
                                Select(wait.until(
                                    EC.presence_of_element_located((By.ID, "selTipoPessoa")))).select_by_value("PJ")
                                time.sleep(1)
                                input_cnpj = wait.until(EC.presence_of_element_located((By.ID, "txtCpfCnpj")))
                                input_cnpj.clear()
                                input_cnpj.send_keys(cpf_reu)
                                clicar_seguro(driver, wait, '//*[@id="btnConsultarNome"]')
                                time.sleep(1.5)
                                clicar_seguro(driver, wait, '//*[@id="btnIncluir"]')
                                time.sleep(1.5)
                            else:
                                status.configure(text=f"L{num_fila}: Sem campo Reu PJ, avancando...")
                            proxima(driver)

                        elif polo_idx == 1 and modo_reu == "NENHUM":
                            # Sem réu: só avança
                            status.configure(text=f"L{num_fila}: Sem Reu, avancando...")
                            proxima(driver)

                        else:
                            # Pessoa fisica: usa CPF/nome informado na planilha selecionada
                            dados_parte = tipo_autor if polo_idx == 0 else tipo_reu
                            if campo_existe(driver, "txtNome") or campo_existe(driver, "txtCpfCnpj"):
                                incluir_pessoa_fisica(driver, wait, status, num_fila, polo_nome, dados_parte)
                            elif not campo_existe(driver, "txtNome") and not campo_existe(driver, "txtCpfCnpj"):
                                status.configure(text=f"L{num_fila}: Partes importadas, avancando...")
                            proxima(driver)

                    # --- DOCUMENTOS E FINALIZAÇÃO ---
                    detectar_campos_novos(driver, "Tela Documentos", status, num_fila)
                    status.configure(text=f"L{num_fila}: Enviando PDF ({tipo_doc})...")
                    upload = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
                    upload.send_keys(CAMINHO_PDF)
                    campo_doc = wait.until(EC.presence_of_element_located((By.ID, "txtTipo_1")))
                    driver.execute_script("arguments[0].click();", campo_doc)
                    time.sleep(0.5)
                    campo_doc.clear()
                    driver.execute_script("arguments[0].value = '';", campo_doc)
                    campo_doc.send_keys(tipo_doc)
                    time.sleep(3)
                    # Mesma logica do incluir_autocomplete(): clica na sugestao via
                    # ActionChains em vez de navegar por teclado (seta+Enter parou de
                    # confirmar a selecao no eProc).
                    wait.until(EC.visibility_of_element_located((By.ID, "divInfraAjaxtxtTipo_1")))
                    time.sleep(0.5)
                    sugestao_doc = driver.find_element(By.XPATH, "//div[@id='divInfraAjaxtxtTipo_1']//li[1]/a")
                    actions.move_to_element(sugestao_doc).pause(0.3).click().perform()
                    time.sleep(1)
                    clicar_seguro(driver, wait, '//*[@id="btnEnviarArquivos"]')
                    time.sleep(2)
                    # Se aparecer alerta de documento duplicado, aceita, exclui e reenvia
                    try:
                        alerta = driver.switch_to.alert
                        alerta.accept()
                        time.sleep(1)
                        # Exclui o documento duplicado
                        btn_excluir = wait.until(EC.presence_of_element_located(
                            (By.CLASS_NAME, "btnExcluirDocumento")
                        ))
                        driver.execute_script("arguments[0].click();", btn_excluir)
                        time.sleep(1)
                        try:
                            driver.switch_to.alert.accept()
                        except:
                            pass
                        time.sleep(1)
                        # Reenvia o arquivo
                        status.configure(text=f"L{num_fila}: Reenviando PDF apos excluir duplicado...")
                        upload2 = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
                        upload2.send_keys(CAMINHO_PDF)
                        campo_doc2 = wait.until(EC.presence_of_element_located((By.ID, "txtTipo_1")))
                        driver.execute_script("arguments[0].click();", campo_doc2)
                        time.sleep(0.5)
                        campo_doc2.clear()
                        driver.execute_script("arguments[0].value = '';", campo_doc2)
                        campo_doc2.send_keys(tipo_doc)
                        time.sleep(3)
                        wait.until(EC.visibility_of_element_located((By.ID, "divInfraAjaxtxtTipo_1")))
                        time.sleep(0.5)
                        sugestao_doc2 = driver.find_element(By.XPATH, "//div[@id='divInfraAjaxtxtTipo_1']//li[1]/a")
                        actions.move_to_element(sugestao_doc2).pause(0.3).click().perform()
                        time.sleep(1)
                        clicar_seguro(driver, wait, '//*[@id="btnEnviarArquivos"]')
                        time.sleep(2)
                    except:
                        pass

                    fechar_alerta(driver)
                    clicar_seguro(driver, wait, '//*[@id="btnSalvar"]')
                    fechar_alerta(driver)
                    driver.switch_to.default_content()
                    iframe = wait.until(
                        EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src,'confirmacao')]")))
                    driver.switch_to.frame(iframe)

                    # Revisão consultiva da IA antes da confirmação final. Nunca bloqueia
                    # o lote: só registra alerta em log/status quando algo parece errado.
                    try:
                        dados_revisao = {
                            "Linha": num_fila,
                            "Assunto": assunto,
                            "TipoDocumento": tipo_doc,
                            "Autor": tipo_autor,
                            "Reu": tipo_reu,
                            "ProcessoOriginario": proc_orig if tem_originario else "",
                        }
                        revisao_ia = _agente_mod.revisar_dados_peticao(dados_revisao)
                        if revisao_ia and revisao_ia.strip().upper() != "OK":
                            status.configure(text=f"L{num_fila}: ⚠ Revisão IA: {revisao_ia[:150]}")
                            _registrar_revisao_ia(num_fila, dados_revisao, revisao_ia)
                    except Exception:
                        pass

                    clicar_seguro(driver, wait, '//*[@id="sbmConfirmar"]')
                    time.sleep(6)
                    driver.switch_to.default_content()

                    # Coleta avisos registrados durante o peticionamento
                    aviso_final = " | ".join(_ultimo_aviso) if _ultimo_aviso else ""
                    _ultimo_aviso.clear()
                    capturar_dados_finais(driver, wait, aviso_final)
                    # Tenta btnNovaPeticao, senão vai pelo menu
                    try:
                        btn = driver.find_elements(By.ID, "btnNovaPeticao")
                        if btn and btn[0].is_displayed():
                            driver.execute_script("arguments[0].click();", btn[0])
                        else:
                            raise Exception("sem botao")
                    except:
                        time.sleep(1)
                        wait.until(EC.presence_of_element_located((By.XPATH, "//a[@aria-label='Petição Inicial']")))
                        clicar_seguro(driver, wait, "//a[@aria-label='Petição Inicial']")
                    time.sleep(2)
                    idx += 1

                except Exception as e_linha:
                    decisao = erro_na_linha(num_fila, e_linha, status)
                    # Fecha qualquer aviso pendente do eproc antes de recuperar a tela.
                    aviso_aceito = aceitar_alertas_pendentes(driver)
                    if decisao == "parar":
                        status.configure(text="Status: Interrompido pelo usuário.")
                        return

                    if decisao == "repetir":
                        if aviso_aceito:
                            status.configure(text=f"L{num_fila}: Aviso aceito. Buscando Petição Inicial...")
                        else:
                            status.configure(text=f"L{num_fila}: Sem aviso. Buscando Petição Inicial...")
                        abrir_peticao_inicial_menu_textual(driver, wait)
                        time.sleep(1)
                        # idx nao avanca: repete a mesma linha da planilha
                        continue

                    # Pular ainda tenta cancelar o processo atual antes de ir para a proxima linha.
                    try:
                        clicar_seguro(driver, wait, '//*[@id="btnCancelar"]')
                        time.sleep(2)
                        aceitar_alertas_pendentes(driver)
                    except:
                        pass
                    try:
                        clicar_seguro(driver, wait, '//*[@id="sbmCancelar"]')
                        time.sleep(2)
                    except:
                        pass
                    idx += 1  # pular: avanca para proxima
                    continue

        status.configure(text="Status: Lote concluído!")
        messagebox.showinfo("AURA", "Processamento finalizado!")

    except Exception as e:
        status.configure(text="Erro geral.")
        messagebox.showerror("Erro AURA", str(e))


# ===============================
# INTERFACE
# ===============================
def selecionar_pdf():
    global CAMINHO_PDF
    arquivo = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
    if arquivo:
        CAMINHO_PDF = arquivo
        label_pdf.configure(text=f"PDF: {os.path.basename(arquivo)}", text_color=COR_SUCESSO)
        if lbl_strip_pdf:
            nome = os.path.basename(arquivo)
            txt = (nome[:26] + "…") if len(nome) > 26 else nome
            lbl_strip_pdf.configure(text=f"📄  {txt}", text_color=COR_SUCESSO)


# selecionar_planilha removida — competências carregadas do Google Sheets


def abrir_aura_gabinete():
    try:
        _auragabinete.AppGUI(janela)
    except Exception as e:
        messagebox.showerror("AURA Gabinete", f"Erro ao abrir o Gabinete:\n\n{e}")


def _compartilhar_login_com_aura_cotri():
    """Grava o config do AURA COTRI (~/.aura_cotri/config.json) com o mesmo
    usuario/senha/url do AURA Principal, para a tela de login já abrir
    preenchida — mesmo formato/local que run_aura_cotri.py usa (carregar_config).
    Nunca lança exceção: se falhar, o AURA COTRI abre e pede login normalmente."""
    try:
        caminho = os.path.join(os.path.expanduser("~"), ".aura_cotri", "config.json")
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"usuario": USUARIO, "senha": SENHA, "url": URL}, f)
    except Exception:
        pass


def abrir_aura_cotri():
    try:
        _compartilhar_login_com_aura_cotri()
        _run_cotri.AuraCotriApp(janela)
    except Exception as e:
        messagebox.showerror("AURA COTRI", f"Erro ao abrir o AURA COTRI:\n\n{e}")


def _compartilhar_login_com_aura_eventoscamaracivel():
    """Grava o config do AURA Eventos Câmara Cível (~/.aura_eventoscamaracivel/config.json)
    com o mesmo usuario/senha/url do AURA Principal, mesmo padrao usado para o
    AURA COTRI (_compartilhar_login_com_aura_cotri). Nunca lanca excecao."""
    try:
        _run_eventoscamaracivel.salvar_config(USUARIO, SENHA, URL)
    except Exception:
        pass


def abrir_aura_eventoscamaracivel():
    try:
        _compartilhar_login_com_aura_eventoscamaracivel()
        _run_eventoscamaracivel.AuraEventosApp(janela)
    except Exception as e:
        messagebox.showerror("AURA Eventos Câmara Cível", f"Erro ao abrir:\n\n{e}")


def _compartilhar_login_com_aura_sessaojulgamento():
    """Grava o config do AURA Sessão de Julgamento (~/.aura_sessao_julgamento/config.json)
    com o mesmo usuario/senha/url do AURA Principal, mesmo padrao usado para o
    AURA COTRI (_compartilhar_login_com_aura_cotri). Nunca lanca excecao."""
    try:
        _cfg_atual = _run_sessaojulgamento.carregar_config()
        _run_sessaojulgamento.salvar_config(USUARIO, SENHA, URL, _cfg_atual.get("perfil", ""))
    except Exception:
        pass


def abrir_aura_sessaojulgamento():
    try:
        _compartilhar_login_com_aura_sessaojulgamento()
        _run_sessaojulgamento.AuraSessaoJulgamentoApp(janela)
    except Exception as e:
        messagebox.showerror("AURA Sessão de Julgamento", f"Erro ao abrir:\n\n{e}")


def abrir_consulta():
    janela_filtro = tk.Toplevel(janela)
    janela_filtro.title("Consultar Histórico")
    janela_filtro.geometry("700x450")
    janela_filtro.configure(bg="#1f2933")
    colunas = ("Data", "Classe", "Magistrado", "Processo")
    tree = ttk.Treeview(janela_filtro, columns=colunas, show='headings')
    for col in colunas:
        tree.heading(col, text=col)
    tree.pack(expand=True, fill='both', padx=10, pady=10)
    try:
        registros = ler_processos_ajuizados()
        for row in registros:
            tree.insert("", tk.END, values=(row.get('Data', ''), row.get('Classe', ''),
                                            row.get('Magistrado', ''), row.get('Processo', '')))
    except Exception as e:
        tk.Label(janela_filtro, text=f"Erro ao carregar histórico: {e}",
                 font=("Segoe UI", 10), bg="#1f2933", fg="#EF4444").pack(pady=20)


def abrir_consulta_intermediario():
    janela_filtro = tk.Toplevel(janela)
    janela_filtro.title("Histórico de Pet. Intermediário")
    janela_filtro.geometry("900x450")
    janela_filtro.configure(bg="#1f2933")
    colunas = ("Data", "Processo", "Evento", "Tipodocumento", "Status", "Motivo")
    tree = ttk.Treeview(janela_filtro, columns=colunas, show='headings')
    tree.heading("Data", text="Data")
    tree.heading("Processo", text="Processo")
    tree.heading("Evento", text="Evento")
    tree.heading("Tipodocumento", text="Tipo Documento")
    tree.heading("Status", text="Status")
    tree.heading("Motivo", text="Motivo")
    tree.column("Data", width=90)
    tree.column("Processo", width=200)
    tree.column("Evento", width=150)
    tree.column("Tipodocumento", width=130)
    tree.column("Status", width=90)
    tree.column("Motivo", width=200)
    tree.pack(expand=True, fill='both', padx=10, pady=10)
    try:
        registros = ler_historico_intermediario()
        if registros:
            for row in registros:
                status_val = row.get('Status', '')
                iid = tree.insert("", tk.END, values=(
                    row.get('Data', ''), row.get('Processo', ''),
                    row.get('Evento', ''), row.get('Tipodocumento', ''),
                    status_val, row.get('Motivo', '')
                ))
                if status_val == 'Sucesso':
                    tree.tag_configure('sucesso', foreground='#10b981')
                    tree.item(iid, tags=('sucesso',))
                else:
                    tree.tag_configure('erro', foreground='#EF4444')
                    tree.item(iid, tags=('erro',))
        else:
            tk.Label(janela_filtro, text="Nenhum registro encontrado.",
                     font=("Segoe UI", 11), bg="#1f2933", fg="#9ca3af").pack(pady=30)
    except Exception as e:
        tk.Label(janela_filtro, text=f"Erro ao carregar histórico: {e}",
                 font=("Segoe UI", 10), bg="#1f2933", fg="#EF4444").pack(pady=20)


def iniciar():
    if not CAMINHO_PDF:
        messagebox.showerror("AURA", "Selecione o PDF antes de continuar.")
        return
    if not DADOS_COMPETENCIA:
        messagebox.showerror("AURA", "Selecione uma competência antes de continuar.")
        return
    prog = JanelaProgresso(janela, len(DADOS_COMPETENCIA))
    proxy = _StatusProxy(status_label, prog)
    def _run():
        executar_peticionamento_lote(proxy)
        janela.after(0, prog.fechar)
    threading.Thread(target=_run, daemon=True).start()


def executar_peticao_intermediaria_linha(driver, wait, status, num_processo, evento,
                                          tipo_doc, caminho_pdf, num_fila=1):
    """Executa UMA linha do fluxo de peticionamento intermediário (pesquisa
    -> Movimentar/Peticionar -> evento -> upload -> tipo -> confirmar
    documentos -> Movimentar/Peticionar) num driver/sessão JÁ logado e no
    perfil certo -- não faz login nem cria driver.

    Extraída do loop de executar_intermediario (que faz login/driver
    próprios) pra ser reaproveitada pelo Passo 5 da regressão de
    homologação (shared/aura_regressao_homologacao.py::passo_advogado_responder),
    que roda na MESMA sessão do Passo 4 (CARTÓRIO), só trocando de perfil
    pra ADVOGADO -- a conta de teste (p0046863) já tem esse perfil, não
    precisa logar de novo."""
    status.configure(text=f"L{num_fila}: Pesquisando {num_processo}...")
    campo = wait.until(EC.element_to_be_clickable((By.ID, "txtNumProcessoPesquisaRapida")))
    driver.execute_script("arguments[0].value = '';", campo)
    campo.send_keys(num_processo)
    time.sleep(0.5)
    campo.send_keys(Keys.RETURN)
    wait.until(EC.url_contains("processo_selecionar"))
    time.sleep(1)

    status.configure(text=f"L{num_fila}: Abrindo movimentação...")
    link = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//a[contains(text(),'Movimentar/Peticionar')]")
    ))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
    driver.execute_script("arguments[0].click();", link)
    wait.until(EC.url_contains("movimentar_peticionar"))
    wait.until(EC.element_to_be_clickable((By.ID, "txtEvento")))

    status.configure(text=f"L{num_fila}: Preenchendo evento ({evento})...")
    _pos_ev = EVENTOS_MAPA.get(evento, (tipo_doc, 1, 1))[1]
    campo_evento = wait.until(EC.element_to_be_clickable((By.ID, "txtEvento")))
    driver.execute_script("arguments[0].click();", campo_evento)
    driver.execute_script("arguments[0].value = '';", campo_evento)
    for char in evento.lower():
        campo_evento.send_keys(char)
        time.sleep(0.05)
    time.sleep(3)
    for _ in range(_pos_ev):
        campo_evento.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.3)
    campo_evento.send_keys(Keys.RETURN)
    time.sleep(1)

    # Fecha o(s) prazo(s) de intimação pendente(s) -- painel "Selecione o(s)
    # prazo(s) a ser(em) fechado(s) (OPCIONAL)" que aparece depois de
    # escolher o evento, com um checkbox por intimação pendente
    # (name="selPrazo[]"). NENHUM vem pré-marcado quando há mais de uma
    # pendência (confirmado por inspeção de DOM ao vivo em 2026-08-18 --
    # bug real visto no Passo 5 da regressão de homologação: a petição
    # submetia sem fechar prazo nenhum). Marca TODOS -- decisão do usuário
    # (mesmo padrão já usado nos Passos 3/4 pra "Selecionar Tudo"): seguro
    # só porque a conta de teste não tem intimações reais de terceiros
    # nesse processo -- reavaliar antes de reusar fora de homologação.
    checkboxes_prazo = driver.find_elements(By.CSS_SELECTOR, "input[name='selPrazo[]']")
    for chk in checkboxes_prazo:
        if not chk.is_selected():
            driver.execute_script("arguments[0].click();", chk)
            time.sleep(0.2)

    status.configure(text=f"L{num_fila}: Enviando PDF...")
    file_input = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='file'][name='file']")
    ))
    driver.execute_script(
        "arguments[0].style.display='block'; arguments[0].style.visibility='visible';",
        file_input
    )
    time.sleep(0.5)
    file_input.send_keys(caminho_pdf)
    time.sleep(2)

    status.configure(text=f"L{num_fila}: Selecionando tipo ({tipo_doc})...")
    _pos_td = EVENTOS_MAPA.get(evento, (tipo_doc, 1, 1))[2]
    campo_tipo = wait.until(EC.presence_of_element_located((By.ID, "txtTipo_1")))
    driver.execute_script("arguments[0].click();", campo_tipo)
    time.sleep(0.5)
    campo_tipo.clear()
    driver.execute_script("arguments[0].value = '';", campo_tipo)
    campo_tipo.send_keys(tipo_doc)
    time.sleep(3)
    # Mesma logica do incluir_autocomplete(): clica na sugestao via ActionChains
    # em vez de navegar por teclado (seta+Enter parou de confirmar a selecao no
    # eProc). _pos_td e a posicao (1-indexada) da sugestao desejada na lista.
    wait.until(EC.visibility_of_element_located((By.ID, "divInfraAjaxtxtTipo_1")))
    time.sleep(0.5)
    sugestao_tipo = driver.find_element(By.XPATH, f"//div[@id='divInfraAjaxtxtTipo_1']//li[{_pos_td}]/a")
    ActionChains(driver).move_to_element(sugestao_tipo).pause(0.3).click().perform()
    time.sleep(1)

    status.configure(text=f"L{num_fila}: Confirmando documentos...")
    btn_enviar = wait.until(EC.element_to_be_clickable((By.ID, "btnEnviarArquivos")))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn_enviar)
    btn_enviar.click()
    time.sleep(3)

    status.configure(text=f"L{num_fila}: Movimentando...")
    btn_mov = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//button[@name='sbmMovimentar']")
    ))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn_mov)
    time.sleep(0.5)
    driver.execute_script("arguments[0].click();", btn_mov)
    wait.until(EC.url_contains("processo_selecionar"))
    time.sleep(1)


def executar_intermediario(status, selecionados):
    """Fluxo de peticionamento intermediário nos processos selecionados."""
    global CAMINHO_PDF

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        status.configure(text="Intermediário: Inicializando Chrome...")
        chrome_options = Options()
        chrome_options.add_experimental_option("detach", True)
        driver = criar_chrome_driver(chrome_options)
        wait = WebDriverWait(driver, 60)

        driver.get(URL)
        driver.maximize_window()

        # LOGIN
        status.configure(text="Intermediário: Autenticando...")
        campo_usuario = wait.until(EC.presence_of_element_located((By.ID, "txtUsuario")))
        campo_usuario.send_keys(USUARIO)
        driver.find_element(By.ID, "pwdSenha").send_keys(SENHA)
        driver.find_element(By.ID, "pwdSenha").send_keys(Keys.RETURN)

        # PERFIL — busca "ADVOGADO" pelo texto em vez de clicar na primeira
        # linha (tr1): posição fixa só funcionava enquanto a conta tinha
        # poucos perfis -- depois que ganhou dezenas de lotações de
        # GABINETE/SECRETARIA (testes da regressão de homologação), a
        # primeira linha deixou de ser ADVOGADO de forma confiável.
        if not _run_cotri.selecionar_perfil(driver, "ADVOGADO"):
            raise RuntimeError("Não foi possível selecionar o perfil ADVOGADO.")
        wait.until(EC.element_to_be_clickable((By.ID, "txtNumProcessoPesquisaRapida")))

        linhas = selecionados

        # Cria Excel de saída
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Resultados"
        ws.append(["Processo", "Evento", "Tipo Documento", "Status", "Motivo"])

        total = len(linhas)
        for idx, linha in enumerate(linhas):
            num_fila = idx + 1
            status.configure(text=f"Intermediário: Linha {num_fila}/{total}...")

            num_processo = str(linha.get('Processo', linha.get('num_processo', ''))).strip()
            evento = str(linha.get('Evento', linha.get('evento', 'PETIÇÃO'))).strip()
            tipo_doc = str(linha.get('Tipodocumento', linha.get('tipo_documento', 'PETIÇÃO'))).strip()

            sucesso = False
            motivo = ""

            try:
                executar_peticao_intermediaria_linha(
                    driver, wait, status, num_processo, evento, tipo_doc,
                    CAMINHO_PDF, num_fila,
                )
                sucesso = True
                status.configure(text=f"L{num_fila}: Sucesso!")

            except Exception as e:
                motivo = str(e)[:200]
                status.configure(text=f"L{num_fila}: Erro — {motivo[:50]}...")

            # Salva no histórico intermediário CSV
            salvar_historico_intermediario({
                "Data": time.strftime("%d/%m/%Y"),
                "Processo": num_processo,
                "Evento": evento,
                "Tipodocumento": tipo_doc,
                "Status": "Sucesso" if sucesso else "Sem sucesso",
                "Motivo": motivo
            })

            # Registra no Excel
            row_excel = [num_processo, evento, tipo_doc,
                         "Sucesso" if sucesso else "Sem sucesso", motivo]
            ws.append(row_excel)
            celula_status = ws.cell(row=idx + 2, column=4)
            if sucesso:
                celula_status.fill = PatternFill(start_color="2ECC71", end_color="2ECC71", fill_type="solid")
                celula_status.font = Font(bold=True, color="FFFFFF")
            else:
                celula_status.fill = PatternFill(start_color="E74C3C", end_color="E74C3C", fill_type="solid")
                celula_status.font = Font(bold=True, color="FFFFFF")
            celula_status.alignment = Alignment(horizontal="center")

        # Salva Excel na pasta do executável
        saida_xlsx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultado_intermediario.xlsx")
        wb.save(saida_xlsx)

        status.configure(text="Intermediário: Concluído!")
        messagebox.showinfo("AURA", f"Peticionamento intermediário finalizado!\nResultado salvo em:\n{saida_xlsx}")

    except Exception as e:
        status.configure(text="Erro.")
        messagebox.showerror("Erro AURA", str(e))


# Mapeamento evento → (tipo_doc, pos_evento, pos_tipo_doc)
# pos=1 significa primeiro resultado (ok), pos=2 segundo, pos=3 terceiro
EVENTOS_MAPA = {
    'PETIÇÃO': ('PETIÇÃO', 1, 1),
    'CONTRARRAZÕES': ('CONTRARRAZÕES', 1, 1),
    'RECURSO ESPECIAL': ('RECURSO ESPECIAL', 1, 3),
    'RECURSO EXTRAORDINÁRIO': ('RECURSO EXTRAORDINÁRIO', 1, 3),
    'Cumprimento sentença': ('CUMPRIMENTO DE SENTENÇA', 1, 1),
    'Embargos de declaração': ('EMBARGOS DE DECLARAÇÃO', 1, 1),
    'Embargos de terceiro': ('EMBARGOS DE TERCEIRO', 1, 1),
    'Agravo interno cível': ('AGRAVO INTERNO CÍVEL', 1, 1),
    'Agravo de Decisão Denegatória de Rec. Especial': ('AGRAVO DE DECISÃO DENEGATORIA DE REC. ESPECIAL', 1, 1),
    'AGRAVO DE DECISÃO DENEGATÓRIA DE REC. EXTRAORDINÁRIO': ('AGRAVO DE DECISÃO DENEGATORIA REC.EXTRAORDINÁRIO', 1, 1),
    'APELAÇÃO': ('APELAÇÃO', 1, 1),
    'Ciência, com renúncia ao prazo': ('RENÚNCIA DE PRAZO', 1, 1),
    'Comunicações': ('OFÍCIO/COMUNICAÇÃO', 1, 1),
    'Consignação em Pagamento': ('PETIÇÃO', 1, 1),
    'CUMPRIMENTO PROVISÓRIA DE SENTENÇA': ('EXE.PROVISÓRIA/CUMPRIMENTO PROVISÓRIA DE SENTENÇA', 1, 1),
    'GUIAS DE RECOLHIMENTO / DEPÓSITO / CUSTAS': ('Guia', 1, 2),
    'Memoriais': ('MEMORIAIS', 1, 1),
    'Mera Ciência': ('CIÊNCIA', 1, 1),
    'Ofício': ('OFÍCIO', 1, 3),
    'Parecer': ('PARECER', 1, 1),
    'Petição - Desastre Climático': ('PETIÇÃO', 1, 1),
    'Petição - Desconstituição de Coisa Julgada': ('PETIÇÃO', 1, 1),
    'Petição - Emenda a Inicial': ('PETIÇÃO', 1, 1),
    'Petição - Pedido de Alvará de Honorários': ('PETIÇÃO', 1, 1),
    'Petição - Pedido de Liminar/Antecipação de Tutela': ('PETIÇÃO', 1, 1),
    'Petição - Pedido de Reconsideração': ('PETIÇÃO', 1, 1),
    'Petição - Pedido de Retirada de Pauta': ('PETIÇÃO', 1, 1),
    'Petição - Prioridade de Tramitação': ('PETIÇÃO', 1, 1),
    'Renúncia ao Prazo': ('RENÚNCIA DE PRAZO', 2, 1),
    'AGRAVO DE DEC DENEG DE PEDIDO DE UNIFORM DE INTERPRET DE LEI': ('AGRAVO', 1, 1),
    'Agravo de Decisão Denegatória de Rec. Extraordinário': ('AGRAVO DE DECISÃO DENEGATORIA REC.EXTRAORDINÁRIO', 1, 1),
    'Alegações Finais': ('ALEGAÇÕES FINAIS', 1, 1),
    'Apresentação de Quesitos': ('QUESITOS PERÍCIA', 1, 1),
    'Apropriação Efetivada': ('PETIÇÃO', 1, 1),
    'Conflito de Competência Cível': ('CONFLITO DE COMPETÊNCIA CÍVEL', 1, 1),
    'Contestação': ('CONTESTAÇÃO', 1, 1),
    'Defesa Prévia': ('DEFESA PRÉVIA/DEFESA PRELIMINAR/RESPOSTA DO RÉU', 1, 1),
    'Embargos a Ação Monitória': ('EMBARGOS À AÇÃO MONITÓRIA', 1, 1),
    'EMBARGOS INFRINGENTES': ('EMBARGOS INFRINGENTES', 1, 1),
    'Exceção de pré-executividade': ('EXCEÇÃO DE PRÉ-EXECUTIVIDADE', 1, 1),
    'Impugnação ao cumprimento de sentença': ('IMPUGNAÇÃO', 1, 1),
    'Impugnação aos Embargos': ('IMPUGNAÇÃO', 1, 1),
    'MANIFESTAÇÃO CREDOR': ('PETIÇÃO', 1, 1),
    'MANIFESTAÇÃO CREDOR (2ª opção)': ('PETIÇÃO', 2, 1),
    'Manifestação PGE': ('PETIÇÃO', 1, 1),
    'Manifestação PGE (2ª opção)': ('PETIÇÃO', 2, 1),
    'Oposição': ('OPOSIÇÃO', 1, 1),
    'Petição - Aceita Proposta de Acordo': ('PETIÇÃO', 1, 1),
    'Petição - Aditamento à Denúncia': ('ADITAMENTO À DENÚNCIA', 1, 1),
    'Petição - Juntada de Documento': ('DOCUMENTOS DIVERSOS', 1, 1),
    'Petição - Pedido de Efeito Suspensivo à Apelação': ('PEDIDO DE EFEITO SUSPENSIVO À APELAÇÃO', 1, 1),
    'PETIÇÃO - PEDIDO DE SUSPENSÃO CONDICIONAL DO PROCESSO': ('PEDIDO DE SUSPENSÃO CONDICIONAL', 1, 1),
    'Proposta de Conciliação': ('PETIÇÃO', 1, 1),
    'Proposta de Conciliação Parcial': ('PETIÇÃO', 1, 1),
    'Razões Finais': ('PETIÇÃO', 1, 1),
    'Reconvenção': ('RECONVENÇÃO', 1, 1),
    'Recurso Ordinário': ('RECURSO ORDINÁRIO', 1, 1),
    'Réplica': ('RÉPLICA', 1, 1),
    'Resposta': ('RESPOSTA', 1, 2),
    'Sem proposta de conciliação': ('PETIÇÃO', 1, 1),
    'Termo de Acordo': ('ACORDO', 3, 1),
}

# Compatibilidade: dicionário simples evento->tipo_doc
EVENTOS_TIPOS = {k: v[0] for k, v in EVENTOS_MAPA.items()}

LISTA_EVENTOS = list(EVENTOS_TIPOS.keys())
LISTA_TIPOS_DOC = sorted(set(EVENTOS_TIPOS.values()))

def abrir_selecao_intermediario():
    """Abre janela com processos ajuizados para seleção do peticionamento intermediário."""
    try:
        processos = ler_processos_ajuizados()
    except Exception as e:
        messagebox.showerror("AURA", f"Erro ao carregar processos do banco de dados:\n{e}")
        processos = []

    jan = tk.Toplevel(janela)
    jan.title("Peticionamento Intermediário — Selecionar Processos")
    jan.geometry("900x600")
    jan.configure(bg="#0D1117")
    jan.grab_set()

    tk.Label(jan, text="Selecione os processos e preencha Evento e Tipo de Documento",
             font=("Consolas", 9), bg="#0D1117", fg="#8B949E").pack(pady=(12, 4))

    tipos_doc = ["Petição", "Petição inicial", "Recurso", "Reclamação",
                 "Cumprimento de sentença", "Tutela Antecipada", "Exceção de impedimento"]

    # --- Painel de entrada manual / arquivo ---
    frame_entrada = tk.Frame(jan, bg="#161B22", highlightbackground="#30363D", highlightthickness=1)
    frame_entrada.pack(fill='x', padx=12, pady=(0, 8))

    tk.Label(frame_entrada, text="Adicionar processos manualmente (um por linha) ou via arquivo:",
             font=("Consolas", 8), bg="#161B22", fg="#8B949E").pack(anchor='w', padx=10, pady=(8, 2))

    frame_entrada_row = tk.Frame(frame_entrada, bg="#161B22")
    frame_entrada_row.pack(fill='x', padx=10, pady=(0, 8))

    txt_manual = tk.Text(frame_entrada_row, height=3, font=("Consolas", 9),
                         bg="#0D1117", fg="#E6EDF3", insertbackground="#2F81F7",
                         relief="flat", highlightbackground="#30363D", highlightthickness=1, width=50)
    txt_manual.pack(side='left', fill='x', expand=True, padx=(0, 8))
    txt_manual.insert("1.0", "Digite os números dos processos aqui...")
    txt_manual.bind("<FocusIn>", lambda e: txt_manual.delete("1.0", "end")
    if txt_manual.get("1.0", "end").strip() == "Digite os números dos processos aqui..." else None)

    frame_btns_entrada = tk.Frame(frame_entrada_row, bg="#161B22")
    frame_btns_entrada.pack(side='left')

    evento_manual = tk.StringVar(value=LISTA_EVENTOS[0])
    tipodoc_manual = tk.StringVar(value=EVENTOS_TIPOS[LISTA_EVENTOS[0]])

    tk.Label(frame_btns_entrada, text="Evento:", font=("Consolas", 8),
             bg="#161B22", fg="#8B949E").pack(anchor='w')
    cb_ev_manual = ttk.Combobox(frame_btns_entrada, textvariable=evento_manual,
                                 values=LISTA_EVENTOS, font=("Consolas", 8),
                                 width=20, state="readonly")
    cb_ev_manual.pack(pady=2)

    tk.Label(frame_btns_entrada, text="Tipo Doc.:", font=("Consolas", 8),
             bg="#161B22", fg="#8B949E").pack(anchor='w')
    cb_td_manual = ttk.Combobox(frame_btns_entrada, textvariable=tipodoc_manual,
                                 values=LISTA_TIPOS_DOC, font=("Consolas", 8),
                                 width=18, state="readonly")
    cb_td_manual.pack(pady=2)

    def on_ev_manual(ev):
        tipodoc_manual.set(EVENTOS_TIPOS.get(evento_manual.get(), evento_manual.get()))
    cb_ev_manual.bind("<<ComboboxSelected>>", on_ev_manual)

    def adicionar_manuais():
        texto = txt_manual.get("1.0", "end").strip()
        if not texto or texto == "Digite os números dos processos aqui...":
            messagebox.showwarning("AURA", "Digite ao menos um número de processo.")
            return
        if not evento_manual.get().strip():
            messagebox.showwarning("AURA", "Preencha o Evento para os processos manuais.")
            return
        numeros = [n.strip() for n in texto.splitlines() if n.strip()]
        for num in numeros:
            # Adiciona linha na lista
            row = tk.Frame(frame_itens, bg="#1C2333", highlightbackground="#30363D", highlightthickness=1)
            row.pack(fill='x', pady=2, padx=2)
            var_chk = tk.BooleanVar(value=True)
            vars_check.append(var_chk)
            tk.Checkbutton(row, variable=var_chk, bg="#1C2333",
                           activebackground="#1C2333", selectcolor="#2F81F7",
                           fg="white", font=("Consolas", 11)).pack(side='left', padx=6, pady=4)
            tk.Label(row, text="manual", font=("Consolas", 8), bg="#1C2333", fg="#8B949E", width=10, anchor='w').pack(
                side='left', padx=2)
            tk.Label(row, text=num, font=("Consolas", 8), bg="#1C2333", fg="#2F81F7", width=28, anchor='w').pack(
                side='left', padx=2)
            tk.Label(row, text="—", font=("Consolas", 8), bg="#1C2333", fg="#8B949E", width=22, anchor='w').pack(
                side='left', padx=2)
            tk.Label(row, text="—", font=("Consolas", 8), bg="#1C2333", fg="#8B949E", width=20, anchor='w').pack(
                side='left', padx=2)
            var_ev = tk.StringVar(value=evento_manual.get().strip())
            vars_evento.append(var_ev)
            tk.Entry(row, textvariable=var_ev, font=("Consolas", 8), width=18,
                     bg="#0D1117", fg="#E6EDF3", insertbackground="#2F81F7",
                     relief="flat", highlightbackground="#30363D", highlightthickness=1).pack(side='left', padx=2)
            var_td = tk.StringVar(value=tipodoc_manual.get())
            vars_tipodoc.append(var_td)
            ttk.Combobox(row, textvariable=var_td, values=tipos_doc,
                         font=("Consolas", 8), width=16, state="readonly").pack(side='left', padx=2)
            processos.append({'Processo': num, 'Data': 'manual', 'Classe': '—', 'Magistrado': '—'})
        txt_manual.delete("1.0", "end")
        canvas.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        messagebox.showinfo("AURA", f"{len(numeros)} processo(s) adicionado(s).")

    def carregar_arquivo():
        arquivo = filedialog.askopenfilename(
            title="Selecione arquivo com processos",
            filetypes=[("CSV/TXT", "*.csv *.txt"), ("Todos", "*.*")]
        )
        if not arquivo:
            return
        with open(arquivo, 'r', encoding='utf-8-sig') as f:
            linhas_arq = [l.strip() for l in f if l.strip()]
        txt_manual.delete("1.0", "end")
        txt_manual.insert("1.0", "\n".join(linhas_arq))

    tk.Button(frame_btns_entrada, text="➕ Adicionar", font=("Consolas", 8, "bold"),
              bg="#2F81F7", fg="white", relief="flat",
              command=adicionar_manuais).pack(fill='x', pady=(4, 2))
    tk.Button(frame_btns_entrada, text="📂 Arquivo", font=("Consolas", 8, "bold"),
              bg="#21262D", fg="#E6EDF3", relief="flat",
              command=carregar_arquivo).pack(fill='x')

    # Frame com scroll
    frame_scroll = tk.Frame(jan, bg="#0D1117")
    frame_scroll.pack(fill='both', expand=True, padx=12, pady=4)

    canvas = tk.Canvas(frame_scroll, bg="#0D1117", highlightthickness=0)
    scrollbar = ttk.Scrollbar(frame_scroll, orient="vertical", command=canvas.yview)
    frame_itens = tk.Frame(canvas, bg="#0D1117")

    frame_itens.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=frame_itens, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Cabeçalho
    cabecalho = tk.Frame(frame_itens, bg="#161B22")
    cabecalho.pack(fill='x', pady=(0, 2))
    for txt, w in [("", 3), ("Data", 10), ("Processo", 28), ("Classe", 22), ("Magistrado", 20), ("Evento", 18),
                   ("Tipo Doc.", 18)]:
        tk.Label(cabecalho, text=txt, font=("Consolas", 8, "bold"),
                 bg="#161B22", fg="#8B949E", width=w, anchor='w').pack(side='left', padx=2)

    # Lista de processos
    vars_check = []
    vars_evento = []
    vars_tipodoc = []

    for proc in processos:
        row = tk.Frame(frame_itens, bg="#161B22", highlightbackground="#30363D", highlightthickness=1)
        row.pack(fill='x', pady=2, padx=2)

        var_chk = tk.BooleanVar()
        vars_check.append(var_chk)
        tk.Checkbutton(row, variable=var_chk, bg="#161B22",
                       activebackground="#161B22", selectcolor="#2F81F7",
                       fg="white", font=("Consolas", 11)).pack(side='left', padx=6, pady=4)

        tk.Label(row, text=proc.get('Data', ''), font=("Consolas", 8),
                 bg="#161B22", fg="#E6EDF3", width=10, anchor='w').pack(side='left', padx=2)
        tk.Label(row, text=proc.get('Processo', ''), font=("Consolas", 8),
                 bg="#161B22", fg="#2F81F7", width=28, anchor='w').pack(side='left', padx=2)
        tk.Label(row, text=proc.get('Classe', '')[:20], font=("Consolas", 8),
                 bg="#161B22", fg="#E6EDF3", width=22, anchor='w').pack(side='left', padx=2)
        tk.Label(row, text=proc.get('Magistrado', '')[:18], font=("Consolas", 8),
                 bg="#161B22", fg="#8B949E", width=20, anchor='w').pack(side='left', padx=2)


        var_ev = tk.StringVar(value=LISTA_EVENTOS[0])
        var_td = tk.StringVar(value=EVENTOS_TIPOS[LISTA_EVENTOS[0]])
        vars_evento.append(var_ev)
        vars_tipodoc.append(var_td)

        cb_ev = ttk.Combobox(row, textvariable=var_ev, values=LISTA_EVENTOS,
                             font=("Consolas", 8), width=22, state="readonly")
        cb_ev.pack(side='left', padx=2)

        cb_td = ttk.Combobox(row, textvariable=var_td, values=LISTA_TIPOS_DOC,
                             font=("Consolas", 8), width=20, state="readonly")
        cb_td.pack(side='left', padx=2)

        def on_ev(ev, vev=var_ev, vtd=var_td):
            vtd.set(EVENTOS_TIPOS.get(vev.get(), vev.get()))
        cb_ev.bind("<<ComboboxSelected>>", on_ev)

    # Botões
    frame_btns = tk.Frame(jan, bg="#0D1117")
    frame_btns.pack(fill='x', padx=12, pady=10)

    def selecionar_todos():
        for v in vars_check:
            v.set(True)

    def desmarcar_todos():
        for v in vars_check:
            v.set(False)

    def confirmar():
        selecionados = []
        for i, (chk, ev, td) in enumerate(zip(vars_check, vars_evento, vars_tipodoc)):
            if chk.get():
                if not ev.get().strip():
                    messagebox.showwarning("AURA", f"Preencha o Evento do processo {processos[i].get('Processo', '')}.")
                    return
                selecionados.append({
                    'Processo': processos[i].get('Processo', ''),
                    'Evento': ev.get().strip(),
                    'Tipodocumento': td.get().strip(),
                })
        if not selecionados:
            messagebox.showwarning("AURA", "Selecione ao menos um processo.")
            return
        jan.destroy()
        prog = JanelaProgresso(janela, len(selecionados))
        proxy = _StatusProxy(status_label, prog)
        def _run():
            executar_intermediario(proxy, selecionados)
            janela.after(0, prog.fechar)
        threading.Thread(target=_run, daemon=True).start()

    tk.Button(frame_btns, text="Selecionar Todos", font=("Consolas", 9),
              bg="#21262D", fg="#E6EDF3", relief="flat", command=selecionar_todos).pack(side='left', padx=4)
    tk.Button(frame_btns, text="Desmarcar Todos", font=("Consolas", 9),
              bg="#21262D", fg="#E6EDF3", relief="flat", command=desmarcar_todos).pack(side='left', padx=4)

    def testar_todos_eventos():
        """Gera uma entrada para cada evento no mesmo processo."""
        num = tk.simpledialog.askstring(
            "Testar Todos os Eventos",
            "Digite o número do processo para testar todos os eventos:",
            parent=jan
        )
        if not num or not num.strip():
            return
        num = num.strip()
        selecionados = [
            {'Processo': num, 'Evento': ev, 'Tipodocumento': td}
            for ev, td in EVENTOS_TIPOS.items()
        ]
        jan.destroy()
        prog_t = JanelaProgresso(janela, len(selecionados))
        proxy_t = _StatusProxy(status_label, prog_t)
        def _run_t():
            executar_intermediario(proxy_t, selecionados)
            janela.after(0, prog_t.fechar)
        threading.Thread(target=_run_t, daemon=True).start()

    tk.Button(frame_btns, text="🧪  TESTAR TODOS EVENTOS", font=("Consolas", 9, "bold"),
              bg="#D29922", fg="white", relief="flat",
              command=testar_todos_eventos).pack(side='left', padx=4)

    tk.Button(frame_btns, text="▶  INICIAR PETICIONAMENTO", font=("Consolas", 10, "bold"),
              bg="#2F81F7", fg="white", relief="flat", width=28,
              command=confirmar).pack(side='right', padx=4, ipady=6)


def iniciar_intermediario():
    if not CAMINHO_PDF:
        messagebox.showerror("AURA", "Selecione o PDF antes de continuar.")
        return
    if not USUARIO or not SENHA or not URL:
        messagebox.showerror("AURA", "Faça login antes de continuar.")
        return
    abrir_selecao_intermediario()


def iniciar_cinprot():
    if not CAMINHO_PDF:
        messagebox.showerror("AURA", "Selecione o PDF antes de continuar.")
        return
    if not DADOS_COMPETENCIA:
        messagebox.showerror("AURA", "Selecione uma competência antes de continuar.")
        return
    prog = JanelaProgresso(janela, len(DADOS_COMPETENCIA))
    proxy = _StatusProxy(status_label, prog)
    def _run():
        executar_peticionamento_lote(proxy, True)
        janela.after(0, prog.fechar)
    threading.Thread(target=_run, daemon=True).start()


# ===============================
# INTERFACE CTK
# ===============================

import ctypes, sys as _sys

# Patch para bug do customtkinter com Python 3.14
try:
    import customtkinter.windows.widgets.ctk_scrollable_frame as _ctk_sf
    _orig_check = _ctk_sf.CTkScrollableFrame.check_if_master_is_canvas
    def _patched_check(self, widget):
        try:
            return _orig_check(self, widget)
        except AttributeError:
            return False
    _ctk_sf.CTkScrollableFrame.check_if_master_is_canvas = _patched_check
except: pass


if _sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass


_scale = _detectar_scaling()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
ctk.set_window_scaling(_scale)
ctk.set_widget_scaling(_scale)
ctk.deactivate_automatic_dpi_awareness()

COR_BG = "#0f1117"
COR_PAINEL = "#1a1d27"
COR_BORDA = "#2a2d3e"
COR_PRIMARIA = "#4f8ef7"
COR_HOVER = "#3a6fd8"
COR_SUCESSO = "#2ecc71"
COR_ERRO = "#e74c3c"
COR_AVISO = "#f39c12"
COR_TEXTO = "#e8eaf0"
COR_SUBTEXTO = "#7c8098"
COR_INPUT_BG = "#252836"
COR_ROXO = "#6c63ff"
COR_ROXO2 = "#5a52d5"
COR_ROXO3 = "#7C3AED"

# Compatibilidade com código legado que usa tk direto em janelas pop-up
BG = COR_BG
CARD = COR_PAINEL
BORDER = COR_BORDA
AZUL = COR_PRIMARIA
ROXO = COR_ROXO
VERDE = COR_SUCESSO
TEXTO = COR_TEXTO
SUBTEXTO = COR_SUBTEXTO
AMARELO = COR_AVISO


def make_card(parent, **kwargs):
    f = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1, **kwargs)
    return f


def make_btn(parent, text, cor, command, width=26):
    btn = tk.Button(parent, text=text, font=("Consolas", 10, "bold"),
                    bg=cor, fg=TEXTO, activebackground=cor,
                    activeforeground=TEXTO, relief="flat", cursor="hand2",
                    width=width, command=command, bd=0)
    btn.bind("<Enter>", lambda e: btn.configure(bg=_lighten(cor)))
    btn.bind("<Leave>", lambda e: btn.configure(bg=cor))
    return btn


def make_input(parent, show=None, default=""):
    entry = tk.Entry(parent, font=("Consolas", 10), bg=COR_INPUT_BG,
                     fg=TEXTO, insertbackground=AZUL, relief="flat",
                     highlightbackground=BORDER, highlightthickness=1,
                     highlightcolor=AZUL, show=show or "")
    if default:
        entry.insert(0, default)
    return entry


# ===============================
# JANELA DE PROGRESSO
# ===============================

class JanelaProgresso:
    """Popup de acompanhamento em tempo real do processamento em lote."""

    def __init__(self, parent, total: int):
        from tkinter import scrolledtext as _st
        self._total = max(total, 1)
        self._inicio = time.time()
        self._fechada = False

        self.jan = ctk.CTkToplevel(parent)
        self.jan.title("AURA — Processando")
        self.jan.geometry("660x530")
        self.jan.configure(fg_color=COR_BG)
        self.jan.resizable(False, False)
        self.jan.protocol("WM_DELETE_WINDOW", lambda: None)
        self.jan.lift()
        self.jan.focus_force()

        # Header
        hdr = ctk.CTkFrame(self.jan, fg_color=COR_PAINEL, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="⚙  Processando lote",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_PRIMARIA).pack(side="left", padx=16, pady=10)
        self._lbl_contador = ctk.CTkLabel(hdr, text=f"0 / {total}",
                                           font=ctk.CTkFont("Segoe UI", 11, "bold"),
                                           text_color=COR_TEXTO)
        self._lbl_contador.pack(side="right", padx=16)

        # Barra de progresso
        pf = ctk.CTkFrame(self.jan, fg_color=COR_PAINEL, corner_radius=0,
                          border_width=1, border_color=COR_BORDA)
        pf.pack(fill="x")
        self._bar = ctk.CTkProgressBar(pf, height=12, fg_color="#1a1d27",
                                        progress_color=COR_PRIMARIA, corner_radius=6)
        self._bar.set(0)
        self._bar.pack(fill="x", padx=16, pady=(12, 4))
        row = ctk.CTkFrame(pf, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 12))
        self._lbl_pct = ctk.CTkLabel(row, text="0%",
                                      font=ctk.CTkFont("Segoe UI", 9, "bold"),
                                      text_color=COR_PRIMARIA)
        self._lbl_pct.pack(side="left")
        self._lbl_tempo = ctk.CTkLabel(row, text="⏱  00:00",
                                        font=ctk.CTkFont("Segoe UI", 9),
                                        text_color=COR_SUBTEXTO)
        self._lbl_tempo.pack(side="right")

        # Log colorido
        log_card = ctk.CTkFrame(self.jan, fg_color=COR_PAINEL,
                                 corner_radius=8, border_width=1, border_color=COR_BORDA)
        log_card.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        lh = ctk.CTkFrame(log_card, fg_color="transparent")
        lh.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(lh, text="LOG DE EXECUÇÃO",
                     font=ctk.CTkFont("Consolas", 8, "bold"),
                     text_color=COR_SUBTEXTO).pack(side="left")
        ctk.CTkFrame(log_card, fg_color=COR_BORDA, height=1).pack(fill="x", padx=10)
        self._log = _st.ScrolledText(
            log_card, font=("Consolas", 9),
            bg="#080b10", fg=COR_TEXTO, relief="flat",
            wrap="word", state="disabled", padx=10, pady=8,
        )
        self._log.pack(fill="both", expand=True, padx=4, pady=(4, 8))
        for tag, cor in (("ok", COR_SUCESSO), ("erro", COR_ERRO),
                         ("aviso", COR_AVISO), ("info", COR_SUBTEXTO)):
            self._log.tag_configure(tag, foreground=cor)

        # Controles
        ctrl = ctk.CTkFrame(self.jan, fg_color="transparent")
        ctrl.pack(fill="x", padx=12, pady=10)
        self._btn_p = ctk.CTkButton(ctrl, text="⏸  PAUSAR",
                                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                                     fg_color=COR_AVISO, hover_color="#d68910",
                                     height=38, corner_radius=7, width=150,
                                     command=self._pausar)
        self._btn_p.pack(side="left", padx=4)

        self._atualizar_tempo()

    def _pausar(self):
        toggle_pausa()
        self.sincronizar_pausa(PAUSADO)

    def _atualizar_tempo(self):
        if self._fechada:
            return
        seg = int(time.time() - self._inicio)
        m, s = divmod(seg, 60)
        try:
            self._lbl_tempo.configure(text=f"⏱  {m:02d}:{s:02d}")
            self.jan.after(1000, self._atualizar_tempo)
        except Exception:
            pass

    def log(self, msg: str, tag: str = "info"):
        if self._fechada:
            return
        hora = time.strftime("%H:%M:%S")
        try:
            self._log.configure(state="normal")
            self._log.insert("end", f"[{hora}]  {msg}\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")
        except Exception:
            pass

    def configure(self, text: str = "", **_):
        if not text or self._fechada:
            return
        tl = text.lower()
        if any(k in tl for k in ("erro", "falha", "fail", "parar")):
            tag = "erro"
        elif any(k in tl for k in ("sucesso", "concluí", "finaliz", "✓")):
            tag = "ok"
        elif any(k in tl for k in ("pausado", "aguard", "aviso", "⏸")):
            tag = "aviso"
        else:
            tag = "info"
        self.log(text, tag)

    def atualizar_progresso(self, atual: int):
        if self._fechada:
            return
        pct = min(atual / self._total, 1.0)
        try:
            self._bar.set(pct)
            self._lbl_pct.configure(text=f"{int(pct * 100)}%")
            self._lbl_contador.configure(text=f"{atual} / {self._total}")
        except Exception:
            pass

    def sincronizar_pausa(self, pausado: bool):
        if self._fechada:
            return
        try:
            if pausado:
                self._btn_p.configure(text="▶  RETOMAR",
                                       fg_color=COR_SUCESSO, hover_color="#27ae60")
            else:
                self._btn_p.configure(text="⏸  PAUSAR",
                                       fg_color=COR_AVISO, hover_color="#d68910")
        except Exception:
            pass

    def fechar(self, msg: str = "Lote concluído!"):
        if self._fechada:
            return
        self.log(f"✓  {msg}", "ok")
        self.atualizar_progresso(self._total)
        self._fechada = True
        try:
            ctk.CTkButton(self.jan, text="✓  FECHAR",
                          font=ctk.CTkFont("Segoe UI", 10, "bold"),
                          fg_color=COR_SUCESSO, hover_color="#27ae60",
                          height=36, corner_radius=7,
                          command=self.jan.destroy).pack(padx=12, pady=(0, 10), fill="x")
            self.jan.protocol("WM_DELETE_WINDOW", self.jan.destroy)
        except Exception:
            pass


class _StatusProxy:
    """Encaminha status.configure(text=) para o label da tela e para JanelaProgresso."""

    def __init__(self, label, prog: "JanelaProgresso | None" = None):
        self._label = label
        self._prog = prog
        self._ultimo_idx = 0

    def configure(self, text: str = "", **_):
        if self._label:
            try:
                self._label.configure(text=text)
            except Exception:
                pass
        if self._prog:
            self._prog.configure(text=text)
            import re as _re
            m = _re.search(r'[Ll]inha\s+(\d+)', text)
            if m:
                n = int(m.group(1))
                if n != self._ultimo_idx:
                    self._ultimo_idx = n
                    self._prog.atualizar_progresso(n)


# ===============================
# APP PRINCIPAL
# ===============================

class AuraApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AURA — Automação Unificada de Rotinas Administrativas")
        self.geometry("520x660")
        self.resizable(False, False)
        self.configure(fg_color=COR_BG)
        self._dot_label = None
        self._dot_on = True
        try:
            self.after(200, lambda: self.iconbitmap(base_path("aura_logo.ico")))
        except:
            pass
        global GROQ_API_KEY
        GROQ_API_KEY = carregar_config().get("groq_key", "")
        _agente_mod.init(GROQ_API_KEY)
        self.geometry("600x760")
        self._build_principal()
        threading.Thread(target=self._checar_update, daemon=True).start()
        threading.Thread(target=self._inicializar_db, daemon=True).start()

    def _inicializar_db(self):
        try:
            inicializar_planilha()
        except Exception as e:
            print(f"[aura_db] Aviso: nao foi possivel inicializar planilha: {e}")

    def _logo_img(self, size=(73, 67)):
        try:
            img = Image.open(base_path("aura_logo.png")).convert("RGBA")
            img = img.crop((0, 0, img.width, 104))
            dados = img.getdata()
            img.putdata([(r, g, b, 0) if r > 220 and g > 220 and b > 220 else (r, g, b, a) for r, g, b, a in dados])
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except:
            return None

    # ── LOGIN ────────────────────────────────────────────────────────────
    def _build_login(self):
        self.frame_login = ctk.CTkFrame(self, fg_color=COR_BG, corner_radius=0)
        self.frame_login.pack(fill="both", expand=True)

        # Header escuro
        header = ctk.CTkFrame(self.frame_login, fg_color="#0c1020", corner_radius=0)
        header.pack(fill="x")

        # Logo com glow ring
        logo = self._logo_img((76, 70))
        if logo:
            glow = ctk.CTkFrame(header, fg_color="#0e1f3d", corner_radius=50,
                                 border_width=2, border_color=COR_PRIMARIA,
                                 width=104, height=104)
            glow.pack(pady=(22, 6))
            glow.pack_propagate(False)
            ctk.CTkLabel(glow, image=logo, text="",
                         fg_color="transparent").place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(header, text="AURA",
                     font=ctk.CTkFont("Segoe UI", 30, "bold"),
                     text_color=COR_PRIMARIA).pack()
        ctk.CTkLabel(header, text="Automação Unificada de Rotinas Administrativas",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=COR_SUBTEXTO).pack(pady=(2, 0))
        ctk.CTkLabel(header, text="CESUPE  ·  TJMG",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color="#3d4f6b").pack(pady=(2, 0))

        # Badge de versão (pill)
        badge_wrap = ctk.CTkFrame(header, fg_color="#1a2a45",
                                   corner_radius=12, border_width=1, border_color="#2a4a7f")
        badge_wrap.pack(pady=(8, 20))
        ctk.CTkLabel(badge_wrap, text=f"  v{VERSAO_ATUAL}  ",
                     font=ctk.CTkFont("Segoe UI", 8, "bold"),
                     text_color=COR_PRIMARIA).pack(padx=4, pady=2)

        # Card de login
        card = ctk.CTkFrame(self.frame_login, fg_color=COR_PAINEL,
                            corner_radius=12, border_width=1, border_color=COR_BORDA)
        card.pack(padx=40, pady=(0, 16), fill="x")

        # Accent bar no topo do card
        ctk.CTkFrame(card, fg_color=COR_PRIMARIA, height=3,
                     corner_radius=0).pack(fill="x")

        def campo(label, show=None, default=""):
            ctk.CTkLabel(card, text=label,
                         font=ctk.CTkFont("Segoe UI", 9, "bold"),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=20, pady=(14, 2))
            e = ctk.CTkEntry(card, font=ctk.CTkFont("Segoe UI", 11),
                             fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                             border_color=COR_BORDA, border_width=1,
                             corner_radius=7, height=38, show=show or "")
            e.bind("<FocusIn>",  lambda _ev: e.configure(border_color=COR_PRIMARIA))
            e.bind("<FocusOut>", lambda _ev: e.configure(border_color=COR_BORDA))
            if default:
                e.insert(0, default)
            e.pack(fill="x", padx=20)
            return e

        _cfg = carregar_config()
        self.entry_usuario = campo("USUÁRIO EPROC", default=_cfg.get("usuario", ""))
        self.entry_senha   = campo("SENHA", show="*")
        self.entry_url     = campo("URL DO SISTEMA", default=_cfg.get("url", "https://eproc2g-hml.tjmg.jus.br/eproc/"))

        ctk.CTkFrame(card, fg_color=COR_BORDA, height=1).pack(fill="x", padx=20, pady=18)

        ctk.CTkButton(card, text="→  ACESSAR SISTEMA",
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      fg_color=COR_PRIMARIA, hover_color=COR_HOVER,
                      height=44, corner_radius=8,
                      command=self._salvar_login).pack(fill="x", padx=20, pady=(0, 20))

        self.bind("<Return>", lambda e: self._salvar_login())

        ctk.CTkLabel(self.frame_login,
                     text="© 2026 CESUPE / TJMG — Todos os direitos reservados",
                     font=ctk.CTkFont("Segoe UI", 7),
                     text_color="#1e2535").pack(pady=6)

    def _salvar_login(self):
        global USUARIO, SENHA, URL, GROQ_API_KEY
        USUARIO = self.entry_usuario.get().strip()
        SENHA   = self.entry_senha.get().strip()
        URL     = self.entry_url.get().strip()
        if USUARIO and SENHA and URL:
            GROQ_API_KEY = carregar_config().get("groq_key", "")
            _agente_mod.init(GROQ_API_KEY)
            salvar_config(USUARIO, SENHA, URL, GROQ_API_KEY)
            self.frame_login.destroy()
            self.geometry("600x760")
            self._build_principal()
            threading.Thread(target=self._checar_update, daemon=True).start()
        else:
            messagebox.showerror("AURA", "Preencha todos os campos.")

    def _abrir_troca_login(self):
        jan = ctk.CTkToplevel(self)
        jan.title("Trocar login")
        jan.geometry("440x420")
        jan.configure(fg_color=COR_BG)
        jan.grab_set()
        jan.lift()
        jan.focus_force()

        ctk.CTkLabel(jan, text="👤  Trocar login",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_PRIMARIA).pack(pady=(20, 4))
        ctk.CTkLabel(jan, text="Atualize as credenciais usadas para acessar o eProc.",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO).pack(pady=(0, 14))

        card = ctk.CTkFrame(jan, fg_color=COR_PAINEL,
                            corner_radius=12, border_width=1, border_color=COR_BORDA)
        card.pack(padx=20, fill="x")

        def campo(label, show=None, default=""):
            ctk.CTkLabel(card, text=label,
                         font=ctk.CTkFont("Segoe UI", 9, "bold"),
                         text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=16, pady=(14, 2))
            e = ctk.CTkEntry(card, font=ctk.CTkFont("Segoe UI", 11),
                             fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                             border_color=COR_BORDA, border_width=1,
                             corner_radius=7, height=38, show=show or "")
            e.bind("<FocusIn>",  lambda _ev: e.configure(border_color=COR_PRIMARIA))
            e.bind("<FocusOut>", lambda _ev: e.configure(border_color=COR_BORDA))
            if default:
                e.insert(0, default)
            e.pack(fill="x", padx=16, pady=(0, 4))
            return e

        entry_usuario = campo("USUÁRIO EPROC", default=USUARIO)
        entry_senha   = campo("SENHA", show="*")
        entry_url     = campo("URL DO SISTEMA", default=URL)

        ctk.CTkFrame(card, fg_color=COR_BORDA, height=1).pack(fill="x", padx=16, pady=14)

        def _salvar_troca():
            global USUARIO, SENHA, URL
            novo_usuario = entry_usuario.get().strip()
            nova_senha   = entry_senha.get().strip()
            nova_url     = entry_url.get().strip()
            if novo_usuario and nova_senha and nova_url:
                USUARIO, SENHA, URL = novo_usuario, nova_senha, nova_url
                salvar_config(USUARIO, SENHA, URL, GROQ_API_KEY)
                self.lbl_chip_usuario.configure(text=f"  👤  {USUARIO}  ")
                messagebox.showinfo("AURA", "Login atualizado.")
                jan.destroy()
            else:
                messagebox.showerror("AURA", "Preencha todos os campos.")

        ctk.CTkButton(card, text="✔  SALVAR LOGIN",
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      fg_color=COR_PRIMARIA, hover_color=COR_HOVER,
                      height=44, corner_radius=8,
                      command=_salvar_troca).pack(fill="x", padx=16, pady=(0, 16))

    def _checar_update(self):
        tem_update, versao_nova, url_download = verificar_atualizacao()
        if tem_update:
            self.after(0, lambda: self._avisar_update(versao_nova, url_download))

    def _avisar_update(self, versao_nova, url_download):
        jan_up = ctk.CTkToplevel(self)
        jan_up.title("Atualização disponível")
        jan_up.geometry("420x200")
        jan_up.configure(fg_color=COR_PAINEL)
        jan_up.grab_set()
        jan_up.lift()
        ctk.CTkLabel(jan_up, text="🔄  Nova versão disponível!",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"), text_color=COR_SUCESSO).pack(pady=(20, 4))
        ctk.CTkLabel(jan_up,
                     text=f"Versão atual: v{VERSAO_ATUAL}   →   Nova versão: v{versao_nova}",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=COR_SUBTEXTO).pack()
        ctk.CTkLabel(jan_up, text="Baixe a nova versão no GitHub.",
                     font=ctk.CTkFont("Segoe UI", 9), text_color=COR_SUBTEXTO).pack(pady=(4, 16))

        def abrir_github():
            import webbrowser
            webbrowser.open(url_download)
            jan_up.destroy()

        ctk.CTkButton(jan_up, text="⬇  Baixar atualização",
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      fg_color=COR_SUCESSO, hover_color="#27ae60",
                      height=38, corner_radius=8, command=abrir_github).pack(padx=30, fill="x")
        ctk.CTkButton(jan_up, text="Agora não",
                      font=ctk.CTkFont("Segoe UI", 9), fg_color="transparent",
                      hover_color=COR_BORDA, text_color=COR_SUBTEXTO,
                      height=28, command=jan_up.destroy).pack(pady=6)

    # ── TELA PRINCIPAL ───────────────────────────────────────────────────
    def _build_principal(self):
        # ── Topbar
        topbar = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0,
                              border_width=1, border_color=COR_BORDA)
        topbar.pack(fill="x")
        logo2 = self._logo_img((28, 26))
        if logo2:
            ctk.CTkLabel(topbar, image=logo2, text="",
                         fg_color="transparent").pack(side="left", padx=(12, 4), pady=8)
        ctk.CTkLabel(topbar, text="AURA",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_PRIMARIA).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(topbar, text="Sistema de Peticionamento em Lote",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_SUBTEXTO).pack(side="left")

        # Badge de versão (direita)
        vb = ctk.CTkFrame(topbar, fg_color="#1a2a45", corner_radius=10,
                          border_width=1, border_color="#2a4a7f")
        vb.pack(side="right", padx=10, pady=8)
        ctk.CTkLabel(vb, text=f"  v{VERSAO_ATUAL}  ",
                     font=ctk.CTkFont("Segoe UI", 8, "bold"),
                     text_color=COR_PRIMARIA).pack(padx=2, pady=1)

        # Chip do usuário logado (clicável para trocar login)
        uc = ctk.CTkFrame(topbar, fg_color="#1a2233", corner_radius=10,
                          border_width=1, border_color=COR_BORDA, cursor="hand2")
        uc.pack(side="right", padx=4, pady=8)
        self.lbl_chip_usuario = ctk.CTkLabel(uc, text=f"  👤  {USUARIO}  ",
                     font=ctk.CTkFont("Segoe UI", 8),
                     text_color=COR_TEXTO, cursor="hand2")
        self.lbl_chip_usuario.pack(padx=2, pady=2)
        uc.bind("<Button-1>", lambda _ev: self._abrir_troca_login())
        self.lbl_chip_usuario.bind("<Button-1>", lambda _ev: self._abrir_troca_login())

        # ── Strip de sessão (competência | PDF)
        strip = ctk.CTkFrame(self, fg_color="#0c1020", corner_radius=0,
                             border_width=1, border_color=COR_BORDA, height=28)
        strip.pack(fill="x")
        strip.pack_propagate(False)

        global lbl_strip_comp, lbl_strip_pdf
        lbl_strip_comp = ctk.CTkLabel(strip,
                                       text="📊  Nenhuma competência selecionada",
                                       font=ctk.CTkFont("Segoe UI", 8),
                                       text_color=COR_SUBTEXTO)
        lbl_strip_comp.pack(side="left", padx=10)
        ctk.CTkFrame(strip, fg_color=COR_BORDA, width=1).pack(side="left", fill="y", pady=5)
        lbl_strip_pdf = ctk.CTkLabel(strip,
                                      text="📄  Nenhum PDF",
                                      font=ctk.CTkFont("Segoe UI", 8),
                                      text_color=COR_SUBTEXTO)
        lbl_strip_pdf.pack(side="left", padx=10)

        # ── Status bar (empacotada antes do corpo para ficar no rodapé)
        sf = ctk.CTkFrame(self, fg_color=COR_PAINEL, corner_radius=0,
                          border_width=1, border_color=COR_BORDA, height=34)
        sf.pack(fill="x", side="bottom")
        sf.pack_propagate(False)
        self._dot_label = ctk.CTkLabel(sf, text="●",
                                        font=ctk.CTkFont("Segoe UI", 10),
                                        text_color=COR_SUCESSO)
        self._dot_label.pack(side="left", padx=(12, 4))
        global status_label
        status_label = ctk.CTkLabel(sf, text="Aguardando...",
                                    font=ctk.CTkFont("Segoe UI", 9),
                                    text_color=COR_SUBTEXTO)
        status_label.pack(side="left")

        global btn_pausa
        btn_pausa = ctk.CTkButton(sf, text="⏸  PAUSAR",
                                   font=ctk.CTkFont("Segoe UI", 8, "bold"),
                                   fg_color=COR_AVISO, hover_color="#d68910",
                                   height=24, corner_radius=6, width=100,
                                   command=toggle_pausa)
        btn_pausa.pack(side="right", padx=8, pady=5)

        # Inicia animação do ponto de status
        self.after(700, self._pulsar_dot)

        # ── Corpo: duas colunas (rolavel -- evita conteudo cortado
        # silenciosamente quando mais cards/botoes forem adicionados no
        # futuro e a janela [600x760, altura fixa] nao tiver mais espaco)
        corpo = ctk.CTkScrollableFrame(self, fg_color=COR_BG, corner_radius=0)
        corpo.pack(fill="both", expand=True)

        col_esq = ctk.CTkFrame(corpo, fg_color="transparent")
        col_esq.pack(side="left", fill="both", expand=True, padx=(12, 5), pady=10)

        col_dir = ctk.CTkFrame(corpo, fg_color="transparent")
        col_dir.pack(side="right", fill="both", expand=True, padx=(5, 12), pady=10)

        def card(parent, titulo, cor_accent=COR_PRIMARIA):
            outer = ctk.CTkFrame(parent, fg_color=COR_PAINEL,
                                  corner_radius=10, border_width=1, border_color=COR_BORDA)
            outer.pack(fill="x", pady=(0, 10))
            ctk.CTkFrame(outer, fg_color=cor_accent, corner_radius=0,
                         width=4).pack(side="left", fill="y")
            inner = ctk.CTkFrame(outer, fg_color="transparent")
            inner.pack(side="left", fill="both", expand=True, padx=10, pady=10)
            ctk.CTkLabel(inner, text=titulo,
                         font=ctk.CTkFont("Segoe UI", 9, "bold"),
                         text_color=cor_accent, anchor="w").pack(fill="x", pady=(0, 6))
            ctk.CTkFrame(inner, fg_color=COR_BORDA, height=1).pack(fill="x", pady=(0, 8))
            return inner

        def abtn(parent, texto, cor, cmd):
            ctk.CTkButton(parent, text=texto,
                          font=ctk.CTkFont("Segoe UI", 10, "bold"),
                          fg_color=cor, hover_color=_lighten(cor),
                          height=38, corner_radius=7, command=cmd
                          ).pack(fill="x", pady=2)

        # ── COLUNA ESQUERDA
        # COMPETÊNCIA
        c_comp = card(col_esq, "📊  COMPETÊNCIA", COR_PRIMARIA)

        def _ao_selecionar_competencia(nome_aba, linhas):
            global DADOS_COMPETENCIA, NOME_COMPETENCIA
            DADOS_COMPETENCIA = linhas
            NOME_COMPETENCIA  = nome_aba
            if lbl_strip_comp:
                txt = (nome_aba[:28] + "…") if len(nome_aba) > 28 else nome_aba
                lbl_strip_comp.configure(text=f"📊  {txt}", text_color=COR_SUCESSO)

        SheetSelectorFrame(
            c_comp,
            on_select=_ao_selecionar_competencia,
            fg_color="transparent",
            border_width=0,
        ).pack(fill="x")

        row_pdf = ctk.CTkFrame(c_comp, fg_color="transparent")
        row_pdf.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(row_pdf, text="📄  PDF",
                      font=ctk.CTkFont("Segoe UI", 9), fg_color="#21262D",
                      hover_color=COR_BORDA, width=76, height=30, corner_radius=6,
                      command=selecionar_pdf).pack(side="left")
        global label_pdf
        label_pdf = ctk.CTkLabel(row_pdf, text="nenhum selecionado",
                                  font=ctk.CTkFont("Segoe UI", 8),
                                  text_color=COR_SUBTEXTO)
        label_pdf.pack(side="left", padx=8)

        # AGENTE
        c_ag = card(col_esq, "🤖  AGENTE", COR_ROXO)
        abtn(c_ag, "🤖  AURA AGENT", COR_ROXO, self._abrir_agente)
        abtn(c_ag, "🔑  CHAVE DA IA", COR_ROXO2, self._abrir_config_api)

        # INTEGRAÇÃO
        c_int = card(col_esq, "🧭  INTEGRAÇÃO", COR_PRIMARIA)
        abtn(c_int, "🧭  AURA GABINETE", COR_PRIMARIA, abrir_aura_gabinete)
        abtn(c_int, "🧭  AURA COTRI", COR_ROXO, abrir_aura_cotri)
        abtn(c_int, "⚖️  AURA EVENTOS CÂMARA CÍVEL", COR_ROXO, abrir_aura_eventoscamaracivel)
        abtn(c_int, "🗳️  AURA SESSÃO DE JULGAMENTO", COR_ROXO, abrir_aura_sessaojulgamento)

        # ── COLUNA DIREITA
        # PETICIONAMENTO
        c_pet = card(col_dir, "▶  PETICIONAMENTO", COR_PRIMARIA)
        abtn(c_pet, "▶  HOMOLOGAR — ADVOGADO", COR_PRIMARIA,  iniciar)
        abtn(c_pet, "▶  HOMOLOGAR — CINPROT",  COR_ROXO,      iniciar_cinprot)
        abtn(c_pet, "📋  INTERMEDIÁRIO",         COR_ROXO3,     iniciar_intermediario)

        # REGISTROS
        c_reg = card(col_dir, "🗂  REGISTROS", COR_SUCESSO)
        abtn(c_reg, "🗂  Histórico de Ajuizamentos",  COR_SUCESSO, abrir_consulta)
        abtn(c_reg, "📋  Histórico Intermediário",    COR_ROXO3,   abrir_consulta_intermediario)

        # REGRESSÃO HOMOLOGAÇÃO
        c_regr = card(col_dir, "🧪  REGRESSÃO HOMOLOGAÇÃO", COR_ROXO)
        abtn(c_regr, "🧪  RODAR TESTE (Passo 1-5)", COR_ROXO, self._abrir_regressao_homologacao)

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

    def _abrir_agente(self):
        def _get_ctx():
            return {
                "pdf":        os.path.basename(CAMINHO_PDF) if CAMINHO_PDF else None,
                "competencia": NOME_COMPETENCIA or None,
                "usuario":    USUARIO or None,
            }
        _agente_mod.abrir_chat_agente(self, _get_ctx)

    def _abrir_config_api(self):
        jan = ctk.CTkToplevel(self)
        jan.title("Chave da IA")
        jan.geometry("440x280")
        jan.configure(fg_color=COR_BG)
        jan.grab_set()
        jan.lift()
        jan.focus_force()

        ctk.CTkLabel(jan, text="🔑  Chave de API da IA",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_ROXO).pack(pady=(20, 4))
        ctk.CTkLabel(
            jan,
            text="Cole aqui a chave da API usada pelo AURA Agent.\n"
                 "Compatível com a API da Groq (console.groq.com/keys) — troque\n"
                 "por uma chave nova a qualquer momento para usar outro modelo/conta.",
            font=ctk.CTkFont("Segoe UI", 9),
            text_color=COR_SUBTEXTO, justify="center",
        ).pack(pady=(0, 14))

        entry_key = ctk.CTkEntry(jan, font=ctk.CTkFont("Segoe UI", 10),
                                  fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
                                  border_color=COR_BORDA, border_width=1,
                                  corner_radius=7, height=38, show="*", width=360)
        chave_atual = carregar_config().get("groq_key", "")
        if chave_atual:
            entry_key.insert(0, chave_atual)
        entry_key.pack(padx=20)

        def _alternar_visibilidade():
            entry_key.configure(show="" if entry_key.cget("show") == "*" else "*")

        ctk.CTkButton(jan, text="👁  Mostrar/ocultar", font=ctk.CTkFont("Segoe UI", 8),
                      fg_color="transparent", hover_color=COR_PAINEL, text_color=COR_SUBTEXTO,
                      height=20, command=_alternar_visibilidade).pack(pady=(6, 0))

        def _salvar_chave():
            global GROQ_API_KEY
            nova_chave = entry_key.get().strip()
            GROQ_API_KEY = nova_chave
            salvar_config(USUARIO, SENHA, URL, nova_chave)
            _agente_mod.init(nova_chave)
            messagebox.showinfo("AURA", "Chave da IA atualizada." if nova_chave else "Chave da IA removida.")
            jan.destroy()

        ctk.CTkButton(jan, text="✔  SALVAR CHAVE", font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      fg_color=COR_ROXO, hover_color=_lighten(COR_ROXO),
                      height=42, corner_radius=8, command=_salvar_chave).pack(fill="x", padx=20, pady=(24, 10))

    def _abrir_regressao_homologacao(self):
        """Abre um diálogo pedindo o Nº do processo de teste e roda o
        pipeline de regressão de homologação de ponta a ponta -- 5 passos
        (COTRI distribui -> GABINETE minuta -> MAGISTRADO assina ->
        CARTÓRIO intima -> ADVOGADO responde, ver
        shared/aura_regressao_homologacao.py::rodar_pipeline_completo) --
        usa o login já feito no AURA Principal (USUARIO/SENHA/URL) pra
        COTRI/GABINETE/CARTÓRIO, e a conta do magistrado é descoberta
        sozinha no Passo 2 (sigla lida da coluna "Assinante indicado" da
        minuta recém-criada) + senha padrão de homologação
        (SENHA_HOMOLOGACAO_PADRAO). O Passo 5 (ADVOGADO) troca de perfil na
        MESMA sessão do Passo 4 (a conta p0046863 já tem perfil ADVOGADO,
        não precisa logar de novo) e reaproveita
        executar_peticao_intermediaria_linha (extraída de
        executar_intermediario) pra submeter a petição -- precisa de um PDF
        já selecionado (CAMINHO_PDF); usa o teste padrão HML.pdf na raiz do
        projeto se o usuário ainda não escolheu nenhum via UI."""
        jan = ctk.CTkToplevel(self)
        jan.title("Regressão de Homologação")
        jan.geometry("460x300")
        jan.configure(fg_color=COR_BG)
        jan.grab_set()
        jan.lift()
        jan.focus_force()

        ctk.CTkLabel(jan, text="🧪  Regressão de Homologação",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=COR_ROXO).pack(pady=(20, 4))
        ctk.CTkLabel(
            jan,
            text="Vai rodar o pipeline completo contra HOMOLOGAÇÃO:\n"
                 "1. COTRI distribui  2. GABINETE minuta + remessa\n"
                 "3. MAGISTRADO assina (login descoberto automaticamente)\n"
                 "4. CARTÓRIO intima  5. ADVOGADO responde\n\n"
                 "Isso cria e assina uma minuta de teste de verdade, e\n"
                 "envia uma petição de teste de verdade.",
            font=ctk.CTkFont("Segoe UI", 9),
            text_color=COR_SUBTEXTO, justify="center",
        ).pack(pady=(0, 10))

        ctk.CTkLabel(jan, text="Nº DO PROCESSO DE TESTE",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=COR_SUBTEXTO, anchor="w").pack(fill="x", padx=20, pady=(6, 2))
        entry_processo = ctk.CTkEntry(
            jan, font=ctk.CTkFont("Segoe UI", 11),
            fg_color=COR_INPUT_BG, text_color=COR_TEXTO,
            border_color=COR_BORDA, border_width=1,
            corner_radius=7, height=38,
            placeholder_text="0000000-00.0000.0.00.0000",
        )
        entry_processo.pack(fill="x", padx=20)

        def _rodar():
            num_processo = entry_processo.get().strip()
            if not num_processo:
                messagebox.showerror("Regressão de Homologação",
                                      "Informe o número do processo de teste.")
                return
            jan.destroy()

            global CAMINHO_PDF
            if not CAMINHO_PDF:
                _pdf_teste_padrao = os.path.join(_pasta_config_externa(), "HML.pdf")
                if os.path.exists(_pdf_teste_padrao):
                    CAMINHO_PDF = _pdf_teste_padrao
                else:
                    messagebox.showerror(
                        "Regressão de Homologação",
                        "Nenhum PDF selecionado e não achei o PDF de teste padrão "
                        f"({_pdf_teste_padrao}). Selecione um PDF (mesmo botão do "
                        "INTERMEDIÁRIO) antes de rodar o Passo 5 (ADVOGADO responde).",
                    )
                    return

            if status_label:
                status_label.configure(text="🧪 Regressão de homologação: rodando (Passo 1/5)...")

            # _DIR_BASE (baseado em __file__) resolve pro diretório temporário
            # de extração do PyInstaller quando rodando como .exe compilado
            # (onefile), não pra pasta real do executável -- o arquivo era
            # gravado num lugar que o usuário nunca acha, e some quando o app
            # fecha. _pasta_config_externa() já resolve certo nos dois casos
            # (dev: pasta do script; .exe: pasta de sys.executable) -- mesmo
            # padrão já usado por salvar_config().
            _log_regressao = os.path.join(_pasta_config_externa(), "regressao_homologacao_ultimo_erro.log")

            def _run():
                try:
                    resultados = _run_regressao_homologacao.rodar_pipeline_completo(
                        usuario=USUARIO, senha=SENHA, url=URL,
                        texto_minuta=_TEXTO_MINUTA_TESTE_REGRESSAO,
                        executar_peticao_fn=executar_peticao_intermediaria_linha,
                        caminho_pdf=CAMINHO_PDF,
                        num_processo=num_processo,
                    )
                except Exception as e:
                    msg = str(e)
                    with open(_log_regressao, "w", encoding="utf-8") as f:
                        f.write(f"erro geral: {msg}\n\n")
                        traceback.print_exc(file=f)
                    if status_label:
                        janela.after(0, lambda: status_label.configure(
                            text=f"❌ Regressão de homologação: erro geral — {msg}"))
                    return
                ok_final = bool(resultados) and all(r["ok"] for r in resultados)
                if ok_final:
                    texto_final = "✅ Regressão de homologação concluída (Passo 1-5)."
                elif resultados:
                    ultimo = resultados[-1]
                    texto_final = f"❌ Regressão de homologação parou em '{ultimo['passo']}': {ultimo['mensagem']}"
                    with open(_log_regressao, "w", encoding="utf-8") as f:
                        f.write(f"parou em '{ultimo['passo']}'\n\nmensagem completa:\n{ultimo['mensagem']}\n\ntodos os resultados:\n{resultados}\n")
                else:
                    texto_final = "❌ Regressão de homologação: nenhum resultado."
                if status_label:
                    janela.after(0, lambda: status_label.configure(text=texto_final))

            threading.Thread(target=_run, daemon=True).start()

        ctk.CTkButton(jan, text="▶  RODAR TESTE (Passo 1-5)",
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      fg_color=COR_ROXO, hover_color=_lighten(COR_ROXO),
                      height=42, corner_radius=8, command=_rodar).pack(fill="x", padx=20, pady=(20, 10))


def toggle_pausa():
    global PAUSADO
    PAUSADO = not PAUSADO
    if PAUSADO:
        btn_pausa.configure(text="▶  RETOMAR", fg_color=COR_SUCESSO, hover_color="#27ae60")
    else:
        btn_pausa.configure(text="⏸  PAUSAR", fg_color=COR_AVISO, hover_color="#d68910")


def salvar_login():
    pass  # handled by AuraApp._salvar_login


status_label = None
label_pdf = None
btn_pausa = None
lbl_strip_comp = None
lbl_strip_pdf = None

janela = AuraApp()

janela.mainloop()