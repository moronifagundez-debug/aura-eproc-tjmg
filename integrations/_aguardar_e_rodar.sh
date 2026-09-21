#!/bin/bash
# Espera o eproc2g-hml voltar a responder (esta indisponivel agora, confirmado
# via curl direto) e so entao dispara a cadeia completa. Loga tudo no mesmo
# arquivo de log da execucao. Limite de espera: ~5h (60 tentativas x 5min).
set -u
URL="https://eproc2g-hml.tjmg.jus.br/eproc/"
LOG="/c/Users/Penam/.aura_eventoscamaracivel/execucao_overnight.log"
MAX_TENTATIVAS=60

echo "[$(date '+%H:%M:%S')] Servidor indisponivel no momento -- aguardando ficar online (checando a cada 5min, ate ${MAX_TENTATIVAS}x)..." >> "$LOG"

tentativa=0
while [ "$tentativa" -lt "$MAX_TENTATIVAS" ]; do
    corpo=$(curl -sL --max-time 20 "$URL" 2>/dev/null)
    if echo "$corpo" | grep -q "txtUsuario"; then
        echo "[$(date '+%H:%M:%S')] Formulario de login detectado na tentativa $((tentativa+1)) -- iniciando execucao." >> "$LOG"
        break
    fi
    tentativa=$((tentativa+1))
    if echo "$corpo" | grep -qi "server_error\|erro interno\|indispon"; then
        motivo="pagina de erro do servidor"
    elif [ -z "$corpo" ]; then
        motivo="sem resposta"
    else
        motivo="pagina sem formulario de login"
    fi
    echo "[$(date '+%H:%M:%S')] Tentativa $tentativa/${MAX_TENTATIVAS}: ainda indisponivel ($motivo)." >> "$LOG"
    sleep 300
done

if [ "$tentativa" -ge "$MAX_TENTATIVAS" ]; then
    echo "[$(date '+%H:%M:%S')] [ERRO] Servidor continuou indisponivel apos ${MAX_TENTATIVAS} tentativas (~5h). Desistindo." >> "$LOG"
    exit 3
fi

cd "/c/Users/Penam/OneDrive/Área de Trabalho/Aura Principal"
python _run_overnight_eventoscamaracivel.py >> "$LOG" 2>&1
