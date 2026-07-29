# ADR-007 — Adiar ProductImage

Status: aceito para a Fase 2.

## Contexto

O PRD prevê imagens no catálogo, mas o contrato detalhado posiciona imagens e
dimensões para uma fase posterior. A implementação auditada no Flowlog não
possui um `ProductImage` funcional. Nesta fase não há requisito operacional
que justifique definir storage, formatos, limites, retenção e processamento.

## Decisão

Não criar model incompleto, campo de upload ou URL externa. Não instalar
Pillow e não copiar mídia. ProductImage será especificado em fase futura com
política de tamanho/formato, isolamento por organização, storage e segurança
de conteúdo aprovados.

## Consequências

O catálogo da Fase 2 funciona sem imagens. A decisão evita cristalizar um
contrato de armazenamento prematuro ou introduzir processamento pesado no
request.
