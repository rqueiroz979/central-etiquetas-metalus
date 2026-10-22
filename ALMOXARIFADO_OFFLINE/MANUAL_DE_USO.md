# Manual de Uso - Almoxarifado Offline

Este documento explica como usar o sistema para cadastrar materiais e fornecedores, gerar etiquetas, visualizar PDFs e imprimir.

As imagens abaixo são exemplos visuais do próprio sistema.

## 1. Abrir o sistema

No computador onde o sistema estiver copiado, abra a pasta do aplicativo e execute:

```bat
INICIAR_ALMOXARIFADO.bat
```

O sistema é portátil. Ele não precisa de instalador, Python ou internet para funcionar.

## 2. O que o sistema guarda

O sistema salva somente:

- Materiais / produtos
- Fornecedores

As etiquetas geradas não ficam armazenadas automaticamente. O PDF é criado em uma pasta temporária para visualizar, imprimir ou salvar manualmente.

## 3. Tela principal

Na tela principal ficam os campos usados para gerar a etiqueta.

![Tela principal do sistema](docs/imagens/01_tela_principal.png)

Campos principais:

- `Tipo de etiqueta`: escolha entre `Matéria-Prima`, `Matéria-Prima Usinados` e `Bens de Consumo`.
- `Código do Produto`: informe ou selecione o código do material.
- `Data`: data que sairá na etiqueta.
- `Nº Lote`: número do lote recebido.
- `Descrição do material`: preenchida automaticamente quando o produto está cadastrado.
- `Insp.`, `Ref.`, `Dimensão 1` e `Dimensão 2`: dados técnicos da etiqueta.
- `Fornecedor (código)`: informe ou selecione o fornecedor.
- `Nome do fornecedor`: preenchido automaticamente quando o fornecedor está cadastrado.
- `PDC`, `Quant.`, `NF`, `O.S.` e `Pallet`: dados complementares da etiqueta.

Ao preencher um campo e pressionar `Enter`, o cursor passa para o próximo campo.

## 4. Selecionar produto ou fornecedor

Para buscar um produto:

1. Clique em `Selecionar` ao lado do campo `Código do Produto`.
2. Pesquise pelo código ou descrição.
3. Selecione o item desejado.

Para buscar um fornecedor:

1. Clique em `Selecionar` ao lado do campo `Fornecedor (código)`.
2. Pesquise pelo código ou nome.
3. Selecione o item desejado.

## 5. Gerar uma etiqueta simples

Use este fluxo quando for apenas uma etiqueta.

1. Escolha o `Tipo de etiqueta`.
2. Preencha os dados da tela principal.
3. Em `Quantidade de etiquetas`, deixe `1`.
4. Escolha o `Formato de impressão`.
5. Clique em `Gerar Etiqueta`.
6. O PDF será exibido no visualizador.
7. Confira a etiqueta.
8. Clique em `Imprimir` ou `Salvar`.

## 6. Gerar etiquetas para vários pallets

Use este fluxo quando o mesmo produto chegar em mais de um pallet.

![Tabela de pallets preenchida](docs/imagens/01_tela_principal.png)

1. Preencha os dados do produto normalmente.
2. Em `Dados Complementares`, preencha:
   - `Quant.` com a quantidade total recebida.
   - `Pallet` com a quantidade de pallets recebidos.
3. Ao informar um pallet maior que `1`, o sistema abre a tabela `Pallets recebidos`.
4. A coluna `Pallet` será preenchida automaticamente:

```text
1/4
2/4
3/4
4/4
```

5. Preencha a quantidade de cada pallet.
6. Se quiser dividir automaticamente, clique em `Dividir auto.`.
7. Confira as quantidades.
8. Clique em `Gerar Etiqueta`.

O sistema gera um PDF com uma etiqueta para cada pallet, em ordem.

Exemplo:

```text
Quantidade total: 136
Pallets: 4

1/4 - 34
2/4 - 34
3/4 - 34
4/4 - 34
```

## 7. Formatos de impressão

Os formatos disponíveis são:

