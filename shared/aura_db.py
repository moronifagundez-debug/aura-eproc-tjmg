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
#    ID: embutido no código (aura_sheets.json é override opcional)
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

# IDs padrão EMBUTIDOS (Forma B): o .exe já nasce apontando para as planilhas
# corretas, sem precisar de nenhum arquivo junto. O aura_sheets.json continua
# sendo um OVERRIDE opcional — se existir (ao lado do .exe ou na raiz do
# projeto), os IDs dele têm PRIORIDADE sobre estes. Para trocar de planilha de
# forma definitiva, edite o ID aqui e recompile.
_SPREADSHEET_ID_PADRAO   = "1sNg3cPQu0uG_RIZqJCopNSiMDYePwwGcti1b6FWPPtU"
ABA_PROCESSOS    = "processos_ajuizados"
ABA_INTERMEDIARIO = "historico_intermediario"

# Colunas novas (Assunto, Tipo_redistribuicao) entram para alimentar o AURA
# COTRI direto da planilha — ver docs/ESTUDO_AURA_COTRI.md, seções 4 e 8.
CABECALHO_PROCESSOS     = ["Data", "Classe", "Magistrado", "Processo", "Chave", "Aviso", "Competência", "Assunto", "Tipo_redistribuicao"]
CABECALHO_INTERMEDIARIO = ["Data", "Processo", "Evento", "Tipodocumento", "Status", "Motivo"]

import sys as _sys


def _dirs_config() -> list[str]:
    """Pastas onde procurar arquivos de config (aura_credentials.json,
    aura_sheets.json), em ordem de prioridade.

    No .exe (congelado), procura PRIMEIRO ao lado do executável — onde o
    usuário coloca/edita os arquivos — e só depois no bundle embutido. Assim
    dá para trocar de planilha/credencial sem recompilar o .exe.
    """
    dirs = []
    if os.environ.get("AURA_BASE_DIR"):          # subprocesso lançado pelo AURA.exe
        dirs.append(os.environ["AURA_BASE_DIR"])
    if hasattr(_sys, "_MEIPASS"):
        dirs.append(os.path.dirname(_sys.executable))  # ao lado do .exe (prioridade)
        dirs.append(_sys._MEIPASS)                      # bundle embutido (fallback)
    else:
        # rodando do código-fonte: raiz do projeto (este arquivo mora em shared/)
        dirs.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    unicos = []
    for d in dirs:
        if d and d not in unicos:
            unicos.append(d)
    return unicos


def _achar_config(nome: str) -> str:
    """Primeiro caminho existente para `nome` entre as pastas candidatas.
    Se não existir em nenhuma, devolve o caminho na primeira (para mensagens)."""
    dirs = _dirs_config()
    for d in dirs:
        p = os.path.join(d, nome)
        if os.path.exists(p):
            return p
    return os.path.join(dirs[0], nome) if dirs else nome


# Mantido por compatibilidade com quem referencia _BASE_DIR (1ª pasta candidata).
_BASE_DIR = _dirs_config()[0]

if hasattr(_sys, "_MEIPASS"):
    os.environ.setdefault(
        "REQUESTS_CA_BUNDLE",
        os.path.join(_sys._MEIPASS, "certifi", "cacert.pem"),
    )

CREDENTIALS_FILE = _achar_config("aura_credentials.json")

# ----------------------------------------------------------
#  IDs DAS PLANILHAS
#  Lidos de aura_sheets.json (na mesma pasta das credenciais e ignorado pelo
#  git). Assim cada instalação aponta para as SUAS planilhas sem editar este
#  arquivo. Se o arquivo não existir, caem nos defaults acima/abaixo.
#  Formato do aura_sheets.json:
#    {
#      "spreadsheet_id": "<id da planilha operacional>",
#      "spreadsheet_id_competencias": "<id da planilha de competências>"
#    }
# ----------------------------------------------------------
_SPREADSHEET_ID_COMPETENCIAS_PADRAO = "19BgcXguj02yI5uthWW7TBj4v22da9EAl3ZmtOU6UEu8"


