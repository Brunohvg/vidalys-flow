# Domínio Products

## Escopo da Fase 2

`apps.products` é um catálogo operacional opcional por `Organization`. Ele
não controla estoque, compras, fornecedores, custos, fiscal, produção,
importação ou sincronização externa.

## Models

- `Product`: nome, descrição, estado e unidade operacional;
- `ProductVariant`: variação, SKU, código de barras e estado;
- `ProductIdentifier`: identificadores adicionais de produto ou variante.

Os estados canônicos são `active`, `inactive` e `archived`. SKU é aparado e
convertido para maiúsculas pelo service; uma constraint funcional no
PostgreSQL também garante unicidade case-insensitive por organização.
Identificadores são normalizados por tipo e únicos por organização, tipo e
valor.

## Autorização e isolamento

Selectors sempre recebem `organization`. Views resolvem a organização ativa
da sessão e revalidam a Membership. Qualquer Membership ativa pode consultar,
criar e editar o catálogo; arquivamento exige `OWNER`, `ADMIN` ou `MANAGER`.
Consultas e mutações cross-organization retornam resposta segura.

## Services e eventos

Criação, edição, mudança de estado, criação de variante e identificadores
passam por services transacionais. Criação de produto grava
`product.created` na outbox. Edições e estados geram auditoria sanitizada.
Não existe I/O externo.

## Interface, API e imagens

A Fase 2 oferece páginas HTML em `/products/`, sem API pública. Referências
externas e importadores ficam para Integrations.

`ProductImage` foi explicitamente adiado; ver ADR-007. Nenhuma mídia,
processamento de imagem, Pillow ou storage externo foi introduzido.

Após o aceite desta fase, este domínio deixa de consultar o Flowlog como
referência ativa.
