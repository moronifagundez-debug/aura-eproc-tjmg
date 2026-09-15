# AURA — Planejamento para concluir os ajustes

> Roteiro do que falta para finalizar os ajustes atuais do AURA (foco:
> COTRI alimentado pela planilha + 3 setores novos), com fases, tarefas,
> critérios de "pronto" e riscos. Base: `ESTUDO_AURA_COTRI.md` e
> `HANDOFF_COTRI_PLANILHA.md`. Atualizado em 2026-09-15.

## Onde estamos

- ✅ **Fase 1** concluída: `processos_ajuizados` com `Assunto` e
  `Tipo_redistribuicao`; peticionamento preenche (Assunto da competência,
  tipo em rodízio pelos 12 tipos); IDs das planilhas configuráveis; gravação
  validada.
- ✅ Infraestrutura Google migrada (nova conta de serviço + planilhas).
- ⏳ **Bloqueio imediato:** planilha de **competências** nova está vazia — as
  competências reais estavam na planilha do AURA antigo. Sem elas, o
  peticionamento não roda.

## Bloqueio 0 — Recuperar as competências (pré-requisito de tudo)

**Tarefa:** dar à nova conta de serviço acesso às competências reais.
- Abrir a planilha antiga (`19BgcXguj02yI5uthWW7TBj4v22da9EAl3ZmtOU6UEu8`).
- Se acessível: compartilhar com a conta de serviço (Leitor) e apontar
  `spreadsheet_id_competencias` no `aura_sheets.json` — ou fazer uma cópia.
- Se inacessível: localizar backup/cópia e importar.
- **Pronto quando:** o AURA Principal lista as competências reais e um
  peticionamento de teste grava linhas com `Assunto`/`Tipo_redistribuicao`.

## Fase 2 — Setores de distribuição (COAPUB / COAPRI / COMED)

O antigo "COTRI" virou COAPUB + COAPRI, e "CODIPRE" virou COMED.
- Atualizar a UI do COTRI (`run_aura_cotri.py`): trocar os rádios
  `("COTRI","CODIPRE")` pelos 3 setores.
- Selecionar o perfil **pelo nome completo** do setor (mais seguro).
- Remover defaults antigos `state.perfil="COTRI"` e o dicionário
  `PREFERENCIAS_POR_PERFIL` (some com a mudança de minuta da Fase 5).
- **Pronto quando:** dá para escolher COAPUB/COAPRI/COMED e o robô loga no
  setor certo.

## Fase 3 — COTRI lendo a fila direto da planilha

- Nova função que monta a fila a partir de `ler_processos_ajuizados()` (em vez
  do CSV manual), reusando o enriquecimento de competência já existente.
- Manter o CSV como alternativa até validar.
- **Pronto quando:** o COTRI processa os processos vindos da planilha, sem CSV.

## Fase 4 — Processo de referência calculado

- Adaptar `buscar_processo_ref`: referência = 2ª instância + número diferente
  + mesma competência (sem regra de órgão). Fonte = a própria planilha.
- **Pronto quando:** redistribuições por dependência acham a referência
  automaticamente.

## Fase 5 — Minuta por peticionamento (sem "preferência")

- Trocar o fluxo de "preferência de minuta" pelo motor do peticionamento
  intermediário, com valores **fixos**:
  - Tipo de documento: `Documento de informação`
  - Evento: `Conclusos os autos para decisão com revisão de autuação (51)`
- **Pronto quando:** o COTRI minuta/conclui igual para os 3 setores, sem
  depender de preferência cadastrada no eproc.

## Frente paralela — Sessão de Julgamento (passos 6–10)

Fora do escopo do COTRI, mas parte do "acabar o AURA". Ver
`MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md`: minutas do passo 7, gestão da
sessão (quórum/composição/pauta/abertura), votação (drag-and-drop, ainda não
observada ao vivo) e encerramento da ata.

## Itens técnicos e de segurança (fazer junto)

- **`AURA.spec`:** parar de embutir `aura_credentials.json` no `.exe` (risco:
  a chave fica extraível). Passar a ler sempre ao lado do `.exe`.
- **Rotacionar a chave** da conta de serviço (foi exposta em chat no debug).
- **Gabinete — fila vazia:** revisar o casamento por nome do magistrado
  (`_filtrar_processos_gabinete`) quando formos mexer no Gabinete.
- **`orgaos_caciv.json`:** revisar por causa dos novos núcleos privados.
- **Armazenamento Google (86%):** liberar espaço; a 100% a gravação é
  bloqueada.

## Ordem sugerida

1. Bloqueio 0 (competências) → validar Fase 1 num peticionamento real.
2. Fase 2 (setores) → 3 (fila) → 4 (referência) → 5 (minuta).
3. Itens de segurança (spec/rotação de chave) em paralelo.
4. Sessão de Julgamento como frente seguinte.

## Como validamos cada entrega

- Rodar por `python aura.py` (grava certo) ou `.exe` recompilado com config ao
  lado.
- Conferir o resultado **na tela do eproc e na planilha** (não confiar só em
  "sem erro").
- Usar `diagnostico_planilha.py` sempre que a gravação parecer não acontecer.
