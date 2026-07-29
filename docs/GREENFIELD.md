# Fundação greenfield

A Vidalys Flow é a sucessora funcional do Flowlog, mas é tecnicamente
independente. Não consulta, importa, migra ou compartilha dados, runtime,
autenticação ou infraestrutura com o Flowlog.

O Flowlog é apenas referência temporária durante a reconstrução. Seu código,
histórico Git, migrations, banco, Redis, usuários, IDs, media, secrets e
configuração de deploy não pertencem a este produto.

O banco `vidalys_flow` começa vazio. Toda entidade nasce diretamente neste
sistema. Não existe ETL, sincronização ou reconciliação entre produtos.

Cada domínio futuro deixará de consultar a referência antiga quando possuir
contrato documentado, migrations novas, testes em PostgreSQL, isolamento por
organização e revisão de segurança no presente repositório.
