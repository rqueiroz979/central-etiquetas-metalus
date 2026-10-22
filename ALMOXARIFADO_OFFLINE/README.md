# ALMOXARIFADO OFFLINE

Aplicativo desktop local para gerar etiquetas do almoxarifado.

## Manual de uso

As instruções para os usuários estão em:

```bat
MANUAL_DE_USO.md
```

Versão em PDF com imagens:

```bat
MANUAL_DE_USO_ALMOXARIFADO.pdf
```

## Dados gravados

O sistema grava somente:

- Produtos / materiais
- Fornecedores

As etiquetas geradas não ficam armazenadas. O PDF é criado em pasta temporária apenas para visualizar, imprimir ou salvar manualmente.

## Execução local

```bat
INICIAR_ALMOXARIFADO.bat
```

## Pacote portátil para outro PC

No PC de desenvolvimento, com as dependências já instaladas, execute:

```bat
CRIAR_PACOTE_PORTATIL.bat
```

Depois copie a pasta abaixo inteira para o outro computador:

```bat
dist\ALMOXARIFADO
```

No computador final, abra:

```bat
INICIAR_ALMOXARIFADO.bat
```

Esse formato não exige instalador nem Python instalado no computador final.

## Arquivos importantes

- Banco persistente: `data/etiquetas.db`
- Logo: `static/logo-metalus.png`
- Configuração: `config.json`
