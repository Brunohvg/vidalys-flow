# Vidalys Flow — Product Experience

## Objetivo

A Fase 10 conclui a experiência operacional antes do cutover. O produto deve favorecer a ação comum mais curta possível sem enfraquecer isolamento por Organization, autorização, privacidade, auditoria, idempotência, concorrência ou os lifecycles canônicos.

## Princípio

**O caminho comum deve ser o caminho mais curto.** Recursos avançados aparecem progressivamente apenas quando necessários.

## Criação rápida de pedido

A tela deve permitir registrar uma venda simples com cliente, valor e método de fulfillment em poucos campos. Produtos são opcionais.

- cliente existente: autocomplete Organization-scoped;
- cliente inexistente: criação inline e atômica com o Order;
- CPF/CNPJ exato pode identificar cadastro canônico; telefone/e-mail exatos são sugestões; nome semelhante nunca faz merge automático;
- endereço só aparece quando o método exigir entrega;
- lookup de CEP é opcional, neutro e sempre possui fallback manual;
- produto/variante/SKU/código de barras podem ser adicionados por autocomplete, mas nunca são pré-requisito para uma venda manual.

## Preço do pedido

`pricing_mode=manual` usa `manual_total` como fonte canônica e pode ter zero OrderItems.

`pricing_mode=itemized` usa exclusivamente a soma dos OrderItems pelas regras monetárias existentes.

Nenhum item fictício é criado. Mudança de modo ou divergência entre valor manual e itens exige escolha explícita do usuário; o sistema não reconcilia silenciosamente.

## Order Workspace

O detalhe do pedido é o centro operacional da venda. Ele compõe contexto e ações dos domínios, mas não cria um lifecycle paralelo.

### Próxima ação

Uma superfície contextual no topo exibe somente comandos válidos e autorizados no estado atual. Exemplos: confirmar pagamento manual, enviar instruções PIX, solicitar checkout hospedado, iniciar preparação, liberar retirada, confirmar retirada, marcar despacho, copiar/enviar rastreio.

A UI delega sempre ao service/policy do domínio proprietário.

## Pagamentos

### Pagamento manual/offline

Deve existir ação explícita para registrar recebimento por PIX direto, dinheiro, cartão presencial, transferência ou outro método permitido. Ela registra método, valor, ator e horário; nunca fabrica provider, external id ou callback.

### Instruções PIX

A Organization pode manter instruções PIX aprovadas em Configurações. Copiar ou enviar a chave não altera o estado financeiro.

### Checkout hospedado

Gerar, copiar, enviar e cancelar link usa o contrato de Payments. `Enviar` passa por Messaging e suas permissões/templates. Fase 10 não ativa provider real.

## Fulfillment

### Retirada

O workspace expõe ações contextualizadas sobre o lifecycle canônico de Fulfillment: iniciar preparação, deixar pronto e concluir retirada. A conclusão pode exigir código de retirada e/ou QR na UX, mas o comando final permanece do domínio Fulfillment.

### Entrega

Preparação, pronto, despacho e conclusão são apresentados sem criar estados novos em Order. Rastreio é mostrado e pode ser comunicado, permanecendo sob os boundaries de Fulfillment/Integrations/Messaging.

## Operação rápida e Central de Retiradas

Dashboard e Pedidos possuem busca rápida por pedido/código/cliente e acesso a QR quando aplicável. A Central de Retiradas lista apenas pickups elegíveis da Organization atual e otimiza uso em balcão/tablet.

## Timeline operacional

O detalhe do pedido apresenta histórico humano curto derivado de evidência canônica sanitizada. Audit completo permanece uma superfície administrativa separada.

## Clientes e Produtos

Clientes e Produtos recebem importação/exportação CSV/XLSX com upload, mapeamento, validação, preview, conflitos, confirmação e resultado. Importadores chamam as mesmas regras canônicas e não fazem gravação cega. Exportações respeitam Organization, papel e mascaramento de PII.

## Busca global e filtros salvos

Busca global cobre pedidos, clientes e produtos sempre na Organization ativa. Filtros salvos são consultas; nunca viram estado, tarefa ou workflow.

## Relatórios

Relatórios são read-only e derivados de dados canônicos. Períodos padrão: hoje, ontem, 7 dias, mês atual, mês anterior, ano e personalizado. Devem suportar comparação com período anterior e CSV/XLSX. Nenhum relatório altera dinheiro ou estados.

## Administração

Superfícies previstas: Meu Perfil, Usuários/Equipe, Configurações e Auditoria. Toda mutação respeita policies existentes e novas policies específicas quando necessárias.

## Margem de revisão de produto e UX

Composição de tela, agrupamento do menu, cards, rótulos, posição de ações, apresentação da Próxima ação, dashboard, relatórios, central de retirada, tipografia, cores secundárias, logo e layouts responsivos são propostas revisáveis dentro da própria Fase 10.

Rework humano de UX não é expansão indevida quando preserva objetivo e invariantes. Organization isolation, autorização, PII, idempotência, fonte canônica de dinheiro, lifecycles, audit sanitizado e guardrails de efeitos externos não podem ser tratados como mera decisão visual.

## Checkpoint visual

A sequência da fase inclui implementação funcional, candidato visual, revisão visual humana, rework visual autorizado, Independent Review, QA/Security e aprovação final humana. A primeira solução visual não é automaticamente definitiva.
