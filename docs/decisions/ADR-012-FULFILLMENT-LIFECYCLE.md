# ADR-012 — Fronteira e ciclo de vida de Fulfillment

Status: implementado e ratificado na Fase 4.

## Contexto

Orders conserva somente os estados comerciais `draft`, `confirmed` e
`cancelled`. A execução física precisa representar entregas e retiradas,
inclusive parciais, sem contaminar Orders com estados logísticos ou introduzir
estoque e providers antes de suas fases.

## Decisão

Fulfillment é um agregado independente, pertencente à Organization e
dependente de um Order confirmado. Um Order pode possuir vários lotes,
identificados por sequência crescente dentro do pedido.

Os métodos são `delivery` e `pickup`. Os estados são `draft`, `preparing`,
`ready`, `in_transit`, `completed` e `cancelled`; `in_transit` existe apenas
para entrega. `completed` e `cancelled` são terminais e nunca são copiados
para `Order.status`.

Delivery copia o endereço já congelado no pedido. Pickup referencia uma
unidade organizacional ativa e congela seu nome. Não há endereço livre,
transportadora, estoque, pagamento ou efeito externo.

## Consequências

O progresso completo do pedido é uma leitura derivada das quantidades dos
lotes. Entregas parciais não exigem mudar o agregado comercial. Devolução,
falha de entrega e logística reversa ficam explicitamente adiadas.

Aceito inicialmente pela aprovação humana explícita do plano e ratificado após
implementação, Review e QA/Segurança em 8 de agosto de 2026. Isso não autoriza
deploy.
