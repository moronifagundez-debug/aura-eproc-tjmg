"""
Pipeline de regressão de homologação — Primeira Parte.

Encadeia robôs reais da AURA seguindo o rito processual de 2ª instância,
partindo de um processo JÁ existente (não roda o AURA ADVOGADO). Três
"personalidades" de login diferentes -- confirmado ao vivo que trocar de
perfil (`selInfraUnidades`) sempre significa trocar de papel + órgão de
atuação juntos, e que só o magistrado titular do processo pode assinar
uma decisão de verdade:

  1. AURA COTRI    -> distribui/decide via Preferência de Minuta da
                       Unidade (ex: "Competência Direito Público"), que
                       agenda o evento de distribuição (ex: "Conclusos
                       para decisão com revisão de autuação") e o órgão
                       de destino dentro da própria minuta -- disparado
                       junto com a assinatura da minuta gerada.
  2. AURA GABINETE -> mesma conta COTRI trocando de perfil pro
                       órgão/lotação do gabinete. Minuta a decisão
                       (evento "Não Concedida a Antecipação de tutela")
                       + agenda a remessa ao cartório (evento "Remetidos
                       os Autos com decisão/despacho") + encaminha a
                       minuta para assinatura -- tudo numa única chamada.
  3. MAGISTRADO    -> conta SEPARADA (login próprio, não COTRI/GABINETE)
                       do magistrado titular do processo -- sigla lida
                       automaticamente da coluna "Assinante indicado" da
                       minuta criada no Passo 2 (não precisa ser
                       informada pelo chamador). Assina a minuta
                       encaminhada no Passo 2, o que dispara os eventos
                       de decisão + remessa agendados, juntos.

Cada passo é uma função fina que só encadeia funções já existentes em
integrations/run_aura_cotri.py e integrations/auragabinete.py -- nenhuma
navegação/login/seleção de perfil é reimplementada aqui.

Nenhum passo aqui é considerado validado sem confirmação visual ao vivo
na tela real do eproc de homologação (ver memória do projeto -- este
módulo nasceu de sessões de pareamento, não de escrita às cegas).
"""
import os
import re
import sys
import time
import traceback

_DIR_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("integrations", "shared"):
    _caminho = os.path.join(_DIR_BASE, _sub)
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

import run_aura_cotri as _cotri
import auragabinete as _gabinete
import run_aura_eventoscamaracivel as _eventoscamaracivel
import run_aura_sessao_julgamento as _sessaojulgamento
from aura_db import ler_processos_ajuizados
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

EVENTO_DECISAO_PADRAO = "Não Concedida a Antecipação de tutela"
EVENTO_REMESSA_PADRAO = "Remetidos os Autos com decisão/despacho"
EVENTO_DISTRIBUICAO_COTRI_PADRAO = "Conclusos para decisão com revisão de autuação"

# Passo 4 -- CARTÓRIO intima (tela "Intimação Eletrônica", acao=processo_intimacao).
# Value real do <option> de #selEventoJudicial, capturado via DOM ao vivo em
# 2026-08-18 -- não é um hash por sessão, é o código fixo do evento no eproc.
VALOR_EVENTO_INTIMACAO_PADRAO = "40400410"  # "...- Despacho/Decisão"
PRAZO_INTIMACAO_PADRAO_DIAS = "1"

# Passo 5 -- ADVOGADO responde (reaproveita aura.py::executar_intermediario).
EVENTO_PETICAO_PADRAO = "PETIÇÃO"
TIPO_DOCUMENTO_PETICAO_PADRAO = "PETIÇÃO"

# Passo 6 -- CARTÓRIO conclui pro GABINETE (tela "Movimentação Processual",
# aberta pelo botão verde "Movimentar" da capa -- mesma tela genérica usada
# pelo Passo 1 v1/executar_movimentar_com_evento). Evento "Conclusos para
# decisão/despacho (51)" -- hdnEvento real capturado ao vivo em 2026-08-19,
# não é um hash por sessão, é o código fixo do evento no eproc. O campo
# Órgão dessa tela vem pré-preenchido/desabilitado (o eproc já sabe pra
# qual assento devolver a partir do cartório) -- não precisa ser escolhido.
EVENTO_CONCLUSOS_DECISAO_PADRAO = "Conclusos para decisão/despacho"
VALOR_EVENTO_CONCLUSOS_PADRAO = "40400164"

# Passo 1 v2 -- distribuição via preferência de minuta da unidade (substitui
# o antigo caminho por "Movimentar Processo"). Ver
# run_aura_cotri.distribuir_com_preferencia_unidade. O órgão de destino NÃO
# é fixado aqui -- é lido dinamicamente do órgão julgador atual do processo
# (ler_orgao_julgador_da_capa), pra funcionar em qualquer câmara/assento.
TERMO_PREFERENCIA_DISTRIBUICAO_PADRAO = "Competência Direito Público"

# Reorganização confirmada pelo usuário em 2026-08-20: o antigo setor único
# "COTRI" foi dividido em dois -- COAPUB (Coordenação de Análise Processual
# Pública) e COAPRI (Coordenação de Análise Processual Privada). A tela de
# Seleção de Perfil do eproc não tem mais nenhum perfil com o texto "COTRI"
# (confirmado ao vivo: a lotação "DIRETOR DISTRIBUIÇÃO" agora só aparece com
# lotação "Coordenação de Análise Processual Pública (COAPUB)" ou "...
# Privada (COAPRI)"), então o valor usado pra selecionar perfil precisa ser
# um desses dois -- escolhido pela competência do processo, igual já se
# fazia pra escolher a preferência de minuta (TERMO_PREFERENCIA_DISTRIBUICAO).
SETOR_DISTRIBUICAO_PUBLICO = "COAPUB"
SETOR_DISTRIBUICAO_PRIVADO = "COAPRI"


def setor_distribuicao_da_competencia(competencia: str) -> str:
    """Mapeia a competência do processo (ex: "Direito Público", "Direito
    Privado") pro setor de distribuição que substituiu o COTRI único.
    Default é COAPUB (público) se a competência não indicar privado --
    mesmo default que `escolher_processo_teste`/`rodar_pipeline_completo`
    já usavam pra "Direito Público"."""
    if "privad" in (competencia or "").strip().lower():
        return SETOR_DISTRIBUICAO_PRIVADO
    return SETOR_DISTRIBUICAO_PUBLICO

# Senha padrão de TODAS as contas de teste no ambiente de HOMOLOGAÇÃO
# (confirmado pelo usuário) -- NÃO é uma senha de produção. Usada como
# padrão pra senha do magistrado, já que o usuário (sigla) é lido
# dinamicamente da própria minuta (ver ler_assinante_indicado_minuta_atual
# em auragabinete.py) e não faz sentido pedir a senha manualmente todo dia
# se ela é sempre a mesma neste ambiente.
SENHA_HOMOLOGACAO_PADRAO = "Senha123"

# Sigla de login (+ lotação pra desambiguar a tela de Seleção de Perfil,
# ver abrir_sessao_magistrado) dos magistrados de teste usados como VOGAIS
# do quórum na Sessão de Julgamento (Passo 8) -- diferente do magistrado
# RELATOR/assinante (Passo 3), cuja sigla é lida dinamicamente da minuta.
# Achadas em 27/08/2026 via Cadastro de Usuários (perfil GERENTE DE
# USUÁRIOS), ver memória do projeto (project_aura_sessao_julgamento.md).
# Mesmos nomes já usados por `presidente`/`votantes` em
# `passo8_cartorio_avancar_sessao` -- decisão explícita do usuário
# (2026-08-27): o robô loga sozinho como o vogal (reusa
# abrir_sessao_magistrado, mesmo padrão já usado pro relator), sem pausa
# manual.
SIGLAS_MAGISTRADOS_HOMOLOGACAO = {
    "CHRISTIAN GOMES LIMA": ("t0026716", "MAGISTRADO"),
    "LILIAN MACIEL SANTOS": ("T0022970", "MAGISTRADO"),
    "FERNANDO CALDEIRA BRANT": ("m2415248", "MAGISTRADO"),
}


class StatusConsole:
    """Substituto mínimo pro widget de status que as funções de
    run_aura_cotri.py (.config(text=...), API tkinter normal) e
    aura.py::executar_intermediario (.configure(text=...), API CTkLabel)
    esperam em `status` -- precisa aceitar os dois nomes (bug real visto em
    2026-08-18: só tinha .config, e o Passo 5 quebrava com AttributeError
    assim que executar_intermediario chamava .configure)."""

    def config(self, text=""):
        if text:
            print(f"[status] {text}")

    configure = config


