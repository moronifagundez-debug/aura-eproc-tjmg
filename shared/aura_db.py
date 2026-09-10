# ============================================================
#  aura_db.py  —  Banco de dados central AURA (Google Sheets)
#  CESUPE  |  Módulo compartilhado por todos os AURAs
# ============================================================
#
#  DEPENDÊNCIAS (apenas stdlib + requests + cryptography):
#    pip install requests cryptography
#
#  NÃO requer google-auth — compatível com Python 3.11, 3.12, 3.13
#
#  ARQUIVO DE CREDENCIAIS:
#    Coloque o JSON da service account na mesma pasta com o nome:
#        aura_credentials.json
#
#  PLANILHA:
#    ID: 1KUiDarIDVsFf4JWeOpUa_6iWl-5vJWM2uUVMkjecSVY
#    Abas: processos_ajuizados | historico_intermediario
# ============================================================

import os
import json
import time
import base64
import requests
from datetime import datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
_CRYPTO_OK = True

# ----------------------------------------------------------
#  CONFIGURAÇÃO
# ----------------------------------------------------------

SPREADSHEET_ID   = "1KUiDarIDVsFf4JWeOpUa_6iWl-5vJWM2uUVMkjecSVY"
ABA_PROCESSOS    = "processos_ajuizados"
ABA_INTERMEDIARIO = "historico_intermediario"

CABECALHO_PROCESSOS     = ["Data", "Classe", "Magistrado", "Processo", "Chave", "Aviso", "Competência"]
CABECALHO_INTERMEDIARIO = ["Data", "Processo", "Evento", "Tipodocumento", "Status", "Motivo"]

import sys as _sys
if hasattr(_sys, "_MEIPASS"):
    # Credenciais embutidas no bundle do executável
    _BASE_DIR = _sys._MEIPASS
    os.environ.setdefault(
        "REQUESTS_CA_BUNDLE",
        os.path.join(_sys._MEIPASS, "certifi", "cacert.pem"),
    )
elif os.environ.get("AURA_BASE_DIR"):
    # Subprocesso (auragabinete) lançado pelo AURA.exe — credenciais no _MEIPASS do pai
    _BASE_DIR = os.environ["AURA_BASE_DIR"]
else:
    # aura_credentials.json fica na raiz do projeto; este arquivo mora em
    # shared/, por isso sobe um nivel.
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(_BASE_DIR, "aura_credentials.json")

# Cache do token em memória (evita uma chamada OAuth a cada operação)
_token_cache = {"token": None, "expires_at": 0}


# ----------------------------------------------------------
#  AUTENTICAÇÃO JWT manual (sem google-auth)
# ----------------------------------------------------------

def _b64url(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _get_token() -> str:
    """Retorna Bearer token válido, usando cache em memória."""
    now = int(time.time())
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
        creds = json.load(f)

    header  = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}))
    payload = _b64url(json.dumps({
        "iss":   creds["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud":   creds["token_uri"],
        "exp":   now + 3600,
        "iat":   now,
    }))

    msg = f"{header}.{payload}".encode()
    pem = creds["private_key"].encode()
    key = serialization.load_pem_private_key(pem, password=None)
    sig = key.sign(msg, asym_padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{header}.{payload}.{_b64url(sig)}"

    resp = requests.post(creds["token_uri"], data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt,
    }, timeout=15)
    resp.raise_for_status()

    access_token = resp.json()["access_token"]
    _token_cache["token"]      = access_token
    _token_cache["expires_at"] = now + 3600
    return access_token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type":  "application/json",
    }


# ----------------------------------------------------------
#  FUNÇÕES INTERNAS DE BAIXO NÍVEL
# ----------------------------------------------------------

def _ler_aba(aba: str) -> list[list]:
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{aba}"
    )
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code in (400, 404):
        # Aba vazia ou não encontrada — retorna lista vazia sem erro
        return []
    resp.raise_for_status()
    return resp.json().get("values", [])


def _garantir_cabecalho(aba: str, cabecalho: list[str]):
    dados = _ler_aba(aba)
    if not dados:
        _append_linhas(aba, [cabecalho])


def _append_linhas(aba: str, linhas: list[list]):
    # Range explícito A1 é obrigatório para o append funcionar em abas vazias
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
        f"/values/{aba}!A1:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )
    resp = requests.post(url, headers=_headers(), json={"values": linhas}, timeout=15)
    resp.raise_for_status()


# ----------------------------------------------------------
#  API PÚBLICA — processos_ajuizados
# ----------------------------------------------------------

def ler_processos_ajuizados() -> list[dict]:
    """
    Retorna lista de dicts com todos os processos ajuizados.
    Chaves: Data, Classe, Magistrado, Processo, Chave, Aviso
    """
    linhas = _ler_aba(ABA_PROCESSOS)
    if len(linhas) < 2:
        return []
    cabecalho = linhas[0]
    return [
        dict(zip(cabecalho, linha + [""] * (len(cabecalho) - len(linha))))
        for linha in linhas[1:]
    ]


