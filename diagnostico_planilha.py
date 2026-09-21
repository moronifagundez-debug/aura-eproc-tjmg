"""Diagnóstico de gravação na planilha do AURA.

NÃO altera o comportamento do app. Só mostra a verdade sobre a configuração
e faz UMA gravação de teste (uma linha claramente marcada, que você pode
apagar depois).

Como usar (na pasta do projeto, com aura_credentials.json e aura_sheets.json
ao lado):

    python diagnostico_planilha.py

O que ele responde:
  - está rodando como .exe (congelado) ou como código-fonte?
  - em quais pastas procurou a config e onde ACHOU cada arquivo?
  - qual SPREADSHEET_ID está realmente sendo usado (o seu ou o antigo padrão)?
  - qual a conta de serviço (client_email)?
  - quantas linhas existem hoje?
  - consegue GRAVAR? (grava uma linha de teste e confere se ela aparece)
  - se falhar, mostra o erro COMPLETO (inclui o caso de armazenamento cheio).
"""

import os
import sys
import json
import traceback

# Garante que o pacote de shared/ seja importável, igual o aura.py faz.
_RAIZ = os.path.dirname(os.path.abspath(__file__))
for _sub in ("shared", "integrations"):
    _p = os.path.join(_RAIZ, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aura_db as db  # noqa: E402


def _linha(titulo=""):
    print("=" * 64)
    if titulo:
        print(titulo)
        print("-" * 64)


_linha("1) ONDE O PROGRAMA PROCURA A CONFIGURAÇÃO")
print("Rodando como .exe (congelado)? ", hasattr(sys, "_MEIPASS"))
print("Pastas de config (na ordem de prioridade):")
for d in db._dirs_config():
    print("   -", d)
print()
print("aura_credentials.json -> ", db.CREDENTIALS_FILE)
print("   existe? ", os.path.exists(db.CREDENTIALS_FILE))
_sheets = db._achar_config("aura_sheets.json")
print("aura_sheets.json      -> ", _sheets)
print("   existe? ", os.path.exists(_sheets))

_linha("2) QUAL PLANILHA ESTÁ SENDO USADA")
print("SPREADSHEET_ID (operacional):", db.SPREADSHEET_ID or "(vazio)")
if not db.SPREADSHEET_ID:
    print("   >>> ATENÇÃO: nenhum ID operacional configurado. O aura_sheets.json NÃO")
    print("       foi encontrado — coloque-o ao lado do AURA.exe (ou na raiz).")
else:
    print("   (ok: ID vindo do aura_sheets.json)")
print("SPREADSHEET_ID_COMPETENCIAS:", db.SPREADSHEET_ID_COMPETENCIAS)
try:
    _creds = json.load(open(db.CREDENTIALS_FILE, encoding="utf-8"))
    print("Conta de serviço (client_email):", _creds.get("client_email"))
    print("   >>> A planilha PRECISA estar compartilhada como Editor com esse e-mail.")
except Exception as e:
    print("Não consegui ler o client_email:", e)

_linha("3) TESTE DE GRAVAÇÃO")
try:
    antes = db.ler_processos_ajuizados()
    print("Linhas em processos_ajuizados ANTES:", len(antes))
    print("Gravando uma linha de TESTE...")
    db.gravar_processo_ajuizado(
        data="TESTE_DIAGNOSTICO",
        classe="TESTE",
        magistrado="TESTE",
        processo="0000000-00.0000.0.00.0000",
        chave="TESTE",
        aviso="linha de teste do diagnostico - pode apagar",
        competencia="TESTE",
        assunto="TESTE",
        tipo_redistribuicao="TESTE",
    )
    depois = db.ler_processos_ajuizados()
    print("Linhas DEPOIS:", len(depois))
    if len(depois) > len(antes):
        print()
        print("✅ GRAVOU COM SUCESSO! A linha de TESTE deve aparecer na planilha")
        print("   de ID:", db.SPREADSHEET_ID)
        print("   Abra ESSA planilha e confira. Pode apagar a linha de teste.")
        print("   Se a linha NÃO aparece na planilha que você está olhando, é")
        print("   porque o ID acima aponta para OUTRA planilha.")
    else:
        print()
        print("⚠ A contagem não aumentou — a gravação não teve efeito visível.")
except Exception:
    print()
    print("❌ ERRO ao gravar (esta é a causa real que estava escondida):")
    traceback.print_exc()
    print()
    print("Dicas de leitura do erro acima:")
    print("  - 'storageQuotaExceeded' / 'quota' / 'insufficient' -> o Google Drive")
    print("    da conta dona da planilha está SEM ESPAÇO e bloqueia edições.")
    print("  - 403 / 'permission' -> a planilha não está compartilhada como Editor")
    print("    com a conta de serviço (client_email acima).")
    print("  - 404 / 'not found' -> o SPREADSHEET_ID está errado.")

_linha()
print("Fim do diagnóstico.")
