# Handoff — AURA Regressão de Homologação: Sessão de Julgamento (Passos 6-10)

> Documento gerado em 2026-08-26 pra continuar este trabalho em outra
> máquina/sessão do Claude Code. Cole/aponte este arquivo pra sessão nova
> logo no início ("lê o arquivo MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md
> na pasta docs/ antes de continuar"). Tudo abaixo veio da memória
> local desta máquina (`.claude/projects/.../memory/`), que NÃO
> sincroniza entre computadores — por isso este arquivo existe.

## Contexto geral

Isto **não é um módulo separado** — é a continuação do pipeline **AURA
Regressão de Homologação** (`shared/aura_regressao_homologacao.py` +
`aura.py`). Passos 1-5 (COTRI distribui → GABINETE minuta → MAGISTRADO
assina → CARTÓRIO intima → ADVOGADO responde) já validados end-to-end
com código, commitados. Passos 6-10 são o rito de **Sessão de
Julgamento**, ainda em construção.

**Prazo**: usuário quer entregar esta parte até o fim da semana de
2026-08-23 (ou seja, prazo bem apertado — hoje, quando este handoff foi
escrito, é 2026-08-26).

### Rito oficial (Passo 6 a 10)
- **Passo 6**: CARTÓRIO cria a Sessão de Julgamento e conclui o processo
  ao GABINETE (evento "Conclusos para decisão/despacho").
- **Passo 7**: GABINETE faz as minutas de julgamento (Relatório/Voto/
  Acórdão) e pauta o processo na sessão criada no Passo 6; anexa
  (agenda evento de juntada) assinando só o Relatório; disponibiliza as
  minutas.
- **Passo 8**: CARTÓRIO fecha a pauta e "realiza o avanço da sessão" —
  quórum, composição, publicação da pauta, intimação, abertura da
  sessão, votação dos vogais, fechamento da sessão e lançamento do
  resultado do julgamento.
- **Passo 9**: assinatura de VOTO e ACÓRDÃO de verdade (Ementa no
  estilo CKEditor "caputEmenta", aplicado automaticamente ao digitar).
  Depois, evento "Juntada de relatório/voto/acórdão com remessa ao
  cartório responsável pelo processo" (evento DIFERENTE do Passo 7).
- **Passo 10**: CARTÓRIO intima as partes com "Expedida e certificada a
  intimação - Julgamento".

## Onde o código mora (decisão explícita do usuário, 2026-08-26)

- **Passo 6** (conclusão): já existe, `shared/aura_regressao_homologacao.py::passo_cartorio_conclui`.
- **Passo 7** (minutas do GABINETE): `integrations/auragabinete.py::EprocBotV4`
  — reaproveita infraestrutura de minuta/CKEditor já madura
  (`_preencher_autocomplete`, `salvar_e_editar`, `_aguardar_ckeditor_pronto`,
  `inserir_texto_editor`, `salvar_minuta_e_sair`, `encaminhar_para_assinatura`).
- **Passo 8** (gestão de sessão do CARTÓRIO): **`integrations/run_aura_sessao_julgamento.py`**
  — **NÃO** `auragabinete.py` (o usuário corrigiu isso explicitamente:
  "não será no auragabinete.py, será no aura, ainda iremos atualizar o
  auragabinete"). Esse arquivo já existia antes (função original:
  launcher headless de uma extensão Chrome que MONITORA sessões em
  produção via localStorage — feature diferente) e já tem
  `login`/`criar_driver`/`navegar_para_listagem_sessoes` reaproveitáveis.
  Já é importado em `aura.py` e abre `AuraSessaoJulgamentoApp` a partir
  de um card na tela principal.

## Estado do código escrito (2026-08-26) — NUNCA rodado via Selenium ainda

### `integrations/run_aura_sessao_julgamento.py` (Passo 8)
Funções novas, todas traduzidas de mapeamento ao vivo (24/08) mas nunca
testadas via Selenium — tratar primeira execução real como teste,
acompanhar com `headless=False`:
- `_achar_linha_sessao`, `_clicar_por_texto`, `_abrir_menu_linha` (helpers).
- `fechar_pauta(driver, filtro_sessao, log)`.
- `abrir_modal_participantes(driver, filtro_sessao, log)`.
- `incluir_magistrado_quorum(driver, nome, presidente, log)`.
- `mudar_aba_modal(driver, nome_aba, log)`.
- `definir_papel_composicao(driver, nome, papel, log)`.
- `salvar_quorum_composicao(driver, log)`.
- `gerar_pauta_publicar_intimar(driver, wait, filtro_sessao, log)`.
- `abrir_sessao(driver, filtro_sessao, log)`.
- `encerrar_ata(driver, filtro_sessao, log)` — ver achado do código-fonte
  abaixo, botão real `sbmEncerrarAtaSessaoJulgamento`.

**Ponto frágil não confirmado**: o seletor do menu "⋮" (`_abrir_menu_linha`)
foi só descrito visualmente, nunca capturado por inspeção de DOM exata —
tenta `[data-toggle='dropdown']`/`.dropdown-toggle` e o ícone Material
`more_vert` como fallback. Maior chance de precisar ajuste no primeiro
teste real.

### `shared/aura_regressao_homologacao.py`
`passo8_cartorio_avancar_sessao(driver, wait, filtro_sessao, presidente,
votantes, log)` — encadeia fechar pauta → quórum → composição → gerar
pauta → abrir sessão. Para em "Sessão aberta" e retorna mensagem clara
sobre o que falta. Ainda não chamado por `rodar_pipeline_completo` nem
por nenhuma UI.

### `integrations/auragabinete.py::EprocBotV4` (Passo 7, parcial)
Funções novas: `salvar_e_editar_com_julgamento_relacionado` (trata alert
nativo "Selecione um julgamento relacionado"), `_editar_minuta_por_titulo(titulo_contendo)`,
`executar_criar_minutas_julgamento(dados)` (cria as 3 minutas RELATÓRIO/
VOTO/ACÓRDÃO, preenche Relatório/Voto/só-Ementa-do-Acórdão, encaminha só
o Relatório pra assinatura).

**Ponto frágil não confirmado**: `_editar_minuta_por_titulo` assume ícone
"Editar minuta" com `acao='minuta_editar'` — inferência por analogia,
nunca validada ao vivo.

**NÃO incluído ainda**: encadear com `executar_incluir_pauta_mesa` (já
existe, ver diff de 24/08 em auragabinete.py — CARTÓRIO incluindo em
Pauta/Mesa) e o agendamento do evento "Juntada de Relatório/Voto/Acórdão
(581)" na Relação de Minutas (mapeado, não codado). Não existe
orquestrador `passo7_gabinete_*` ainda.

**IMPORTANTE — perfil errado documentado numa versão antiga do código**:
quem inclui processo em Pauta/Mesa é o perfil **GABINETE** (órgão COM
assento, ex. `20CACIV-A1`), **não CARTÓRIO** (órgão sem assento). Um
comentário antigo em `aura_regressao_homologacao.py` (de 2026-08-20,
antes dessa correção) ainda assume CARTÓRIO — ignorar, a correção de
2026-08-23 é a que vale.

## Achados do código-fonte real do eproc (2026-08-26, sem precisar de login)

Usuário conseguiu o código-fonte completo do eproc (`eproc2-master`,
PHP/Twig/JS/SQL) e subiu extraído pro Google Drive. Usei
`mcp__claude_ai_Google_Drive__*` (search_files, download_file_content)
pra ler os controladores reais de `App\Controladores\SessaoJulgamento\`
— não precisa de login nenhum pra isso, é só ler arquivo.

**Como acessar de novo**: `search_files` com `title contains 'Nome.php'`
ou `parentId = '<id>'`; `download_file_content` retorna base64 —
arquivos grandes (>~90KB) estouram o limite inline e são salvos em
`tool-results/mcp-claude_ai_Google_Drive-download_file_content-*.txt`
como JSON `{content, id, mimeType, title}` — decodificar com Python
(`json.load` + `base64.b64decode`), não tentar ler o base64 bruto.
Pasta raiz do repo no Drive: **"eproc2-master"**.

### Achado principal — destrava o fim do Passo 8
A ação que faltava ("CARTÓRIO fecha a sessão e lança o resultado")
chama-se **"Encerrar Ata"** (`App\Controladores\SessaoJulgamento\EncerrarAta`).
Recurso de permissão: `sessao_julgamento_encerrar_ata`. Botão real:
**`sbmEncerrarAtaSessaoJulgamento`**. PRÉ-REQUISITO confirmado no código:
só fica disponível quando NENHUM item da sessão está "sem resultado" nem
"sem evento" — todo processo pautado precisa já ter sido julgado E ter o
evento lançado antes de encerrar a ata. `EncerrarAta::acaoModalComAbas()`
monta um modal com 4 abas combinadas (EncerrarAta + Dados + Quorum +
Composicao) — provavelmente o MESMO modal já mapeado como "Alterar os
magistrados participantes", só que a 4ª aba só aparece quando elegível.
Código escrito (`encerrar_ata` acima) mas nunca testado ao vivo.

### Achado crítico — votação é DRAG-AND-DROP, não clique simples
`item_resultado.js` (JS real da tela de julgar um item, achado via busca
por texto "Pedir Vista" no Drive) revela que a tela de julgamento de um
item **NÃO é um botão de clique único** — é uma interface de
**arrastar-e-soltar** (jQuery `.draggable`). Cada magistrado do quórum é
um cartão arrastável; o usuário ARRASTA pra uma seção: `#section-relator`,
`.section-divergencia` (pode ter múltiplas, cada uma com textarea de
fundamentação), `#section-pedido-vista`. Só depois de organizar os
cartões, um botão "Salvar" monta o estado inteiro num payload
(`getRelator`/`getPedidoDeVista`/`montarArrayTesesDivergencia`) e envia
pro backend (`ItemResultado::acaoSalvar`).

Os ícones simples (👍 thumb_up/👎 thumb_down/👁 visibility/↩ undo) mapeados
ao vivo em 25/08 na aba Pauta do "Painel da Sessão" continuam existindo
de verdade (confirmados por onclick real) — hipótese NÃO CONFIRMADA: são
um atalho de 1 clique que faz o equivalente a "arrastar e salvar" pro
caso simples (1 vogal, sem divergência). Pode ser também uma ação
totalmente separada. **Só dá pra fechar isso vendo a tela ao vivo.**

**Por isso não escrevi (nem vou escrever às cegas) nenhuma automação
Selenium pro drag-and-drop** — simular mousedown/mousemove/mouseup de
verdade é muito mais frágil, e o risco de errar sem nunca ter visto a
tela é alto demais. **Este é o motivo técnico real de por que a votação
continua sendo o item mais bloqueado do Passo 8 — não é só a barreira de
login, é que a interação em si é complexa e não foi observada ao vivo.**

Próximo passo real: 1) confirmar ao vivo se os ícones de atalho bastam
pro caso comum, ou se cai na tela de drag-and-drop; 2) se cair no
drag-and-drop, ler o Twig (`sessao_julgamento/recursos/item_resultado/*.twig`,
ainda não lido) pra entender a estrutura DOM exata antes de automatizar.

