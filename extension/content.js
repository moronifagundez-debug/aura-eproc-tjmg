// AURA Sessão de Julgamento — content script.
//
// So faz algo na tela "Painel da Sessao de Julgamento" (acao=
// sessao_julgamento_exibir_painel). NÃO clica em nada -- as abas do painel
// (Sessão/Pauta/Mesa/Privados-Internos e as sub-abas internas "Com
// apontamentos"/"Todos") so carregam a tabela via AJAX quando recebem um
// clique de verdade (evento confiavel do sistema operacional); um clique
// disparado por JS (mesmo simulando mousedown+mouseup+click) e' ignorado
// pelo framework -- o mesmo problema ja documentado no AURA Eventos Câmara
// Cível (autocomplete que so responde a "clique nativo, nao JS"). Por isso
// quem revela as abas e' o launcher Python/Selenium (clique nativo via
// WebDriver, que o Chrome trata como confiavel) -- este script so observa
// o DOM (MutationObserver) e extrai o que ja estiver visivel, de qualquer
// aba que o Selenium (ou um consultor navegando manualmente) tenha revelado.
//
// Cada mudanca de estado vira um evento: logado no console com prefixo
// estavel, mandado para o background (badge/notificacao) e guardado no
// historico visivel no popup. TAMBEM espelhado em localStorage da propria
// pagina do eproc (chave CHAVE_LOCALSTORAGE_EVENTOS) -- confirmado ao vivo
// que driver.get_log('browser') do Selenium NAO captura console.log do
// content script (roda em isolated world, o CDP Log domain que alimenta
// get_log so' pega o world principal da pagina); localStorage, ao contrario
// de chrome.storage, e' compartilhado entre o isolated world do content
// script e o main world da pagina, entao o launcher Python consegue ler
// direto via driver.execute_script("return localStorage.getItem(...)")
// sem precisar descobrir o id da extensao nem abrir aba extra.
const PREFIXO_EVENTO = "[AURA-EVENTO]";
const PREFIXO_CICLO = "[AURA-CICLO]";
const CHAVE_LOCALSTORAGE_EVENTOS = "__aura_sj_eventos__";
const LIMITE_EVENTOS_LOCALSTORAGE = 200;

function emitirEvento(evento) {
    console.log(`${PREFIXO_EVENTO} ${JSON.stringify(evento)}`);
    chrome.runtime.sendMessage({ tipo: "evento_sessao_julgamento", evento }).catch(() => {});
    try {
        const atual = JSON.parse(localStorage.getItem(CHAVE_LOCALSTORAGE_EVENTOS) || "[]");
        atual.push({ ...evento, recebido_em: Date.now() });
        localStorage.setItem(
            CHAVE_LOCALSTORAGE_EVENTOS,
            JSON.stringify(atual.slice(-LIMITE_EVENTOS_LOCALSTORAGE))
        );
    } catch (e) {
        // localStorage pode falhar (quota, modo privado) -- nao critico, o
        // chrome.storage/sendMessage acima ja cobre o caminho principal.
    }
}

// IDs dos LINKS de cada aba monitorada (nao dos paineis de conteudo -- a
// tabela de dados NAO fica dentro do painel de cada aba, e sim numa area
// unica e compartilhada #area-principal-painel/#tabela-itens-sj, reaproveitada
// pra qualquer aba que estiver ativa no momento; confirmado inspecionando o
// DOM ao vivo). Por isso a unica forma confiavel de saber de qual aba veio a
// tabela atual e' checar qual desses links tem a classe "active" agora --
// nao dá pra subir o DOM a partir da linha, ela nunca fica dentro do painel.
//
// So Pauta e Mesa -- Sessao e Privados/Internos ficam de fora por decisao
// explicita (Sessao tem categorias/sub-abas aninhadas que poluem o sinal;
// Privados/Internos nao entrou no pedido de foco).
const IDS_LINK_POR_ABA = {
    "tab-pauta": "Pauta",
    "tab-mesa": "Mesa",
};

const RE_NUM_PROCESSO = /\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}/;
const DEBOUNCE_MS = 800; // espera a "poeira" da AJAX assentar antes de extrair
const CICLO_HEARTBEAT_MS = 30000; // varredura de seguranca mesmo sem mutacao nova

