# AURA — Guia dos Ajustes (o que já foi feito e o que falta)

> **Guia dos ajustes atuais do AURA** (foco: AURA Distribuição alimentado pela
> planilha + 3 setores novos), com o que já está concluído, o que falta e como
> validar. Par com o `PLANEJAMENTO_FUNCIONAMENTO_AURA.md` (o que o AURA faz).
> Base: `ESTUDO_AURA_COTRI.md` e `HANDOFF_COTRI_PLANILHA.md`.
> Atualizado em 2026-09-18.

## Onde estamos (já resolvido)

- ✅ **Fase 1** — `processos_ajuizados` com `Assunto` e `Tipo_redistribuicao`; o
  peticionamento preenche (Assunto da competência, tipo em rodízio pelos 12
  tipos); gravação validada.
- ✅ Infraestrutura Google migrada (nova conta de serviço + planilhas).
- ✅ **Competências resolvidas:** `spreadsheet_id_competencias` aponta para a
  planilha do AURA antigo (dados reais), compartilhada com a conta de serviço.
- ✅ **Planilha operacional fixa no código (2026-09-16/17):** o ID é sempre o
  embutido (`1sNg3cPQu0uG_...`); nenhum `aura_sheets.json` externo consegue
  redirecionar a gravação. Falhas de gravação viram log, não silêncio.
- ✅ **Interligação dos AURAs (2026-09-17):** o Gabinete passou a herdar
  `usuario/senha/url` da tela inicial (como os demais robôs); endereços
  padronizados em `/eproc/`. Ver `ESTUDO_INTERLIGACAO_AURA.md`.

## Fase 2 — Setores + renome ✅ FEITO (2026-09-17)

- Nome exibido: **AURA COTRI → AURA Distribuição** (janela, relatório, botão,
  mensagens).
- Setores: `COTRI/CODIPRE` → **COMED / COAPRI / COAPUB** na UI e nos defaults
  (default COAPUB); seleção de perfil casa pelo **nome completo**.
- A assinatura por preferência antiga foi aposentada (substituída pela minuta,
  Fase 5).

## Fase 3 — AURA Distribuição lendo a fila da planilha ✅ FEITO (2026-09-17/18)

- **Minuta:** a fila vem de `aura_db.ler_processos_ajuizados()` (planilha
  central); o CSV virou **opcional**.
- **Redistribuição:** idem — fila e referências montadas da planilha central
  (`fila_redistribuicao_da_planilha`); CSVs de redistribuição/referências
  viraram **opcionais**.
- Coluna `Processo` reconhecida em `_COLUNAS_NUMERO_PROCESSO`.

## Fase 4 — Processo de referência calculado ✅ FEITO (2026-09-18)

- A referência de cada processo é **calculada da própria planilha**: número
  diferente + **mesma competência** (sem regra de órgão), via
  `buscar_processo_ref`. Validado por simulação.
- Um processo sem par de mesma competência **não bloqueia o lote** (só falha/pula
  a própria linha).

## Fase 5 — Minuta de "Informação" ✅ IMPLEMENTADO (2026-09-17), a validar em HML

Correção de rumo importante: **é MINUTAR (como o Gabinete), não peticionar.**

- Para cada processo: cria minuta **Tipo/Modelo = "Informação"** com o **evento
  de conclusão** `Conclusos para decisão com revisão de autuação (51)`,
  insere um **texto fixo** e **assina** — **só gera o evento (sem remessa)**.
- Motores: formulário + texto reaproveitam o motor do **AURA Gabinete**;
  **assinatura reaproveita o fluxo comprovado do COTRI antigo** (editor CKE +
  iframe).
- **Blindagem anti-duplicidade:** processos já concluídos com sucesso são
  pulados (a planilha central é append-only). Só no modo planilha.
- ⚠️ **Falta validar em HOMOLOGAÇÃO** antes de produção (comportamentos que só a
  tela real confirma — ver a lista na Fase 5 do `ESTUDO_AURA_COTRI.md`).

## Passo imediato — Validar em homologação

Recompilar o `.exe` (ou rodar por `python`) e, num processo de **teste em
homologação**, conferir a minuta (Fase 5) e a redistribuição pela planilha:
- a minuta "Informação" é criada, com o texto certo, e **assinada**;
- a redistribuição pega o tipo/competência da planilha e acha a referência;
- os registros caem na planilha **nova** e nada é feito em duplicidade.
- **Pronto quando:** os itens acima se confirmarem na **tela do eProc**.

## Frente paralela — Sessão de Julgamento (passos 6–10)

Fora do escopo da Distribuição, mas parte do "acabar o AURA". Ver
`MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md`: minutas do passo 7, gestão da sessão
(quórum/composição/pauta/abertura), votação (drag-and-drop, ainda não observada
ao vivo) e encerramento da ata.

## Itens técnicos e de segurança (ainda pendentes)

- **`AURA.spec` — credencial:** o `.exe` ainda **embute o
  `aura_credentials.json`** (a chave fica extraível do binário). Avaliar ler a
  credencial sempre **ao lado do `.exe`** em vez de embutir.
- **Rotacionar a chave** da conta de serviço (foi exposta em chat no debug).
- **`orgaos_caciv.json`:** revisar por causa dos novos núcleos privados.
- **Armazenamento Google:** liberar espaço; a 100% a gravação é bloqueada.
- **Gabinete — fila vazia:** revisar o casamento por nome do magistrado
  (`_filtrar_processos_gabinete`) quando formos mexer no Gabinete.

## Ordem sugerida (daqui pra frente)

1. **Validar em homologação** as Fases 3/4/5 (minuta + redistribuição).
2. Itens de segurança (parar de embutir a credencial + rotacionar a chave).
3. Revisar `orgaos_caciv.json` para os núcleos privados novos.
4. Sessão de Julgamento como frente seguinte.

## Como validamos cada entrega

- Rodar por `python aura.py` ou pelo `.exe` **recompilado**.
- Conferir o resultado **na tela do eProc e na planilha** (não confiar só em
  "sem erro").
- Usar `diagnostico_planilha.py` sempre que a gravação parecer não acontecer.