### Lead ainda não fechado — "lançar resultado" por item
`ItemResultado.php` (painel) tem `acaoGerarDecisao`, `acaoAdicionarDivergencia`,
`acaoConfirmar`, `acaoAtualizarBloco`, rota `sessao_julgamento_item_julgar`
— parece ser o mecanismo de registrar o resultado formal de cada
processo (passo ANTES de poder encerrar a ata). Trata retificação de
ata, execução penal, "juízo substituto", divergência com "tese" — mais
complexo que os 4 ícones simples. Não deu tempo de mapear a fundo.

### Lead NÃO encontrado
Os `acao=` dos ícones simples (`sessao_julgamento_item_acompanha_relator`/
`_acompanha_divergencia`/`_pedir_vista`/`_retirar`, mapeados ao vivo via
onclick em 25/08) **não aparecem em nenhum arquivo PHP** achado por busca
de texto no Drive inteiro (só achei o ícone `acompanha_relator.png`).
Devem ser tratados por `SessaoJulgamentoItemRN.php` (1.2MB, classe de
regra de negócio) via AJAX direto, mas grep nesse arquivo não achou as
strings. **Continua valendo mais confiar no `acao=` extraído ao vivo do
onclick (runtime, já confirmado) do que tentar re-derivar do PHP.**

