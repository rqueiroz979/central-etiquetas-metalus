# Instalar o Almoxarifado no Zorin OS

O aplicativo para Linux é a mesma versão desktop Qt usada como base no Windows. O pacote abre uma janela própria, sem navegador, e não exige Python no computador de destino.

## Gerar o pacote

Faça o build no Zorin OS ou em Ubuntu compatível, usando a mesma arquitetura do computador de destino:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip dpkg-dev
bash build_linux.sh
```

O primeiro build precisa de internet para baixar as dependências de empacotamento. O arquivo `.deb` será criado em `dist/linux/`.

## Instalar e abrir

Instale pelo gerenciador de aplicativos ou pelo terminal:

```bash
sudo apt install ./dist/linux/almoxarifado-metalus_1.0.0_*.deb
```

Abra **Almoxarifado** pelo menu de aplicativos. O pacote declara as bibliotecas nativas usadas pelo Qt e pelo PDF; o APT instala automaticamente as que ainda faltam durante a instalação. O computador precisa de internet nessa etapa se precisar baixar dependências. Python e pasta-fonte não são necessários.

Para remover:

```bash
sudo apt remove almoxarifado-metalus
```

## Dados do usuário

O banco SQLite e a configuração ficam separados dos binários instalados:

- `$XDG_DATA_HOME/Almoxarifado`, se `XDG_DATA_HOME` estiver definido;
- `~/.local/share/Almoxarifado`, caso contrário.

Inclua essa pasta nos backups para preservar os cadastros.

## Problemas comuns

- **Arquitetura incompatível:** gere o `.deb` na mesma arquitetura do computador de destino (por exemplo, `amd64`).
- **Dependências nativas:** instale com `sudo apt install ./arquivo.deb` para que o APT resolva os pacotes necessários.
- **Build:** gere o `.deb` no Linux; um pacote Windows não pode produzir o executável Linux e vice-versa.

## Baixar pelo GitHub

O workflow de build gera o instalador Linux em cada execução concluída. No GitHub, abra **Actions → Build desktop packages**, selecione uma execução e baixe o artefato **Almoxarifado-Zorin-Linux**. Antes de publicar o artefato, o workflow instala o `.deb` com o APT e testa a inicialização do aplicativo.