def gravar_processo_ajuizado(
    data: str,
    classe: str,
    magistrado: str,
    processo: str,
    chave: str,
    aviso: str = "",
    competencia: str = "",
):
    """Grava uma linha nova na aba processos_ajuizados."""
    _garantir_cabecalho(ABA_PROCESSOS, CABECALHO_PROCESSOS)
    _append_linhas(ABA_PROCESSOS, [[data, classe, magistrado, processo, chave, aviso, competencia]])


def processo_ja_ajuizado(processo: str) -> bool:
    """Verifica se um número de processo já existe (detecção de duplicatas)."""
    return any(r.get("Processo") == processo for r in ler_processos_ajuizados())


# ----------------------------------------------------------
#  API PÚBLICA — historico_intermediario
# ----------------------------------------------------------

def ler_historico_intermediario() -> list[dict]:
    """
    Retorna lista de dicts com todo o histórico do Peticionamento Intermediário.
    Chaves: Data, Processo, Evento, Tipodocumento, Status, Motivo
    """
    linhas = _ler_aba(ABA_INTERMEDIARIO)
    if len(linhas) < 2:
        return []
    cabecalho = linhas[0]
    return [
        dict(zip(cabecalho, linha + [""] * (len(cabecalho) - len(linha))))
        for linha in linhas[1:]
    ]


def gravar_historico_intermediario(
    processo: str,
    evento: str,
    tipodocumento: str,
    status: str,
    motivo: str = "",
    data: str = None,
):
    """Grava uma linha nova na aba historico_intermediario."""
    _garantir_cabecalho(ABA_INTERMEDIARIO, CABECALHO_INTERMEDIARIO)
    if data is None:
        data = datetime.now().strftime("%d/%m/%Y")
    _append_linhas(ABA_INTERMEDIARIO, [[data, processo, evento, tipodocumento, status, motivo]])


def intermediario_ja_executado(processo: str, evento: str) -> bool:
    """Verifica se processo+evento já foi executado com sucesso."""
    return any(
        r.get("Processo") == processo
        and r.get("Evento") == evento
        and r.get("Status") == "Sucesso"
        for r in ler_historico_intermediario()
    )


# ----------------------------------------------------------
#  UTILITÁRIO
# ----------------------------------------------------------

def inicializar_planilha():
    """Garante cabeçalhos nas duas abas. Chamar uma vez na inicialização."""
    _garantir_cabecalho(ABA_PROCESSOS, CABECALHO_PROCESSOS)
    _garantir_cabecalho(ABA_INTERMEDIARIO, CABECALHO_INTERMEDIARIO)



# ----------------------------------------------------------
#  PLANILHA DE COMPETÊNCIAS
# ----------------------------------------------------------

SPREADSHEET_ID_COMPETENCIAS = "19BgcXguj02yI5uthWW7TBj4v22da9EAl3ZmtOU6UEu8"

CABECALHO_COMPETENCIAS = [
    "AREA", "Classeprocessual", "tipojustica",
    "Numero de processo originario", "Tipodocumento",
    "Tipoautor", "Tiporeu", "Assunto"
]


def listar_abas_competencias() -> list[str]:
    """
    Retorna os nomes de todas as abas da planilha de competências.
    Cada aba = uma competência (ex: 'Primeira Seção Cível - ADV').
    """
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID_COMPETENCIAS}"
        f"?fields=sheets.properties.title"
    )
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    sheets = resp.json().get("sheets", [])
    return [s["properties"]["title"] for s in sheets]


def ler_competencia(nome_aba: str) -> list[dict]:
    """
    Lê todas as linhas de uma aba de competência.
    Retorna lista de dicts com as colunas da planilha.
    """
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID_COMPETENCIAS}"
        f"/values/{nome_aba}"
    )
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code in (400, 404):
        return []
    resp.raise_for_status()
    linhas = resp.json().get("values", [])
    if len(linhas) < 2:
        return []
    cabecalho = linhas[0]
    return [
        dict(zip(cabecalho, linha + [""] * (len(cabecalho) - len(linha))))
        for linha in linhas[1:]
        if any(str(c).strip() for c in linha)
    ]

# ----------------------------------------------------------
#  TESTE RÁPIDO  →  python aura_db.py
# ----------------------------------------------------------

if __name__ == "__main__":
    print("Testando conexão com Google Sheets...")
    try:
        inicializar_planilha()
        print("✓ Cabeçalhos verificados")

        processos = ler_processos_ajuizados()
        print(f"✓ processos_ajuizados: {len(processos)} registro(s)")

        historico = ler_historico_intermediario()
        print(f"✓ historico_intermediario: {len(historico)} registro(s)")

        abas = listar_abas_competencias()
        print(f"✓ competencias: {len(abas)} aba(s) — {abas[:3]}")

        print("\nConexão OK. aura_db pronto para uso.")
    except Exception as e:
        print(f"✗ Erro: {e}")