// Valores conhecidos da coluna "Tipo" -- usados para achar as colunas por
// CONTEUDO em vez de indice fixo. As linhas da tabela tem uma celula extra
// no inicio (numero da linha/checkbox de selecao) que nao aparece no
// cabecalho visivel, entao qualquer indice fixo fica desalinhado; procurar
// pelo texto de cada celula e' mais resistente a isso e a diferencas de
// layout entre abas (Sessao/Pauta/Mesa tem colunas ligeiramente diferentes).
const TIPOS_CONHECIDOS = ["Pauta", "Mesa", "Sessão", "Privado", "Interno"];

function ehPaginaDoPainel() {
    const params = new URLSearchParams(location.search);
    return params.get("acao") === "sessao_julgamento_exibir_painel";
}

function extrairInfoSessao() {
    // Cabecalho da propria sessao (nao de um processo especifico) -- ex:
    // "Sessão Ordinária Presencial - 05ª CÂMARA CÍVEL - 06/08/2026 (Pauta
    // aberta)". O status entre parenteses no final e' o dado mais critico
    // aqui: e' o que marca a transicao de pre-sessao pra pos-sessao (ex:
    // "Pauta aberta"/"Sessão virtual aberta" -> "Ata encerrada").
    const header = document.getElementById("cabecalho-painel-sj");
    if (!header) return null;
    const textoCompleto = header.innerText.replace(/\s+/g, " ").trim();
    if (!textoCompleto) return null;
    // Os icones de acao do cabecalho (edit, wifi_tethering, etc.) vem colados
    // no texto DEPOIS do "(status)" -- por isso pega o ULTIMO parenteses da
    // string, nao exige que esteja no final (o status nunca tem parenteses
    // aninhados dentro dele nos casos observados).
    const statusMatches = [...textoCompleto.matchAll(/\(([^)]+)\)/g)];
    const statusMatch = statusMatches.length ? statusMatches[statusMatches.length - 1] : null;
    return {
        texto_completo: textoCompleto,
        tipo_sessao: textoCompleto.split(" - ")[0].trim(),
        status_sessao: statusMatch ? statusMatch[1].trim() : "",
    };
}

function abaAtivaAgora() {
    // A tabela de dados e' compartilhada entre todas as abas -- a unica
    // forma de saber de qual aba os dados atuais vieram e' checar qual
    // link de aba tem a classe "active" agora mesmo.
    for (const [id, nome] of Object.entries(IDS_LINK_POR_ABA)) {
        const el = document.getElementById(id);
        if (el && el.classList.contains("active")) return nome;
    }
    return "desconhecida";
}

