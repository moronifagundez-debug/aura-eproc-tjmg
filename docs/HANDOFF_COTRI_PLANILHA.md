# Handoff — AURA COTRI via planilha + troca de credenciais Google

> Resumo para continuar em outra sessão do Claude Code. No início da nova
> sessão: "leia o HANDOFF_COTRI_PLANILHA.md e o ESTUDO_AURA_COTRI.md na pasta
> docs/ antes de continuar". Branch de trabalho: `claude/sleepy-bohr-slls1p`.
> Última atualização: 2026-09-14.

## Objetivo geral

Fazer o **AURA COTRI** ser alimentado **direto pela planilha do Google
Sheets** (não mais por CSV manual), para minutar e redistribuir. O
peticionamento (`aura.py`) grava os processos; o COTRI vai ler dali.
Detalhes do plano em `ESTUDO_AURA_COTRI.md`.

## Arquitetura (como as peças conversam)

- Elo central = Google Sheets, via `shared/aura_db.py`.
- Planilha **operacional** (abas `processos_ajuizados` e
  `historico_intermediario`): o peticionamento **grava**; o COTRI vai **ler**.
- Planilha de **competências** (1 aba por competência): o peticionamento
  **lê** o que peticionar. É referência estável.
- `aura.py` = peticionamento. `integrations/run_aura_cotri.py` = COTRI
  (assinatura + redistribuição). `integrations/auragabinete.py` = gabinete.

## Decisões já tomadas (ver ESTUDO_AURA_COTRI.md)

1. Ampliar `processos_ajuizados` com **2 colunas**: `Assunto` e
   `Tipo_redistribuicao` (o resto o COTRI deriva).
2. Processo de **referência** da redistribuição = 2ª instância + número
   diferente + mesma competência (sem regra de órgão). É calculado da própria
   planilha (todo ajuizado é 2ª instância).
3. `Tipo_redistribuicao` em **rodízio cíclico** pelos 12 tipos.
4. Minuta por **peticionamento** (não por "preferência" do setor): evento e
   tipo de documento **fixos** → Tipo de documento `Documento de informação`,
   evento `Conclusos para decisão com revisão de autuação (51)`.
5. Setores de distribuição mudaram: agora são **3** — COAPUB (Pública),
   COAPRI (Privada), COMED (Medidas Urgentes, ex-CODIPRE). Seleção por **nome
   completo** do setor. Qual setor usar = escolha do usuário (sem mapa
   automático por ora).

## Contexto de infraestrutura (importante)

- A credencial antiga (`aura_credentials.json`) foi **perdida**. Foi criada
  uma **nova conta de serviço**: `aura-banco-de-dados@aura-banco-de-dados.iam.gserviceaccount.com`.
- Os IDs das planilhas agora vêm de **`aura_sheets.json`** (na raiz, ao lado
  do `aura_credentials.json`; ambos no `.gitignore`). Guia completo em
  `CONFIGURAR_PLANILHAS.md`.
- Planilhas do usuário devem ser **Planilhas Google nativas** (não .xlsx) e
  **compartilhadas** com o e-mail da conta de serviço.
- Modelos prontos em `modelos/` (`modelo_planilha_operacional.xlsx` e
  `modelo_planilha_competencias.xlsx`).
- Planilha operacional nova do usuário: ID `1sNg3cPQu0uG_RIZqJCopNSiMDYePwwGcti1b6FWPPtU`.

## O que já foi feito (commits na branch)

- `ESTUDO_AURA_COTRI.md` — estudo/plano completo (5 fases).
- **aura_db.py**:
  - IDs lidos de `aura_sheets.json` (fallback nos defaults); `_limpar_id_planilha`
    tolera colar a URL inteira.
  - `_dirs_config`/`_achar_config`: no `.exe`, procura config **ao lado do
    executável** antes do bundle (`_MEIPASS`).
  - `_garantir_cabecalho` cria a aba que faltar (addSheet) e dá erro claro se
    o arquivo não for Planilha Google nativa / não compartilhado.
  - `CABECALHO_PROCESSOS` + `gravar_processo_ajuizado` com `Assunto` e
    `Tipo_redistribuicao`.
  - `TIPOS_REDISTRIBUICAO` (12 tipos) + `proximo_tipo_redistribuicao()` (rodízio
    por contagem de linhas: tipo = N % 12).
