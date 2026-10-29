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

Se baixou o artefato **Almoxarifado-Zorin-Linux** pelo GitHub, primeiro extraia o ZIP. No Zorin, o gerenciador gráfico pode mostrar “tipo de arquivo não suportado” ao abrir diretamente um `.deb`; nesse caso, instale pelo terminal para que o APT reconheça o pacote local e resolva as dependências:

```bash
sudo apt install "/caminho/para/almoxarifado-metalus_1.1.0_amd64.deb"
```

Substitua o caminho de exemplo pelo caminho do arquivo extraído. Se o terminal estiver aberto na pasta do `.deb`, também pode usar:

```bash
sudo apt install ./almoxarifado-metalus_1.1.0_amd64.deb
```

Abra **Almoxarifado** pelo menu de aplicativos. O pacote declara as bibliotecas nativas usadas pelo Qt e pelo PDF; o APT instala automaticamente as que ainda faltam durante a instalação. O computador precisa de internet nessa etapa se precisar baixar dependências. Python e pasta-fonte não são necessários.

No primeiro início, o aplicativo copia para o banco local os cadastros iniciais da versão Windows (materiais e fornecedores). Registros já existentes no banco do Linux são preservados; a importação não sobrescreve códigos que já tenham cadastro.

Para remover:

```bash
sudo apt remove almoxarifado-metalus
```

## Dados do usuário

O banco SQLite e a configuração ficam separados dos binários instalados:

- `$XDG_DATA_HOME/Almoxarifado`, se `XDG_DATA_HOME` estiver definido;
- `~/.local/share/Almoxarifado`, caso contrário.

Inclua essa pasta nos backups para preservar os cadastros.

O aplicativo e o atalho do menu são instalados para todos os usuários do computador. Cada conta Linux mantém seus próprios cadastros na pasta de dados acima; os bancos não são compartilhados entre contas. Os PDFs temporários também usam uma pasta privada por execução, então uma conta não precisa de permissão sobre os arquivos temporários de outra. O workflow do GitHub testa a inicialização do pacote também com uma segunda conta Linux antes de disponibilizar o instalador.

## Problemas comuns

- **Arquitetura incompatível:** gere o `.deb` na mesma arquitetura do computador de destino (por exemplo, `amd64`).
- **Dependências nativas:** instale com `sudo apt install ./arquivo.deb` para que o APT resolva os pacotes necessários.
- **Build:** gere o `.deb` no Linux; um pacote Windows não pode produzir o executável Linux e vice-versa.

## Baixar pelo GitHub

O workflow de build gera o instalador Linux em cada execução concluída. No GitHub, abra **Actions → Build desktop packages**, selecione uma execução e baixe o artefato **Almoxarifado-Zorin-Linux**. Antes de publicar o artefato, o workflow instala o `.deb` com o APT e testa a inicialização do aplicativo.