function extrairLinha(tr) {
    const textoLinha = (tr.innerText || "").trim();
    const matchProcesso = textoLinha.match(RE_NUM_PROCESSO);
    if (!matchProcesso) return null;

    const tds = Array.from(tr.querySelectorAll("td"));

    // Acha as colunas pelo CONTEUDO (nao pelo indice -- a linha real tem uma
    // celula a mais no inicio, numero/checkbox, que desalinha qualquer
    // indice fixo). "Tipo" tem um valor conhecido; magistrado e' a celula
    // logo antes dela.
    const idxTipo = tds.findIndex((td) => TIPOS_CONHECIDOS.includes(td.innerText.trim()));
    const tdTipo = idxTipo >= 0 ? tds[idxTipo] : null;
    const tdMagistrado = idxTipo > 0 ? tds[idxTipo - 1] : null;
    const tdProcesso = tds.find((td) => RE_NUM_PROCESSO.test(td.innerText));
    const tdComposicao = tds.find((td) => /^\d+\s*-\s*\(/.test(td.innerText.trim()));
    const tdJulgamento = tds.find((td) => /Status anterior:/i.test(td.innerText));

    const texto = (td) => (td ? td.innerText.replace(/\s+/g, " ").trim() : "");

    const julgamentoTexto = tdJulgamento ? tdJulgamento.innerText : "";
    const linhasJulgamento = julgamentoTexto.split("\n").map((s) => s.trim()).filter(Boolean);

    // "Composição anterior:" aparece dentro da mesma celula de julgamento
    // quando o processo teve pedido de vista/mudanca de relator -- lista os
    // magistrados que compunham o colegiado antes da troca. Fica entre a
    // linha "Composição anterior:" e a ultima linha (que e' sempre o tipo de
    // julgamento, ex: "Mérito").
    const idxComposicaoAnterior = linhasJulgamento.findIndex((l) => /^Composição anterior:/i.test(l));
    const composicaoAnterior = idxComposicaoAnterior >= 0
        ? linhasJulgamento.slice(idxComposicaoAnterior, linhasJulgamento.length - 1)
            .join(" ").replace(/^Composição anterior:\s*/i, "").trim()
        : "";

    const icones = Array.from(tr.querySelectorAll("i.material-icons")).map((i) => i.textContent.trim());

    // Guarda o texto bruto de TODAS as celulas tambem -- "nao deixe passar
    // nada": qualquer coisa que os campos estruturados acima nao cobrirem
    // (ex: Minuta/RELATÓRIO, Pedidos) ainda fica visivel aqui.
    const celulasBrutas = tds.map((td) => td.innerText.replace(/\s+/g, " ").trim());
    const minuta = celulasBrutas[celulasBrutas.length - 1] || "";

    // Contagem de Destaques: numero dentro do badge/circulo sobre o icone de
    // bandeira na celula de Destaques -- exclui a celula do processo, que
    // tambem tem um "badge" (o selo da classe processual, ex: "AC"/"PET"),
    // senao a contagem vem sempre errada (pega o texto da classe).
    const celulasSemProcesso = tdProcesso ? tds.filter((td) => td !== tdProcesso) : tds;
    let destaquesCount = 0;
    for (const td of celulasSemProcesso) {
        const badge = td.querySelector(".badge, [class*='badge']");
        const badgeTexto = badge ? badge.textContent.trim() : "";
        if (/^\d+$/.test(badgeTexto)) {
            destaquesCount = parseInt(badgeTexto, 10);
            break;
        }
    }

    // Tamanho do colegiado: conta os assentos listados dentro do parenteses
    // da composicao (ex: "3 - (5CACIV-A1, 5CACIV-A2, 5CACIV-A4)" -> 3).
    // Usado pra saber se a votacao ja fechou ou ainda falta gente votar.
    const composicaoTexto = texto(tdComposicao);
    const matchAssentos = composicaoTexto.match(/\(([^)]+)\)/);
    const tamanhoComposicao = matchAssentos
        ? matchAssentos[1].split(",").map((s) => s.trim()).filter(Boolean).length
        : 0;

    const votosFavoraveis = icones.filter((i) => i === "thumb_up").length;
    const votosContrarios = icones.filter((i) => i === "thumb_down").length;
    const votosRegistrados = votosFavoraveis + votosContrarios;

    // "Incluído" = ainda na pauta aguardando julgamento (estagio ativo).
    // Qualquer outro status (Retirado, Excluído, Julgado, etc.) significa
    // que o processo ja saiu do ciclo de votacao corrente.
    const aindaAtivo = /^Inclu[ií]do$/i.test((linhasJulgamento[0] || "").trim());
    const votacaoPendente = aindaAtivo && tamanhoComposicao > 0 && votosRegistrados < tamanhoComposicao;

    return {
        processo: matchProcesso[0],
        magistrado: texto(tdMagistrado),
        tipo: texto(tdTipo),
        processo_classe_assunto: texto(tdProcesso),
        composicao: composicaoTexto,
        composicao_anterior: composicaoAnterior,
        tamanho_composicao: tamanhoComposicao,
        julgamento_status: linhasJulgamento[0] || "",
        julgamento_status_anterior: (julgamentoTexto.match(/Status anterior:\s*(.+)/) || [])[1] || "",
        julgamento_tipo: linhasJulgamento[linhasJulgamento.length - 1] || "",
        sigilo: /Segredo de Justiça/i.test(textoLinha),
        vista_mp: /Vista Ministério Público/i.test(textoLinha),
        divergencia: icones.includes("warning"),
        adiado_ou_retirado_marcador: icones.includes("grade"),
        votos_favoraveis: votosFavoraveis,
        votos_contrarios: votosContrarios,
        votacao_pendente: votacaoPendente,
        destaques: destaquesCount,
        minuta: minuta,
        celulas_brutas: celulasBrutas,
        sustentacoes: [],
    };
}