### Confirmações que validam o código já escrito (sem mudança necessária)
- `Quorum.php::acaoIncluirQuorum` usa parâmetro `seq_magistrado_quorum`,
  ação AJAX-partial separada de `acaoSalvarAlteracaoQuorum` — confirma
  "Incluir" e "Salvar" como ações distintas reais.
- `SessaoJulgamentoQuorumDTO` tem `getStrSinPresidente()`/
  `getStrSinParticipanteEventual()` como campos booleanos reais —
  confirma os 2 checkboxes já documentados.
- `GerarPauta::acaoGerar` lê `$_POST['sin_lancar_evento']` (bate com id
  `chk_lancar_evento_S` confirmado por DOM ao vivo — convenção eproc
  `chk<Campo>_S` → POST `sin_<campo>`) e dispara `intimarPauta()` junto
  quando 'S'. Existe `acaoIntimar`/`doIntimar` SEPARADA — confirma que
  "Disponibilizar Pauta" no menu depois de Publicar/Intimar é ação real
  independente, não redundante.
- `Composicao.php`: abas usam `acao=sessao_julgamento_alterar_composicao`/
  `_consultar_composicao`; salva via AJAX `acao_ajax=salvar_composicoes`
  (JS `grade_composicoes.js`, onde vive o ciclo de estado do span — não
  lido ainda, mas comportamento de clique já confirmado ao vivo deve bater).

