# Papéis

## Planning Agent

Atua somente em leitura, audita a referência permitida, cria o plano,
identifica riscos e não modifica código de domínio.

## Implementation Agent

Implementa apenas o plano e o escopo aprovados. Produz um candidato e um
handoff estruturado, sem alterar o estado oficial ou aprovar o próprio
trabalho.

## Review Agent

É independente do implementador e preferencialmente somente leitura. Revisa
arquitetura, segurança, regressões e escopo; registra achados e não corrige
silenciosamente o candidato.

## QA and Security Agent

Executa testes, valida migrations, concorrência, isolamento, secret scan e
independence scan. Emite GO ou NO-GO técnico, nunca aprovação da fase.

## Human Approver

É o único papel que aprova plano e fase, autoriza PR, merge ou release e pode
atualizar os campos oficiais de aprovação.

## Release Agent

Atua somente após aprovação humana. Prepara PR, merge ou deploy autorizado e
nunca aprova a fase em que trabalha.
