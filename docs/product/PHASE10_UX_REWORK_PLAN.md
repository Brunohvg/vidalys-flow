# Fase 10 — Plano de Rework de UX orientado pelo Flowlog

## Objetivo

Reformular a experiência operacional do Vidalys Flow usando como referência a lógica de uso já validada no Flowlog, sem reutilizar código, banco, runtime, infraestrutura, secrets, identidade técnica ou lifecycles do sistema legado.

O princípio é simples: o usuário trabalha por tarefa e por pedido; a aplicação continua delegando cada mutação ao domínio canônico proprietário.

## Regras invariantes

- O Order Workspace é o centro operacional da venda.
- Orders, Payments, Fulfillment e Messaging mantêm lifecycles independentes.
- A UI nunca replica regra de negócio que pertença a service/policy canônico.
- Toda leitura e mutação permanece Organization-scoped.
- Pagamento usa o total confirmado persistido do Order; dinheiro não vem confiado do browser.
- PIX configurado é instrução operacional, não evidência de pagamento.
- Provider real, sandbox, callback público, credencial real e efeito externo permanecem proibidos na Fase 10.
- PII, masking, autorização, idempotência, concorrência, auditoria e fail-closed não podem ser reduzidos por decisão visual.

## Referência operacional do Flowlog

A lógica validada a preservar é:

1. criação simples;
2. após criar, redirecionar para o detalhe do pedido;
3. o detalhe é a superfície principal de operação;
4. editar/atualizar um pedido retorna ao próprio detalhe;
5. mudanças de entrega, pagamento, despacho, retirada, cancelamento e comunicação são ações contextuais do pedido;
6. o usuário não precisa navegar por módulos técnicos para concluir uma operação cotidiana.

## Arquitetura de experiência aprovada para o rework

### Navegação principal

Menu cotidiano reduzido para:

- Dashboard
- Pedidos
- Clientes
- Produtos
- Relatórios
- Configurações

`Nova venda` deve existir como ação principal destacada, não como mais um módulo técnico.

Payments, Fulfillment, Messaging e Integrations deixam de ser destinos primários da operação diária. Suas páginas continuam disponíveis para administração, pesquisa avançada, diagnóstico ou operações globais quando necessárias.

### Nova venda

A criação deve pedir somente o necessário para iniciar a venda:

- cliente existente por autocomplete ou cliente novo inline;
- produtos/variantes opcionais, ou valor manual;
- somente campos mínimos indispensáveis ao contrato canônico.

Após criação bem-sucedida, o usuário cai no Order Workspace.

Informações secundárias são completadas progressivamente dentro do pedido.

### Order Workspace

A página do pedido deve concentrar:

- cabeçalho com número, cliente, total e estados canônicos resumidos;
- próxima ação contextual;
- cliente;
- itens e preço;
- pagamento manual;
- instruções PIX;
- hosted checkout: criar, abrir, copiar, enviar e cancelar;
- fulfillment de retirada/entrega;
- tracking: definir, copiar e enviar;
- comunicação contextual;
- impressão operacional;
- timeline sanitizada.

As ações devem preferir operação inline, modal ou painel contextual e retornar ao próprio pedido.

### Impressão

Adicionar superfície de impressão contextual ao pedido, começando por:

- etiqueta de entrega/retirada;
- resumo do pedido.

A impressão é representação de dados canônicos existentes e não cria lifecycle novo. Deve respeitar Organization e masking/PII.

### Mobile

No mobile, substituir a exposição da sidebar completa por navegação curta orientada a tarefas. Prioridade:

- Início
- Pedidos
- Nova venda
- Clientes
- Mais

## Plano de execução

### UX-01 — Simplificar shell e navegação

- reduzir menu principal;
- destacar Nova venda;
- mover áreas técnicas para Configurações/links contextuais;
- manter rotas técnicas existentes sem torná-las parte da navegação cotidiana;
- preparar identidade visual Vidalys.

Critério de saída: usuário comum não precisa escolher Payments, Fulfillment ou Messaging no menu para operar um pedido.

### UX-02 — Reformular Nova venda

- reduzir campos obrigatórios aparentes;
- cliente inline/autocomplete;
- produto/variante/SKU/barcode em uma única busca;
- venda manual simples;
- criação redireciona ao Order Workspace;
- detalhes secundários progressivos.

Critério de saída: venda simples pode ser iniciada em poucos campos e o restante é resolvido no pedido.

### UX-03 — Consolidar edição e atualização no Order Workspace

- editar informações permitidas sem abandonar o pedido;
- adicionar/remover itens conforme lifecycle e contrato;
- ações válidas aparecem conforme estado e autorização;
- preservar concorrência/versionamento/idempotência.

Critério de saída: fluxo equivalente ao padrão create -> detail -> contextual updates do Flowlog, com services canônicos Vidalys.

### UX-04 — Pagamentos dentro do pedido

- registrar pagamento manual inline;
- mostrar/copiar/enviar PIX inline;
- criar/copiar/abrir/enviar/cancelar hosted checkout inline;
- remover dependência de navegação para Payments no caminho comum;
- hardening da autorização também na service layer.

Critério de saída: operação financeira cotidiana vinculada ao pedido é concluída no Order Workspace sem lifecycle paralelo.

### UX-05 — Fulfillment e tracking dentro do pedido

- retirada/entrega e próximas ações contextuais;
- tracking inline;
- envio do tracking via Messaging;
- sem exigir navegação para Fulfillment no caminho comum.

Critério de saída: preparação, retirada, despacho e rastreio são operáveis no pedido.

### UX-06 — Comunicação contextual

- confirmação, PIX, checkout e rastreio enviados a partir do contexto do pedido;
- Messaging mantém consentimento, template, policy, idempotência, auditoria e provider fail-closed.

Critério de saída: usuário pensa em `Enviar ao cliente`, não em navegar para o módulo Messaging.

### UX-07 — Etiqueta e impressão

- etiqueta contextual;
- resumo do pedido;
- layout print-friendly;
- testes de Organization/PII.

### UX-08 — Dashboard e lista de pedidos

- dashboard orientado ao trabalho pendente;
- lista com busca/filtros e próximas ações claras;
- acesso rápido a pedido/código/cliente/retirada;
- eliminar informação técnica desnecessária.

### UX-09 — Identidade visual e responsividade

- aplicar logo oficial Vidalys Flow quando o asset aprovado estiver disponível no repositório;
- usar design tokens coerentes com a identidade já aprovada;
- revisar login, shell, cards, tabelas, formulários, feedback e mobile.

### UX-10 — Pendências funcionais finais da Fase 10

Depois do núcleo operacional validado:

- workflow completo de importação;
- estratégia CSV/XLSX sem dependência não aprovada;
- autocomplete explícito de ProductVariant;
- revisão final de terminologia Organization;
- relatórios e acabamento.

## Estratégia de validação

Cada incremento deve:

1. preservar contratos e rotas canônicas;
2. adicionar/ajustar testes comportamentais;
3. rodar Foundation CI;
4. somente avançar após base verde ou diagnóstico explícito;
5. ser validado manualmente no ambiente local antes de candidato visual final.

Ao fim do rework:

- self-audit contra `PRODUCT_EXPERIENCE.md` e manifest da Fase 10;
- Foundation CI completa;
- candidato visual;
- revisão visual humana;
- apenas depois, handoff para Independent Review em sessão separada.