- `A4 - 8 etiquetas (90 x 60 mm)`
- `Etiqueta 100 x 70 mm`

Os mesmos formatos são usados para `Matéria-Prima`, `Matéria-Prima Usinados` e `Bens de Consumo`.

## 8. Visualizador de PDF

Depois de gerar a etiqueta, o PDF aparece no visualizador da própria tela.

![Visualizador de PDF integrado](docs/imagens/02_visualizador_pdf.png)

Botões do visualizador:

- `-`: diminuir zoom.
- `+`: aumentar zoom.
- `Ajustar`: ajustar o PDF à largura do visualizador.
- `Imprimir`: enviar o PDF para a impressora.
- `Salvar`: salvar uma cópia do PDF em uma pasta escolhida.
- `Externo`: abrir o PDF no leitor padrão do Windows.
- `Fechar`: fechar o visualizador.

## 9. Abrir último PDF

O botão `Abrir último PDF` reabre o último PDF gerado durante a sessão atual do sistema.

Observação: como o sistema não armazena etiquetas automaticamente, ao fechar o sistema o PDF temporário pode ser apagado. Para guardar uma etiqueta, use o botão `Salvar`.

## 10. Atualizar / nova etiqueta

Na tela principal, o botão `Atualizar` limpa os campos para começar uma nova etiqueta.

Ele também:

- Fecha o visualizador de PDF.
- Volta `Quantidade de etiquetas` para `1`.
- Limpa a tabela de pallets.
- Mantém a data atual preenchida.

## 11. Cadastros

Para acessar os cadastros, clique no card `Cadastros`.

![Tela de cadastros](docs/imagens/03_cadastros.png)

Nessa tela é possível:

- Importar tabela de produtos e fornecedores.
- Cadastrar ou atualizar materiais/produtos manualmente.
- Cadastrar ou atualizar fornecedores manualmente.
- Pesquisar itens cadastrados.

## 12. Importar tabela

O sistema aceita arquivos:

![Importação de tabela](docs/imagens/04_importacao.png)

- CSV
- ODS
- XLSX
- XLSM

Para importar:

1. Acesse `Cadastros`.
2. Clique em `Importar tabela`.
3. Escolha o arquivo.
4. Confira o nome do arquivo selecionado na tela.
5. Aguarde a mensagem de conclusão.

Ao terminar, o sistema informa quantos materiais e fornecedores foram inseridos ou atualizados.

## 13. Cadastro manual

Para cadastrar ou atualizar um material:

1. Entre em `Cadastros`.
2. Selecione a aba `Materiais / Produtos`.
3. Preencha `Código`.
4. Preencha `Descrição`.
5. Clique em `Salvar Material / Produto`.

Para cadastrar ou atualizar um fornecedor:

1. Entre em `Cadastros`.
2. Selecione a aba `Fornecedores`.
3. Preencha `Código`.
4. Preencha `Nome`.
5. Clique em `Salvar Fornecedor`.

Se o código já existir, o sistema atualiza o cadastro.

## 14. Cuidados importantes

- Não apague a pasta `data`, pois nela fica o banco de produtos e fornecedores.
- Para levar o sistema para outro computador, copie a pasta completa do aplicativo.
- Não execute o sistema de dentro do arquivo `.zip`; primeiro extraia a pasta.
- Para guardar uma etiqueta, use `Salvar` no visualizador de PDF.
- Se a impressora não aparecer, confira se ela está instalada no Windows.

## 15. Problemas comuns

### O produto não preenche a descrição automaticamente

Verifique se o produto está cadastrado em `Cadastros > Materiais / Produtos`.

### O fornecedor não preenche o nome automaticamente

Verifique se o fornecedor está cadastrado em `Cadastros > Fornecedores`.

### O PDF não abriu no leitor externo

Use o visualizador interno do sistema ou instale um leitor de PDF padrão no Windows.

### A impressão não saiu corretamente

Confira:

- Impressora selecionada.
- Tamanho do papel.
- Orientação da impressão.
- Se a escala da impressora está em tamanho real ou 100%.
