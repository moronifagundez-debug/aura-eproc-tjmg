# ============================================================
#  aura_monitor.py — Monitor transversal do AURA
#  CESUPE | Módulo compartilhado por todos os AURAs
# ------------------------------------------------------------
#  Duas responsabilidades, ambas pensadas para o USUÁRIO DA
#  HOMOLOGAÇÃO:
#
#  (A) AVISAR ERROS de forma padronizada — qualquer robô chama
#      `notificar_erro(...)` e o erro vira: log em arquivo +
#      registro na execução + (opcional) popup na tela.
#
#  (B) DETECTAR MUDANÇAS no código-fonte (ESTRUTURA) das páginas
#      do eProc que o AURA opera. Compara a "forma" da página
#      (ids/names de campos e botões, actions de form, ações do
#      menu) com um baseline salvo. Se mudou, guarda um resumo
#      para reportar UMA VEZ no fim da execução — não bloqueia,
#      não fica avisando toda hora (depois de reportar, atualiza
#      o baseline).
#
#  Só stdlib (+ selenium opcional, apenas para ler a página).
# ============================================================

import os
import json
import hashlib
import logging
from datetime import datetime

logger = logging.getLogger("aura_monitor")

# Pasta gravável do monitor (baseline + logs), no perfil do usuário.
PASTA_MONITOR = os.path.join(os.path.expanduser("~"), ".aura_monitor")
ARQ_BASELINE = os.path.join(PASTA_MONITOR, "paginas_fingerprint.json")
ARQ_LOG_ERROS = os.path.join(PASTA_MONITOR, "erros_homologacao.log")


def _garantir_pasta():
    try:
        os.makedirs(PASTA_MONITOR, exist_ok=True)
    except Exception:
        pass


# ------------------------------------------------------------
# (A) AVISO DE ERROS
# ------------------------------------------------------------
# Acumula os erros da execução atual, para um resumo no fim.
_erros_execucao = []


def notificar_erro(contexto: str, erro, popup=None, num_fila=None):
    """Registra e avisa um erro de forma padronizada.

    - contexto: onde ocorreu (ex.: "Minuta COAPUB", "Login Gabinete").
    - erro: a exceção ou mensagem.
    - popup: função opcional que mostra na tela (ex.: um messagebox já
      montado pelo chamador). Se None, não abre janela (só loga/registra).
    - num_fila: número da linha/processo, quando fizer sentido.

    Nunca levanta exceção: avisar não pode quebrar o fluxo."""
    msg = str(erro)
    entrada = {
        "quando": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "contexto": contexto,
        "linha": num_fila,
        "mensagem": msg,
    }
    _erros_execucao.append(entrada)
    try:
        _garantir_pasta()
        with open(ARQ_LOG_ERROS, "a", encoding="utf-8") as f:
            linha = f"{entrada['quando']} | {contexto}"
            if num_fila is not None:
                linha += f" | linha {num_fila}"
            f.write(linha + f" | {msg}\n")
    except Exception:
        pass
    try:
        if callable(popup):
            popup(f"[{contexto}] {msg}")
    except Exception:
        pass
    return entrada


def houve_erros() -> bool:
    return bool(_erros_execucao)


def relatorio_erros_texto() -> str:
    if not _erros_execucao:
        return ""
    linhas = [f"Erros nesta execução ({len(_erros_execucao)}):", ""]
    for e in _erros_execucao:
        pref = f"linha {e['linha']}: " if e["linha"] is not None else ""
        linhas.append(f"• [{e['contexto']}] {pref}{e['mensagem']}")
    return "\n".join(linhas)


# ------------------------------------------------------------
# (B) DETECÇÃO DE MUDANÇA NA ESTRUTURA DAS PÁGINAS
# ------------------------------------------------------------
_mudancas_execucao = []

