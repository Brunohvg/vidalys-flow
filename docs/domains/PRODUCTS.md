# Domínio Products

## Escopo canônico

`apps.products` é um catálogo operacional opcional por `Organization`. Ele não
controla estoque, compras, fornecedores, custos, fiscal ou produção. A Fase 2
estabeleceu o catálogo e suas regras; a Fase 10 acrescenta autocomplete e
transferência de cadastros sem criar sincronização externa ou novo domínio de
estoque.

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
Consultas, autocomplete, importação e exportação aplicam Organization scope e
mutações cross-organization retornam resposta segura.

## Services e eventos

Criação, edição, mudança de estado, criação de variante e identificadores
passam por services transacionais. Criação de produto grava
`product.created` na outbox. Edições e estados geram auditoria sanitizada.
Não existe I/O externo.

## Uso em Orders

Product e ProductVariant são opcionais para Orders. Pedidos itemizados podem
selecioná-los por autocomplete usando nome, SKU, código de barras ou
identificadores permitidos. Pedidos em `pricing_mode=manual` não exigem
Product nem OrderItem. Orders continua responsável por congelar os snapshots
comerciais no momento da confirmação.

## Importação e exportação CSV

A Fase 10 adiciona transferência CSV Organization-scoped. O import valida
cabeçalho, limite de linhas, `product_key`, nome e regras de SKU/barcode antes
de concluir o lote. Linhas com o mesmo `product_key` continuam agrupadas em um
único Product e suas variantes são criadas pelos services canônicos. Um erro de
qualquer linha cancela o lote transacionalmente.

Retries do mesmo lote concluído são seguros. `platform` mantém receipts de lote
e linha usando digests HMAC opacos e IDs técnicos; conteúdo do arquivo, nomes,
SKU ou códigos de barras não são copiados para os receipts. Reenvio do mesmo
arquivo concluído é reconhecido como já importado e não duplica Products ou
Variants.

A exportação preserva a representação determinística de Products/Variants e
nunca mistura Organizations. XLSX permanece uma evolução de
produto/documentação e não altera o contrato canônico enquanto não houver
implementação aprovada e dependência travada.

## Interface, API e imagens

O domínio oferece páginas HTML em `/products/`, incluindo cadastro, variantes,
identificadores, importação e exportação CSV, sem API pública e sem
sincronização externa.

`ProductImage` foi explicitamente adiado; ver ADR-007. Nenhuma mídia,
processamento de imagem, Pillow ou storage externo foi introduzido.

Não há reutilização de runtime, dados, IDs ou infraestrutura do Flowlog.
