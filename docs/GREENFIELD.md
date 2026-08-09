# Fundação greenfield

A Vidalys Flow é a sucessora funcional do Flowlog, mas é tecnicamente
independente. Não consulta, importa, migra ou compartilha dados, runtime,
autenticação ou infraestrutura com o Flowlog.

O Flowlog é apenas referência temporária durante a reconstrução. Seu código,
histórico Git, migrations, banco, Redis, usuários, IDs, media, secrets e
configuração de deploy não pertencem a este produto.

Não haverá API de sincronização, ponte de autenticação, compartilhamento de
infraestrutura ou dependência operacional entre os produtos. O encerramento
futuro do sistema antigo é uma decisão operacional separada e não autoriza
migração, importação ou integração.

O banco `vidalys_flow` começa vazio. Toda entidade nasce diretamente neste
sistema. Não existe ETL, sincronização ou reconciliação entre produtos.

Cada domínio deixa de consultar a referência antiga somente depois de possuir
contrato greenfield aprovado, migrations novas, testes em PostgreSQL,
isolamento por organização, Review e QA/Segurança concluídos no presente
repositório. Orders e Fulfillment já concluíram esse processo. O planejamento
e a implementação de Fulfillment foram produzidos apenas com os contratos da
Vidalys Flow e não consultaram o Flowlog.
