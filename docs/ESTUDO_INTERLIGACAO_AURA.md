# Estudo — Interligação dos AURAs (URL + usuário compartilhados)

> **Objetivo:** entender por que o **AURA Gabinete** usa o endereço e o usuário
> errados, e como fazer **todos os AURAs** usarem sempre o **mesmo endereço e o
> mesmo usuário indicados na tela inicial** (`aura.py`). Estudo antes de mexer.
> Atualizado em 2026-09-17.

---

## 1. A ideia central (o que "interligado" significa aqui)

A **tela inicial** do AURA (`aura.py`, o "AURA Principal") é o lugar onde o
usuário digita **uma vez**:

- **URL do sistema** (o endereço do eproc)
- **Usuário** e **Senha**
- (e a chave da IA)

Esses valores são salvos no arquivo **`aura_config.json`** (ao lado do `.exe`),
pelas funções `salvar_config()` / `carregar_config()` (`aura.py:108` e `:119`).

A promessa da interligação é: **os robôs-filhos (Gabinete, COTRI, Eventos,
Sessão) devem herdar esses mesmos valores** — sem o usuário redigitar nada e sem
o risco de um robô ir para um endereço diferente.

---

## 2. Como a interligação funciona hoje (dois mecanismos)

### Mecanismo A — "compartilhar login" (COTRI, Eventos, Sessão)

Quando o `aura.py` abre um desses robôs, ele chama antes uma função
`_compartilhar_login_com_*` que **copia** `USUARIO/SENHA/URL` para o robô:

| Robô | Função em `aura.py` | Onde grava o config do robô |
|------|---------------------|-----------------------------|
| COTRI | `_compartilhar_login_com_aura_cotri` (`aura.py:1381`) | `~/.aura_cotri/config.json` |
| Eventos | `_compartilhar_login_com_aura_eventoscamaracivel` (`:1403`) | config próprio (`run_aura_eventoscamaracivel.salvar_config`) |
| Sessão | `_compartilhar_login_com_aura_sessaojulgamento` (`:1421`) | config próprio (`run_aura_sessao_julgamento.salvar_config`) |

E, do lado do robô, ele **consome** esse valor com prioridade sobre o fixo:

```python
self.url = (_cfg.get("url") or URL_PADRAO).strip()   # config vence; fixo é só plano B
```

(ver `run_aura_eventoscamaracivel.py:1261`, `run_aura_cotri.py:3333`,
`run_aura_sessao_julgamento.py:1408`)

➡️ **Resultado:** quando abertos pela tela inicial, esses três já usam o
endereço e o usuário certos.

### Mecanismo B — nenhum (Gabinete) ❌

`abrir_aura_gabinete()` (`aura.py:1374`) é **o único** que **não** chama
nenhuma função de compartilhar login:

```python
def abrir_aura_gabinete():
    try:
        _auragabinete.AppGUI(janela)   # abre direto, sem passar usuario/senha/url
    ...
```

E, dentro do `auragabinete.py`, **tudo é fixo no código**:

```python
URL_EPROC_GABINETE = "https://eproc2g-hml.tjmg.jus.br/versao/"   # linha 349
USUARIO_EPROC      = "MG123456"                                   # linha 357  (usuário de teste!)
SENHA_EPROC        = "Senha*123456"                               # linha 358
```

Esses valores fixos são usados diretamente no login e na abertura do site:

```python
self.driver.get(URL_EPROC_GABINETE)              # linha 576  -> endereço errado
self.bot.fazer_login(USUARIO_EPROC, SENHA_EPROC) # linha 6620 -> usuário errado
```

➡️ **Resultado:** o Gabinete **ignora** a tela inicial. Sempre vai para
`/versao/` e loga como `MG123456`, não importa o que você digitou.

> 💡 Detalhe importante: o Gabinete **já lê** o `aura_config.json` — mas só para
> pegar a **chave da IA** (`_carregar_groq_key`, `auragabinete.py:376`). O
> "encanamento" para ler do mesmo arquivo **já existe**; falta só ler também
> `usuario/senha/url`.

---

## 3. As divergências encontradas (o mapa do problema)

| Robô | Endereço que usa | Consome a URL da tela inicial? | Usuário que usa |
|------|------------------|-------------------------------|-----------------|
| **Principal** (`aura.py`) | `.../eproc/` | — (é a fonte) | o digitado |
| **COTRI** | `.../eproc/` (plano B) | ✅ sim | o da tela inicial |
| **Eventos** | `.../versao/` (plano B) | ✅ sim | o da tela inicial |
| **Sessão** | `https://eproc2g.tjmg.jus.br/eproc/` (plano B, **produção!**) | ✅ sim | o da tela inicial |
| **Gabinete** | `.../versao/` **fixo** | ❌ **não** | ❌ **`MG123456` fixo** |

Três achados:

1. **🔴 Gabinete (principal):** não recebe nem consome `usuario/senha/url` da
   tela inicial. É a causa direta do "endereço e usuário errados".
2. **🟡 Diferença `/eproc/` vs `/versao/`:** os "planos B" (`URL_PADRAO`) não são
   iguais entre os robôs. Isso só aparece se o robô rodar **sem** a tela inicial
   (modo avulso). Vale padronizar para não confundir.
3. **🟡 Sessão aponta para PRODUÇÃO no plano B** (`eproc2g` sem `-hml`). Se
   alguém abrir a Sessão avulsa, vai para o ambiente real. Merece um alerta.