- **aura.py**: `capturar_dados_finais` grava `Assunto` (da linha da
  competência) e `Tipo_redistribuicao` (rodízio); o `except` mudo virou log
  (`aura_gravacao_planilha.log`) — falhas de gravação não são mais escondidas.
- **diagnostico_planilha.py** — mostra config resolvida, ID em uso, conta de
  serviço e faz uma gravação de teste com erro completo. NÃO altera o app.
- `CONFIGURAR_PLANILHAS.md`, `aura_sheets.exemplo.json`, `.gitignore`
  (ignora `aura_sheets.json`).

**Fase 1 do plano = concluída** (colunas + rodízio + IDs configuráveis).

## Estado atual / o que funciona

- Gravação na planilha operacional **funciona** (confirmado pelo
  `diagnostico_planilha.py`: gravou linha de teste; ID correto; conta de
  serviço ok). Rodar por `python aura.py` grava certo.
- O bug de "não gravava sem erro" era o **`.exe` não achar o `aura_sheets.json`**
  (procurava no `_MEIPASS`); corrigido — agora lê ao lado do `.exe` (precisa
  recompilar com `pyinstaller AURA.spec` e pôr `aura_sheets.json` na pasta
  `dist`). O armazenamento (86%) NÃO era a causa.

## Competências — RESOLVIDO (2026-09-15)

O usuário apontou o `spreadsheet_id_competencias` (no `aura_sheets.json`) para
a **planilha de competências do AURA antigo**, que tem os dados reais, e a
**compartilhou com a conta de serviço como Editor**. Ou seja, o robô já lê as
competências reais — o bloqueio que impedia o teste real de peticionamento
está superado.

**Próximo passo:** rodar um peticionamento real de teste e conferir na aba
`processos_ajuizados` as colunas `Assunto` e `Tipo_redistribuicao` preenchidas
(valida a Fase 1 de ponta a ponta).

## Como testar o peticionamento (depois de resolver as competências)

1. Apagar a linha `TESTE_DIAGNOSTICO` da aba `processos_ajuizados`.
2. `cd C:\Users\p0125581\Downloads\AURA` e `python aura.py`.
3. Selecionar a competência real, escolher o PDF, clicar em
   ▶ HOMOLOGAR — ADVOGADO; testar com 1–2 processos.
4. Conferir na planilha as colunas `Assunto` e `Tipo_redistribuicao`.

## Próximas fases do plano (ver ESTUDO_AURA_COTRI.md §10)

- Fase 2 — 3 setores novos (COAPUB/COAPRI/COMED) na UI + seleção por nome
  completo; remover defaults antigos "COTRI"/"CODIPRE".
- Fase 3 — COTRI lê a fila direto de `ler_processos_ajuizados()`.
- Fase 4 — referência calculada (2ª instância + número diferente + mesma
  competência).
- Fase 5 — minuta por peticionamento (evento/tipo fixos).

## Pendências menores registradas

- `orgaos_caciv.json` pode precisar de revisão (novos núcleos privados).
- `AURA.spec` embute `aura_credentials.json` no `.exe` (risco de segurança);
  avaliar parar de embutir e sempre ler ao lado do `.exe`.
- Considerar **rotacionar** a chave da conta de serviço (foi compartilhada
  em chat durante o debug).
- Armazenamento da conta Google em 86% — se chegar a 100%, bloqueia gravação.

## Preferências do usuário

Iniciante em programação; programa em Python e front-end web. Explicar os
funcionamentos, não só entregar código. Responder em português.
