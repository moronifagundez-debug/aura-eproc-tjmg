// AURA — bridge injetado no MUNDO PRINCIPAL da página (world: "MAIN", document_start).
// Roda no mesmo contexto JS da própria página eproc — por isso consegue enxergar
// CKEDITOR/jQuery e sobrescrever window.alert/confirm antes de qualquer script do eproc rodar.
//
// Fase atual: Milestone 0 (spikes de risco). Ver plano em
// C:\Users\Penam\.claude\plans\stateful-drifting-pearl.md
//
// Uso manual no DevTools (depois de recarregar a extensão e a página):
//   window.__auraBridge.checkAlertOverrideActive()
//   window.__auraBridge.checkCkEditor()

(function () {
  const LOG = (...args) => console.log("[AURA-BRIDGE]", ...args);

  const _alertOriginal = window.alert;
  const _confirmOriginal = window.confirm;
  let _overrideInstaladoEm = Date.now();

  function relayParaMundoIsolado(tipo, texto) {
    window.postMessage({ __aura: true, tipo, texto, quando: Date.now() }, "*");
  }

  // Espelha o comportamento de `_tratar_alert` (auragabinete.py) — aceita
  // incondicionalmente, mas registra o texto para a decisão humana acontecer
  // depois, na UI da extensão (não no dialog nativo, que bloqueia tudo).
  window.alert = function (msg) {
    LOG("alert() interceptado:", msg);
    relayParaMundoIsolado("alert_interceptado", msg);
    return undefined;
  };

  window.confirm = function (msg) {
    LOG("confirm() interceptado (auto-aceito):", msg);
    relayParaMundoIsolado("confirm_interceptado", msg);
    return true;
  };

  LOG("override de alert/confirm instalado em", new Date(_overrideInstaladoEm).toISOString());

  window.__auraBridge = {
    // Spike (c): prova que o override venceu a corrida contra os scripts do eproc.
    checkAlertOverrideActive() {
      const ok = window.alert !== _alertOriginal && window.confirm !== _confirmOriginal;
      LOG("checkAlertOverrideActive ->", ok, "(instalado em", new Date(_overrideInstaladoEm).toISOString() + ")");
      return ok;
    },

    // Spike (b): CKEDITOR.instances é alcançável a partir do world MAIN?
    checkCkEditor() {
      if (typeof CKEDITOR === "undefined") {
        LOG("checkCkEditor -> CKEDITOR não existe nesta página");
        return null;
      }
      const instancias = Object.keys(CKEDITOR.instances || {}).map((id) => {
        const ed = CKEDITOR.instances[id];
        let tamanhoDados = -1;
        try {
          tamanhoDados = (ed.getData() || "").length;
        } catch (e) {
          tamanhoDados = -1;
        }
        return {
          id,
          status: ed.status,
          tamanhoDados,
        };
      });
      LOG("checkCkEditor -> instâncias encontradas:", instancias);
      return instancias;
    },

    // Usado nos marcos 1+ para de fato escrever no editor (não é o teste do spike,
    // é a implementação real que o spike valida ser viável).
    setCkEditorData(instanceId, texto) {
      if (typeof CKEDITOR === "undefined" || !CKEDITOR.instances[instanceId]) {
        LOG("setCkEditorData -> instância não encontrada:", instanceId);
        return false;
      }
      CKEDITOR.instances[instanceId].setData(texto);
      LOG("setCkEditorData -> ok em", instanceId);
      return true;
    },
  };
})();
