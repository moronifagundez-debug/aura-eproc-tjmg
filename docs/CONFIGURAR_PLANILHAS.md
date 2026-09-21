# Como configurar as planilhas do AURA (do zero)

Guia para quando **não há mais** o `aura_credentials.json` (a chave de acesso
ao Google Sheets) e precisamos criar tudo de novo, usando **as nossas
planilhas**.

O AURA usa **duas planilhas** do Google Sheets e **uma credencial**:

| Item | O que é | Arquivo/onde |
|------|---------|--------------|
| Planilha **operacional** | onde o peticionamento grava os processos (abas `processos_ajuizados` e `historico_intermediario`) | Google Sheets |
| Planilha de **competências** | o "molde" do que peticionar (cada aba = uma competência) | Google Sheets |
| **Credencial** | chave da conta de serviço que autoriza o robô a ler/gravar | `aura_credentials.json` |

> Só **você** consegue criar a credencial e as planilhas (exige login na
> conta Google de vocês). O código já está pronto para receber os IDs.

---

## Parte A — Criar a credencial (`aura_credentials.json`)

1. Acesse **https://console.cloud.google.com/** e faça login.
2. No topo, **crie um projeto** (ex.: "AURA"). Selecione-o.
3. Menu **APIs e serviços → Biblioteca**. Busque **Google Sheets API** e
   clique em **Ativar**.
4. Menu **APIs e serviços → Credenciais → Criar credenciais → Conta de
   serviço**. Dê um nome (ex.: "aura-robo") e conclua.
5. Abra a conta de serviço criada → aba **Chaves → Adicionar chave → Criar
   nova chave → JSON → Criar**. Um arquivo `.json` será baixado.
6. **Renomeie** esse arquivo para **`aura_credentials.json`** e coloque na
   **raiz do projeto** (mesma pasta do `aura.py`).
7. Abra o `aura_credentials.json` e **copie o valor de `client_email`**
   (algo como `aura-robo@aura-xxxx.iam.gserviceaccount.com`). Você vai usar
   no passo B.3.

> O `aura_credentials.json` **nunca** vai para o git (já está no
> `.gitignore`). Guarde uma cópia em local seguro.

---

## Parte B — Criar as duas planilhas

Use os modelos prontos da pasta `modelos/` — eles já têm as abas e colunas
com os **nomes exatos** que o código espera.

1. Acesse **https://drive.google.com/**.
2. **Planilha operacional:** menu **Novo → Upload de arquivo** e envie
   `modelos/modelo_planilha_operacional.xlsx`. Depois clique com o botão
   direito no arquivo enviado → **Abrir com → Planilhas Google**. Isso cria
   a planilha do Google já com as abas `processos_ajuizados` e
   `historico_intermediario` corretas. (Pode renomear o arquivo à vontade —
   o que importa são os **nomes das abas**, não mexa neles.)
3. **Compartilhe** essa planilha com o `client_email` do passo A.7, como
   **Editor** (botão **Compartilhar** → cole o e-mail → Editor → Enviar).
4. Repita 2 e 3 para a **planilha de competências**
   (`modelos/modelo_planilha_competencias.xlsx`). Nela, **renomeie a aba de
   exemplo** para o nome da competência real e crie **uma aba por
   competência**, preenchendo as linhas.
5. Copie o **ID** de cada planilha. O ID é o trecho da URL entre `/d/` e
   `/edit`:
   `https://docs.google.com/spreadsheets/d/`**`ESTE_PEDACO_É_O_ID`**`/edit`

---

## Parte C — Conectar no código

1. Faça uma cópia do arquivo `aura_sheets.exemplo.json` chamada
   **`aura_sheets.json`** (na raiz do projeto).
2. Cole os dois IDs:
   ```json
   {
     "spreadsheet_id": "ID_DA_PLANILHA_OPERACIONAL",
     "spreadsheet_id_competencias": "ID_DA_PLANILHA_DE_COMPETENCIAS"
   }
   ```
3. Pronto. O código lê esse arquivo automaticamente (`aura_db.py`). O
   `aura_sheets.json` também fica fora do git.

### Testar a conexão
Com `aura_credentials.json` e `aura_sheets.json` no lugar, rode:
```
python shared/aura_db.py
```
Se aparecer "Conexão OK", está tudo certo. Os cabeçalhos das abas
`processos_ajuizados` e `historico_intermediario` são criados/conferidos
automaticamente na primeira execução.

---

## Colunas novas já incluídas (plano do COTRI)

A aba `processos_ajuizados` já vem com duas colunas novas do nosso plano
(ver `ESTUDO_AURA_COTRI.md`):

- **Assunto** — usado na redistribuição do COTRI.
- **Tipo_redistribuicao** — o motivo de redistribuição (será gerado em
  rodízio pelos 12 tipos, na fase de implementação).

Por enquanto elas podem ficar vazias; o importante é o cabeçalho já estar
regular. A lógica que as preenche entra na Fase 1 do plano.
