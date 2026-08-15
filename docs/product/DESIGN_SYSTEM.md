# Vidalys Flow — Design System

## Direção

O Vidalys Flow deve parecer moderno, premium e operacional. A interface precisa favorecer leitura rápida, ações claras e densidade controlada sem aparência de ERP pesado.

## Princípios visuais

- base predominantemente clara;
- violeta/índigo como identidade principal de ação e destaque;
- texto principal em azul-marinho/grafite de alto contraste;
- cards com bordas suaves, raio consistente e sombras discretas;
- espaços generosos entre grupos e maior densidade apenas em tabelas operacionais;
- estados de sucesso, atenção, erro e informação distinguíveis também por ícone/texto, nunca só por cor;
- ações primárias únicas por contexto; ações secundárias visualmente subordinadas;
- responsividade real para desktop, tablet e mobile;
- acessibilidade de teclado, foco visível, labels e contraste adequados.

## Tipografia

A tipografia do protótipo inicial foi considerada simples demais. A Fase 10 deve avaliar uma família de maior personalidade para marca, headings e KPIs, preservando alta legibilidade operacional. A família final somente é congelada após revisão visual humana.

Regras mínimas:
- marca/heading: personalidade própria, peso forte e boa leitura;
- corpo/tabelas/forms: alta legibilidade em tamanhos pequenos;
- números monetários/KPIs: alinhamento e distinção claros;
- nenhuma fonte externa deve criar dependência insegura ou bloquear renderização; fallback de sistema obrigatório.

## Tokens conceituais

Os nomes semânticos abaixo são estáveis; valores exatos permanecem revisáveis:
- `surface-page`, `surface-card`, `surface-muted`;
- `text-primary`, `text-secondary`, `text-muted`;
- `brand-primary`, `brand-strong`, `brand-soft`;
- `success`, `warning`, `danger`, `info`;
- `border-default`, `border-strong`, `focus-ring`;
- escalas de spacing, radius, shadow e typography.

## Componentes prioritários

- sidebar/top navigation responsiva;
- page header e breadcrumbs quando necessários;
- KPI card;
- contextual action card / Próxima ação;
- tables com filtros e paginação;
- autocomplete/combobox acessível;
- money input;
- status badge;
- timeline;
- modal/dialog de confirmação;
- drawer de cadastro inline;
- upload/import wizard;
- empty state;
- toast/flash sanitizado;
- search command surface;
- QR/código de retirada;
- chart container com alternativa textual/tabular.

## Ordem visual de uma tela operacional

1. contexto e identidade da entidade;
2. estado atual;
3. próxima ação principal;
4. informação necessária para decidir;
5. histórico/ações secundárias;
6. detalhes técnicos apenas quando solicitados.

## Order Workspace

O workspace não deve exibir todas as ações simultaneamente. Ações válidas derivam dos estados/policies e a `Próxima ação` recebe maior peso visual. Pagamento, fulfillment e comunicação aparecem em cards separados para preservar boundaries conceituais.

## Formulário de pedido rápido

O formulário mínimo deve ficar visível primeiro: cliente, valor e método operacional. Endereço, itens e ajustes aparecem progressivamente. A conclusão da venda simples não pode exigir navegação para outra tela.

## Tabelas e relatórios

Tabelas devem oferecer filtros claros, cabeçalho fixo quando útil, estados vazios e exportação separada. Gráficos são complementares; valores essenciais também precisam existir em texto/tabela.

## Revisão humana

Layout, tipografia, cores secundárias, radius, sombras, posição de cards, labels e logo permanecem revisáveis durante a Fase 10. Uma primeira implementação não congela a decisão visual.
