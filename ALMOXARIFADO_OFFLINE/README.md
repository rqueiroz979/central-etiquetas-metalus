# ALMOXARIFADO Desktop

Esta é a versão desktop Qt usada como base para os pacotes finais de Windows e Zorin OS. Ela abre em janela própria, sem navegador.

## Versão publicada

A versão atual é a **v1.1.0**. Ela inclui a criação avulsa de etiquetas de prateleira e a geração de lotes a partir de planilhas CSV, ODS, XLSX ou XLSM. O lote aceita até 300 etiquetas, uma por página no formato 100 × 70 mm. O período de testes de 45 dias começou em 29/10/2026.

## Executar a partir do código-fonte

No Windows, use `INICIAR_APP_OFFLINE.bat`. No Linux, instale as dependências e execute:

```bash
python3 -m pip install -r requirements.txt
python3 qt_app.py
```

## Pacotes finais

Os pacotes são gerados pelos scripts na raiz do repositório:

- Windows: `build_windows.bat` e Inno Setup com `windows_installer.iss`;
- Zorin OS / Ubuntu: `bash build_linux.sh`.

No GitHub Actions, o workflow de build gera o instalador `Almoxarifado-Setup.exe` e o pacote `almoxarifado-metalus_1.1.0_amd64.deb`, disponíveis nos artefatos da [execução da v1.1.0](https://github.com/rqueiroz979/central-etiquetas-metalus/actions/runs/40944698586). A pasta `dist\windows\ALMOXARIFADO` também pode ser distribuída como versão portátil. Veja o [guia principal](../README.md) e o [guia de instalação Linux](../INSTALACAO_LINUX.md).

Para instruções de uso com imagens das telas, incluindo a criação avulsa e em lote de etiquetas de prateleira a partir de planilhas, consulte o [manual ilustrado em Markdown](MANUAL_DE_USO.md) ou o [manual em PDF](MANUAL_DE_USO_ALMOXARIFADO.pdf).

## Dados

No Windows portátil, o banco SQLite fica em `data/etiquetas.db` ao lado do executável. No Zorin, configuração e dados são armazenados em `$XDG_DATA_HOME/Almoxarifado` ou em `~/.local/share/Almoxarifado`.
