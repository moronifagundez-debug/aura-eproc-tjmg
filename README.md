# AURA — Automação eproc 2º Grau (TJMG)

Robô de automação e ferramentas de apoio para o eproc 2G do TJMG, desenvolvido no CESUPE.

## Estrutura

| Caminho | Descrição |
| --- | --- |
| `aura.py` | Aplicação principal (interface e orquestração das rotinas) |
| `integrations/` | Rotinas específicas: gabinete, COTRI, eventos da Câmara Cível, sessão de julgamento |
| `shared/` | Módulos compartilhados: banco de dados, infraestrutura, seletor de planilhas, agente e regressão de homologação |
| `extension/` | Extensão Chrome "AURA Sessão de Julgamento" (Manifest V3) |
| `AURA.spec` | Especificação PyInstaller para gerar o executável |
| `MAPEAMENTO_SESSAO_JULGAMENTO_HANDOFF.md` | Documentação de mapeamento das telas da sessão de julgamento |

## Configuração

1. Copie `aura_api_padrao.example.json` para `aura_api_padrao.json` e preencha a chave da API.
2. Defina as credenciais do eproc por variáveis de ambiente:

```bash
set AURA_USUARIO=seu_usuario
set AURA_SENHA=sua_senha
```

O arquivo `aura_api_padrao.json` e os arquivos de credenciais estão no `.gitignore` e **não devem ser versionados**.

## Build

```bash
pyinstaller AURA.spec
```

Os executáveis gerados em `dist/` não são versionados.

## Extensão Chrome

Carregue a pasta `extension/` em `chrome://extensions` com o modo desenvolvedor ativado.

---

Uso interno — Tribunal de Justiça de Minas Gerais / CESUPE.