// Sustentacao Oral nao vem na linha do processo -- fica numa linha auxiliar
// separada logo abaixo (classe "tr-subnivel"), sem numero de processo, com
// uma ou mais entradas no formato:
// "Sustentação Oral: <advogado> representante de <parte> - <polo> - (<status de presença>)"
const RE_SUSTENTACAO = /Sustentação Oral:\s*(.+?)\s+representante de\s+(.+?)\s*-\s*([^-()]+?)\s*-\s*\(([^)]+)\)/gi;

function extrairSustentacoes(texto) {
    const resultados = [];
    let m;
    RE_SUSTENTACAO.lastIndex = 0;
    while ((m = RE_SUSTENTACAO.exec(texto)) !== null) {
        resultados.push({
            advogado: m[1].trim(),
            parte: m[2].trim(),
            polo: m[3].trim(),
            presenca: m[4].trim(),
        });
    }
    return resultados;
}

// Modal "Histórico dos Julgamentos do Processo" -- aberto pelo item
// "Histórico do julgamento" no menu de acoes (icone mais_vert/⋮) de cada
// linha da Pauta/Mesa. E' so' leitura (lista, sem botao de salvar/editar);
// quem abre e' sempre o Selenium com clique nativo (⋮ depois "Histórico do
// julgamento"), nunca este content script -- aqui so observamos se o modal
// aparecer no DOM. Ao contrario da tabela principal, essa tabela do modal
// tem exatamente 7 celulas por linha de dados (sem celula extra de
// numero/checkbox), entao indice fixo e' seguro aqui.
function extrairModalHistorico() {
    const modal = document.getElementById("modal-sessao-julgamento");
    if (!modal || !modal.classList.contains("show")) return null;

    const textoModal = modal.innerText.replace(/\s+/g, " ").trim();
    const matchProcesso = textoModal.match(RE_NUM_PROCESSO);
    if (!matchProcesso) return null;

    const tabela = modal.querySelector("table");
    if (!tabela) return null;

    const entradas = [];
    tabela.querySelectorAll("tbody tr").forEach((tr) => {
        const tds = Array.from(tr.querySelectorAll("td"));
        if (tds.length < 7) return; // linha de icones/acao, nao de dados
        const texto = (idx) => tds[idx].innerText.replace(/\s+/g, " ").trim();
        const julgamentoTexto = tds[5].innerText;
        const linhasJulgamento = julgamentoTexto.split("\n").map((s) => s.trim()).filter(Boolean);
        entradas.push({
            data_sessao: texto(0),
            orgao: texto(1),
            status_sessao: texto(2),
            tipo_seq: texto(3),
            magistrado: texto(4),
            julgamento_status: linhasJulgamento[0] || "",
            julgamento_status_anterior: (julgamentoTexto.match(/Status anterior:\s*(.+)/) || [])[1] || "",
            julgamento_tipo: linhasJulgamento[linhasJulgamento.length - 1] || "",
            minuta: texto(6),
        });
    });

    return { processo: matchProcesso[0], entradas };
}

// Mesmo magistrado aparecendo mais de uma vez com status "Incluído" (ativo/
// votando) no historico do MESMO processo -- sinal bruto, nao uma conclusao
// definitiva (pode ser um voto corrigido de proposito). Filosofia do
// projeto: "e' um sistema de ajuda, tudo pode ser importante" -- reportar o
// padrao e deixar o consultor julgar a relevancia.
function detectarVotoDuplicadoSuspeito(historico) {
    const porMagistrado = {};
    for (const e of historico.entradas) {
        if (!/inclu[ií]do/i.test(e.julgamento_status)) continue;
        porMagistrado[e.magistrado] = (porMagistrado[e.magistrado] || 0) + 1;
    }
    return Object.entries(porMagistrado)
        .filter(([, contagem]) => contagem > 1)
        .map(([magistrado, contagem]) => ({ magistrado, contagem }));
}

