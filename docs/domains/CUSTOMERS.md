# Domínio Customers

## Escopo da Fase 2

`apps.customers` é o cadastro operacional de pessoas físicas e jurídicas de
uma `Organization`. O domínio não contém pedidos, CRM de prospecção,
campanhas, importadores ou compatibilidade com o Flowlog.

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

## Autorização e isolamento

Selectors recebem `organization` explicitamente. Views resolvem a organização
ativa da sessão e revalidam uma `Membership` ativa. A organização nunca é
autorizada apenas por um identificador enviado pelo cliente.

Qualquer Membership ativa pode consultar, criar e editar registros. Somente
`OWNER`, `ADMIN` e `MANAGER` podem mesclar clientes ou bloquear cadastros.
Dados pessoais são mascarados para `OPERATOR` na tela de detalhe.

## Services e eventos

Criação, edição, mudança de estado, contatos, endereços, notas e merge passam
por services transacionais. Criação e merge gravam eventos reais na outbox;
alterações relevantes geram `AuditEvent` sanitizado. Conteúdo de nota,
documento, telefone e e-mail não entra no payload de auditoria ou outbox.

O merge bloqueia origem e destino em ordem determinística, exige a mesma
organização, move relações sem apagar dados e deixa a origem inativa apontando
para o registro canônico.

## Interface e API

A Fase 2 oferece páginas HTML em `/customers/`, sem API pública. A API,
credenciais e importadores pertencem à futura fase de Integrations e não são
transportados apenas por existirem no repositório de referência.

Após o aceite desta fase, este domínio deixa de consultar o Flowlog como
referência ativa.
