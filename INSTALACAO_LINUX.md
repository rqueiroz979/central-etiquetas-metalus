# Gerar e instalar no Zorin OS Lite

O usuário final recebe somente um pacote `.deb`, sem a pasta-fonte. O pacote inclui o executável e os arquivos de interface; o usuário não precisa instalar Python nem usar `pip`. Gere o `.deb` em uma máquina Zorin OS Lite ou Ubuntu da mesma arquitetura do computador de destino.

## Gerar o pacote

1. Na máquina de desenvolvimento Linux, instale as ferramentas de build:

	```bash
	sudo apt update
	sudo apt install -y python3 python3-venv python3-pip dpkg-dev
	```

2. Na pasta-fonte do projeto, rode:

	```bash
	bash build_linux.sh
	```

	O primeiro build precisa de internet para instalar as dependências de build. O pacote final será criado em `dist/linux/`.

3. Copie somente o arquivo `.deb` gerado para o computador do usuário. Não copie a pasta-fonte, `.venv`, `build/` ou `requirements.txt`.

## Instalar no Zorin

1. Copie o `.deb` para o computador com Zorin OS Lite.
2. Dê duplo clique no arquivo e escolha instalar pelo instalador de aplicativos. Se solicitado, informe a senha de uma conta administradora.
3. Abra **Central de Etiquetas Metalus** pelo menu. Uma janela de terminal acompanha o app; mantenha-a aberta enquanto estiver usando o sistema. O navegador será aberto automaticamente.

Alternativamente, no terminal, navegue até a pasta do `.deb` e instale com:

```bash
sudo apt install ./central-etiquetas-metalus_1.0.0_*.deb
```

O APT instala automaticamente as dependências nativas declaradas no pacote. O app não exige Python, acesso à internet ou código-fonte no computador do usuário após a instalação.

## Remover

```bash
sudo apt remove central-etiquetas-metalus
```

## Dados do usuário

Configuração, banco de dados, backups e PDFs ficam em `~/.local/share/CentralEtiquetasMetalus`, separados dos arquivos instalados. Inclua essa pasta nos backups para preservar os dados.

## Problemas comuns

- **Arquitetura incompatível:** o pacote precisa ser gerado para a arquitetura do computador de destino. O nome do arquivo mostra a arquitetura, como `amd64` ou `arm64`.
- **Dependências do sistema:** instale pelo terminal com `sudo apt install ./arquivo.deb` para que o APT resolva as dependências automaticamente.
- **Porta 5000 ocupada:** feche o programa que estiver usando essa porta e abra o app novamente.