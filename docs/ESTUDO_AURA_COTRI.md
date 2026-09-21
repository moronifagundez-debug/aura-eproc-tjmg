# Estudo — AURA COTRI alimentado pela planilha (antes de alterar código)

> Documento de estudo/desenho. Levanta **tudo que o AURA COTRI precisa**
> para minutar e redistribuir, e propõe **como o peticionamento pode gerar
> esses dados** na planilha `processos_ajuizados`. Nenhuma linha de código
> foi alterada ainda — este arquivo é o plano que vamos seguir.
>
> Base: conversa de 2026-09-11 (pendências fechadas na mesma data).

---

## 1. Como o fluxo funciona hoje (resumo)

- O elo entre todos os AURAs é **uma planilha do Google Sheets**, acessada
  por `shared/aura_db.py`.
- Aba central: **`processos_ajuizados`**, colunas atuais (`aura_db.py:39`):
  `Data · Classe · Magistrado · Processo · Chave · Aviso · Competência`.
- O **peticionamento** (`aura.py`) grava uma linha ali a cada processo
  ajuizado, via `capturar_dados_finais()` → `salvar_no_historico()`
  (`aura.py:171` e `aura.py:148`).
- O **COTRI** (`integrations/run_aura_cotri.py`) faz DUAS coisas:
  1. **Assinatura/minuta** em lote (`executar_assinatura_cotri`, linha 2596).
  2. **Redistribuição** em lote (`executar_redistribuicao_cotri`, linha 2789).
- Hoje o COTRI **não** é alimentado pela planilha: a fonte primária é um
  **CSV importado à mão**. A planilha só **completa a competência** que
  falta (`enriquecer_competencia_via_sheets`, linha 479).

Objetivo: fazer `processos_ajuizados` ser a **fonte primária** do COTRI —
para minutar e redistribuir.

---

## 2. Decisões tomadas (2026-09-11)

1. **Ampliar `processos_ajuizados`** (em vez de criar aba nova), mas com um
   conjunto **mínimo** de colunas novas (ver seção 4).
2. **Processo de referência** (redistribuições por dependência): basta ser
   **2ª instância**, **número diferente** do processo redistribuído e
   **mesma competência**. **NÃO** precisa considerar órgão. Como todo
   processo ajuizado pelo AURA já é de 2ª instância, a referência sai do
   próprio `processos_ajuizados`.
3. **Tipo de redistribuição em loop cíclico**: os motivos (radios de
   `TIPO_RADIO_ID`) entram na coluna `Tipo_redistribuicao` em rodízio; ao
   chegar no último, volta ao primeiro. **Cobrir os 12 tipos.**
4. **Minuta por peticionamento, não por "preferência"**: o COTRI vai
   **peticionar e concluir** o processo, igual ao *peticionamento
   intermediário* (`executar_intermediario`, `aura.py:1605`). O **evento** e
   o **tipo de documento são sempre os mesmos** (constantes fixas):
   - Tipo de documento: **`Documento de informação`**
   - Evento: **`Conclusos para decisão com revisão de autuação (51)`**
5. **Setores de distribuição mudaram**: agora são **três** (seção 6). A
   seleção de perfil casa pelo **nome completo do setor**. **Qual setor
   usar é escolha do usuário** (não vamos derivar da competência
   automaticamente por ora — esse fluxo fica para depois).

---

## 3. Inventário — o que o COTRI precisa

### 3.1 Assinatura / minuta
Com a decisão 4, a minuta deixa de depender da "preferência" do setor.
Passa a precisar por processo de:

| Dado | Origem |
|------|--------|
| `numero_processo` | planilha `processos_ajuizados` |
| `Evento` (fixo) | constante `Conclusos para decisão com revisão de autuação (51)` |
| `Tipodocumento` (fixo) | constante `Documento de informação` |
| PDF da petição | modelo único (como no intermediário, `CAMINHO_PDF`) |
| setor | escolhido pelo usuário na UI (1 dos 3) |

### 3.2 Redistribuição
Fonte: `_MAPA_REDISTRIBUIR` (257), `_preencher_campos_do_tipo` (2200),
`_COM_COMPETENCIA` (1854), `_COM_PROCESSO_REF` (1862).

| Campo | Quando é exigido | De onde vem |
|-------|------------------|-------------|
| `numero_processo` | sempre | planilha |
| `tipo` | sempre | coluna `Tipo_redistribuicao` (loop, decisão 3) |
| `competencia` | tipos em `_COM_COMPETENCIA` | coluna `Competência` (já existe) |
| `classe_judicial` | opcional | coluna `Classe` (já existe) |
| `assunto` | opcional | coluna nova `Assunto` |
| `processo_ref` | tipos em `_COM_PROCESSO_REF` | **calculado** da própria planilha (seção 5) |
| `motivo_retorno` | só "Retorna Autos" | ver Pendências |