function extrairTabela(escopo) {
    const tabelas = (escopo || document).querySelectorAll("table");
    const itens = [];

    tabelas.forEach((tabela) => {
        let categoriaAtual = null;
        let ultimoItem = null;
        const linhas = tabela.querySelectorAll("tbody > tr");
        linhas.forEach((tr) => {
            const textoLinha = (tr.innerText || "").trim();
            const tds = tr.querySelectorAll("td");

            if (!RE_NUM_PROCESSO.test(textoLinha) && /\(\d+\)\s*$/.test(textoLinha) && tds.length <= 2) {
                categoriaAtual = textoLinha.replace(/\s+/g, " ").trim();
                return;
            }

            const item = extrairLinha(tr);
            if (item) {
                item.categoria = categoriaAtual;
                itens.push(item);
                ultimoItem = item;
                return;
            }

            // Linha auxiliar sem numero de processo (ex: "tr-subnivel" com
            // Sustentação Oral) -- pertence ao ultimo processo processado,
            // ja que sempre aparece logo abaixo dele na mesma tabela.
            if (ultimoItem && /Sustentação Oral:/i.test(textoLinha)) {
                ultimoItem.sustentacoes.push(...extrairSustentacoes(textoLinha));
            }
        });
    });
    return itens;
}

function varrerAbaAtual() {
    // So a aba atualmente ativa tem dados na tabela compartilhada -- entao
    // so faz sentido extrair "a fatia" dessa aba especifica por vez.
    const snapshot = {};
    for (const item of extrairTabela(document)) {
        snapshot[item.processo] = item;
    }
    return snapshot;
}

function compararSnapshots(anterior, atual, primeiraLeitura) {
    const eventos = [];
    const agora = new Date().toLocaleTimeString("pt-BR");

    // Na primeira leitura de uma aba (nunca vista antes nesta sessao do
    // navegador) nao existe "anterior" de verdade -- tratar cada processo
    // ja existente como "novo_item" faria parecer que eles estao surgindo
    // um a um, quando na real e' so' o carregamento inicial. Um unico
    // evento resume tudo; "novo_item" de verdade so' passa a disparar
    // depois dessa baseline estabelecida.
    if (primeiraLeitura) {
        const total = Object.keys(atual).length;
        const abaDoPrimeiro = total > 0 ? Object.values(atual)[0].aba_painel : null;
        eventos.push({
            hora: agora, processo: null, tipo_evento: "carregamento_inicial",
            mensagem: `Carregamento inicial da aba '${abaDoPrimeiro || "?"}': ${total} processo(s) encontrado(s).`,
        });
        return eventos;
    }

    for (const [processo, itemNovo] of Object.entries(atual)) {
        const itemAntigo = anterior[processo];
        if (!itemAntigo) {
            const sustTexto = itemNovo.sustentacoes && itemNovo.sustentacoes.length
                ? ` -- ${itemNovo.sustentacoes.length} pedido(s) de sustentação oral.`
                : "";
            eventos.push({
                hora: agora, processo, tipo_evento: "novo_item",
                mensagem: `Processo ${processo} apareceu em '${itemNovo.aba_painel}' (${itemNovo.categoria || "sem categoria"}).${sustTexto}`,
            });
            continue;
        }

        if (itemAntigo.votacao_pendente && !itemNovo.votacao_pendente) {
            eventos.push({
                hora: agora, processo, tipo_evento: "votacao_completa",
                mensagem: `Processo ${processo}: votação completa (${itemNovo.votos_favoraveis + itemNovo.votos_contrarios}/${itemNovo.tamanho_composicao} votos registrados).`,
            });
        }

        if (itemNovo.julgamento_status !== itemAntigo.julgamento_status) {
            eventos.push({
                hora: agora, processo, tipo_evento: "mudanca_status",
                mensagem: `Processo ${processo}: status mudou de '${itemAntigo.julgamento_status}' para '${itemNovo.julgamento_status}'.`,
            });
        }

        if (!itemAntigo.divergencia && itemNovo.divergencia) {
            eventos.push({
                hora: agora, processo, tipo_evento: "divergencia",
                mensagem: `Processo ${processo}: entrou em DIVERGÊNCIA no colegiado.`,
            });
        }

        if (itemNovo.composicao !== itemAntigo.composicao) {
            eventos.push({
                hora: agora, processo, tipo_evento: "mudanca_composicao",
                mensagem: `Processo ${processo}: composição do colegiado mudou de '${itemAntigo.composicao}' para '${itemNovo.composicao}'.`,
            });
        }

        const votosAntes = itemAntigo.votos_favoraveis + itemAntigo.votos_contrarios;
        const votosAgora = itemNovo.votos_favoraveis + itemNovo.votos_contrarios;
        if (votosAgora > votosAntes) {
            eventos.push({
                hora: agora, processo, tipo_evento: "novo_voto",
                mensagem: `Processo ${processo}: novo voto disponibilizado ao colegiado (${itemNovo.votos_favoraveis} a favor / ${itemNovo.votos_contrarios} contra).`,
            });
        }

        if (itemNovo.destaques !== itemAntigo.destaques) {
            eventos.push({
                hora: agora, processo, tipo_evento: "mudanca_destaques",
                mensagem: `Processo ${processo}: contagem de destaques mudou de ${itemAntigo.destaques} para ${itemNovo.destaques}.`,
            });
        }

        if (itemNovo.categoria !== itemAntigo.categoria) {
            eventos.push({
                hora: agora, processo, tipo_evento: "mudanca_categoria",
                mensagem: `Processo ${processo}: movido de '${itemAntigo.categoria}' para '${itemNovo.categoria}'.`,
            });
        }

        const sustAntes = itemAntigo.sustentacoes || [];
        const sustAgora = itemNovo.sustentacoes || [];
        if (sustAgora.length !== sustAntes.length) {
            eventos.push({
                hora: agora, processo, tipo_evento: "mudanca_sustentacao",
                mensagem: `Processo ${processo}: pedidos de sustentação oral mudaram de ${sustAntes.length} para ${sustAgora.length}.`,
            });
        }
        for (let i = 0; i < Math.min(sustAntes.length, sustAgora.length); i++) {
            if (sustAntes[i].presenca !== sustAgora[i].presenca) {
                eventos.push({
                    hora: agora, processo, tipo_evento: "sustentacao_presenca_atualizada",
                    mensagem: `Processo ${processo}: presença de ${sustAgora[i].advogado} (sustentação oral) mudou de '${sustAntes[i].presenca}' para '${sustAgora[i].presenca}'.`,
                });
            }
        }
    }

    for (const processo of Object.keys(anterior)) {
        if (!(processo in atual)) {
            eventos.push({
                hora: agora, processo, tipo_evento: "item_sumiu",
                mensagem: `Processo ${processo} não aparece mais no painel (pode ter saído da aba monitorada).`,
            });
        }
    }

    return eventos;
}