# ---------------------------------------------------------------------------
# Escolha do processo de teste
# ---------------------------------------------------------------------------
def escolher_processo_teste(competencia_contendo="Direito Público"):
    """Escolhe o processo mais recente da competência informada, lendo a
    aba 'processos_ajuizados' (mesma fonte que o AURA INTERMEDIÁRIO usa).
    Ignora linhas sem número de processo ou com aviso/erro registrado."""
    candidatos = [
        p for p in ler_processos_ajuizados()
        if competencia_contendo in (p.get("Competência") or "")
        and (p.get("Processo") or "").strip()
        and not (p.get("Aviso") or "").strip()
    ]
    if not candidatos:
        raise RuntimeError(
            f"Nenhum processo utilizável encontrado para competência "
            f"contendo {competencia_contendo!r} em 'processos_ajuizados'."
        )

    def _data_ordenavel(p):
        try:
            d, m, a = p["Data"].split("/")
            return (a, m, d)
        except Exception:
            return ("0000", "00", "00")

    candidatos.sort(key=_data_ordenavel)
    return candidatos[-1]["Processo"]


# ---------------------------------------------------------------------------
# Sessões (driver/bot) reaproveitando setup já existente em cada robô
# ---------------------------------------------------------------------------
def abrir_sessao_cotri(usuario, senha, url, perfil=SETOR_DISTRIBUICAO_PUBLICO):
    """Replica o setup usado no início de executar_assinatura_cotri /
    executar_redistribuicao_cotri: cria driver, loga, seleciona perfil.

    NÃO fecha o driver sozinho se o login/seleção de perfil falhar --
    antes fechava (pra não deixar janela órfã), mas isso contrariava a
    diretriz do usuário de nunca fechar o Chrome em erro (2026-08-19,
    "a homologação é justamente para ver o que pode dar errado"; achado
    ao vivo em 2026-08-20 que esse fechamento aqui dentro também
    contava -- via de fora parecia "abre e fecha sozinho"). O Chrome
    fica aberto pra inspeção; o chamador ainda recebe a exceção
    normalmente, só não ganha um `driver` de volta pra fechar.

    `perfil` default é COAPUB (setor de distribuição de Direito Público) --
    o antigo perfil único "COTRI" não existe mais no eproc (setor dividido
    em COAPUB/COAPRI, ver setor_distribuicao_da_competencia)."""
    driver, wait, _ = _cotri.criar_driver()
    driver.get(url)
    driver.maximize_window()
    _cotri.fazer_login(driver, wait, usuario, senha)
    if not _cotri.selecionar_perfil(driver, perfil):
        raise RuntimeError(
            f"Não foi possível selecionar o perfil de distribuição {perfil} -- "
            "verifique se o usuário tem esse perfil (COAPUB/COAPRI) no eproc. "
            "Chrome deixado aberto de propósito pra inspeção (não fecha em erro)."
        )
    return driver, wait


def fechar_sessao_cotri(driver, url):
    """Encerra a sessão (acao=sair, via `deslogar`) e só depois fecha o
    Chrome. Fechar o navegador direto sem deslogar antes deixa a sessão do
    eproc ativa no servidor e atrapalha o login seguinte com a mesma conta
    -- ex.: Passo 1/2 e Passo 4/5 reabrem sessão nova (driver novo) com o
    mesmo usuário (p0046863), então a sessão anterior precisa ser encerrada
    de verdade primeiro (confirmado pelo usuário ao vivo, 2026-08-19; mesmo
    padrão já usado em abrir_sessao_magistrado/deslogar). Retorna True se
    driver.quit() completou sem exceção (só informativo -- chamado sempre
    de dentro de um finally, então o valor de retorno não muda o fluxo do
    chamador)."""
    try:
        deslogar(driver, url)
    except Exception:
        pass
    try:
        driver.quit()
        return True
    except Exception:
        return False


def _termo_camara_da_capa(orgao_texto: str) -> str:
    """Converte o texto da capa do processo (ex: "19ª CACIV - Assento 1")
    na sigla usada no combobox de troca de perfil #selInfraUnidades (ex:
    "19CACIV-A1") -- confirmado ao vivo (2026-08-16) que os dois textos
    descrevem a mesma câmara/assento com nomenclaturas diferentes (um por
    extenso com "Assento N", o outro como sigla compacta "NCACIV-AN"), então
    um NÃO é substring do outro -- por isso não dá pra simplesmente reusar o
    texto da capa como termo de busca no combobox."""
    if not orgao_texto:
        return ""
    m_num = re.search(r"(\d+)\s*ª?\s*C[AÁ]CIV", orgao_texto, re.IGNORECASE)
    if not m_num:
        return ""
    m_assento = re.search(r"Assento\s*(\d+)", orgao_texto, re.IGNORECASE)
    if m_assento:
        return f"{m_num.group(1)}CACIV-A{m_assento.group(1)}"
    return f"{m_num.group(1)}CACIV"


def _termo_cartorio_da_capa(orgao_texto: str) -> str:
    """Mesma leitura de _termo_camara_da_capa, mas retorna a sigla do
    CARTÓRIO (sem sufixo de assento, ex: "19CACIV") -- órgão SEPARADO do
    gabinete do desembargador (ex: "19CACIV-A4"), confirmado ao vivo em
    2026-08-17: "cartório" x "gabinete" é uma distinção de ÓRGÃO/lotação,
    não de tipo de usuário (mesmo TIPO_USUARIO_GERENTE_SECRETARIA nos
    dois) -- ver run_aura_eventoscamaracivel.carregar_camara/orgaos_caciv.json,
    que já modela o cartório como o nó final da cadeia de cada câmara."""
    if not orgao_texto:
        return ""
    m_num = re.search(r"(\d+)\s*ª?\s*C[AÁ]CIV", orgao_texto, re.IGNORECASE)
    if not m_num:
        return ""
    return f"{m_num.group(1)}CACIV"


def _trocar_perfil_com_cadastro_fallback(driver, wait, usuario, sigla_orgao):
    """Troca pro perfil GERENTE GABINETE/SECRETARIA de `sigla_orgao` na
    sessão atual (mesmo driver, sem novo login); se a lotação ainda não
    existir, cadastra sozinho (_cadastrar_lotacao_gabinete -- genérica
    apesar do nome, funciona pra gabinete OU cartório) e tenta de novo.
    Fatorado de trocar_para_gabinete pra trocar_para_cartorio reusar sem
    duplicar o try/except."""
    perfil_alvo = f"{sigla_orgao}/GERENTE GABINETE/SECRETARIA"
    try:
        _eventoscamaracivel.trocar_perfil(driver, wait, perfil_alvo)
    except (NoSuchElementException, TimeoutException):
        # TimeoutException também é tratada aqui (não só NoSuchElementException):
        # se a aba não estiver na tela normal do eproc (com #selInfraUnidades no
        # cabeçalho) -- ex.: presa numa tela de confirmação pós-assinatura do
        # Passo 1 -- trocar_perfil não acha o elemento e o wait.until estoura
        # timeout em vez de levantar NoSuchElementException diretamente.
        print(f"[status] Perfil '{perfil_alvo}' não encontrado/não confirmado -- cadastrando lotação...")
        _cadastrar_lotacao_gabinete(driver, wait, usuario, sigla_orgao)
        _eventoscamaracivel.trocar_perfil(driver, wait, perfil_alvo)
    return perfil_alvo


def trocar_para_gabinete(driver, wait, usuario, orgao_texto):
    """Troca o perfil ativo para GERENTE GABINETE/SECRETARIA no órgão
    distribuído no Passo 1, na MESMA sessão/driver do COTRI -- não fecha o
    Chrome e abre outro (confirmado pelo usuário ao vivo: "ele tem que
    apenas trocar o perfil para o órgão do processo depois do COTRI
    assinar"). Usa o combobox #selInfraUnidades (mesmo padrão já testado
    em produção por run_aura_eventoscamaracivel.trocar_perfil). Se essa
    lotação ainda não existir na conta, cadastra sozinho e tenta de novo
    ("se não existir o perfil ele cadastra").

    Retorna um EprocBotV4 com o driver já anexado (sem abrir navegador
    novo), pra reaproveitar executar_minutar_com_agendamento como está."""
    sigla_camara = _termo_camara_da_capa(orgao_texto)
    if not sigla_camara:
        raise RuntimeError(
            f"Não foi possível extrair a sigla da câmara a partir do "
            f"órgão distribuído no Passo 1 ({orgao_texto!r})."
        )
    _trocar_perfil_com_cadastro_fallback(driver, wait, usuario, sigla_camara)

    bot = _gabinete.EprocBotV4(log_callback=print)
    bot.driver = driver
    bot.wait = wait
    bot.wait_longo = WebDriverWait(driver, _gabinete.TIMEOUT_LONGO)
    bot._janela_principal = driver.current_window_handle
    return bot