**Os 12 tipos** (`TIPO_RADIO_ID:1830`): Dependência a Juízo · Dependência
a Processo/Colegiado · Dependência a Processo/Magistrado · Impedimento ·
Suspeição · Incompetência · Incompetência c/ Dependência Colegiado ·
Incompetência c/ Dependência Magistrado · Livre · Retorna Autos ·
Alteração da Competência do Órgão Julgador · Por dependência por Alteração
da Competência.

---

## 4. Colunas novas em `processos_ajuizados` (mínimo necessário)

Graças às decisões, o conjunto novo é **enxuto**:

| Nova coluna | Para quê | Origem |
|-------------|----------|--------|
| `Assunto` | preencher redistribuição (tipos com competência) | planilha de competências / capa |
| `Tipo_redistribuicao` | motivo em loop cíclico (12 tipos) | gerado em rodízio no peticionamento |

Já **não** são necessárias (descartadas após as respostas):
- `Instancia` → todo processo ajuizado é 2ª instância (implícito).
- `Processo_origem` → não necessário agora.
- `Orgao_julgador` → referência não usa órgão; não precisa por ora.
- `Setor_distribuicao` → o usuário escolhe o setor na UI.
- `Evento` / `Tipodocumento` → são constantes fixas no código, não colunas.

`Classe_judicial` reaproveita a coluna `Classe` que já existe.

Compatibilidade: `ler_processos_ajuizados` lê por cabeçalho (dict), então
**acrescentar colunas no fim não quebra** nada. Linhas antigas ficam com as
novas vazias — tratar vazio com regra padrão.

---

## 5. Regra do processo de referência (decisão 2)

A referência é **calculada** sobre o próprio `processos_ajuizados` (todos
2ª instância). Para o processo P, candidato válido é a linha onde:

1. `Processo` ≠ P (número diferente); e
2. `Competência` compatível com a de P.

Escolher um candidato (ex.: primeiro elegível, ou rodízio para variar).
`buscar_processo_ref` (linha 375) já descarta o próprio processo e casa
competência — basta **remover** a lógica de câmara/órgão (`camara_excluir`,
`_extrair_camara`) e apontar a fonte para a planilha em vez do CSV.

---

## 6. Setores de distribuição — os três novos (decisão 5)

Confirmado pelo HTML da tela "Seleção de perfil" (upload `selecao_perfil.txt`):

| Código | Nome completo (Lotação) | data-descricao |
|--------|-------------------------|----------------|
| COMED  | `Coordenação de Análise de Medidas Urgentes (COMED)` | `DIRETOR DISTRIBUIÇÃO / COMED` |
| COAPRI | `Coordenação de Análise Processual Privada (COAPRI)` | `DIRETOR DISTRIBUIÇÃO / COAPRI` |
| COAPUB | `Coordenação de Análise Processual Pública (COAPUB)` | `DIRETOR DISTRIBUIÇÃO / COAPUB` |

- Antigo **COTRI** → **COAPUB + COAPRI**. Antigo **CODIPRE** → **COMED**.
- Seleção de perfil casa pelo **nome completo** da Lotação (mais seguro que
  a sigla). Ajustar `_perfil_compativel` (linha 1021).
- Onde atualizar: UI de perfil (`run_aura_cotri.py:3596`, hoje só
  `COTRI`/`CODIPRE`), defaults `state.perfil` (`:143` e fallbacks),
  `selecionar_perfil` (`:850`). Com a decisão 4, `PREFERENCIAS_POR_PERFIL`
  (`:1297`) tende a sair de cena.
- **Qual setor usar é escolha do usuário** — sem mapa automático de
  competência→setor por enquanto.

---

## 7. Minuta por peticionamento (decisão 4)

Trocar `localizar_link_preferencia` + assinar (linha 1311 e 2596) pelo
motor do intermediário: `executar_peticao_intermediaria_linha` (chamado em
`aura.py:1659`), que precisa por processo de `Processo`, `Evento`,
`Tipodocumento` e um PDF.

Valores **fixos** (iguais para os 3 setores):
- `Tipodocumento` = **Documento de informação**
- `Evento` = **Conclusos para decisão com revisão de autuação (51)**

Assim some a dependência de `PREFERENCIAS_POR_PERFIL` e dos nomes de
preferência por setor.

---

## 8. Modelo de dados proposto (planilha ampliada)

`processos_ajuizados` passaria a ter (novas em **negrito**):

```
Data · Classe · Magistrado · Processo · Chave · Aviso · Competência
· **Assunto** · **Tipo_redistribuicao**
```

Só duas colunas novas. O resto o COTRI deriva (competência/classe já
existem; referência é calculada; evento/tipodoc são constantes; setor é
escolha do usuário).

