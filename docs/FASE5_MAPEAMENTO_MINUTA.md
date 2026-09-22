# Fase 5 — O que preciso capturar no eProc (minuta por peticionamento)

> Guia rápido do que me mandar (prints ou HTML) para eu automatizar a **minuta
> por peticionamento sem preferência** no AURA Distribuição. Objetivo: descobrir
> as **posições exatas** dos campos de autocomplete, para o robô escolher o
> evento e o tipo de documento certos — sem chutar. Atualizado em 2026-09-17.

## Por que preciso disso

O robô "digita" no campo e depois desce N vezes na lista de sugestões até o item
certo. Esse **N** depende de quais sugestões o eProc mostra, e isso eu só sei
vendo a sua tela. O evento combinado (`Conclusos para decisão com
revisão de autuação (51)`) não está no mapa que já temos, por isso a calibração.

## Passo a passo (faça com UM processo de teste em homologação)

1. **Abra o processo** de teste no eProc (mesmo login do AURA).
2. Clique em **Movimentar/Peticionar** (ou o caminho que você usa hoje para
   lançar essa conclusão — **me diga qual é**, se for outro).
3. No campo **Evento**, digite: `Conclusos para decisão com revisão`
   - 📸 **Print 1:** a lista de sugestões que aparece, **inteira e na ordem**.
   - ✍️ Me diga **qual item** da lista é o correto (o 1º? o 2º?).
4. Selecione o evento correto.
   - 📸 **Print 2:** se aparecer algum painel de **prazos** ("Selecione o(s)
     prazo(s)...") ou qualquer aviso, capture.
5. No campo **Tipo de documento** (depois de anexar um PDF qualquer de teste),
   digite: `Documento de informação`
   - 📸 **Print 3:** a lista de sugestões do tipo, **inteira e na ordem**.
   - ✍️ Me diga **qual item** é o correto.
6. 📸 **Print 4:** a tela final antes de confirmar (botões de enviar/movimentar),
   só para eu conferir que os botões são os mesmos do peticionamento comum.

## Melhor ainda (opcional): o HTML da página

Se puder, na tela de **Movimentar/Peticionar** com esse evento selecionado:
- clique com o botão direito → **Salvar como** → "Página da Web, completa"; **ou**
- aperte **F12** (DevTools) → aba **Elements** → botão direito no `<html>` →
  **Copy → Copy outerHTML** → cole num arquivo `.txt` e me mande.

Com o HTML eu confirmo de uma vez os identificadores dos campos
(`txtEvento`, `txtTipo_1`, o input de arquivo, `btnEnviarArquivos`,
`sbmMovimentar`) e as posições — sem depender só dos prints.

## O que já está resolvido (não precisa capturar)

- **PDF da minuta:** você escolhe na UI, igual ao peticionamento intermediário.
- **Evento e tipo fixos:** já combinados (constantes no código).
- **Setores:** COMED / COAPRI / COAPUB já estão na interface (Fase 2 feita).
- **Fonte da fila:** virá da planilha `processos_ajuizados` (Fase 3, que posso
  fazer em paralelo assim que você quiser).

## Quando você me mandar

Eu: (1) calibro as posições, (2) porto o motor de peticionamento para o AURA
Distribuição com o evento/tipo fixos, (3) mantenho o CSV como alternativa até
validarmos, e (4) te explico como testar num processo de homologação antes de
usar pra valer.