def trocar_para_cartorio(driver, wait, usuario, orgao_texto):
    """Troca o perfil ativo para GERENTE GABINETE/SECRETARIA no CARTÓRIO
    (órgão sem assento, ex: "19CACIV") -- diferente do gabinete do
    desembargador (trocar_para_gabinete, com assento, ex: "19CACIV-A4").
    Usado no Passo 4 (CARTÓRIO intima as partes), que só pode rodar DEPOIS
    da assinatura do magistrado (Passo 3) ter disparado a remessa de
    verdade pro cartório -- por isso é uma sessão nova (abrir_sessao_cotri
    de novo), não a mesma sessão dos Passos 1-2 (já fechada nesse ponto)."""
    sigla_cartorio = _termo_cartorio_da_capa(orgao_texto)
    if not sigla_cartorio:
        raise RuntimeError(
            f"Não foi possível extrair a sigla do cartório a partir do "
            f"órgão do processo ({orgao_texto!r})."
        )
    _trocar_perfil_com_cadastro_fallback(driver, wait, usuario, sigla_cartorio)


def trocar_para_advogado(driver, wait, usuario):
    """Troca o perfil ativo pra ADVOGADO na MESMA sessão/driver do Passo 4
    (sem novo login) -- a conta de teste (p0046863) já tem esse perfil
    cadastrado, sem lotação/órgão associado (aparece no combobox
    #selInfraUnidades como "{SIGLA} - ADVOGADO", confirmado por inspeção de
    DOM ao vivo em 2026-08-18). Diferente de trocar_para_gabinete/
    trocar_para_cartorio, não tem fallback de cadastro -- se esse perfil
    não existir na conta, é erro de configuração da conta de teste, não
    algo que o robô deva tentar corrigir sozinho."""
    perfil_alvo = f"{usuario.strip().upper()} - ADVOGADO"
    _eventoscamaracivel.trocar_perfil(driver, wait, perfil_alvo)


def _cadastrar_lotacao_gabinete(driver, wait, usuario, sigla_camara):
    """Cadastra a lotação GERENTE GABINETE/SECRETARIA em `sigla_camara`
    para `usuario`, se ainda não existir -- reaproveita
    run_aura_eventoscamaracivel.garantir_lotacao (já testado em produção
    pelo AURA EVENTOS CÂMARA CÍVEL) em vez de reimplementar o fluxo de
    Cadastro de Usuários aqui."""
    # O Cadastro de Usuários só funciona de verdade sob o perfil "GERENTE DE
    # USUÁRIOS" (confirmado ao vivo e replicado do padrão já usado em
    # run_aura_eventoscamaracivel.py, ex: linha 1015 -- troca pra esse
    # perfil sempre antes de chamar garantir_lotacao). Faltava essa troca
    # aqui: sem ela, ainda logado como COTRI, o menu "Cadastro de Usuários"
    # não expõe o formulário certo e txtSiglaOab nunca aparece (timeout).
    _eventoscamaracivel.trocar_perfil(driver, wait, _eventoscamaracivel.PERFIL_GERENTE_USUARIOS)
    _eventoscamaracivel.abrir_cadastro_usuarios(driver, wait)
    valores = _eventoscamaracivel.resolver_valores_orgao(
        driver, wait, [sigla_camara], usuario, exigir_todos=False,
    )
    if sigla_camara not in valores:
        raise RuntimeError(
            f"Órgão {sigla_camara!r} não encontrado no cadastro de "
            "usuários -- não é possível cadastrar a lotação."
        )
    descricao = _eventoscamaracivel._ULTIMO_MAPA_DESCRICOES.get(sigla_camara, "")
    orgao = {
        "sigla": sigla_camara,
        "descricao": f"{sigla_camara} - {descricao}",
        "orgao_valor": valores[sigla_camara],
    }
    _eventoscamaracivel.garantir_lotacao(driver, wait, usuario, orgao, log=print)


def abrir_sessao_magistrado(usuario_magistrado, senha, url, lotacao_contendo=""):
    """Abre uma sessão NOVA (login do zero) com a conta do MAGISTRADO --
    diferente de COTRI/GABINETE, que compartilham uma única conta (p0046863)
    trocando de perfil. `usuario_magistrado` é a sigla do magistrado titular
    do processo (ex: 't0011585'), lida da coluna "Assinante indicado" da
    minuta -- NÃO é um valor fixo, muda por processo/relator.

    Só o magistrado pode assinar uma decisão de verdade (confirmado pelo
    usuário em pareamento ao vivo) -- COTRI/GABINETE são sempre papel de
    assessor/cartório, nunca assinam em nome do magistrado. Cada sessão
    usa um `driver` (janela do Chrome) próprio, então não há sessão de
    cookies compartilhada com COTRI/GABINETE pra deslogar aqui -- a
    função `deslogar` é só pra encerrar a sessão do magistrado no fim do
    pipeline (ver rodar_pipeline_primeira_parte)."""
    driver, wait, _ = _cotri.criar_driver()
    driver.get(url)
    driver.maximize_window()
    _cotri.fazer_login(driver, wait, usuario_magistrado, senha)

    # Conta com uma única lotação: o eproc pula direto a tela "Seleção de
    # perfil" e já cai logado no perfil certo -- não há nenhum <button
    # list-group-item> pra selecionar nesse caso, e selecionar_perfil
    # (que só sabe procurar nessa tela) retorna False depois de ~20s de
    # retry mesmo com o login 100% correto. Detecta isso ANTES de chamar
    # selecionar_perfil: se não sobrou nenhum botão de perfil na tela e já
    # saímos da tela de login (sem #txtUsuario), está tudo certo, segue.
    time.sleep(1)
    tem_tela_selecao = bool(driver.find_elements(By.XPATH, '//button[contains(@class,"list-group-item")]'))
    ainda_na_tela_login = bool(driver.find_elements(By.ID, "txtUsuario"))
    if tem_tela_selecao:
        termo_busca = lotacao_contendo or "MAGISTRADO"
        if not _cotri.selecionar_perfil(driver, termo_busca):
            # Diagnóstico: lista os perfis realmente disponíveis na tela,
            # já que o termo de busca (sigla do órgão) pode estar certo e
            # ainda assim não bater com o texto/data-descricao real dos
            # botões -- sem isso não dá pra saber se é formato diferente
            # do esperado ou se a lotação genuinamente não existe.
            try:
                botoes = driver.find_elements(By.XPATH, '//button[contains(@class,"list-group-item")]')
                opcoes = [
                    (b.get_attribute("data-descricao") or b.text or "").strip()
                    for b in botoes
                ]
            except Exception:
                opcoes = ["<falha ao listar>"]
            raise RuntimeError(
                f"Não foi possível selecionar o perfil do magistrado "
                f"(buscou por {termo_busca!r}) para a conta {usuario_magistrado!r}. "
                f"Perfis disponíveis na tela: {opcoes}"
            )
    elif ainda_na_tela_login:
        raise RuntimeError(
            f"Login falhou para a conta {usuario_magistrado!r} -- ainda na "
            "tela de login depois de tentar entrar."
        )
    # else: sem tela de seleção e fora da tela de login -- conta com
    # lotação única, já caiu logada no perfil certo. Nada a fazer.
    return driver, wait


def deslogar(driver, url):
    """Encerra a sessão atual sem fechar o navegador -- usado entre trocar
    de conta (ex: COTRI/GABINETE -> MAGISTRADO), já que login novo com
    outra conta não funciona por cima de uma sessão de cookies ainda
    ativa.

    Clica no link real "Encerrar Sessão" do menu de perfil
    (id="btn-encerrar-sessao", href="controlador.php?acao=sair&hash=...")
    em vez de montar a URL de acao=sair à mão -- correção do usuário ao
    vivo em 2026-08-20 (colou o HTML real do link): sem o `hash` da
    sessão embutido no link, `acao=sair` construído manualmente pode
    devolver "Link sem assinatura" e travar a sessão em vez de encerrá-la
    de verdade -- mesmo padrão que já causou outros travamentos de login
    nesta mesma sessão de trabalho. Clique via JS: não exige o elemento
    estar visível (o link fica dentro do menu de perfil, não precisa
    abrir o menu antes)."""
    try:
        clicou = driver.execute_script(
            "var el = document.getElementById('btn-encerrar-sessao'); "
            "if (el) { el.click(); return true; } return false;"
        )
    except Exception:
        clicou = False
    if not clicou:
        # Fallback só se o link não existir na tela (ex: página fora do
        # padrão do eproc) -- menos confiável, mas melhor que nada.
        base = url.rstrip("/").split("/versao")[0] + "/versao"
        driver.get(f"{base}/controlador.php?acao=sair")
    time.sleep(2)


# ---------------------------------------------------------------------------
# Resultado estruturado por passo
# ---------------------------------------------------------------------------
def _resultado(passo, ok, mensagem, inicio, num_processo="", **extra):
    return {
        "passo": passo,
        "processo": num_processo,
        "ok": bool(ok),
        "mensagem": str(mensagem),
        "duracao_s": round(time.time() - inicio, 1),
        **extra,
    }