def _limpar_id_planilha(valor: str) -> str:
    """Extrai o ID puro mesmo que colem a URL inteira do Google Sheets.

    Aceita:
      - o ID puro (1AbC...)
      - a URL completa (.../spreadsheets/d/<ID>/edit?gid=...#gid=...)
      - o trecho <ID>/edit?gid=...#gid=...
    e devolve só o <ID> (sem /edit, ?query ou #hash)."""
    valor = (valor or "").strip()
    if "/d/" in valor:                      # URL completa
        valor = valor.split("/d/", 1)[1]
    valor = valor.split("/", 1)[0]          # corta /edit e o que vier depois
    valor = valor.split("?", 1)[0].split("#", 1)[0]  # corta ?query e #hash
    return valor.strip()


def _carregar_ids_planilhas() -> tuple[str, str]:
    caminho = _achar_config("aura_sheets.json")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return (
            _limpar_id_planilha(cfg.get("spreadsheet_id", "")),
            _limpar_id_planilha(cfg.get("spreadsheet_id_competencias", "")),
        )
    except FileNotFoundError:
        return "", ""
    except Exception as e:
        print(f"[aura_db] Aviso: falha ao ler aura_sheets.json: {e}")
        return "", ""


_id_ops, _id_comp = _carregar_ids_planilhas()

# PLANILHA OPERACIONAL: o ID vem SEMPRE do código (embutido). Nenhum arquivo
# externo (aura_sheets.json, mesmo velho, ao lado do .exe) consegue redirecionar
# a gravação para outra planilha. É a garantia de "nunca errar de planilha" que
# a operação pediu: para trocar de planilha, edite _SPREADSHEET_ID_PADRAO acima
# e RECOMPILE o .exe. (O `_id_ops` lido do arquivo é ignorado de propósito.)
SPREADSHEET_ID = _SPREADSHEET_ID_PADRAO
if _id_ops and _id_ops != _SPREADSHEET_ID_PADRAO:
    print(
        "[aura_db] Aviso: 'spreadsheet_id' do aura_sheets.json foi IGNORADO — "
        "a planilha operacional é fixa no código (" + _SPREADSHEET_ID_PADRAO + ")."
    )

# COMPETÊNCIAS: continua aceitando override opcional (aponta para a planilha do
# AURA antigo, que guarda os dados reais). Não é a planilha de gravação, então
# não corre o risco acima.
SPREADSHEET_ID_COMPETENCIAS = _id_comp or _SPREADSHEET_ID_COMPETENCIAS_PADRAO


def _sid() -> str:
    """ID da planilha operacional, exigindo configuração. Sem aura_sheets.json
    (com 'spreadsheet_id'), levanta erro claro em vez de gravar na planilha
    errada."""
    if not SPREADSHEET_ID:
        raise RuntimeError(
            "Planilha operacional não configurada.\n"
            "Coloque o arquivo aura_sheets.json (com a chave 'spreadsheet_id') "
            "AO LADO do AURA.exe — ou na raiz do projeto, ao rodar por código.\n"
            "Sem ele, o AURA não sabe em qual planilha gravar."
        )
    return SPREADSHEET_ID

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
        f"https://sheets.googleapis.com/v4/spreadsheets/{_sid()}"
        f"/values/{aba}"
    )
    resp = requests.get(url, headers=_headers(), timeout=15)
    if resp.status_code in (400, 404):
        # Aba vazia ou não encontrada — retorna lista vazia sem erro
        return []
    resp.raise_for_status()
    return resp.json().get("values", [])


def _titulos_abas() -> list[str]:
    """Nomes de todas as abas da planilha operacional. Serve para saber se a
    aba já existe antes de gravar (e para detectar arquivo não-nativo)."""
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{_sid()}"
        f"?fields=sheets.properties.title"
    )
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return [s["properties"]["title"] for s in resp.json().get("sheets", [])]


