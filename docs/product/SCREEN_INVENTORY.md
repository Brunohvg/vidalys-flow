# Vidalys Flow — Inventário de telas da Fase 10

Este documento define as superfícies funcionais e a ordem lógica de navegação. Subtelas e modais podem ser consolidados visualmente durante a revisão humana, desde que as capacidades e boundaries permaneçam.

## Acesso e contexto

1. Login.
2. Seleção de Organization quando houver mais de uma Membership ativa.
3. Dashboard operacional.

## Operação

4. Pedidos — lista, busca, filtros e filtros salvos.
5. Novo Pedido — criação rápida com Customer inline, valor manual ou itens opcionais.
6. Pedido — detalhe/workspace consolidado.
7. Pedido — confirmação/cancelamento comercial conforme lifecycle de Orders.
8. Pedido — pagamento manual/offline conforme policy de Payments.
9. Pedido — gerar/copiar/enviar/cancelar checkout hospedado.
10. Pedido — copiar/enviar instruções PIX da Organization.
11. Pedido — iniciar/preparar/liberar fulfillment conforme lifecycle.
12. Pedido — despacho/tracking para delivery.
13. Pedido — validação e conclusão de retirada para pickup.
14. Central de Retiradas — fila read-only derivada e ação canônica de validação.
15. Fulfillment — lista.
16. Fulfillment — criação/edição de draft.
17. Fulfillment — detalhe/transições.
18. Pagamentos — lista.
19. Pagamento — detalhe/intents/attempts/ações autorizadas.

## Cadastros

20. Clientes — lista.
21. Cliente — novo/editar.
22. Cliente — detalhe.
23. Clientes — importar CSV/XLSX.
24. Clientes — exportar CSV/XLSX.
25. Produtos — lista.
26. Produto — novo/editar.
27. Produto — detalhe/variantes/identificadores.
28. Produtos — importar CSV/XLSX.
29. Produtos — exportar CSV/XLSX.

## Comunicação e integrações

30. Mensagens — lista.
31. Mensagem — detalhe.
32. Mensagem — envio transacional autorizado.
33. Canais/conexões/templates/preferências/regras de Messaging conforme contratos atuais.
34. Integrações — conexões/endpoints/estado operacional e reconciliação autorizada.

## Análise

35. Relatórios — visão de pedidos/vendas por período.
36. Relatórios — detalhamento e exportação.

## Administração e conta

37. Usuários/Equipe — lista.
38. Usuário/Membership — detalhe e papel.
39. Configurações — visão geral.
40. Configurações — Organização e Unidades.
41. Configurações — Pagamentos/PIX.
42. Configurações — Pedidos/Fulfillment quando houver parâmetro canônico configurável.
43. Configurações — Messaging/Integrations por links para os domínios proprietários.
44. Auditoria — timeline administrativa filtrável e sanitizada.
45. Meu Perfil.

## Componentes globais

- busca global Organization-scoped;
- operação rápida na Dashboard e em Pedidos;
- Próxima ação contextual no Order Workspace;
- notificações/feedback de comando sem expor payload sensível;
- navegação responsiva desktop/tablet/mobile;
- estados vazios, erros seguros e confirmação de ações destrutivas.

## Fora do inventário

Não são módulos contratados: Processos, Tarefas, Solicitações, CRM de prospecção, ERP, estoque, fiscal, contabilidade ou marketing. Attention queues e filtros não criam modelos de tarefa/workflow.