async function verificarModalHistorico() {
    const historico = extrairModalHistorico();
    if (!historico) return;

    const chave = "historico_julgamento_" + historico.processo;
    const armazenado = await chrome.storage.local.get(chave);
    const anterior = armazenado[chave] || null;
    const agora = new Date().toLocaleTimeString("pt-BR");

    if (!anterior || anterior.entradas.length !== historico.entradas.length) {
        console.log(`${PREFIXO_CICLO} ${JSON.stringify({
            historico_julgamento: historico.processo,
            total_entradas: historico.entradas.length,
        })}`);
    }

    const suspeitos = detectarVotoDuplicadoSuspeito(historico);
    for (const s of suspeitos) {
        const jaAvisado = anterior && detectarVotoDuplicadoSuspeito(anterior)
            .some((a) => a.magistrado === s.magistrado && a.contagem === s.contagem);
        if (jaAvisado) continue; // ja notificado nesse mesmo estado, nao repete
        const evento = {
            hora: agora,
            processo: historico.processo,
            tipo_evento: "voto_duplicado_suspeito",
            mensagem: `Processo ${historico.processo}: magistrado ${s.magistrado} aparece ${s.contagem}x com status "Incluído" no histórico de julgamento -- pode ser voto duplicado, confira.`,
        };
        emitirEvento(evento);
    }

    await chrome.storage.local.set({ [chave]: historico });
}

