# Visão futura de Payments

Payments pertence à Fase 05 e não está implementado. Este documento registra
uma direção de produto para planejamento futuro, não um contrato técnico já
aprovado.

## Direção proposta

- Mercado Pago e Pagar.me: primeiros conectores planejados para geração de
  links de pagamento;
- Appmax: conector posterior, depois que o núcleo canônico e os primeiros
  conectores estiverem estabilizados;
- nenhum provider será o modelo de domínio: a Vidalys Flow terá estados,
  comandos e identificadores canônicos próprios;
- a ordem exata entre Mercado Pago e Pagar.me será decidida no planejamento da
  Fase 05 conforme conta comercial, sandbox, custos, meios de pagamento e
  requisitos operacionais disponíveis naquele momento.

## Fluxo esperado

```text
Order elegível
  → PaymentIntent canônico
  → solicitação idempotente ao adapter do provider
  → link retornado e armazenado sem segredo
  → cliente paga no checkout hospedado pelo provider
  → webhook autenticado
  → evento persistido e deduplicado
  → estado financeiro canônico atualizado
  → audit/outbox sanitizados
```

## Guardrails obrigatórios

- Organization derivada da Membership; nunca aceita livremente do request;
- credenciais distintas por ambiente e nunca versionadas;
- assinatura e origem de webhook verificadas antes do processamento;
- idempotência tanto na criação do link quanto na recepção de eventos;
- nenhuma captura ou armazenamento de número completo de cartão/CVV;
- valores recalculados no servidor e comparados com o Order elegível;
- logs, audit e outbox sem tokens, documentos ou payloads sensíveis;
- timeout, retry controlado, reconciliação e tratamento de eventos fora de
  ordem;
- sandbox e testes de contrato antes de habilitar produção;
- nenhum endpoint, credencial, webhook ou máquina do Flowlog será reutilizado.

## Decisões ainda necessárias na Fase 05

- provider inicial e sequência de rollout;
- Pix, boleto e cartão disponíveis em cada conector;
- expiração, cancelamento, reembolso e reconciliação;
- taxas, parcelamento e responsabilidade por juros;
- vínculo entre Order, Fulfillment e estado financeiro;
- política de fallback entre providers;
- modelo de webhook, retenção e suporte operacional.

