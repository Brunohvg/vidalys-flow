# ADR-012 — Fronteira e ciclo de vida de Fulfillment

Status: aceito para implementação na Fase 4.

## Contexto

Orders conserva somente os estados comerciais `draft`, `confirmed` e
`cancelled`. A execução física precisa representar entregas e retiradas,
inclusive parciais, sem contaminar Orders com estados logísticos ou introduzir
estoque e providers antes de suas fases.

## Decisão proposta

Fulfillment será um agregado independente, pertencente à Organization e
dependente de um Order confirmado. Um Order poderá possuir vários lotes,
identificados por sequência crescente dentro do pedido.

Os métodos serão `delivery` e `pickup`. Os estados serão `draft`, `preparing`,
`ready`, `in_transit`, `completed` e `cancelled`; `in_transit` existirá apenas
para entrega. `completed` e `cancelled` serão terminais e nunca serão copiados
para `Order.status`.

Delivery copiará o endereço já congelado no pedido. Pickup referenciará uma
unidade organizacional ativa e congelará seu nome. Não haverá endereço livre,
transportadora, estoque, pagamento ou efeito externo.

## Consequências

O progresso completo do pedido será uma leitura derivada das quantidades dos
lotes. Entregas parciais não exigem mudar o agregado comercial. Devolução,
falha de entrega e logística reversa ficam explicitamente adiadas.

Aceito pela aprovação humana explícita do plano em 8 de agosto de 2026. Isso
não aprova implementação, merge ou deploy.
