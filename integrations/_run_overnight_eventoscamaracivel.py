"""Launcher standalone para a cadeia completa de eventos por camara civel.
Roda fora da GUI (headless), logando em stdout com timestamp e flush imediato,
para acompanhamento via redirecionamento de log em execucao noturna."""

import sys
import time

import run_aura_eventoscamaracivel as m


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main():
    cfg = m.carregar_config()
    usuario = (cfg.get("usuario") or m.USUARIO_PADRAO).strip()
    senha = (cfg.get("senha") or m.SENHA_PADRAO).strip()
    url = (cfg.get("url") or m.URL_PADRAO).strip()
    if not (usuario and senha and url):
        log("[ERRO] Config nao encontrado/incompleto em ~/.aura_eventoscamaracivel/config.json")
        sys.exit(2)

    # Cadeia completa (2CACIV..21CACIV + Esp) ja rodou com sucesso; o
    # processo esta agora no cartorio da 21CACIVEsp (ultimo no daquela
    # execucao). Essa rodada e so para cobrir 4CACIVEsp/8CACIVEsp com os
    # assentos reais (4/8CACIVESP-AN) recem-corrigidos no orgaos_caciv.json
    # -- essas duas nao tinham gabinetes mapeados na execucao anterior.
    resultados = m.executar_cadeia_completa(
        resume_a_partir_de="4CACIVEsp",
        holder_atual={"sigla": "21CACIVEsp", "descricao": "21CACIVEsp - 21ª CÂMARA CÍVEL ESPECIALIZADA"},
        num_processo="2811115-06.2026.8.13.0000",
        usuario=usuario,
        senha=senha,
        url=url,
        dry_run=False,
        garantir_lotacoes=True,
        limpar_lotacoes_ao_final=True,
        headless=True,
        log=log,
    )
    erros = [r for r in resultados if "erro" in r]
    log(f"=== FIM: {len(resultados)} orgaos processados, {len(erros)} com erro ===")
    return 0 if not erros else 1


if __name__ == "__main__":
    sys.exit(main())
