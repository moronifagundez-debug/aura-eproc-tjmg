# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files
import certifi

datas = [
    ('aura_logo.ico', '.'),
    ('aura_logo.png', '.'),
    ('aura_credentials.json', '.'),
    ('aura_api_padrao.json', '.'),
    ('orgaos_caciv.json', '.'),
    # Certificados SSL necessários para requests/urllib3 chamar a API Google
    (certifi.where(), 'certifi'),
]

# IDs das planilhas: se o aura_sheets.json existir na raiz no momento do build,
# ele é embutido no .exe. Assim o executável já aponta para as SUAS planilhas.
# (Também pode ser colocado ao lado do AURA.exe depois, que tem prioridade.)
if os.path.exists('aura_sheets.json'):
    datas.append(('aura_sheets.json', '.'))
binaries = []
hiddenimports = [
    'requests', 'certifi',
    'cryptography',
    'cryptography.hazmat.primitives.hashes',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.primitives.asymmetric.padding',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.openssl',
    'cryptography.hazmat.bindings._rust',
    'openpyxl', 'openpyxl.styles',
    'aura_db', 'aura_sheet_selector', 'AURAAGENT',
    'auragabinete', 'run_aura_cotri', 'run_aura_eventoscamaracivel',
    'tkinter', 'tkinter.scrolledtext', 'tkinter.filedialog',
    'tkinter.messagebox', 'tkinter.simpledialog',
]

for pkg in ('selenium', 'webdriver_manager', 'customtkinter', 'PIL', 'requests', 'certifi'):
    tmp = collect_all(pkg)
    datas    += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

a = Analysis(
    ['aura.py'],
    pathex=['integrations', 'shared'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AURA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['aura_logo.ico'],
)
