# ADR-009 — Dinheiro em Orders

Status: aceito para a Fase 3.

## Decisão

Orders usa BRL, Decimal(14,2) para dinheiro, Decimal(12,3) para quantidade e
`ROUND_HALF_UP`. Cada bruto de linha é arredondado antes de descontos e
acréscimos; os agregados somam os valores persistidos das linhas.

Acréscimo exige motivo comercial e não representa frete, tributo, juros ou
taxa de pagamento. Somente manager tier aplica desconto ou acréscimo.

## Consequências

Não há float nem cálculo autoritativo no cliente. Frete, impostos e efeitos
financeiros futuros não contaminam os totais comerciais desta fase.
