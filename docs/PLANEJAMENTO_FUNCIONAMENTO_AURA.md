# AURA — Guia de Funcionamento (visão completa)

> **Guia para entender o que o AURA faz hoje** (de ponta a ponta): o que é,
> quais módulos existem, como os dados circulam e qual o fluxo jurídico que ele
> automatiza. Serve de par com o `PLANEJAMENTO_AJUSTES_AURA.md`, que lista o
> que ainda precisa melhorar. Atualizado em 2026-09-16.

## 1. O que é o AURA

O AURA é um conjunto de **robôs (RPA)** que operam o sistema **eproc do TJMG**
pelo navegador (Selenium/Chrome), automatizando tarefas repetitivas do fluxo
processual da 2ª instância (câmaras cíveis). Em vez de um servidor clicar
manualmente no eproc, o AURA faz isso de forma automática, em lote, e
**registra tudo numa planilha central** no Google Sheets.

**Objetivo maior (pedido do usuário):** "o AURA tem que ser capaz de fazer
qualquer coisa dentro do eproc".

## 2. Componentes (o "mapa" do sistema)

### Aplicativos (o que o usuário abre)
| Módulo | Arquivo | O que faz |
|--------|---------|-----------|
| **AURA Principal** | `aura.py` | Tela central (hub). Faz o **peticionamento** (ajuizamento) e o **peticionamento intermediário**; abre os outros AURAs; roda a regressão de homologação. |
| **AURA Gabinete** | `integrations/auragabinete.py` | Robô `EprocBotV4`: **minuta e movimenta** processos no gabinete do magistrado. |
| **AURA COTRI** | `integrations/run_aura_cotri.py` | **Assinatura** de minutas e **redistribuição** de processos nos setores de distribuição. |
| **AURA Eventos Câmara Cível** | `integrations/run_aura_eventoscamaracivel.py` | Mapeia quais **eventos** aparecem em cada gabinete/cartório de cada câmara. |
| **AURA Sessão de Julgamento** | `integrations/run_aura_sessao_julgamento.py` + `extension/` | Acompanha a **sessão de julgamento** (painel, votos, divergência) via extensão de Chrome. |

### Peças compartilhadas (a "fundação")
| Módulo | Arquivo | Papel |
|--------|---------|-------|
| **Banco central** | `shared/aura_db.py` | Lê/grava no Google Sheets (a "ponte" entre todos os AURAs). |
| **Seletor de competências** | `shared/aura_sheet_selector.py` | Componente de UI que lista as competências da planilha. |
| **Infra** | `shared/aura_infra.py` | ChromeDriver resiliente, checagem de atualização, utilidades de UI. |
| **Agente IA** | `shared/AURAAGENT.py` | Assistente conversacional (Groq) e revisão de dados da petição. |
| **Regressão homologação** | `shared/aura_regressao_homologacao.py` | Orquestra um teste ponta a ponta do rito (passos 1–8). |

### Dados (as planilhas e arquivos)
- **Planilha operacional** (Google Sheets): abas `processos_ajuizados` e
  `historico_intermediario`.
- **Planilha de competências** (Google Sheets): 1 aba por competência; é o
  "molde" do que peticionar.
- **Credencial**: `aura_credentials.json` (chave da conta de serviço Google;
  fica **fora do git**). É o único arquivo de config obrigatório.
- **IDs das planilhas**: **embutidos no código** (`aura_db.py`). O
  `aura_sheets.json` é um **override opcional** — se existir (ao lado do `.exe`
  ou na raiz), seus IDs têm prioridade sobre os embutidos.
- **Registro fixo**: `orgaos_caciv.json` (as 23 câmaras cíveis e assentos).

## 3. Como os dados circulam (o coração do sistema)

```
   Planilha de COMPETÊNCIAS  ──(o que peticionar)──►  AURA Principal
                                                          │ ajuíza no eproc
                                                          ▼
                                            grava linha em processos_ajuizados
                                                          │
                    ┌─────────────────────────────────────┼───────────────────┐
                    ▼                                       ▼                   ▼
             AURA GABINETE                            AURA COTRI          (outros AURAs)
        (lê a fila pelo magistrado)          (vai ler a fila p/ redistribuir
         minuta/movimenta                      e assinar — em construção)
```

