# ADR-005 — Identidade e unicidade de Customer

Status: aceito para a Fase 2.

## Decisão

Customer usa UUID e pertence obrigatoriamente a uma Organization. CPF/CNPJ é
opcional, normalizado, validado e único por organização quando preenchido.
Telefone e e-mail são normalizados, mas não são únicos: uma organização pode
ter clientes distintos que compartilham um contato.

Identificação exata pode apresentar candidatos. Nome semelhante é apenas
sugestão e nunca provoca merge automático. Merge é uma operação explícita,
autorizada, transacional, auditada e preserva a origem como redirecionamento
lógico.

## Consequências

Não há identidade global entre organizações. Conflitos não são resolvidos
por sobrescrita silenciosa, e o futuro domínio Orders deverá criar snapshots
em vez de depender do cadastro mutável.
