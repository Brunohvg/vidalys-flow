# Domínio Customers

## Escopo canônico

`apps.customers` é o cadastro operacional de pessoas físicas e jurídicas de
uma `Organization`. O domínio não contém pedidos, CRM de prospecção ou
campanhas. A Fase 2 estabeleceu o cadastro e suas regras de identidade; a Fase
10 acrescenta criação inline em quick-order e transferência de cadastros sem
mudar essas regras canônicas.

## Models

- `Customer`: identidade, tipo, nome, documento normalizado, estado e
  redirecionamento lógico de merge;
- `ContactPoint`: telefone, WhatsApp ou e-mail normalizado;
- `CustomerAddress`: endereço operacional e marcações de padrão;
- `CustomerNote`: nota operacional curta, com autor e exclusão lógica;
- `CustomerMerge`: registro imutável da mesclagem.

Documento, quando informado, é validado como CPF/CNPJ e é único somente
dentro da organização. E-mails e telefones não são únicos: famílias e
empresas podem compartilhar contatos. Correspondências exatas servem para
sugerir revisão; nomes semelhantes nunca executam merge automático.

## Autorização, isolamento e privacidade

Selectors recebem `organization` explicitamente. Views resolvem a organização
ativa da sessão e revalidam uma `Membership` ativa. A organização nunca é
autorizada apenas por um identificador enviado pelo cliente.

Qualquer Membership ativa pode consultar, criar e editar registros. Somente
`OWNER`, `ADMIN` e `MANAGER` podem mesclar clientes ou bloquear cadastros.
Dados pessoais são mascarados para `OPERATOR` na tela de detalhe e em
exportações. Documento, e-mail e telefone completos continuam disponíveis em
exportação apenas para manager tier, pela mesma regra usada nas superfícies de
detalhe. Exportação nunca mistura dados entre Organizations.

## Services e eventos

Criação, edição, mudança de estado, contatos, endereços, notas e merge passam
por services transacionais. Criação e merge gravam eventos reais na outbox;
alterações relevantes geram `AuditEvent` sanitizado. Conteúdo de nota,
documento, telefone e e-mail não entra no payload de auditoria ou outbox.

O merge bloqueia origem e destino em ordem determinística, exige a mesma
organização, move relações sem apagar dados e deixa a origem inativa apontando
para o registro canônico.

## Quick-order

Na Fase 10, Orders pode solicitar criação de Customer como parte de uma única
operação de quick-order. A identidade continua pertencendo a Customers:

- documento exato reutiliza o Customer canônico quando encontrado;
- contato exato pode sugerir um cadastro existente, mas não autoriza merge
  automático;
- nome semelhante nunca é suficiente para merge;
- se for necessária criação, ela usa o service canônico de Customers dentro da
  transação do quick-order;
- a idempotência é reclamada antes da criação inline para que retry não duplique
  Customer nem Order.

## Importação e exportação CSV

A Fase 10 adiciona transferência CSV Organization-scoped. Importação não grava
linhas diretamente por ORM fora das regras do domínio: cada Customer continua
sendo criado pelos services canônicos.

O import é transacional e valida cabeçalho, limite de linhas, tipos e regras do
Customer antes de concluir o lote. Um erro cancela o lote inteiro.

Retries do mesmo lote concluído são seguros. `platform` mantém receipts de lote
e linha usando digests HMAC opacos e IDs técnicos; conteúdo do CSV, nome,
documento, e-mail ou telefone não é persistido nesses receipts. O mesmo arquivo
concluído é reconhecido como já importado, evitando duplicação mesmo quando uma
linha não possui documento.

A exportação preserva o formato CSV e aplica Organization scope e mascaramento
por papel. XLSX permanece uma evolução de produto/documentação e não altera o
contrato canônico enquanto não houver implementação aprovada e dependência
travada.

## Interface e API

O domínio oferece páginas HTML em `/customers/`, incluindo cadastro, detalhe,
importação e exportação CSV, sem API pública. Não existe compatibilidade de
runtime/dados com Flowlog nem chamada a provider externo.
