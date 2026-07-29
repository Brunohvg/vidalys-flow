# ADR-002 — User nativo e Membership

Status: aceito.

## Decisão

`users.User` usa UUID e e-mail como identidade. O e-mail é normalizado para
minúsculas no manager/model e protegido no PostgreSQL por constraint
funcional case-insensitive.

Papéis pertencem à `organizations.Membership`, não ao User. Um usuário pode
participar de várias organizações. A organização pode possuir vários OWNERs,
mas o service impede desativar o último OWNER ativo sob lock transacional.