# ---------------------------------------------------------------------------
# Passo 1 -- COTRI distribui, via Preferência de Minuta da Unidade
# ---------------------------------------------------------------------------
# v2 (2026-08-16, validado ao vivo ponta a ponta): o caminho certo NÃO é a
# tela genérica "Movimentar Processo" (v1, ver executar_movimentar_com_evento
# -- mantida em run_aura_cotri.py por já ser usada em outros fluxos), é a
# Preferência de Minuta da Unidade -- combina minuta + evento + assinatura
# num fluxo só, com documento anexado de verdade. Requer a senha da conta
# COTRI porque a assinatura (executar_assinatura) já acontece aqui dentro.
def passo_cotri_distribuir(driver, wait, num_processo, url, senha,
                            termo_preferencia=TERMO_PREFERENCIA_DISTRIBUICAO_PADRAO,
                            evento=EVENTO_DISTRIBUICAO_COTRI_PADRAO,
                            orgao_destino=None):
    inicio = time.time()
    status = StatusConsole()
    ultimo_aviso = []
    try:
        orgao_usado = _cotri.distribuir_com_preferencia_unidade(
            driver, wait, num_processo, url, senha, ultimo_aviso, status, num_fila=1,
            termo_preferencia=termo_preferencia, evento=evento, orgao_destino=orgao_destino,
        )
        return _resultado(
            "cotri_distribuir", True,
            " | ".join(ultimo_aviso) or f"Distribuído via preferência '{termo_preferencia}': {evento}",
            inicio, num_processo, orgao_destino=orgao_usado,
        )
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("cotri_distribuir", False, detalhe, inicio, num_processo)


# ---------------------------------------------------------------------------
# Passo 2 -- GABINETE minuta + remessa
# ---------------------------------------------------------------------------
def passo_gabinete_minutar(bot, num_processo, texto_minuta,
                            evento=EVENTO_DECISAO_PADRAO,
                            evento_remessa=EVENTO_REMESSA_PADRAO):
    inicio = time.time()
    dados = {
        "num_processo": num_processo,
        "tipo_modelo": "DESPACHO",
        "descricao": "",
        "assinante": "",
        "tratamento": "",
        "sigilo": "",
        "status_minuta": "Rascunho",
        "cabecalho": {},
        "precedente_relevante": "",
        "agendar": "S",
        "evento": evento,
        "evento_remessa": evento_remessa,
        "comportamento_localizador": "",
        "marcar_todos_atuais": "N",
        "novo_localizador": "",
        "localizadores_secundarios": "",
        "localizadores_desativar": "",
        "intimar_automatico": "",
        "texto_minuta": texto_minuta,
        "salvar_e_sair": "S",
        # Assinatura fica para o passo 3 (MAGISTRADO) -- não autoassinar aqui.
        "assinar": "",
        "senha": "",
        # "N" aqui de propósito: quem encaminha pra assinatura é este
        # módulo de teste (logo abaixo), depois de ler o Assinante
        # Indicado -- assim executar_minutar_com_agendamento (função de
        # PRODUÇÃO, usada pelo AURA GABINETE de verdade) fica exatamente
        # como sempre foi pra quem não é este pipeline de teste.
        "encaminhar_assinatura": "N",
    }
    try:
        ok, motivo = bot.executar_minutar_com_agendamento(dados)
        if not ok:
            return _resultado("gabinete_minutar", False, motivo, inicio, num_processo)

        # Sigla do magistrado lida da própria tela (coluna "Assinante
        # indicado" da minuta recém-criada) -- é o que permite o Passo 3
        # logar como o magistrado certo sem pedir isso manualmente. Lida
        # ANTES de encaminhar pra assinatura de propósito: não confirmado
        # ao vivo se o ícone usado pra achar a linha (img[acao=
        # 'minuta_para_assinar']) continua no DOM depois de clicado.
        assinante_indicado = bot.ler_assinante_indicado_minuta_atual()
        bot.encaminhar_para_assinatura()

        return _resultado("gabinete_minutar", True, motivo, inicio, num_processo,
                           assinante_indicado=assinante_indicado)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("gabinete_minutar", False, detalhe, inicio, num_processo)


# ---------------------------------------------------------------------------
# Passo 3 -- MAGISTRADO assina (conta separada, lida dinamicamente da minuta)
# ---------------------------------------------------------------------------
# Descoberta arquitetural do pareamento ao vivo (2026-08-16): só o
# magistrado/desembargador titular do processo pode assinar uma decisão de
# verdade -- COTRI/GABINETE nunca assinam em nome dele, são sempre papel de
# assessor/cartório. Por isso este passo abre uma sessão NOVA (login
# separado, ver abrir_sessao_magistrado) em vez de reaproveitar a sessão
# COTRI/GABINETE.
def passo_magistrado_assinar(driver, wait, num_processo, senha):
    """Assina, no "Painel do Magistrado", a minuta 'Para assinar' referente
    a `num_processo`. Pressupõe que a sessão já está logada como o
    magistrado certo (abrir_sessao_magistrado) e que a minuta já foi
    encaminhada para assinatura no Passo 2
    (EprocBotV4.encaminhar_para_assinatura, já embutido em
    executar_minutar_com_agendamento)."""
    inicio = time.time()
    try:
        # O Painel do Magistrado tem várias linhas com link pra
        # acao=minuta_area_trabalho, uma por card (Minutas para assinar,
        # Minutas bloqueadas, Minutas gabinete para assinatura, etc.) --
        # pegar sempre o primeiro sem filtrar (bug anterior) cai na linha
        # errada. Acha a <tr> cujo texto é especificamente "Minutas para
        # assinar" (não "assinatura", que é outra linha/card -- as duas
        # palavras não são substring uma da outra) e pega o link de DENTRO
        # dela -- mais direto e confiável do que tentar achar o link
        # primeiro e adivinhar o ancestral certo depois.
        linha_dashboard = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((
                By.XPATH, "//tr[contains(normalize-space(.), 'Minutas para assinar')]",
            ))
        )
        link = linha_dashboard.find_element(
            By.XPATH, ".//a[contains(@href, 'acao=minuta_area_trabalho')]"
        )
        href_link = link.get_attribute("href") or ""

        # O contador abre a "Minuta Área de Trabalho" numa ABA NOVA (mesmo
        # padrão window.open já visto na preferência de minuta do Passo 1)
        # -- por isso a URL da aba original nunca mudava e a linha "sumia":
        # ela estava numa aba diferente que o código nunca trocava pra
        # olhar. Rastreia as janelas antes/depois do clique e troca pra
        # nova se ela existir.
        janelas_antes = set(driver.window_handles)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
        time.sleep(0.3)
        try:
            link.click()
        except Exception:
            driver.execute_script("arguments[0].click();", link)
        time.sleep(3)

        nova_janela = None
        for _ in range(10):
            extras = set(driver.window_handles) - janelas_antes
            if extras:
                nova_janela = extras.pop()
                break
            time.sleep(0.5)
        if nova_janela:
            driver.switch_to.window(nova_janela)
        elif "acao=minuta_area_trabalho" not in driver.current_url and href_link:
            # Nem abriu aba nova, nem a aba atual navegou -- último recurso:
            # navega direto pro href já capturado, na aba atual mesmo.
            driver.get(href_link)
            time.sleep(3)

        # Overlay de carregamento "infra" (mesmo padrão usado em
        # run_aura_eventoscamaracivel._clicar) -- se a grade carrega os
        # dados via AJAX depois da navegação, esse overlay cobre a tela
        # enquanto isso acontece; esperar ele sumir evita procurar a linha
        # cedo demais, antes dos dados chegarem.
        try:
            WebDriverWait(driver, 10).until(
                EC.invisibility_of_element_located((By.ID, "divInfraAvisoFundo"))
            )
        except TimeoutException:
            pass

        # "Minuta Área de Trabalho" abre como um FORMULÁRIO DE FILTROS (com
        # Status já vindo "Para assinar" pré-preenchido) -- a tabela de
        # resultados só aparece depois de clicar em "Consultar", no canto
        # superior direito. Confirmado ao vivo (mapeamento manual, 2026):
        # sem esse clique a lista fica vazia pra sempre, não é questão de
        # esperar mais. Esse clique é OBRIGATÓRIO, não best-effort.
        botao_consultar = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH, "//*[self::a or self::button][normalize-space(.)='Consultar']",
            ))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", botao_consultar)
        time.sleep(0.3)
        try:
            botao_consultar.click()
        except Exception:
            driver.execute_script("arguments[0].click();", botao_consultar)
        time.sleep(4)

        # Ambiente de HOMOLOGAÇÃO, decisão do usuário: em vez de achar a
        # linha específica do processo, usa o "Selecionar Tudo" do
        # cabeçalho (id="imgInfraCheck") -- mais simples e, nesta conta de
        # teste, só há mesmo a minuta deste pipeline pendente. Espera a
        # grade carregar (pelo menos 1 linha de dado, com checkbox) antes
        # de clicar, pra não clicar num "selecionar tudo" vazio.
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.XPATH, "//tr[.//input[@type='checkbox']]"))
        )
        selecionar_tudo = driver.find_element(By.ID, "imgInfraCheck")
        driver.execute_script("arguments[0].click();", selecionar_tudo)
        time.sleep(1)

        # PENDÊNCIA: não confirmado ao vivo via Selenium se este botão é
        # <a> ou <button> na "Minuta Área de Trabalho" (só clicado
        # visualmente na tela) -- casa os dois pra não quebrar por isso.
        btn_assinar = driver.find_element(
            By.XPATH, "//*[self::a or self::button][normalize-space(.)='Assinar']"
        )
        driver.execute_script("arguments[0].click();", btn_assinar)
        time.sleep(3)
        _cotri.fechar_alerta_silencioso(driver, [])

        _confirmar_assinatura_lista_minutas(driver, senha)

        return _resultado("magistrado_assinar", True, "Assinatura concluída.", inicio, num_processo)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("magistrado_assinar", False, detalhe, inicio, num_processo)