---

## 9. Pendências

**Fechadas (2026-09-11):**
- Referência: número diferente + 2ª instância + mesma competência (sem órgão). ✔
- Evento/Tipodocumento da minuta: fixos (seção 7). ✔
- Instância/processo de origem: não necessários (todos 2ª instância). ✔
- Mapa competência→setor: não automatizar; usuário escolhe. ✔
- Loop de tipos: cobre os 12. ✔

**Em aberto:**
1. **`orgaos_caciv.json`** — foram criados **novos núcleos privados**; pode
   ser necessário reajustar o registro de órgãos (item futuro, não bloqueia
   a redistribuição já que a referência não usa órgão).
2. **`motivo_retorno`** do tipo "Retorna Autos" — como será informado no
   loop (valor fixo? rodízio dos motivos de `_MOTIVO_RETORNO_ID`?).
3. **PDF/modelo** único da minuta (o mesmo do intermediário?).
4. **Fluxo de escolha do setor pelo usuário** — desenhar depois (por linha
   na planilha? por lote na UI?).

---

## 10. Plano de implementação sugerido (fases)

- **Fase 1 — Planilha:** ✅ FEITO. `CABECALHO_PROCESSOS` e
  `gravar_processo_ajuizado` ganharam `Assunto` e `Tipo_redistribuicao`; o
  peticionamento preenche em `capturar_dados_finais` (Assunto vem da linha da
  competência; o tipo é gerado em rodízio pelos 12 tipos via
  `proximo_tipo_redistribuicao` em `aura_db.py`). IDs das planilhas agora
  vêm de `aura_sheets.json` (ver CONFIGURAR_PLANILHAS.md).
- **Fase 2 — Setores:** ✅ FEITO (2026-09-17). UI com os 3 setores
  (COMED/COAPRI/COAPUB), match por nome completo, default COAPUB; nome exibido
  virou **AURA Distribuição**; a assinatura por preferência foi protegida (avisa
  "em migração" para os setores novos, em vez de cair na PPG antiga).
- **Fase 3 — Distribuição lê da planilha:** ✅ FEITO (2026-09-17). A fila da
  minuta vem por padrão de `aura_db.ler_processos_ajuizados()` (planilha
  central); o CSV virou opcional (só se o usuário selecionar um arquivo). A
  coluna `Processo` entrou em `_COLUNAS_NUMERO_PROCESSO`.
- **Fase 4 — Referência calculada:** ✅ FEITO (2026-09-18). A redistribuição
  monta fila **e** referências a partir da planilha central
  (`fila_redistribuicao_da_planilha`): a referência de cada processo é calculada
  da própria planilha — **número diferente + mesma competência** (sem regra de
  órgão), via `buscar_processo_ref`. CSVs de redistribuição/referências viraram
  **opcionais** (alternativa). Blindagem anti-duplicidade também na redistribuição
  (modo planilha). Processo sem par de mesma competência **não bloqueia o lote**:
  falha/pula só a própria linha.
- **Fase 5 — Minuta de "Informação" (NÃO é peticionamento):** ✅ IMPLEMENTADO
  (2026-09-17), **a validar em homologação**. Correção de rumo: o combinado é
  **MINUTAR** como o AURA Gabinete (não peticionar). O robô acessa o processo,
  cria uma minuta de **Tipo/Modelo = "Informação"** com o **evento de conclusão**
  `Conclusos para decisão com revisão de autuação (51)`, insere um
  **texto fixo** e **assina** — **só gera o evento (sem remessa)**.
  - **Motores:** formulário + inserir texto = motor do **AURA Gabinete**
    (`EprocBotV4`, tela `minuta_cadastrar`); **assinatura = fluxo comprovado do
    COTRI antigo** (`_salvar_e_editar` → `_assinar_no_editor` →
    `_inserir_senha_e_confirmar`, no editor CKE + iframe).
  - **Blindagem anti-duplicidade:** a planilha central é um log append-only;
    processos já minutados com sucesso (registrados em
    `~/.aura_cotri/minuta_resultados.csv`) são **pulados** (na mesma execução e
    nas futuras), para nunca criar minutas/assinaturas repetidas.
  - **A validar em HOMOLOGAÇÃO antes de usar pra valer** (comportamentos que só
    a tela real confirma):
    1. o botão "Assinar" aparece inline no editor sem pré-marcar status
       "Para assinar" (por isso esse passo foi **removido**);
    2. o texto fixo cai no corpo do editor (foco correto após "Salvar e Editar");
    3. a minuta abre em nova aba e o retorno à aba principal funciona entre linhas;
    4. o evento de conclusão é aceito via `txtEvento` (agendamento) sem remessa.

Cada fase é testável isolada e mantém o CSV manual como alternativa até a
planilha estar validada.
