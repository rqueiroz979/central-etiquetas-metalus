# Central de Etiquetas Metalus

Aplicativo web em Flask para gerar etiquetas em PDF sem depender de LibreOffice.

## O que o projeto entrega hoje

- tela inicial centralizando os módulos de etiquetas;
- módulo de `Matéria-Prima` com preenchimento automático de material e fornecedor via SQLite;
- geração com preview no navegador, download em PDF e impressão;
- área administrativa protegida por senha para cadastro de materiais e fornecedores;
- módulo de `Identificação` com importação de arquivo `.ods` ou `.xlsx`, preenchimento inicial dos campos e geração individual ou em lote;
- estrutura administrativa preparada para futuras etiquetas.

## Requisitos

- Para gerar os pacotes ou executar a partir do código-fonte: Python 3.10+.
- Para usuários finais: não é necessário instalar Python.

## Instalação

### Para usuários finais

- **Windows:** execute `CentralEtiquetasMetalus.exe`.
- **Zorin OS Lite:** instale o arquivo `.deb` gerado para a arquitetura do computador e abra **Central de Etiquetas Metalus** pelo menu.

Os usuários recebem somente o executável ou pacote de instalação. Não precisam receber esta pasta-fonte, instalar Python ou executar `pip`.

### Gerar os pacotes

Gere cada pacote no sistema de destino: `.exe` no Windows com `build_windows.bat` e `.deb` no Zorin/Ubuntu com `bash build_linux.sh`. Os arquivos finais ficam em `dist/windows/` e `dist/linux/`, respectivamente. Consulte o [guia do Linux](INSTALACAO_LINUX.md) para os detalhes.

Os scripts instalam PyInstaller e as dependências de build somente no computador de desenvolvimento. Os pacotes incluem as dependências Python e os arquivos de interface.

### Executar a partir do código-fonte

Este fluxo é somente para desenvolvimento e requer Python 3.10 ou superior:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Observação:

- a importação do módulo `Identificação` não precisa de bibliotecas extras; ela usa parser baseado em `zipfile` e `xml.etree` para arquivos `.ods` e `.xlsx`;
- se `ezodf` não estiver instalado, o app continua funcionando normalmente; apenas a carga inicial de `Material` e `Fornecedor` a partir da planilha ODS não acontece.

## Configuração

No modo de desenvolvimento, edite `config.json`. No app empacotado, a configuração é copiada no primeiro uso para a pasta de dados do usuário descrita abaixo.

- `template_path`: caminho da planilha ODS original usada para importar os cadastros iniciais;
- `output_dir`: pasta onde os PDFs gerados serão salvos;
- `db_path`: caminho do banco SQLite;
- `admin_password`: senha da área administrativa;
- `flask_secret_key`: chave secreta da sessão Flask.

Variáveis de ambiente aceitas. No PowerShell:

```bash
$env:ETIQUETA_ADMIN_PASSWORD = "sua_senha_forte"
$env:FLASK_SECRET_KEY = "uma_chave_forte"
```

No Zorin OS Lite:

```bash
export ETIQUETA_ADMIN_PASSWORD="sua_senha_forte"
export FLASK_SECRET_KEY="uma_chave_forte"
```

Se nada for alterado, o projeto usa a senha administrativa padrão `Metalus@admin`. Troque isso antes de usar em ambiente compartilhado.

## Executar

Via terminal:

```bash
python app.py
```

Para desenvolvimento no Windows, `INICIAR_APP.bat`:

- cria o ambiente virtual `.venv` se ainda não existir;
- instala as dependências do `requirements.txt`;
- inicia o app automaticamente.

Abra no navegador:

- local: `http://localhost:5000`
- rede interna: `http://IP_DO_COMPUTADOR:5000`

## Dados do usuário

No Windows, banco, configuração, backups e PDFs ficam em `%LOCALAPPDATA%\CentralEtiquetasMetalus`. No Linux, ficam em `~/.local/share/CentralEtiquetasMetalus`, separados dos binários instalados. Inclua essa pasta nos backups do usuário.

## Fluxos disponíveis

### 1. Central

A rota inicial (`/`) exibe a central com atalhos para:

- `Etiqueta de Matéria-Prima`;
- `Etiqueta Usinados`;
- `Etiqueta de Identificação`;
- `Administração`.

### 2. Etiqueta de Matéria-Prima

Campos principais:

- código do produto;
- data;
- lote;
- descrição do material;
- insp., ref., dimensões;
- fornecedor, PDC, quantidade, NF, O.S. e pallet.

Recursos:

- busca automática de material e fornecedor por código;
- preview antes de baixar;
- impressão direta pelo navegador;
- histórico salvo no SQLite.

Layouts suportados:

- `A4 - 12 etiquetas` de `90,5 x 44,0 mm`;
- `100 x 70 mm` para etiqueta térmica;
- `140 x 70 mm` para o modelo de usinados.

### 3. Etiqueta de Identificação

Recursos atuais:

- importação de arquivo `.ods` ou `.xlsx`;
- extração das colunas `OS`, `Peca` e `Qtde`;
- preenchimento inicial dos campos da etiqueta;
- geração individual;
- geração em lote com seleção de múltiplos registros;
- preview, download e impressão do PDF.

### 4. Administração

A área administrativa permite:

- desbloqueio por senha;
- cadastro e atualização de materiais/produtos;
- cadastro e atualização de fornecedores;
- navegação entre subtelas já preparadas para novos modelos de etiqueta.

## Estrutura principal

- `app.py`: rotas Flask e orquestração dos fluxos;
- `database.py`: SQLite, consultas e carga inicial dos cadastros;
- `pdf_label.py`: geração dos PDFs dos modelos de etiqueta;
- `ods_import.py`: leitura de planilhas `.ods` e `.xlsx` usadas no módulo de identificação;
- `templates/`: telas HTML;
- `static/`: CSS e logo;
- `data/`: banco SQLite;
- `output/`: PDFs gerados.

## Observações

- o app pode usar `FLASK_DEBUG=1` ou `flask_debug` no `config.json` quando você quiser rodar em modo debug;
- o banco e a pasta de saída são criados automaticamente quando necessário;
- a importação automática do ODS original só ocorre quando a base estiver vazia;
- o projeto agora possui `requirements.txt` para facilitar a instalação em outra máquina.