def _confirmar_assinatura_lista_minutas(driver, senha):
    """Preenche a senha e confirma no modal "Assinar lista de minutas"
    (aberto a partir da tela "Minuta Área de Trabalho" do painel do
    magistrado -- diferente do modal do editor CKEditor usado no Passo 1/2,
    que fica dentro do iframe ifrSubFrm). PENDÊNCIA: não foi confirmado ao
    vivo se este modal também roda num iframe -- esta função tenta entrar
    no ifrSubFrm se ele existir e cai para o documento principal se não."""
    frame = None
    try:
        frame = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.ID, "ifrSubFrm")))
        driver.switch_to.frame(frame)
    except Exception:
        frame = None
    try:
        # O campo VISÍVEL é mascarado (type="text", classe "masked") -- o
        # input[type=password] real fica oculto/sombra, sincronizado por JS
        # (mesmo padrão do campo de senha da assinatura CKEditor em
        # run_aura_cotri.py). send_keys direto no input[type=password]
        # levanta ElementNotInteractableException porque ele não é
        # visível/focável -- por isso usa o campo visível (#txtSenha,
        # mesmo id/padrão já usado em produção) com _preencher_senha (5
        # estratégias) em vez de mexer no oculto diretamente.
        try:
            campo_senha = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "txtSenha"))
            )
        except TimeoutException:
            campo_senha = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type=password]"))
            )
        _cotri._preencher_senha(driver, campo_senha, senha, StatusConsole(), 1)
        time.sleep(0.5)
        btn = driver.find_element(By.XPATH, "//button[contains(normalize-space(.), 'Assinar com Senha')]")
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(3)
    finally:
        if frame is not None:
            driver.switch_to.default_content()


# ---------------------------------------------------------------------------
# Passo 4 -- CARTÓRIO intima as partes (Intimação Eletrônica)
# ---------------------------------------------------------------------------
# Mapeado ao vivo em 2026-08-17 (fluxo/campos) e os ids reais confirmados por
# inspeção de DOM ao vivo em 2026-08-18 (mcp__claude-in-chrome, sem Selenium
# ainda). Nenhuma parte deste passo tinha sido executada de ponta a ponta via
# Selenium até este ponto -- primeira execução real vai confirmar/corrigir.
IDS_PRAZO_INTIMACAO_TODOS = [
    "txtPrazoTodos", "txtPrazoEntPrazoEspecial", "txtPrazoEntPrazoSimples",
    "txtPrazoNaoEntPrazoSimples", "txtPrazoDPU",
]


def _selecionar_evento_intimacao(driver, wait, evento):
    """Seleciona a opção em #selEventoJudicial (select nativo, NÃO
    autocomplete) -- por value se `evento` for só dígitos (ex: "40400410"),
    senão por substring do texto visível (case-insensitive)."""
    select_el = wait.until(EC.presence_of_element_located((By.ID, "selEventoJudicial")))
    sel = Select(select_el)
    evento_str = str(evento).strip()
    if evento_str.isdigit():
        sel.select_by_value(evento_str)
        return
    for opcao in sel.options:
        texto = (opcao.get_attribute("textContent") or "").strip()
        if evento_str.lower() in texto.lower():
            sel.select_by_visible_text(texto)
            return
    raise NoSuchElementException(
        f"Evento de intimação {evento!r} não encontrado em #selEventoJudicial"
    )


def _marcar_todos_e_preencher_prazo(driver, wait, prazo_dias):
    """Marca "Todos" (chkSelTodosTipoParte -- cascateia as 4 subcategorias
    de parte: Entidades com prazo especial/simples, Partes com prazo
    simples, DPU) e preenche o prazo em CADA campo txtPrazo* individualmente
    -- confirmado por inspeção de DOM ao vivo (2026-08-18) que marcar só o
    resumo "Todos" NÃO cascateia o valor do prazo pros campos das
    subcategorias (ficam habilitados e vazios, independentes um do outro).

    Decisão do usuário já registrada pra este mesmo pipeline (Passo 3,
    "Selecionar Tudo"): usar "Todos" direto é seguro só porque a conta de
    teste não tem outras partes/processos reais pendentes de intimação --
    reavaliar antes de reusar fora de homologação."""
    chk_todos = wait.until(EC.element_to_be_clickable((By.ID, "chkSelTodosTipoParte")))
    if not chk_todos.is_selected():
        driver.execute_script("arguments[0].click();", chk_todos)
        time.sleep(0.5)
    for campo_id in IDS_PRAZO_INTIMACAO_TODOS:
        try:
            campo = driver.find_element(By.ID, campo_id)
        except NoSuchElementException:
            continue
        if not campo.is_displayed() or not campo.is_enabled():
            continue
        campo.clear()
        campo.send_keys(str(prazo_dias))


def _confirmar_e_intimar(driver, wait):
    """Marca o checkbox obrigatório "Marque essa opção após confirmar os
    eventos/documentos sugeridos pelo sistema." (chkSelEventosDocTodos --
    sem ele, o clique em Intimar dispara um alert() nativo de validação que
    trava a aba, mesmo padrão já visto em outros pontos do eproc) e clica
    no botão final (id="btnSalvar", name="sbmProcessoIntimar", texto
    "Intimar" -- confirmado por inspeção de DOM ao vivo).

    BUG REAL corrigido em 2026-08-18: a primeira inspeção de DOM (feita sem
    testar de verdade) pegou o id ERRADO -- chkSelEventoDocumentoIntimacao
    NÃO é este checkbox, é "Habilitar opção de intimação/citação por
    documento(s) do evento" (outro campo, do lado direito da tela, sem
    relação nenhuma com a confirmação). Usar o id errado deixava o
    checkbox obrigatório de fato desmarcado -- reproduzido ao vivo via
    mcp__claude-in-chrome: clicar em Intimar sem marcar
    chkSelEventosDocTodos dispara o alert() de validação (o aviso que o
    usuário viu na tela durante a primeira rodada real do pipeline)."""
    chk_confirmar = wait.until(EC.element_to_be_clickable((By.ID, "chkSelEventosDocTodos")))
    if not chk_confirmar.is_selected():
        driver.execute_script("arguments[0].click();", chk_confirmar)
        time.sleep(0.3)
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@name='sbmProcessoIntimar']")))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(2)

    # Confirmação real de sucesso -- não basta "não deu exceção" (foi assim
    # que o bug do checkbox errado passou despercebido em 2026-08-18: o
    # clique "funcionava" sem lançar nada mesmo com o checkbox certo
    # desmarcado). Dois checks:
    avisos = []
    _cotri.fechar_alerta_silencioso(driver, avisos)
    if avisos:
        raise RuntimeError(
            "Intimar disparou alert() de validação do eproc (checkbox "
            f"obrigatório provavelmente faltando): {' | '.join(avisos)}"
        )
    WebDriverWait(driver, 15).until(EC.url_contains("processo_selecionar"))
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#tblEventos tbody tr"))
    )
    descricao_evento_novo = driver.find_element(
        By.CSS_SELECTOR, "#tblEventos tbody tr td.infraEventoDescricao"
    ).text
    if "intimação eletrônica" not in descricao_evento_novo.lower():
        raise RuntimeError(
            "Depois de clicar Intimar, o evento mais recente do processo não "
            f"é uma intimação eletrônica (é {descricao_evento_novo!r}) -- a "
            "intimação pode não ter sido registrada de verdade."
        )


def passo_cartorio_intima(driver, wait, num_processo,
                           evento=VALOR_EVENTO_INTIMACAO_PADRAO,
                           prazo_dias=PRAZO_INTIMACAO_PADRAO_DIAS):
    """CARTÓRIO intima as partes da decisão (Passo 4). Pressupõe que a
    sessão já está no perfil do cartório certo (trocar_para_cartorio,
    chamado pelo orquestrador) -- este passo só pesquisa o processo e opera
    a tela de Intimação Eletrônica."""
    inicio = time.time()
    try:
        _eventoscamaracivel.buscar_processo(driver, wait, num_processo)
        _eventoscamaracivel.abrir_intimar(driver, wait)
        _selecionar_evento_intimacao(driver, wait, evento)
        _marcar_todos_e_preencher_prazo(driver, wait, prazo_dias)
        _confirmar_e_intimar(driver, wait)
        return _resultado("cartorio_intima", True, f"Intimação lançada: evento {evento}", inicio, num_processo)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("cartorio_intima", False, detalhe, inicio, num_processo)


