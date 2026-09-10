// AURA — diagnósticos do Milestone 0 (spikes de risco), mundo ISOLADO do content script.
// Ver plano em C:\Users\Penam\.claude\plans\stateful-drifting-pearl.md
//
// IMPORTANTE no DevTools: este script roda no mundo isolado da extensão, não no
// mundo da página. No console, troque o contexto (dropdown "top" no topo do
// painel Console) para algo como "AURA Sessão de Julgamento" antes de chamar
// window.__auraSpike.*  — __auraBridge (main_world_bridge.js) é o contrário,
// esse sim aparece direto no contexto "top" porque roda no mundo principal.
//
// Uso manual:
//   __auraSpike.testSyntheticClick('#123456_anchor')       // spike (a)
//   __auraSpike.watchFileInput("input[type='file']")        // spike (d)

(function () {
  const LOG = (...args) => console.log("[AURA-SPIKE]", ...args);

  window.addEventListener("message", (event) => {
    if (!event.data || !event.data.__aura) return;
    LOG("relay do main_world_bridge:", event.data.tipo, "->", event.data.texto);
  });

  window.__auraSpike = {
    // Spike (a): clique disparado por JS é aceito pelo widget (mesma dúvida já
    // levantada nos comentários de content.js sobre cliques "trusted" no eproc).
    // Não dá pra provar sucesso automaticamente (depende de reação visual da
    // página) — o teste é: rodar isto e checar visualmente se a UI reagiu como
    // reagiria a um clique de mouse real.
    testSyntheticClick(selector) {
      const el = document.querySelector(selector);
      if (!el) {
        LOG("testSyntheticClick -> elemento não encontrado:", selector);
        return false;
      }
      LOG("testSyntheticClick -> disparando click sintético em", selector, el);
      const evt = new MouseEvent("click", { bubbles: true, cancelable: true, view: window });
      const aceitou = el.dispatchEvent(evt);
      LOG("testSyntheticClick -> dispatchEvent retornou", aceitou, "— confira visualmente se a página reagiu (ex: aba trocou, dropdown abriu, resultado foi selecionado)");
      return aceitou;
    },

    // Spike (d): um listener no mundo isolado enxerga um `change` real disparado
    // pelo usuário ao escolher um arquivo no picker nativo?
    watchFileInput(selector) {
      const el = document.querySelector(selector);
      if (!el) {
        LOG("watchFileInput -> elemento não encontrado:", selector);
        return false;
      }
      LOG("watchFileInput -> escutando 'change' em", selector, "— agora selecione um arquivo manualmente no picker nativo");
      el.addEventListener(
        "change",
        () => {
          LOG("watchFileInput -> change recebido! arquivos:", el.files && el.files.length);
        },
        { once: true }
      );
      return true;
    },

    // Spike (c), complemento: confirma pelo lado isolado que o override do
    // mundo principal está de fato instalado (roda checkAlertOverrideActive lá).
    checkAlertOverride() {
      LOG("checkAlertOverride -> chame window.__auraBridge.checkAlertOverrideActive() no contexto 'top' do console");
    },
  };

  LOG("spike_diagnostics carregado em", location.href);
})();