## Mapeamento ao vivo já validado (2026-08-24, antes do código-fonte)

### Fechar pauta manualmente
Ícone Material Icons `no_meeting_room`/`meeting_room` na coluna "Ações"
de CADA LINHA da listagem "Sessões de Julgamento" (não no menu "⋮" nem
na barra de topo):
```html
<a role="presentation" href="#/" name="imgRecursoSessaoJulgamentoAjax"
   acao="sessao_julgamento_fechar_pauta"
   id_recurso_sessao_julgamento="<hash>"
   descricao="Fechar a pauta da sessão de julgamento"
   id_sessao_julgamento="<hash_sessao>"
   sin_solicitar_confirmacao="S">
  <i class="material-icons">no_meeting_room</i>
</a>
```
Clique nativo dispara `window.confirm()` nativo — sobrescrever
`window.confirm = function(){return true;}` ANTES do clique é mais
confiável que interceptar o alert depois. Resultado: "Pauta aberta" →
"Pauta fechada". Não precisa esperar a Data Limite Pauta chegar — dá pra
fechar manualmente antes.

### Quórum e Composição
Modal "Sessão Telepresencial - <Câmara> - <Data>" (aberto por "Alterar
os magistrados participantes da sessão de julgamento" no menu "⋮"):

**Aba QUÓRUM**: botão "Incluir" é uma seta (`<a>`) na tabela
"Magistrados não cadastrados" — magistrados com badge "Com processos"
(relator) têm 2 `<a>` na linha, pegar o ÚLTIMO. Depois de incluído,
marcar checkbox "Presidente" (2º checkbox, índice 1 — o 1º é
"Participante Eventual"). Salvar com botão azul "Salvar" (sem id fixo
nesta aba, pegar por texto).

**Aba COMPOSIÇÃO**: tabela NÃO usa `<tbody>` (linhas inseridas via JS
como filhas diretas de `<table>`) — usar
`document.querySelectorAll('tr')` + filtrar por
`getBoundingClientRect().width>0`. Célula clicável: `<span
class="grade-composicao-magistrado-papel-<estado>" data-id-papel="<N>">`
no 3º `<td>` (índice 2). Cada clique CICLA: indefinido(-1) → 1 clique =
votante → 2 cliques = presidente → (3 = presidente-sem-voto, não
testado) → volta. Botão salvar: `#btnSalvar` (id fixo, compartilhado
entre as 2 abas).

### Gerar Pauta + Publicar + Intimar (1 ação só)
Menu "⋮" > "Gerar Pauta da Sessão de Julgamento", wizard de 3 telas:
1. **Tela 1**: botão **"Validar"** (`<a class="btn btn-primary">`, NÃO `<button>`).
2. **Tela 2** (só se algum processo tem aviso): checkboxes já marcados,
   clicar **"Gravar"** (`<a>`).
3. **Tela 3**: marcar `chk_lancar_evento_S` + `chk_publicar_S` (ids
   fixos, NUNCA usar seletor genérico de checkbox aqui — o modal fica
   sobre a listagem cheia de filtros/checkboxes, um clique em lote pega
   os errados) → botão **"Gerar pauta"** (`<a>`).

Resultado: "Pauta fechada" → **"Intimação realizada"** direto.

### Abrir a Sessão
Ícone da linha muda pra `meeting_room`, `onclick="window.abrirRecursoSessaoModal('...acao=sessao_julgamento_abrir_sessao...')"`,
tooltip "Abrir a Sessão de Julgamento". Modal com campo "Data e Hora do
Início" (pré-preenchido) + aviso vermelho de confirmação. Botão de
confirmar é `<button>` "Salvar" (não `<a>` — inconsistente com os
wizards acima). Resultado: "Sessão aberta".

### Painel da Sessão de Julgamento (onde ficam os ícones de voto)
Caminho: `Sessão de Julgamento` (menu) → `Calendário de Sessões de
Julgamento` → clicar no evento no calendário → ícone `playlist_play`
(`acao=sessao_julgamento_exibir_painel`) → abre "Painel da Sessão de
Julgamento" em nova aba → aba **Pauta**.

Ícones por item da Pauta (confirmados via atributo `descricao`, extraído
por JS porque é `onclick`, não `href`):
- 👍 `thumb_up` = "Acompanhar o Relator..." (`acao=sessao_julgamento_item_acompanha_relator`)
- 👎 `thumb_down` = "Acompanhar a Divergência..." (`acao=sessao_julgamento_item_acompanha_divergencia`)
- 👁 `visibility` = "Pedir Vista..." (`acao=sessao_julgamento_item_pedir_vista`)
- ↩ `undo` = "Retirar de pauta" (`acao=sessao_julgamento_item_retirar`)

**Ver seção "votação é drag-and-drop" acima — esses ícones podem ser só
um atalho, não confirmado.**

## Passo 7 validado ao vivo ponta a ponta (2026-08-24)

1. Capa do processo → "Nova" (Minutas) → Tipo de documento/Modelo
   (`#txtModelo`) = **"\*\*\* RELATÓRIO \*\*\*"** (não "Relatório/Voto") →
   revela "Texto Inicial 2"/"Texto Inicial 3" (`#TXTINI2_txtModelo`/
   `#TXTINI3_txtModelo`) = **"\*\*\* VOTO \*\*\*"** / **"\*\*\* ACÓRDÃO \*\*\*"**.
2. "Salvar e Editar" → cria **3 MINUTAS SEPARADAS mas VINCULADAS** (não
   1 documento com 3 campos): RELATÓRIO, VOTO, ACÓRDÃO.
3. Se o processo já teve Julgamento antes: alert nativo "Selecione um
   julgamento relacionado" trava — aceitar alert, marcar radio do
   Julgamento antigo em "Julgamento Relacionado", salvar de novo.
4. Preencher: Relatório e Voto no corpo normal (`_7` do CKEditor), Voto
   terminando em "VOTO POR..."; Acórdão só a **Ementa** (`_7`), corpo
   (`_8`/`_10`) fica VAZIO até o Passo 9. Dá pra usar
   `CKEDITOR.instances['<id>_7'].setData(...)` direto.
5. Agendar evento: "Alterar Dados" do RELATÓRIO → marcar as 3 minutas em
   "Relação de Minutas" → marcar `#chkEventoAgendamento` → `#txtEvento`
   → **"Juntada de Relatório/Voto/Acórdão (581)"** → Salvar. Roda dentro
   de iframe `#ifrSubFrm` — precisa `switch_to.frame` + clique NATIVO no
   item do autocomplete (JS sintético não registra, campo oculto real é
   `#hdnEvento`).
6. Encaminhar só o RELATÓRIO pra assinatura: ícone `img[alt="Encaminhar
   minuta para assinatura"]` na linha dele — Status "Rascunho" →
   "Para assinar". Voto/Acórdão ficam Rascunho.
7. Magistrado assina: Painel do Magistrado → "Relatório para assinar" →
   marcar linha → `#btnAssinar` → modal (iframe `#ifrSubFrm`) → senha em
   `#txtSenha` (visível, tipo text mascarado — NÃO o `input[type=password]`
   oculto) → `#sbmAssinarComSenha`.
8. **Resultado confirmado no histórico real**: Evento 17, "Juntada de
   Relatório/Voto/Acórdão", doc RELT1 anexado.

**Pendência**: "Disponibilizar minuta" (botão `title="Disponibilizar"`
no editor, ícone de linha na capa) — nunca clicado/testado. Código
especulativo pré-existente (`executar_disponibilizar_minutas`, escrito
2026-08-18 ANTES de qualquer mapeamento ao vivo) usa seletores
adivinhados que **não batem** com o nome real do botão — não confiar
nele até validar.

## Regras de pareamento (como o usuário quer que isso seja construído)

- **Pareamento ao vivo, não código às cegas**: confirmar cada passo novo
  com screenshot/observação real antes de seguir, especialmente ações
  que mudam estado real em homologação. "Não deu exceção" NÃO é sinal de
  sucesso — verificar o resultado real na tela/histórico.
- **Reusar UMA sessão contínua por robô** — trocar de perfil dentro da
  mesma sessão/login quando possível, não logar de novo a cada
  micro-teste (login repetido pode disparar captcha).
- **NÃO matar `chrome.exe` por PID** pra limpar — pode derrubar janelas
  que deveriam ficar de pé. Preferir `driver.quit()` dentro do script.
- **Clique NATIVO do Selenium, não JS sintético**, pra qualquer
  autocomplete/dropdown do eproc (jQuery UI) — sinal de sucesso real é o
  campo oculto (`hdnEvento` etc) ficar preenchido, dropdown fechar.
- **Deslogar antes de fechar o Chrome** — sempre clicar o link real
  `#btn-encerrar-sessao` antes de `driver.quit()`, nunca só fechar a
  janela ou montar `acao=sair` na mão (sem hash certo dá "Link sem
  assinatura" e não encerra de verdade). Sessão presa trava login em
  QUALQUER lugar depois (até no celular do usuário), não só no robô.
- **Cookie de sessão é compartilhado entre TODAS as abas do mesmo perfil
  Chrome** — não dá pra ter 2 contas eproc diferentes logadas em abas
  separadas do mesmo Chrome ao mesmo tempo (logar na 2ª derruba a 1ª em
  todas as abas, inclusive quebrando locks de edição pendentes).
- Contas de teste conhecidas: `p0046863` (COTRI/GABINETE, múltiplos
  perfis), `t0023093` (magistrado), `m2415248` / FERNANDO CALDEIRA BRANT
  (magistrado, relator do processo de teste da Sessão de Julgamento),
  **`P0125581` / RANYER SEGAL PONTES** (GABINETE — conta usada depois que
  `p0046863` ficou bloqueada uma vez). Senha padrão de homologação:
  `Senha123`. Vogais do quórum de teste: CHRISTIAN GOMES LIMA e LILIAN
  MACIEL SANTOS (Presidente) — **sigla de login deles ainda não
  descoberta**, precisa achar no Cadastro de Usuários (exige login
  prévio) ou perguntar ao usuário.

## Pendências reais (nada escondido)

1. **Votação dos vogais** — bloqueada por 2 motivos reais: (a) precisa
   login manual de um vogal (Christian ou Lilian), nunca feito por mim;
   (b) a interação real é drag-and-drop, nunca observada ao vivo, não
   dá pra automatizar às cegas com segurança.
2. **Lançar resultado por item** (`ItemResultado.php`, antes de poder
   "Encerrar Ata") — lead encontrado, não mapeado a fundo.
3. **Encerrar Ata** (fechar sessão) — código escrito, nunca testado.
4. **Passo 9** (assinatura real pós-julgamento) e **Passo 10**
   (intimação final) — só descritos no rito, nada mapeado ao vivo.
5. **Disponibilizar minutas** — botão achado, nunca clicado.
6. **Incluir em Pauta/Mesa** encadeado com criação de minutas (Passo 7
   completo) — função já existe (`executar_incluir_pauta_mesa`), falta
   encadear.
7. **Mapear todos os 11 tipos de Julgamento além de "Mérito"** — pedido
   explícito do usuário ("AURA TEM QUE SER CAPAZ DE FAZER QUALQUER COISA
   DENTRO DO EPROC"), fora de escopo até agora.

## Avisos de segurança do usuário (aplicam a todo trabalho autônomo)

- "o eproc é um sistema jurídico, se der qualquer aviso na tela do
  chrome tire print e leia".
- "o chrome não pode simplesmente ser fechado, tem que encerrar sessão".