# ---------------------------------------------------------------------------
# Passo 5 -- ADVOGADO responde (petição intermediária)
# ---------------------------------------------------------------------------
# Roda na MESMA sessão/driver do Passo 4 -- decisão explícita do usuário
# (2026-08-18): "não precisa fechar a sessão. o p0046863 é advogado" --
# a conta de teste já tem perfil ADVOGADO cadastrado (sem lotação/órgão),
# então é só trocar de perfil (trocar_para_advogado) igual os Passos 2/4
# fazem pros perfis deles, não abrir sessão nova.
#
# A submissão em si reaproveita aura.py::executar_peticao_intermediaria_linha
# (extraída de executar_intermediario -- mesmo motor do botão "📋
# INTERMEDIÁRIO" da tela principal, incluindo o botão final
# name="sbmMovimentar", confirmado pelo usuário que é o MESMO elemento que
# a tela do advogado chama de "Peticionar"). Essa função não é importada
# aqui: aura.py já importa este módulo no topo (`import
# aura_regressao_homologacao as _run_regressao_homologacao`), então `import
# aura` aqui criaria um ciclo -- o chamador (aura.py) passa a própria
# função como `executar_peticao_fn`.
def passo_advogado_responder(driver, wait, usuario, executar_peticao_fn, num_processo,
                              caminho_pdf,
                              evento=EVENTO_PETICAO_PADRAO,
                              tipo_documento=TIPO_DOCUMENTO_PETICAO_PADRAO):
    """ADVOGADO responde à intimação do Passo 4 com uma petição
    intermediária, na mesma sessão/driver (só troca de perfil).
    `executar_peticao_fn` já cuida de pesquisar o processo, preencher
    evento/tipo, upload do PDF e submeter -- nada disso é reimplementado
    aqui."""
    inicio = time.time()
    status = StatusConsole()
    try:
        trocar_para_advogado(driver, wait, usuario)
        executar_peticao_fn(driver, wait, status, num_processo, evento, tipo_documento, caminho_pdf, 1)
        return _resultado("advogado_responder", True, f"Petição enviada: {evento}", inicio, num_processo)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("advogado_responder", False, detalhe, inicio, num_processo)


# ---------------------------------------------------------------------------
# Passo 6 -- CARTÓRIO conclui pro GABINETE
# ---------------------------------------------------------------------------
# Mapeado ao vivo em 2026-08-19 (ver memória do projeto), código escrito em
# 2026-08-20 reaproveitando funções já validadas em produção:
# run_aura_eventoscamaracivel.buscar_processo/abrir_movimentar (mesmo botão
# "Movimentar Processo" que o Passo 1 v1 já usava) e
# run_aura_cotri.preencher_evento_movimentar/clicar_movimentar (autocomplete
# de evento + submit, já testados em produção). Nada disso é reimplementado
# aqui -- só encadeado.
#
# PENDÊNCIA REAL (não resolvida ainda, não escondida): o rito correto tem o
# CARTÓRIO incluindo o processo numa Sessão de Julgamento (pauta/mesa)
# ENQUANTO o processo ainda está no cartório -- a ação "Incluir em
# Pauta/Mesa" só aparece na capa nesse estado (ver
# project_aura_sessao_julgamento). Essa inclusão foi mapeada (modal
# "Incluir item na Sessão", campos capturados) mas o "Salvar" NUNCA foi
# testado de verdade por falta de processo de teste no ambiente -- por
# isso essa função só cobre a movimentação de volta pro gabinete, e ainda
# não foi encadeada em rodar_pipeline_completo. Rodar sozinha (fora do
# pipeline) até a inclusão em pauta ser validada e escrita também, senão
# o Passo 6 automatizado repete o mesmo erro de ORDEM que já aconteceu no
# mapeamento ao vivo (concluir antes de incluir em pauta).
def _confirmar_conclusos(driver, wait, contem_no_texto="conclusos"):
    """Confirma que a movimentação de verdade aconteceu -- mesmo padrão de
    verificação real já usado em _confirmar_e_intimar (não basta "não deu
    exceção"): espera voltar pra capa do processo e confere que o evento
    mais recente do histórico realmente é uma conclusão, não só que o
    clique não lançou erro."""
    WebDriverWait(driver, 15).until(EC.url_contains("processo_selecionar"))
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#tblEventos tbody tr"))
    )
    descricao_evento_novo = driver.find_element(
        By.CSS_SELECTOR, "#tblEventos tbody tr td.infraEventoDescricao"
    ).text
    if contem_no_texto not in descricao_evento_novo.lower():
        raise RuntimeError(
            "Depois de clicar Movimentar, o evento mais recente do processo não "
            f"parece ser a conclusão pro gabinete (é {descricao_evento_novo!r}) -- "
            "a movimentação pode não ter sido registrada de verdade."
        )


def passo_cartorio_conclui(driver, wait, num_processo,
                            evento=EVENTO_CONCLUSOS_DECISAO_PADRAO):
    """CARTÓRIO movimenta o processo de volta pro GABINETE (Passo 6).
    Pressupõe que a sessão já está no perfil do cartório certo
    (trocar_para_cartorio, chamado pelo orquestrador ou pelo chamador
    direto) -- este passo só pesquisa o processo e opera a tela de
    Movimentação Processual: capa -> botão "Movimentar" (verde) ->
    autocomplete "Evento a ser lançado" -> "Conclusos para
    decisão/despacho (51)" -> botão "Movimentar". Não mexe no campo
    Órgão (vem pré-preenchido/desabilitado nessa tela)."""
    inicio = time.time()
    try:
        _eventoscamaracivel.buscar_processo(driver, wait, num_processo)
        _eventoscamaracivel.abrir_movimentar(driver, wait)
        _cotri.preencher_evento_movimentar(driver, wait, evento)
        _cotri.clicar_movimentar(driver, wait)
        _confirmar_conclusos(driver, wait)
        return _resultado("cartorio_conclui", True, f"Movimentado: {evento}", inicio, num_processo)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("cartorio_conclui", False, detalhe, inicio, num_processo)


# ---------------------------------------------------------------------------
# Passo 8 -- CARTÓRIO avança a sessão: fecha a pauta, monta quórum e
# composição, gera a pauta (publica + intima) e abre a sessão.
# ---------------------------------------------------------------------------
# Mapeado ao vivo em 2026-08-24 (ver project_aura_sessao_julgamento na
# memória do projeto), código escrito em 2026-08-26. Por decisão explícita
# do usuário, a mecânica de gestão de sessão (ações de CARTÓRIO na
# listagem de Sessões de Julgamento) vive em
# integrations/run_aura_sessao_julgamento.py -- NÃO em auragabinete.py,
# que fica reservado pras ações de minuta do GABINETE (EprocBotV4).
#
# NUNCA rodado via Selenium ainda -- primeira execução real precisa de
# acompanhamento visual (headless=False) antes de confiar, mesmo padrão
# já aplicado a todo esse módulo (ver docstring do arquivo).
#
# PENDÊNCIA REAL (não escondida): votação dos vogais, fechamento da sessão
# e lançamento do resultado do julgamento continuam bloqueados -- exigem
# login como um dos magistrados vogais do quórum, e por regra de trabalho
# desta sessão a senha de login é sempre digitada pelo usuário manualmente,
# nunca por automação. Esta função para em 'Sessão aberta' (fim do que já
# foi mapeado ao vivo) e não tenta ir além -- Passo 9/10 (assinatura
# pós-julgamento, intimação final) também ainda não mapeados.
def passo8_cartorio_avancar_sessao(driver, wait, filtro_sessao, presidente, votantes, log=print):
    """CARTÓRIO fecha a pauta, monta quórum/composição, gera a pauta
    (publica+intima) e abre a sessão -- nessa ordem, na mesma
    sessão/driver já no perfil do cartório certo (trocar_para_cartorio,
    chamado pelo orquestrador ou pelo chamador direto).

    `filtro_sessao`: texto que identifica a linha da sessão de forma
    única na listagem (ex. a data/hora da sessão, "24/09/2026 13:30").
    `presidente`: nome do magistrado presidente (ex. "LILIAN MACIEL
    SANTOS"). `votantes`: lista dos demais magistrados votantes (ex.
    ["CHRISTIAN GOMES LIMA", "FERNANDO CALDEIRA BRANT"])."""
    inicio = time.time()
    try:
        _sessaojulgamento.navegar_para_listagem_sessoes(driver, wait, log=log)

        if not _sessaojulgamento.fechar_pauta(driver, filtro_sessao, log=log):
            return _resultado("cartorio_fechar_pauta", False,
                               "Falha ao fechar a pauta -- ver log.", inicio)

        if not _sessaojulgamento.abrir_modal_participantes(driver, filtro_sessao, log=log):
            return _resultado("cartorio_quorum_composicao", False,
                               "Falha ao abrir modal de quórum/composição -- ver log.", inicio)

        if not _sessaojulgamento.incluir_magistrado_quorum(driver, presidente, presidente=True, log=log):
            return _resultado("cartorio_quorum_composicao", False,
                               f"Falha ao incluir presidente '{presidente}' no quórum.", inicio)
        for nome in votantes:
            if not _sessaojulgamento.incluir_magistrado_quorum(driver, nome, presidente=False, log=log):
                return _resultado("cartorio_quorum_composicao", False,
                                   f"Falha ao incluir votante '{nome}' no quórum.", inicio)

        if not _sessaojulgamento.mudar_aba_modal(driver, "Composição", log=log):
            return _resultado("cartorio_quorum_composicao", False,
                               "Falha ao trocar pra aba Composição.", inicio)
        if not _sessaojulgamento.definir_papel_composicao(driver, presidente, "presidente", log=log):
            return _resultado("cartorio_quorum_composicao", False,
                               f"Falha ao definir '{presidente}' como Presidente na composição.", inicio)
        for nome in votantes:
            if not _sessaojulgamento.definir_papel_composicao(driver, nome, "votante", log=log):
                return _resultado("cartorio_quorum_composicao", False,
                                   f"Falha ao definir '{nome}' como Votante na composição.", inicio)

        if not _sessaojulgamento.salvar_quorum_composicao(driver, log=log):
            return _resultado("cartorio_quorum_composicao", False,
                               "Falha ao salvar quórum/composição.", inicio)

        if not _sessaojulgamento.gerar_pauta_publicar_intimar(driver, wait, filtro_sessao, log=log):
            return _resultado("cartorio_gerar_pauta", False,
                               "Falha ao gerar/publicar/intimar a pauta -- ver log.", inicio)

        if not _sessaojulgamento.abrir_sessao(driver, filtro_sessao, log=log):
            return _resultado("cartorio_abrir_sessao", False,
                               "Falha ao abrir a sessão -- ver log.", inicio)

        return _resultado(
            "cartorio_avancar_sessao", True,
            "Sessão avançada até 'Sessão aberta' (fechar pauta + quórum + "
            "composição + gerar pauta + abrir sessão). Votação dos vogais e "
            "encerramento da ata continuam em passo8_votacao_e_encerramento "
            "(abaixo) -- chamada separada, ver docstring.",
            inicio,
        )
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("cartorio_avancar_sessao", False, detalhe, inicio)


