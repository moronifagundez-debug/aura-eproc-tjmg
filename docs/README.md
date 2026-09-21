# Documentação do AURA — Índice

Todos os documentos do projeto ficam nesta pasta `docs/`. Este índice diz **o
que é cada um** e **em que ordem ler**, conforme o seu objetivo.

> Convenção: os documentos se citam entre si pelo **nome do arquivo** (ex.:
> `ESTUDO_AURA_COTRI.md`). Como estão todos aqui em `docs/`, é só procurar pelo
> nome nesta mesma pasta.

---

## 🚀 Comece por aqui (visão geral)

Para entender o AURA como um todo — o que ele faz e o que falta.

| Documento | Para que serve |
|-----------|----------------|
| [PLANEJAMENTO_FUNCIONAMENTO_AURA.md](PLANEJAMENTO_FUNCIONAMENTO_AURA.md) | **O que o AURA já faz hoje** — a frota de robôs, a planilha central, o rito completo. É o retrato do funcionamento atual. |
| [PLANEJAMENTO_AJUSTES_AURA.md](PLANEJAMENTO_AJUSTES_AURA.md) | **O que ainda falta melhorar** — fases, tarefas e critérios de "pronto". É o par do documento acima. |

## 🔬 Estudos técnicos (análise antes de mexer)

Investigações feitas antes de alterar o código, com diagnóstico e plano.

| Documento | Para que serve |
|-----------|----------------|
| [ESTUDO_AURA_COTRI.md](ESTUDO_AURA_COTRI.md) | Plano completo (5 fases) para o **AURA Distribuição (ex-COTRI) ser alimentado direto pela planilha**. Base das decisões de redistribuição e minuta. |
| [ESTUDO_INTERLIGACAO_AURA.md](ESTUDO_INTERLIGACAO_AURA.md) | Por que o **Gabinete usava endereço/usuário errados** e como todos os robôs passaram a herdar `usuario/senha/url` da tela inicial. Inclui o que já foi implementado. |

## 🛠️ Guias práticos (passo a passo)

Como configurar e operar.

| Documento | Para que serve |
|-----------|----------------|
| [CONFIGURAR_PLANILHAS.md](CONFIGURAR_PLANILHAS.md) | Como **configurar as planilhas do Google** (IDs, conta de serviço, `aura_sheets.json`). |
| [MONITOR_AURA.md](MONITOR_AURA.md) | O **monitor** (`shared/aura_monitor.py`): avisar erros ao usuário da homologação + detectar (uma vez) mudanças na estrutura das páginas do eProc. Como estender ao resto do AURA. |

## 🔁 Handoffs (retomar contexto em outra sessão)

Resumos densos para continuar um trabalho específico depois — inclusive em outra
máquina ou sessão do Claude Code.

| Documento | Para que serve |
|-----------|----------------|
| [HANDOFF_COTRI_PLANILHA.md](HANDOFF_COTRI_PLANILHA.md) | Estado e decisões do trabalho de **COTRI via planilha + credenciais Google**. |
| [MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md](MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md) | Mapeamento detalhado da **Sessão de Julgamento (passos 6–10)** para continuar essa frente. |

---

## Como estes documentos se conectam

```
Visão geral                     Estudos                    Guias / Handoffs
─────────────                   ───────                    ────────────────
FUNCIONAMENTO ─── par ──► AJUSTES ──┬─ base ─► ESTUDO_AURA_COTRI ──► HANDOFF_COTRI_PLANILHA
                                    │                              └─► CONFIGURAR_PLANILHAS
                                    ├─────────► ESTUDO_INTERLIGACAO_AURA
                                    └─ frente ─► MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF
```

- **Quer entender o todo?** Leia os dois de *Visão geral*.
- **Vai mexer na distribuição/planilha?** *ESTUDO_AURA_COTRI* → *CONFIGURAR_PLANILHAS* → *HANDOFF_COTRI_PLANILHA*.
- **Vai mexer no login/endereço dos robôs?** *ESTUDO_INTERLIGACAO_AURA*.
- **Vai mexer na Sessão de Julgamento?** *MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF*.