# JS que extrai a ESTRUTURA da página (não os valores). Assim mudanças de
# conteúdo dinâmico não geram ruído; só campos/botões/ações novos ou removidos.
_JS_ESTRUTURA = r"""
const out = [];
const push = (p, v) => { if (v) out.push(p + ':' + v); };
document.querySelectorAll('input,select,textarea,button').forEach(el => {
    push(el.tagName.toLowerCase(), (el.id || el.name || ''));
});
document.querySelectorAll('form').forEach(f => push('form', (f.getAttribute('action') || '').split('?')[0]));
document.querySelectorAll('a[onclick]').forEach(a => {
    const m = (a.getAttribute('onclick') || '').match(/acao=([a-zA-Z_]+)/);
    if (m) push('acao', m[1]);
});
return Array.from(new Set(out)).sort();
"""


def _estrutura_da_pagina(driver) -> list:
    try:
        itens = driver.execute_script(_JS_ESTRUTURA)
        return [str(x) for x in (itens or []) if x]
    except Exception as e:
        logger.debug("Falha ao ler estrutura da página: %s", e)
        return []


def _carregar_baseline() -> dict:
    try:
        with open(ARQ_BASELINE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.debug("Falha ao ler baseline: %s", e)
        return {}


def _salvar_baseline(d: dict):
    _garantir_pasta()
    try:
        with open(ARQ_BASELINE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("Falha ao salvar baseline: %s", e)


def registrar_fingerprint(driver, nome_pagina: str):
    """Captura a estrutura da página atual e compara com o baseline.

    - 1ª vez que vê a página: só grava o baseline (não é "mudança").
    - Igual ao baseline: nada.
    - Diferente: guarda um resumo (adicionados/removidos) para o relatório do
      fim e ATUALIZA o baseline (para avisar só uma vez).

    NUNCA bloqueia nem levanta — detecção é best-effort."""
    try:
        estrutura = _estrutura_da_pagina(driver)
        if not estrutura:
            return
        h = hashlib.sha256("\n".join(estrutura).encode("utf-8")).hexdigest()[:16]
        base = _carregar_baseline()
        antigo = base.get(nome_pagina)
        if antigo is None:
            base[nome_pagina] = {"hash": h, "itens": estrutura,
                                 "visto": datetime.now().isoformat()}
            _salvar_baseline(base)
            return
        if antigo.get("hash") == h:
            return
        antes = set(antigo.get("itens", []))
        agora = set(estrutura)
        _mudancas_execucao.append({
            "pagina": nome_pagina,
            "adicionados": sorted(agora - antes),
            "removidos": sorted(antes - agora),
        })
        base[nome_pagina] = {"hash": h, "itens": estrutura,
                             "visto": datetime.now().isoformat()}
        _salvar_baseline(base)
        logger.info("Estrutura da página '%s' mudou desde a última execução.", nome_pagina)
    except Exception as e:
        logger.debug("registrar_fingerprint falhou: %s", e)


def houve_mudancas() -> bool:
    return bool(_mudancas_execucao)


def relatorio_mudancas_texto() -> str:
    if not _mudancas_execucao:
        return ""
    linhas = ["Mudanças no código-fonte das páginas do eProc (só aviso):", ""]
    for m in _mudancas_execucao:
        linhas.append(f"• Página '{m['pagina']}':")
        if m["adicionados"]:
            linhas.append(f"    + novos: {', '.join(m['adicionados'][:25])}")
        if m["removidos"]:
            linhas.append(f"    - removidos: {', '.join(m['removidos'][:25])}")
    linhas += [
        "",
        "Isto NÃO impede a execução. Serve para identificar melhorias/mudanças "
        "relevantes no eProc — se algo parou de funcionar, pode ter relação.",
    ]
    return "\n".join(linhas)


# ------------------------------------------------------------
# Ciclo de vida da execução
# ------------------------------------------------------------
def iniciar_execucao():
    """Zera os acumuladores no começo de um lote."""
    _erros_execucao.clear()
    _mudancas_execucao.clear()


def relatorio_final_texto() -> str:
    """Resumo único do fim: mudanças de página + erros (o que houver)."""
    partes = []
    if houve_mudancas():
        partes.append(relatorio_mudancas_texto())
    if houve_erros():
        partes.append(relatorio_erros_texto())
    return "\n\n".join(partes)
