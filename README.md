# Almoxarifado Metalus

O aplicativo final é o **ALMOXARIFADO desktop**, baseado na versão que já está em uso no Windows. Ele abre em uma janela própria, sem navegador, e reorganiza os painéis quando a janela fica menor. A mesma base Qt é empacotada para Windows e Zorin OS.

## Versão atual e período de testes

A versão publicada para validação é a **v1.1.0**. Ela inclui etiquetas de prateleira avulsas e geração de lotes a partir de planilhas. O ciclo de testes de 45 dias começou em **29/10/2026**, com previsão de término em **13/12/2026**; novas melhorias podem ser planejadas depois de avaliar esse período.

O código-fonte principal dessa versão fica em `ALMOXARIFADO_OFFLINE/`:

- `qt_app.py`: janela desktop, formulários, cadastros e visualização/impressão de PDF;
- `database.py`: cadastros locais de materiais e fornecedores em SQLite;
- `pdf_label.py`: geração dos PDFs;
- `static/`: ícones e logotipo.

O [manual de uso ilustrado](ALMOXARIFADO_OFFLINE/MANUAL_DE_USO.md) explica a geração de etiquetas de produção, a criação avulsa e em lote de etiquetas de prateleira a partir de planilhas, a divisão de quantidades por pallet, o visualizador de PDF e os cadastros. A versão em PDF está disponível em [MANUAL_DE_USO_ALMOXARIFADO.pdf](ALMOXARIFADO_OFFLINE/MANUAL_DE_USO_ALMOXARIFADO.pdf).

## Arquivos gerados e dados locais

As pastas `.venv/`, `.build-windows/`, `.build-linux/`, `build/` (inclusive `ALMOXARIFADO_OFFLINE/build/`) e `__pycache__/` contêm ambientes ou arquivos temporários de desenvolvimento/build. Podem ser removidas; os ambientes e arquivos de build são recriados quando necessários.

As pastas locais `dist/`, `data/`, `output/`, `APP_ETIQUETAS_ALMOX/` e o arquivo `APP_ETIQUETAS_ALMOX.rar` não são incluídos no Git: podem conter instaladores, bancos de dados, PDFs ou a versão Windows de referência. Preserve os dados que precisar; se houver arquivos de backup, confira o conteúdo antes de removê-los.

## Usar no Windows

Para executar a partir do código-fonte, abra `INICIAR_APP.bat`. É necessário Python 3.10 ou superior; na primeira execução, o iniciador instala as dependências do aplicativo.

Para gerar o instalador Windows:

```bat
build_windows.bat
```

O instalador `dist\windows\Almoxarifado-Setup.exe` é gerado pelo workflow do GitHub Actions. Localmente, após `build_windows.bat`, compile `windows_installer.iss` com o Inno Setup. O aplicativo instalado guarda banco e configuração em `%LOCALAPPDATA%\Almoxarifado`; não precisa de Python.

Para uma versão portátil sem instalador, copie a pasta inteira `dist\windows\ALMOXARIFADO` e abra `INICIAR_ALMOXARIFADO.bat`. Não copie apenas o `.exe`: o diretório `_internal` também é necessário. Na versão portátil, os dados ficam junto ao executável.

Para preservar cadastros existentes ao migrar para o instalador, feche o aplicativo e copie o banco antigo para `%LOCALAPPDATA%\Almoxarifado\data\etiquetas.db`.

## Usar no Zorin OS

Gere o pacote `.deb` no Zorin OS ou em uma versão compatível do Ubuntu, para a mesma arquitetura do computador de destino:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip dpkg-dev
bash build_linux.sh
```

O pacote será criado em `dist/linux/`. Instale-o pelo terminal com APT, que também resolve as dependências:

```bash
sudo apt install ./dist/linux/almoxarifado-metalus_1.1.0_*.deb
```

Depois da instalação, abra **Almoxarifado** pelo menu de aplicativos. Python e internet não são necessários no computador de uso.

## Executar no Linux a partir do código-fonte

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r ALMOXARIFADO_OFFLINE/requirements.txt
python ALMOXARIFADO_OFFLINE/qt_app.py
```

## Dados e compatibilidade de tela

- No Windows portátil, configuração e banco ficam junto ao executável: `config.json` e `data\etiquetas.db`.
- No Zorin, o aplicativo é instalado para todos os usuários. Cada conta mantém seus dados em `$XDG_DATA_HOME/Almoxarifado` ou, se a variável não estiver definida, em `~/.local/share/Almoxarifado`; os arquivos temporários também são privados por execução.
- O primeiro início já carrega os cadastros iniciais da versão Windows: 4.501 materiais e 52 fornecedores. Cada instalação mantém seu próprio banco; os cadastros existentes no computador são preservados e não são sincronizados entre Windows e Linux. Para atualizar os dados, use **Cadastros → Importar tabela** (CSV, ODS, XLSX ou XLSM).
- A janela inicial considera a área de tela disponível; em larguras menores, os painéis passam de lado a lado para uma disposição vertical. As páginas também permitem rolagem para acessar o conteúdo em telas com pouca altura.

## Instaladores gerados pelo GitHub

O workflow `.github/workflows/build-packages.yml` roda em push para `main` e também pode ser iniciado em **Actions → Build desktop packages → Run workflow**. A execução que gerou os instaladores v1.1.0 está em [Build desktop packages — execução 9](https://github.com/rqueiroz979/central-etiquetas-metalus/actions/runs/40944698586). Ela gerou:

- o artefato **Almoxarifado-Windows**, que contém `Almoxarifado-Setup.exe`;
- o artefato **Almoxarifado-Zorin-Linux**, que contém `almoxarifado-metalus_1.1.0_amd64.deb`.

Abra a execução, role até **Artifacts** e baixe o ZIP da plataforma desejada. Extraia o ZIP antes de abrir o instalador do Windows ou instalar o `.deb` no Zorin. Os artefatos desta execução expiram em **27/01/2027**; depois dessa data, use uma execução mais recente. Os jobs instalaram e iniciaram os aplicativos de teste antes de publicar os arquivos.
