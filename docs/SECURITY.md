# Segurança

## Isolamento

- autorização organizacional é feita por Membership ativa;
- todo dado operacional deve possuir organização explícita;
- User não contém papel global de organização;
- a remoção do último OWNER ativo é recusada em transação;
- testes cross-organization são obrigatórios.
- a organização ativa da sessão é revalidada contra Membership a cada uso;
- IDs de Customer e Product são sempre resolvidos dentro da organização;
- services recusam ator sem Membership ativa, mesmo fora das views.

## Dados pessoais

- CPF/CNPJ existe somente no cadastro de Customer e é necessário ao contrato;
- documento é único apenas por organização;
- telefone e e-mail não são globalmente únicos;
- `OPERATOR` recebe documento e contatos mascarados no detalhe;
- conteúdo de nota, documento e contatos não entram em auditoria/outbox;
- snapshots de pedido com documento, contato e endereço usam schema fechado,
  não entram em logs/auditoria/outbox e são mascarados para `OPERATOR`;
- nome semelhante nunca inicia merge automático;
- merge exige papel gerencial, motivo, locks e auditoria.

## Catálogo

- SKU e identificadores possuem constraints por organização;
- escrita cross-organization é recusada pelo service;
- ProductImage foi adiado até existir política aprovada de upload e storage;
- não há preço, estoque, importador ou integração externa nesta fase.

## Secrets

- `.env` não é versionado;
- exemplos contêm somente placeholders;
- logs e auditoria não recebem senhas, tokens, cookies ou credenciais;
- o payload de auditoria e outbox é sanitizado antes da persistência;
- o scanner local cobre assinaturas comuns sem imprimir valores.

## Efeitos externos

`VIDALYS_DEMO_MODE=1` bloqueia publishers externos. A ausência da variável
em produção também bloqueia por padrão. Liberar efeitos no futuro exigirá
valor explícito, provider aprovado, credenciais por organização e testes.

O publisher desta fase é interno, determinístico e não executa I/O externo.

## Pedidos

- todo Order, item, histórico, sequência e recibo idempotente é organization-scoped;
- preço-base pode ser informado por qualquer Membership ativa, mas desconto,
  acréscimo, cancelamento e dados pessoais completos exigem manager tier;
- todo acréscimo exige motivo e não pode representar frete, tributo, juros ou
  taxa de pagamento;
- Customer mesclado e Product/Variant indisponível bloqueiam confirmação;
- motivos livres permanecem no agregado e nunca entram em AuditEvent ou OutboxEvent;
- admin é somente leitura para impedir que contorne services, locks e policies.
