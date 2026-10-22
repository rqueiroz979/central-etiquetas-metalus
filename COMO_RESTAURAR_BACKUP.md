# Como restaurar backup da Central de Etiquetas Metalus

## Quando usar

Use este procedimento quando o computador antigo apresentar problema, quando for trocar de máquina ou quando for necessário recuperar os dados da Central de Etiquetas.

## O que o backup geral contém

O backup geral contém:

- banco de dados SQLite;
- cadastros;
- históricos, se existirem;
- PDFs gerados;
- configurações do sistema.

## Como restaurar em um PC novo

1. Instale ou copie a Central de Etiquetas Metalus para o novo computador.
2. Instale o Python e as dependências do projeto.
3. Execute o sistema.
4. Abra a Administração.
5. Informe a senha administrativa.
6. Vá até Backup e Restauração.
7. Selecione o arquivo `.zip` do backup geral.
8. Clique em `Restaurar backup geral`.
9. Aguarde a mensagem de sucesso.
10. Reinicie a Central de Etiquetas.
11. Abra novamente o sistema e confira cadastros, configurações e PDFs.

## Observação importante

Antes de restaurar, o sistema cria automaticamente um backup do estado atual.
