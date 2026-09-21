# Monitor do AURA — avisar erros + detectar mudanças nas páginas

> Módulo transversal `shared/aura_monitor.py`, pensado para o **usuário da
> homologação**. Faz duas coisas, sem atrapalhar a execução. Atualizado em
> 2026-09-18.

## Por que existe

Dois pedidos:
1. **Sempre avisar quando der erro** — de forma padronizada, direcionada a quem
   está homologando (não falhar em silêncio).
2. **Avisar se o código-fonte das páginas do eProc mudou** — para identificar
   melhorias/mudanças relevantes. Mas **sem bloquear** e **sem ficar avisando
   toda hora**: informa **uma vez**, como relatório no fim.

## Como funciona

### (A) Aviso de erros — `notificar_erro(contexto, erro, popup=None, num_fila=None)`
- Registra o erro em `~/.aura_monitor/erros_homologacao.log` e num acumulador da
  execução.
- Se receber `popup` (uma função que mostra na tela), avisa também na hora.
- Nunca levanta exceção (avisar não pode quebrar o fluxo).
- No fim, `relatorio_erros_texto()` resume todos os erros da execução.

### (B) Mudança de página — `registrar_fingerprint(driver, nome_pagina)`
- Extrai a **estrutura** da página (ids/names de campos e botões, `action` dos
  forms, `acao=` dos links) — **não** os valores, então conteúdo dinâmico não
  gera ruído.
- Compara com um **baseline** salvo em `~/.aura_monitor/paginas_fingerprint.json`:
  - **1ª vez** que vê a página → só grava o baseline (não é "mudança").
  - **Igual** → nada.
  - **Diferente** → guarda um resumo (campos **adicionados/removidos**) e
    **atualiza o baseline** (para avisar só **uma vez**).
- É best-effort: se algo falhar, não interrompe nada.

### Ciclo de vida (por lote)
- `iniciar_execucao()` no começo (zera os acumuladores).
- No fim, `relatorio_final_texto()` junta **mudanças de página + erros** num
  texto único, mostrado **uma vez** (ex.: um `messagebox`).

## Onde já está ligado (AURA Distribuição)

- **Minuta** (`executar_assinatura_cotri`) e **Redistribuição**
  (`executar_redistribuicao_cotri`):
  - `iniciar_execucao()` no início;
  - `registrar_fingerprint` nas telas `minuta_cadastrar` e
    `redistribuicao_processo`;
  - cada erro por linha também vai para `notificar_erro` (além do diálogo que já
    aparece);
  - no fim, `_mostrar_relatorio_monitor()` mostra o relatório único.

## Como estender ao resto do AURA (rollout)

O padrão é sempre o mesmo — 3 pontos por fluxo:

1. No **início** do lote: `aura_monitor.iniciar_execucao()`.
2. Ao **abrir cada tela** que o robô opera:
   `aura_monitor.registrar_fingerprint(driver, "<nome_da_tela>")`
   (ex.: no Gabinete: `minuta_cadastrar`; no Peticionamento:
   `movimentar_peticionar`; na Sessão: as telas do painel).
3. Em cada `except` e no **fim** do lote:
   `aura_monitor.notificar_erro(contexto, e, num_fila=...)` e mostrar
   `aura_monitor.relatorio_final_texto()` uma vez.

Sugestão de próximos adotantes: **AURA Gabinete**, **AURA Peticionamento**
(`aura.py`) e **Eventos Câmara Cível**. Assim o "avisar sempre" e o "relatório
de mudanças" passam a valer para o AURA como um todo.

## Arquivos gerados (no perfil do usuário)

- `~/.aura_monitor/paginas_fingerprint.json` — baseline das estruturas.
- `~/.aura_monitor/erros_homologacao.log` — histórico de erros.

Para "resetar" o baseline (ex.: depois de uma grande atualização do eProc),
basta apagar o `paginas_fingerprint.json` — na próxima execução ele regrava sem
avisar, e passa a avisar de novo só nas mudanças seguintes.