def _criar_aba(aba: str):
    """Cria uma aba nova na planilha (usado quando ela ainda não existe)."""
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{_sid()}"
        f":batchUpdate"
    )
    body = {"requests": [{"addSheet": {"properties": {"title": aba}}}]}
    resp = requests.post(url, headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()


def _garantir_cabecalho(aba: str, cabecalho: list[str]):
    try:
        titulos = _titulos_abas()
    except requests.HTTPError as e:
        raise RuntimeError(
            "Não consegui abrir a planilha pelo Google Sheets API.\n"
            "Verifique dois pontos:\n"
            "  1) O arquivo no Drive precisa ser uma PLANILHA GOOGLE nativa "
            "(não pode continuar como .xlsx). Converta com 'Abrir com > "
            "Planilhas Google' e use o ID da planilha nova.\n"
            "  2) A planilha precisa estar compartilhada como Editor com o "
            "e-mail da conta de serviço (client_email do aura_credentials.json).\n"
            f"Detalhe técnico: {e}"
        ) from e

    if aba not in titulos:
        _criar_aba(aba)
        _append_linhas(aba, [cabecalho])
        return

    dados = _ler_aba(aba)
    if not dados:
        _append_linhas(aba, [cabecalho])


def _append_linhas(aba: str, linhas: list[list]):
    # Range explícito A1 é obrigatório para o append funcionar em abas vazias
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{_sid()}"
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
    assunto: str = "",
    tipo_redistribuicao: str = "",
):
    """Grava uma linha nova na aba processos_ajuizados.

    assunto e tipo_redistribuicao alimentam o AURA COTRI (ver
    docs/ESTUDO_AURA_COTRI.md). Ficam vazios enquanto o peticionamento não os
    preenche — a coluna já existe no cabeçalho para manter o protocolo regular.
    """
    _garantir_cabecalho(ABA_PROCESSOS, CABECALHO_PROCESSOS)
    _append_linhas(ABA_PROCESSOS, [[
        data, classe, magistrado, processo, chave, aviso, competencia,
        assunto, tipo_redistribuicao,
    ]])


def processo_ja_ajuizado(processo: str) -> bool:
    """Verifica se um número de processo já existe (detecção de duplicatas)."""
    return any(r.get("Processo") == processo for r in ler_processos_ajuizados())


# Os 12 tipos de redistribuição, na MESMA ordem e com os MESMOS nomes de
# TIPO_RADIO_ID (integrations/run_aura_cotri.py) — é o que o COTRI resolve na
# hora de redistribuir. O peticionamento grava um por processo, em rodízio.
TIPOS_REDISTRIBUICAO = [
    "Dependencia a Juizo",
    "Dependencia a Processo/Colegiado",
    "Dependencia a Processo/Magistrado",
    "Impedimento do Magistrado",
    "Suspeicao do Magistrado",
    "Incompetencia",
    "Incompetencia c/ Dependencia Colegiado",
    "Incompetencia c/ Dependencia Magistrado",
    "Livre",
    "Retorna Autos",
    "Alteracao da Competencia do Orgao Julgador",
    "Por dependencia por Alteracao da Competencia",
]


def proximo_tipo_redistribuicao() -> str:
    """Devolve o próximo tipo de redistribuição em rodízio cíclico.

    A escolha é baseada em quantos processos já existem na aba: o processo nº N
    recebe TIPOS_REDISTRIBUICAO[N % 12]. Assim, ao chegar no 12º tipo, volta ao
    primeiro — cobrindo os 12 tipos de forma contínua entre execuções. Nunca
    lança exceção: se a planilha estiver inacessível, cai no primeiro tipo.
    """
    try:
        n = len(ler_processos_ajuizados())
    except Exception:
        n = 0
    return TIPOS_REDISTRIBUICAO[n % len(TIPOS_REDISTRIBUICAO)]


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
#  (SPREADSHEET_ID_COMPETENCIAS é resolvido no topo, junto de SPREADSHEET_ID)
# ----------------------------------------------------------

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