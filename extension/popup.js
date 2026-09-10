const CHAVE_HISTORICO = "historico_eventos";

function formatarEvento(evento) {
    const div = document.createElement("div");
    div.className = "evento " + (evento.tipo_evento || "");
    const hora = document.createElement("div");
    hora.className = "hora";
    hora.textContent = `${evento.hora || ""} · ${evento.tipo_evento || ""}`;
    const msg = document.createElement("div");
    msg.textContent = evento.mensagem || "";
    div.appendChild(hora);
    div.appendChild(msg);
    return div;
}

async function carregar() {
    const { [CHAVE_HISTORICO]: historico = [] } = await chrome.storage.local.get(CHAVE_HISTORICO);
    const lista = document.getElementById("lista");
    lista.innerHTML = "";
    if (historico.length === 0) {
        lista.innerHTML = '<div class="vazio">Nenhum evento ainda.</div>';
        return;
    }
    for (const evento of historico) {
        lista.appendChild(formatarEvento(evento));
    }
    chrome.action.setBadgeText({ text: "" });
}

document.addEventListener("DOMContentLoaded", carregar);