# ---------------------------------------------------------------------------
# Passo 8 (continuação) -- votação dos vogais + CARTÓRIO encerra a ata.
# ---------------------------------------------------------------------------
# Mapeado ao vivo em 2026-08-27 (ver project_aura_sessao_julgamento na
# memória do projeto). Decisão explícita do usuário: o robô loga sozinho
# como cada vogal (reusa abrir_sessao_magistrado, mesmo padrão já usado
# pro relator no Passo 3) -- sem pausa manual, diferente do que valeu
# durante o mapeamento ao vivo desta sessão (regra de trabalho só minha,
# não do robô). NUNCA RODADO via Selenium ainda -- votar_item_pauta e
# navegar_ate_painel_sessao_via_calendario (run_aura_sessao_julgamento.py)
# nunca clicaram/navegaram de verdade, só foram inspecionados por DOM.
# Tratar a primeira execução real como teste acompanhado (headless=False),
# ver roteiro em MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md.
def passo8b_votar_um_vogal(nome_vogal, url, filtro_sessao, votos,
                            senha=SENHA_HOMOLOGACAO_PADRAO, log=print):
    """Loga sozinho como `nome_vogal` (conta própria, driver dedicado --
    `abrir_sessao_magistrado`, mesma função já usada pro relator no Passo
    3), navega até o Painel da Sessão via calendário e vota cada item de
    `votos`. Desloga e fecha o driver sempre no fim (finally), sucesso ou
    falha -- mesmo motivo já documentado em `abrir_sessao_magistrado`
    (sessão de cookies não permite logar com outra conta por cima).

    `votos`: [{"num_processo": "...", "tipo_voto": "acompanha_relator"}, ...]
    -- ver ACOES_VOTO_ITEM_PAUTA em run_aura_sessao_julgamento.py pros
    tipos válidos."""
    inicio = time.time()
    nome_norm = (nome_vogal or "").strip().upper()
    par = SIGLAS_MAGISTRADOS_HOMOLOGACAO.get(nome_norm)
    if not par:
        return _resultado(
            "votacao_vogal", False,
            f"Sigla de login não cadastrada para '{nome_vogal}' -- "
            "adicionar em SIGLAS_MAGISTRADOS_HOMOLOGACAO.", inicio)
    sigla, lotacao = par
    driver = None
    try:
        driver, wait = abrir_sessao_magistrado(sigla, senha, url, lotacao_contendo=lotacao)
        if not _sessaojulgamento.navegar_ate_painel_sessao_via_calendario(
                driver, wait, filtro_sessao, log=log):
            return _resultado("votacao_vogal", False,
                               f"{nome_vogal}: falha ao navegar até o Painel via calendário.", inicio)
        for voto in votos:
            if not _sessaojulgamento.votar_item_pauta(
                    driver, voto["num_processo"], voto["tipo_voto"], log=log):
                return _resultado(
                    "votacao_vogal", False,
                    f"{nome_vogal}: falha ao votar processo {voto['num_processo']}.",
                    inicio, voto["num_processo"])
        return _resultado("votacao_vogal", True,
                           f"{nome_vogal}: {len(votos)} voto(s) registrado(s).", inicio)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("votacao_vogal", False, detalhe, inicio)
    finally:
        if driver is not None:
            try:
                deslogar(driver, url)
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass


def passo8c_encerrar_ata(driver_cartorio, wait_cartorio, filtro_sessao, log=print):
    """Roda no driver do CARTÓRIO (o mesmo já usado por
    `passo8_cartorio_avancar_sessao`, mantido aberto o tempo todo) --
    DEPOIS de todos os itens pautados já terem resultado/evento (pré-
    requisito confirmado no código-fonte do eproc, ver docstring de
    `encerrar_ata` em run_aura_sessao_julgamento.py)."""
    inicio = time.time()
    try:
        _sessaojulgamento.navegar_para_listagem_sessoes(driver_cartorio, wait_cartorio, log=log)
        if not _sessaojulgamento.encerrar_ata(driver_cartorio, filtro_sessao, log=log):
            return _resultado("cartorio_encerrar_ata", False, "Falha ao encerrar a ata -- ver log.", inicio)
        return _resultado("cartorio_encerrar_ata", True, "Ata encerrada.", inicio)
    except Exception as e:
        detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
        return _resultado("cartorio_encerrar_ata", False, detalhe, inicio)


def passo8_votacao_e_encerramento(driver_cartorio, wait_cartorio, url, filtro_sessao,
                                   plano_votos, log=print):
    """Continuação de `passo8_cartorio_avancar_sessao` (que para em 'Sessão
    aberta') -- vota cada vogal de `plano_votos` (`passo8b_votar_um_vogal`,
    uma conta/driver por vez, em sequência) e, se todos OK, encerra a ata
    no driver do cartório (`passo8c_encerrar_ata`), fechando o Passo 8.

    `plano_votos`: [{"nome": "CHRISTIAN GOMES LIMA", "votos": [...]}, ...].
    Retorna a lista de resultados (`_resultado`) de cada vogal + o de
    encerrar_ata por último; para no primeiro vogal que falhar, sem tentar
    encerrar a ata (ela nem ficaria disponível com item sem resultado)."""
    resultados = []
    for item in plano_votos:
        r = passo8b_votar_um_vogal(item["nome"], url, filtro_sessao, item["votos"], log=log)
        resultados.append(r)
        if not r["ok"]:
            return resultados
    resultados.append(passo8c_encerrar_ata(driver_cartorio, wait_cartorio, filtro_sessao, log=log))
    return resultados