async function cicloDeVerificacao() {
    await verificarModalHistorico();

    const abaAtual = abaAtivaAgora();
    if (abaAtual === "desconhecida") {
        // Nenhuma aba conhecida esta marcada "active" agora -- provavelmente
        // um estado transitorio entre cliques (ex: overlay de carregamento).
        // Nao da pra atribuir os dados com confianca, entao pula este ciclo
        // em vez de arriscar rotular errado ou disparar item_sumiu a toa.
        return;
    }

    // Storage guarda um mapa por aba -- {aba: {processo: item}} -- porque a
    // tabela e' compartilhada entre as abas (so uma aba tem dados por vez).
    // Isso evita: (1) perder dados de abas ja reveladas quando o Selenium
    // troca de aba antes do debounce disparar, e (2) falso "item_sumiu"
    // para processos de OUTRAS abas so porque a aba atual nao os mostra.
    // "__infoSessao" guarda o cabecalho da sessao em si (tipo/status),
    // separado dos mapas por aba de processos.
    const chave = "snapshot_" + location.href.split("?")[0] + "_" + (new URLSearchParams(location.search).get("id_sessao_julgamento") || "sem_id");
    const armazenado = await chrome.storage.local.get(chave);
    const snapshotCompleto = armazenado[chave] || {};
    const primeiraLeituraDaAba = !(abaAtual in snapshotCompleto);
    const fatiaAnterior = snapshotCompleto[abaAtual] || {};

    const infoSessaoAnterior = snapshotCompleto.__infoSessao || null;
    const infoSessaoAtual = extrairInfoSessao();
    if (infoSessaoAtual) {
        if (infoSessaoAnterior && infoSessaoAnterior.status_sessao !== infoSessaoAtual.status_sessao) {
            const evento = {
                hora: new Date().toLocaleTimeString("pt-BR"),
                processo: null,
                tipo_evento: "mudanca_status_sessao",
                mensagem: `Status da sessão mudou de '${infoSessaoAnterior.status_sessao}' para '${infoSessaoAtual.status_sessao}' (${infoSessaoAtual.tipo_sessao}).`,
            };
            emitirEvento(evento);
        }
        snapshotCompleto.__infoSessao = infoSessaoAtual;
    }

    const fatiaAtual = varrerAbaAtual();
    for (const item of Object.values(fatiaAtual)) {
        item.aba_painel = abaAtual;
    }

    // So atualiza a fatia dessa aba se realmente ha algo extraido -- evita
    // sobrescrever uma fatia boa com uma vazia quando uma mutacao efemera
    // (ex: painel fechando/reabrindo) dispara o observer no meio do caminho.
    if (Object.keys(fatiaAtual).length === 0 && Object.keys(fatiaAnterior).length > 0) {
        return;
    }

    const resumoPorAba = {};
    const pendentesPorAba = {};
    const sustentacoesPorAba = {};
    for (const [aba, fatia] of Object.entries({ ...snapshotCompleto, [abaAtual]: fatiaAtual })) {
        if (aba === "__infoSessao") continue; // nao e' uma aba de processos, e' o cabecalho da sessao
        resumoPorAba[aba] = Object.keys(fatia).length;
        pendentesPorAba[aba] = Object.values(fatia).filter((item) => item.votacao_pendente).length;
        sustentacoesPorAba[aba] = Object.values(fatia).reduce(
            (soma, item) => soma + (item.sustentacoes ? item.sustentacoes.length : 0), 0
        );
    }
    console.log(`${PREFIXO_CICLO} ${JSON.stringify({
        url: location.href,
        aba_atual: abaAtual,
        resumo: resumoPorAba,
        aguardando_voto: pendentesPorAba,
        sustentacoes_orais: sustentacoesPorAba,
        tipo_sessao: infoSessaoAtual ? infoSessaoAtual.tipo_sessao : null,
        status_sessao: infoSessaoAtual ? infoSessaoAtual.status_sessao : null,
    })}`);

    const eventos = compararSnapshots(fatiaAnterior, fatiaAtual, primeiraLeituraDaAba);
    for (const evento of eventos) {
        emitirEvento(evento);
    }

    snapshotCompleto[abaAtual] = fatiaAtual;
    await chrome.storage.local.set({ [chave]: snapshotCompleto });
}

let _debounceTimer = null;
function agendarVerificacao() {
    if (_debounceTimer) clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(cicloDeVerificacao, DEBOUNCE_MS);
}

(function iniciar() {
    if (!ehPaginaDoPainel()) return;
    console.log(`${PREFIXO_CICLO} AURA Sessão de Julgamento (PRÉ-SESSÃO) ativo nesta página (modo observador -- não clica em nada, só extrai o que já está visível).`);

    const observador = new MutationObserver(() => agendarVerificacao());
    observador.observe(document.body, { childList: true, subtree: true, characterData: true });

    // Heartbeat: garante uma varredura periodica mesmo se nada mudar no DOM
    // (ex: sessao parada, sem novos votos) -- assim o launcher ve que o
    // ciclo continua rodando.
    setInterval(cicloDeVerificacao, CICLO_HEARTBEAT_MS);
    agendarVerificacao();
})();
