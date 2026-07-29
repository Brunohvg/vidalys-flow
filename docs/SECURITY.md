# Segurança

## Isolamento

- autorização organizacional é feita por Membership ativa;
- todo dado operacional futuro deve possuir organização explícita;
- User não contém papel global de organização;
- a remoção do último OWNER ativo é recusada em transação;
- testes cross-organization são obrigatórios.

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