- Tudo gira em torno da aba **`processos_ajuizados`** (o "caderno"
  compartilhado). O AURA Principal escreve; os outros leem.
- O acesso ao Google Sheets é feito pelo `aura_db.py` com uma **conta de
  serviço** (autenticação JWT, sem depender de login humano).
- Os **IDs das planilhas são embutidos no código** (operacional + competências),
  com `aura_sheets.json` como override opcional — então o `.exe` já nasce
  apontando para as planilhas certas, sem precisar de arquivo junto.

## 4. O fluxo jurídico que o AURA automatiza (rito de homologação)

O `aura_regressao_homologacao.py` encadeia o rito completo (usado como teste
de ponta a ponta):

1. **COTRI/COAPUB/COAPRI** distribui o processo.
2. **GABINETE** minuta a decisão.
3. **MAGISTRADO** assina.
4. **CARTÓRIO** intima.
5. **ADVOGADO** responde.
6. **CARTÓRIO** conclui para julgamento (cria a Sessão).
7. **GABINETE** faz as minutas de julgamento (Relatório/Voto/Acórdão) e pauta.
8. **CARTÓRIO** gere a sessão (quórum, composição, pauta, abertura, votação,
   encerramento da ata).
9. Assinatura de Voto/Acórdão.
10. **CARTÓRIO** intima o julgamento.

Cada AURA cobre um pedaço desse rito. Os passos 1–5 já estão validados; os
passos 6–10 (Sessão de Julgamento) estão em construção (ver
`MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md`).

## 5. Como o AURA opera o eproc (princípios técnicos)

- **Uma sessão contínua por robô**: troca de perfil dentro do mesmo login em
  vez de relogar (evita captcha).
- **Clique nativo do Selenium** em autocompletes/dropdowns do eproc; sinal de
  sucesso é o campo oculto ficar preenchido.
- **Sempre encerrar a sessão** (link real de "Encerrar Sessão") antes de
  fechar o Chrome — sessão presa trava login em qualquer lugar.
- **Verificar o resultado real na tela** — "não deu exceção" não é sinal de
  sucesso.
- **IA como apoio**: o AURAAGENT ajuda a achar assunto equivalente e a revisar
  os dados da petição, sem bloquear o lote.

## 6. Distribuição e execução

- Roda como **código-fonte** (`python aura.py`) ou como **executável**
  (`AURA.exe`, gerado com PyInstaller via `AURA.spec`).
- **No `.exe`:** os IDs das planilhas já vêm embutidos; só o
  `aura_credentials.json` é necessário (embutido no build pelo `AURA.spec`).
  Um `aura_sheets.json` ao lado do `.exe` sobrescreve os IDs, se preciso.
- **Rodando por código:** `aura_credentials.json` (e, opcional,
  `aura_sheets.json`) na raiz do projeto.
- **Conferência:** `diagnostico_planilha.py` mostra qual planilha está em uso e
  faz uma gravação de teste.
- Ambiente-alvo dos testes: **eproc de homologação** do TJMG.

## 7. Estado atual — o que já funciona (setembro/2026)

- **Peticionamento** e **gravação na planilha**: funcionando e validado.
- Colunas novas para o COTRI (`Assunto`, `Tipo_redistribuicao`): **prontas** e
  sendo preenchidas (tipo em rodízio pelos 12 tipos).
- Migração de credenciais/planilhas Google: **concluída** (nova conta de
  serviço + planilhas próprias).
- **Competências reais acessíveis**: a planilha de competências do AURA antigo
  foi compartilhada com a conta de serviço; o robô já lê os dados reais.
- **Gravação no `.exe` corrigida (2026-09-16):** antes o executável gravava na
  planilha antiga porque não achava o `aura_sheets.json` e caía num ID antigo
  fixo. Agora os IDs são embutidos no código, o ID antigo foi removido e falhas
  de gravação não são mais silenciosas — o `.exe` grava na planilha certa
  (basta recompilar da branch atual).

## 8. O que ainda está em construção

- **COTRI alimentado direto pela planilha** (assinatura + redistribuição) — hoje
  o COTRI ainda depende de CSV manual e dos setores antigos. Ver Fases 2–5 no
  `PLANEJAMENTO_AJUSTES_AURA.md`.
- **Sessão de Julgamento (passos 6–10)** — em construção; ver
  `MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md`.
