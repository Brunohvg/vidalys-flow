# Estratégia de branches

`main` aponta para o último `approved_head`. O padrão futuro é:

```text
main
└── phase/<id>-<name>
```

Exemplos: `phase/03-orders`, `phase/04-fulfillment` e
`phase/05-payments`.

Cada fase nasce diretamente de `main` no SHA aprovado. Uma branch pertence a
um único agente ativo por vez. Review e QA devem evitar mutações; se uma
correção for autorizada, ela volta ao implementador ou ocorre em branch
separada com handoff explícito.

PR, merge, release e atualização de `main` só acontecem após aprovação
humana. Branches históricas são preservadas; não há force-push, rebase
destrutivo, exclusão ou criação da fase seguinte sobre candidato não
aprovado.
