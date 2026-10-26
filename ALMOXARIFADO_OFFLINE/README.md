# ALMOXARIFADO Desktop

Esta é a versão desktop Qt usada como base para os pacotes finais de Windows e Zorin OS. Ela abre em janela própria, sem navegador.

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

No GitHub Actions, o workflow de build gera o instalador `Almoxarifado-Setup.exe` e o pacote `.deb`, ambos disponíveis nos artefatos da execução. A pasta `dist\windows\ALMOXARIFADO` também pode ser distribuída como versão portátil. Veja o [guia principal](../README.md) e o [guia de instalação Linux](../INSTALACAO_LINUX.md).

## Dados

No Windows portátil, o banco SQLite fica em `data/etiquetas.db` ao lado do executável. No Zorin, configuração e dados são armazenados em `$XDG_DATA_HOME/Almoxarifado` ou em `~/.local/share/Almoxarifado`.
