// AURA Sessão de Julgamento — background service worker.
//
// Recebe eventos do content script, guarda um historico (limitado) em
// chrome.storage.local para o popup exibir, atualiza o badge da extensao e
// dispara notificacao do sistema para eventos que merecem atencao imediata
// do consultor (divergencia e novo voto) -- os demais ficam so no historico.

const CHAVE_HISTORICO = "historico_eventos";
const LIMITE_HISTORICO = 200;
// Filosofia do projeto: e' um sistema de ajuda pro consultor, nao um
// classificador de anomalias -- na duvida, notifica. "mudanca_status_sessao"
// e' especialmente critico: marca a transicao de pre-sessao pra pos-sessao
// (ex: "Pauta aberta" -> "Ata encerrada").
const TIPOS_NOTIFICAVEIS = new Set([
    "divergencia",
    "novo_voto",
    "mudanca_status_sessao",
    "sustentacao_presenca_atualizada",
    "mudanca_composicao",
]);

async function registrarEvento(evento) {
    const { [CHAVE_HISTORICO]: historicoAtual = [] } = await chrome.storage.local.get(CHAVE_HISTORICO);
    const novoHistorico = [{ ...evento, recebido_em: Date.now() }, ...historicoAtual].slice(0, LIMITE_HISTORICO);
    await chrome.storage.local.set({ [CHAVE_HISTORICO]: novoHistorico });

    const pendentes = novoHistorico.filter((e) => TIPOS_NOTIFICAVEIS.has(e.tipo_evento)).length;
    chrome.action.setBadgeText({ text: pendentes > 0 ? String(Math.min(pendentes, 99)) : "" });
    chrome.action.setBadgeBackgroundColor({ color: "#e74c3c" });

    if (TIPOS_NOTIFICAVEIS.has(evento.tipo_evento)) {
        chrome.notifications.create({
            type: "basic",
            iconUrl: "icon128.png",
            title: "AURA Sessão de Julgamento — Pré-sessão",
            message: evento.mensagem,
            priority: 2,
        }).catch(() => {
            // notifications.create pode falhar sem icone valido/em modo headless -- nao critico.
        });
    }
}

chrome.runtime.onMessage.addListener((mensagem) => {
    if (mensagem && mensagem.tipo === "evento_sessao_julgamento" && mensagem.evento) {
        registrarEvento(mensagem.evento);
    }
});