---

## 4. Proposta — fazer todos funcionarem igual

### Princípio: **uma única fonte da verdade** = `aura_config.json` (tela inicial)

Todo robô deve, na abertura, ler `usuario/senha/url` **da tela inicial** e usar
o valor fixo (`URL_PADRAO`) **apenas** como plano B para execução avulsa.

### Ajuste 1 — Gabinete passa a herdar login (o principal)

**No `aura.py`:** criar `_compartilhar_login_com_gabinete()` (igual às outras) e
chamá-la em `abrir_aura_gabinete()` **antes** de abrir a janela. Como o Gabinete
já lê o `aura_config.json`, basta a tela inicial garantir que ele esteja salvo
(o que `salvar_config` já faz ao logar).

**No `auragabinete.py`:**
- Transformar `URL_EPROC_GABINETE`, `USUARIO_EPROC`, `SENHA_EPROC` em
  **planos B** (renomear para `*_PADRAO`).
- Criar um `carregar_config()` que lê `usuario/senha/url` do `aura_config.json`
  (o mesmo caminho de `_carregar_groq_key`).
- `_abrir_site` passa a usar os valores lidos:
  ```python
  cfg = carregar_config()
  url     = (cfg.get("url")     or URL_EPROC_GABINETE_PADRAO)
  usuario = (cfg.get("usuario") or USUARIO_EPROC_PADRAO)
  senha   = (cfg.get("senha")   or SENHA_EPROC_PADRAO)
  self.bot.abrir_site(url)          # em vez do driver.get fixo
  self.bot.fazer_login(usuario, senha)
  ```
- **Pronto quando:** abrir o Gabinete pela tela inicial e ver que ele vai para a
  **mesma URL** e loga com o **mesmo usuário** digitados no Principal.

### Ajuste 2 — Padronizar o endereço (`/eproc/` vs `/versao/`)

Decidir **um** caminho canônico para o plano B de todos os robôs. Duas opções:
- (a) todos `/eproc/` (igual à tela inicial); **ou**
- (b) confirmar que Gabinete/Eventos realmente precisam de `/versao/` (é uma
  página diferente do eproc?).
- **Precisa da sua confirmação:** `/versao/` é de propósito para o
  Gabinete/Eventos, ou foi só um valor que ficou? Isso decide o Ajuste 2.

### Ajuste 3 — Sessão: plano B não deveria ser produção

Trocar o `URL_PADRAO` da Sessão de `eproc2g.tjmg.jus.br` (produção) para
`eproc2g-hml...` (homologação), para execução avulsa não cair no ambiente real
sem querer. (Quando aberta pela tela inicial, ela já usa a URL de lá — este
ajuste é só uma trava de segurança.)

---

## 5. Ordem sugerida e como validar

1. **Ajuste 1 (Gabinete)** — é o pedido principal e o de maior impacto.
2. **Ajuste 3 (trava da Sessão)** — rápido e seguro.
3. **Ajuste 2 (padronizar `/eproc/` vs `/versao/`)** — depende da sua resposta.

**Como validar cada um (sem confiar só em "não deu erro"):**
- Abrir o robô **pela tela inicial** e olhar a barra de endereço do navegador:
  tem que ser a **URL da tela inicial**.
- Conferir no cabeçalho do eproc que o **usuário logado** é o seu.
- Repetir abrindo o robô **avulso** (sem a tela inicial) e ver que ele cai no
  plano B esperado.

---

## 5.1. O que já foi implementado (2026-09-17)

Decisão adotada: **padronizar tudo em `/eproc/`, mas sempre podendo ser trocado
pela tela inicial** (a URL virou configurável, igual ao usuário).

- ✅ **Ajuste 1 — Gabinete herda login.** `auragabinete.py` ganhou
  `carregar_config()` (lê `usuario/senha/url` do `aura_config.json`, com busca
  robusta de caminho); as constantes viraram planos B (`*_PADRAO`);
  `abrir_navegador(url)` e `_abrir_site` passaram a usar os valores herdados. No
  `aura.py`, `abrir_aura_gabinete()` agora chama
  `_compartilhar_login_com_gabinete()` (merge no `aura_config.json`, sem apagar a
  chave de IA). Precedência validada: **config vence; plano B só no modo avulso.**
- ✅ **Ajuste 2 — padronização `/eproc/`.** Trocado `/versao/` → `/eproc/` no
  Eventos (`URL_PADRAO`) e no script `_aguardar_e_rodar.sh`. COTRI e Principal já
  eram `/eproc/`.
- ⏸️ **Sessão de Julgamento — mantida em produção de propósito.** O código diz
  explicitamente que ela roda contra **sessões reais em andamento**
  (`run_aura_sessao_julgamento.py:72-78`), e o caminho já é `/eproc/`. Quando
  aberta pela tela inicial, herda a URL de lá; então o padrão de produção é só a
  reserva do modo avulso. Não alterado.

**Falta:** recompilar o `.exe` e validar em uso real (abrir o Gabinete pela tela
inicial e conferir URL + usuário no navegador).

## 6. Resumo de uma linha

Hoje **COTRI, Eventos e Sessão** já herdam login da tela inicial; o **Gabinete
não herda nada** (URL e usuário fixos no código). O conserto é dar ao Gabinete o
mesmo mecanismo dos outros — lendo `usuario/senha/url` do `aura_config.json`,
que ele já abre para a chave da IA — e padronizar os "planos B".
