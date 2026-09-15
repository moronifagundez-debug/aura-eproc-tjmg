# AURA — Planejamento de Funcionamento (visão completa)

> Como o AURA funciona hoje, de ponta a ponta: o que é, quais módulos existem,
> como os dados circulam e qual o fluxo jurídico que ele automatiza.
> Documento de referência. Atualizado em 2026-09-15.

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
- **Config local** (fora do git): `aura_credentials.json` (chave da conta de
  serviço Google) e `aura_sheets.json` (IDs das planilhas).
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
- Os arquivos de config (`aura_credentials.json`, `aura_sheets.json`) ficam
  **ao lado do executável** (ou na raiz, ao rodar por código).
- Ambiente-alvo dos testes: **eproc de homologação** do TJMG.

## 7. Estado atual (setembro/2026)

- Peticionamento e gravação na planilha: **funcionando** (validado).
- Colunas novas para o COTRI (`Assunto`, `Tipo_redistribuicao`): **prontas**
  e sendo preenchidas.
- Migração de credenciais/planilhas Google: **concluída** (nova conta de
  serviço + planilhas próprias).
- Em construção: alimentar o COTRI direto da planilha (Fases 2–5, ver
  `PLANEJAMENTO_AJUSTES_AURA.md`) e a Sessão de Julgamento (passos 6–10).
