# Auditoria histórica de Messaging/Evolution no Flowlog

Data: 12 de agosto de 2026

Referência congelada: `Brunohvg/Flowlog` no SHA
`31a3e7b8fe305b93cdcbcdfa7420b8e597412756`

Modo: somente leitura, autorizado explicitamente pelo humano

## Limite da consulta

A consulta ficou restrita aos models, contratos, dispatch, regras, templates,
adapter/client Evolution e testes de evento/provider/webhook de
`apps/messaging`, além das auditorias `docs/v2/*MESSAGING*` e
`docs/v2/EVOLUTION_API_AUDIT.md`. O módulo legado
`apps/integrations/whatsapp` e `apps/notifications` foi considerado somente por
meio da auditoria registrada e da árvore de arquivos, para identificar falhas.

Não foram acessados banco, Redis, runtime, `.env`, secrets, dados, contatos,
mensagens reais, templates reais, sessões, QR codes, endpoints ativos,
providers configurados, servidor ou infraestrutura. Nenhum arquivo do Flowlog
foi modificado e nenhum código foi copiado.

## O que funcionou como ideia

- domínio canônico neutro com provider registry e capabilities;
- separação entre conexão do provider e canal/instância do WhatsApp;
- Evolution API `WHATSAPP-BAILEYS` identificada como linked-device não oficial;
- nome de instância determinístico para reconciliar criação incerta;
- token próprio por canal, sem usar a chave global em cada envio;
- QR e pairing code efêmeros;
- cliente HTTP isolado, HTTPS, allowlist de host, defesa contra SSRF, sem
  redirects e sem retry automático;
- timeout de envio como `uncertain`, sem reenvio ou failover cego;
- correlação por provider connection + channel + message ID;
- deduplicação PostgreSQL e transições monotônicas;
- eventos da outbox recarregam o agregado em vez de confiar no payload;
- suite comum de contrato para cada provider.

Essas ideias serão redesenhadas sobre os contratos atuais da Vidalys Flow. Os
models, services, migrations, eventos, filas e estados do Flowlog não serão
transportados.

## O que foi rejeitado

O legado anterior apresentou problemas que não podem reaparecer:

- coexistência de duas camadas de notificação e um único client real oculto;
- credenciais de instância em texto claro no banco/admin;
- webhook sem autenticação real, deduplicação ou isolamento forte;
- handlers globais sujeitos a colisão de nomes e envio duplicado;
- métodos específicos por evento e templates livres espalhados;
- telefone corrigido por heurística regional;
- campanhas, engajamento e transacional misturados;
- acoplamento direto a domínios e execução por mecanismo de fila diferente.

A implementação atual usará somente a outbox/Celery da Vidalys Flow, aliases
opacos para secrets, templates fechados, normalização canônica existente,
Organization explícita e callbacks minimizados.

## Diferenças deliberadas do desenho posterior do Flowlog

- o Flowlog posterior persistia conteúdo renderizado; a Vidalys Flow não
  persistirá o body completo nesta fase;
- o Flowlog posterior persistia credenciais criptografadas; a Vidalys Flow
  manterá somente referências opacas a um canal de secrets;
- o Flowlog tratava `read` como estado; a Vidalys Flow manterá read/open/click
  fora do ciclo canônico para reduzir tracking e dependência do provider;
- o Flowlog permitia mídia; a Fase 06 limitará Evolution a texto/template e
  link, deixando anexos para decisão posterior;
- os onze tópicos do Flowlog não são copiados: o allowlist usa somente eventos
  realmente emitidos pelos domínios aprovados deste repositório.

## Conclusão

A Evolution API é compatível com o desenho provider-neutral se entrar como uma
opção explícita, não oficial e limitada. Ela não substitui a Meta Cloud API:
ambas são adapters WhatsApp distintos. Amazon SES continua como canal de
e-mail. Todos permanecem desligados durante implementação e CI.

Adoção em sandbox ou produção exige nova autorização, instalação exclusiva,
versão/licença revalidadas, secrets próprios, Security Review dos webhooks,
destinatários de teste e evidência sanitizada.