# ---------------------------------------------------------------------------
# Orquestrador -- pipeline completo (5 passos, um botão só)
# ---------------------------------------------------------------------------
def rodar_pipeline_completo(usuario, senha, url, texto_minuta,
                             executar_peticao_fn, caminho_pdf,
                             senha_magistrado=SENHA_HOMOLOGACAO_PADRAO,
                             competencia="Direito Público", num_processo=None,
                             evento_intimacao=VALOR_EVENTO_INTIMACAO_PADRAO,
                             prazo_intimacao_dias=PRAZO_INTIMACAO_PADRAO_DIAS,
                             evento_peticao=EVENTO_PETICAO_PADRAO,
                             tipo_documento_peticao=TIPO_DOCUMENTO_PETICAO_PADRAO):
    """Roda os 5 passos em sequência contra homologação: COTRI distribui ->
    GABINETE minuta+remessa -> MAGISTRADO assina -> CARTÓRIO intima ->
    ADVOGADO responde. Para no primeiro passo que falhar (os passos
    seguintes dependem do processo já ter avançado). Retorna lista de
    resultados estruturados (1 a 5 itens).

    `usuario`/`senha` são a conta única COTRI/GABINETE/CARTÓRIO/ADVOGADO
    (troca de perfil na mesma sessão/conta o tempo todo -- a conta de teste
    já tem os 4 perfis, "p0046863 é advogado" também, confirmado pelo
    usuário; nenhum passo faz login separado exceto o MAGISTRADO, que é
    sempre uma conta diferente). A conta do MAGISTRADO não precisa ser
    informada -- a sigla é lida dinamicamente da coluna "Assinante
    indicado" da minuta criada no Passo 2 (ver
    auragabinete.EprocBotV4.ler_assinante_indicado_minuta_atual);
    `senha_magistrado` tem como padrão a senha comum de todas as contas de
    teste em homologação (SENHA_HOMOLOGACAO_PADRAO), só passe algo
    diferente se o magistrado do processo escolhido tiver senha diferente.

    `executar_peticao_fn` é aura.py::executar_peticao_intermediaria_linha
    (extraída de executar_intermediario), passada pelo chamador pra evitar
    import circular (aura.py já importa este módulo) -- ver
    passo_advogado_responder. `caminho_pdf` é o PDF de teste usado na
    petição do Passo 5 (responsabilidade do chamador garantir que existe)."""
    resultados = []
    if not num_processo:
        num_processo = escolher_processo_teste(competencia)
    print(f"Processo de teste: {num_processo}")

    setor_distribuicao = setor_distribuicao_da_competencia(competencia)

    # Passo 1 — COTRI distribui (preferência de minuta da unidade)
    # Passo 2 — GABINETE minuta + remessa + encaminha para assinatura
    # Os dois rodam na MESMA sessão/driver (mesma conta, só troca de perfil
    # -- confirmado pelo usuário ao vivo: não fecha o Chrome entre um passo
    # e outro). O driver só é fechado no fim (ou em qualquer falha) deste
    # bloco -- isso também evita deixar uma janela órfã aberta se algo
    # falhar no meio do Passo 2.
    driver, wait = abrir_sessao_cotri(usuario, senha, url, perfil=setor_distribuicao)
    # `falhou_bloco1` começa True (assume falha) e só vira False no fim do
    # try, depois de tudo dar certo -- qualquer `return` antecipado (falha
    # de um passo) ou exceção não tratada deixa True. Decisão explícita do
    # usuário (2026-08-19): NÃO fechar o Chrome quando um passo falha --
    # "a homologação é justamente para ver o que pode dar errado", fechar
    # destrói a janela bem na hora que mais precisa dela pra diagnóstico.
    falhou_bloco1 = True
    try:
        r1 = passo_cotri_distribuir(driver, wait, num_processo, url, senha)
        resultados.append(r1)
        if not r1["ok"]:
            return resultados

        orgao_gabinete = r1.get("orgao_destino") or ""
        try:
            bot = trocar_para_gabinete(driver, wait, usuario, orgao_gabinete)
        except Exception as e:
            detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
            resultados.append(_resultado("gabinete_minutar", False, detalhe, time.time(), num_processo))
            return resultados

        r2 = passo_gabinete_minutar(bot, num_processo, texto_minuta)
        resultados.append(r2)
        if not r2["ok"]:
            return resultados

        usuario_magistrado = r2.get("assinante_indicado", "")
        if not usuario_magistrado:
            resultados.append(_resultado(
                "magistrado_assinar", False,
                "Não foi possível ler a sigla do magistrado (Assinante indicado) "
                "na minuta criada no Passo 2 -- ver EprocBotV4.ler_assinante_indicado_minuta_atual.",
                time.time(), num_processo,
            ))
            return resultados
        falhou_bloco1 = False
    finally:
        if falhou_bloco1:
            print("[regressao] Passo 1/2 falhou -- Chrome deixado aberto de propósito pra inspeção (não fecha em erro).")
        else:
            fechar_sessao_cotri(driver, url)

    # Passo 3 — MAGISTRADO assina (conta separada, não COTRI/GABINETE;
    # login descoberto no Passo 2, sem precisar ser informado pelo chamador)
    #
    # lotacao_contendo=<sigla do órgão> (não o texto genérico "MAGISTRADO"):
    # a tela "Seleção de perfil" mostra o texto do órgão/lotação (ex: "19°
    # CACIV - Assento 4 (19CACIV-A4)"), não um rótulo de papel/cargo -- uma
    # conta de desembargador pode nem ter a palavra "MAGISTRADO" em nenhum
    # perfil listado. Usa a sigla compacta (mesma usada no combobox
    # #selInfraUnidades) por ser a forma que aparece de forma estável nos
    # dois lugares -- ver _termo_camara_da_capa.
    sigla_camara_mag = _termo_camara_da_capa(orgao_gabinete)
    driver_mag, wait_mag = abrir_sessao_magistrado(
        usuario_magistrado, senha_magistrado, url, lotacao_contendo=sigla_camara_mag,
    )
    falhou_bloco3 = True
    try:
        r3 = passo_magistrado_assinar(driver_mag, wait_mag, num_processo, senha_magistrado)
        falhou_bloco3 = not r3["ok"]
    finally:
        if falhou_bloco3:
            print("[regressao] Passo 3 (magistrado) falhou -- Chrome deixado aberto de propósito pra inspeção (não fecha em erro).")
        else:
            deslogar(driver_mag, url)
            driver_mag.quit()
    resultados.append(r3)
    if not r3["ok"]:
        return resultados

    # Passo 4 — CARTÓRIO intima, e Passo 5 — ADVOGADO responde: sessão NOVA
    # (a do Passo 1/2 já foi fechada, e só faz sentido intimar depois que a
    # remessa de verdade do Passo 3 já aconteceu), mas os dois passos ficam
    # na MESMA sessão/driver -- decisão explícita do usuário (2026-08-18):
    # "não precisa fechar a sessão, o p0046863 é advogado" -- a conta tem
    # os perfis CARTÓRIO e ADVOGADO, então é só trocar de perfil de novo
    # entre um passo e outro, igual o Passo 1/2 já faz. O driver só fecha
    # no fim (ou em qualquer falha) deste bloco. Reusa o mesmo setor de
    # distribuição (COAPUB/COAPRI) do Passo 1 só como ponto de entrada --
    # a troca de perfil de verdade pro cartório acontece logo abaixo
    # (trocar_para_cartorio), então não importa qual dos dois setores loga
    # aqui primeiro, mas reusar o mesmo evita depender de outro default.
    driver_cart, wait_cart = abrir_sessao_cotri(usuario, senha, url, perfil=setor_distribuicao)
    falhou_bloco2 = True
    try:
        try:
            trocar_para_cartorio(driver_cart, wait_cart, usuario, orgao_gabinete)
        except Exception as e:
            detalhe = f"{e}\n\n--- traceback ---\n{traceback.format_exc()}"
            resultados.append(_resultado("cartorio_intima", False, detalhe, time.time(), num_processo))
            return resultados
        r4 = passo_cartorio_intima(
            driver_cart, wait_cart, num_processo,
            evento=evento_intimacao, prazo_dias=prazo_intimacao_dias,
        )
        resultados.append(r4)
        if not r4["ok"]:
            return resultados

        r5 = passo_advogado_responder(
            driver_cart, wait_cart, usuario, executar_peticao_fn, num_processo,
            caminho_pdf, evento=evento_peticao, tipo_documento=tipo_documento_peticao,
        )
        resultados.append(r5)
        falhou_bloco2 = not r5["ok"]
    finally:
        if falhou_bloco2:
            print("[regressao] Passo 4/5 falhou -- Chrome deixado aberto de propósito pra inspeção (não fecha em erro).")
        else:
            fechar_sessao_cotri(driver_cart, url)

    return resultados


if __name__ == "__main__":
    # Execução manual/ao vivo para validação passo a passo -- ver plano.
    from aura_db import ler_processos_ajuizados  # noqa: F401  (import já feito acima; mantém claro p/ leitura)

    TEXTO_MINUTA_TESTE = (
        "Vistos etc.\n\n"
        "Trata-se de pedido de antecipação de tutela recursal. "
        "Ausentes os requisitos legais para a concessão da medida "
        "(fumus boni iuris e periculum in mora), indefiro o pedido de "
        "antecipação de tutela.\n\n"
        "[TESTE DE REGRESSÃO AURA -- NÃO É UMA DECISÃO REAL]"
    )

    import aura  # só disponível quando rodado a partir da raiz do projeto

    resultados = rodar_pipeline_completo(
        usuario="", senha="", url="",  # preencher antes de rodar ao vivo (COTRI/GABINETE)
        texto_minuta=TEXTO_MINUTA_TESTE,
        executar_peticao_fn=aura.executar_peticao_intermediaria_linha,
        caminho_pdf="",  # preencher com o PDF de teste antes de rodar ao vivo
        # senha_magistrado usa SENHA_HOMOLOGACAO_PADRAO por padrão --
        # o usuário do magistrado é lido automaticamente no Passo 2.
    )
    for r in resultados:
        print(r)
