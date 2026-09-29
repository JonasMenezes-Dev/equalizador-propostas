# Equalizador de Propostas

Aplicação para normalizar, comparar e recomendar propostas comerciais de fornecedores a partir de planilhas Excel.

O projeto transforma dados de cotações em uma análise técnica e comercial auditável. Ele identifica abas e colunas, equaliza os itens cotados, calcula indicadores, classifica fornecedores e gera um relatório Excel com tabelas, alertas e insights.

## Funcionalidades

- Importação de arquivos `.xlsx`, `.xlsm`, `.xltx` e `.xltm`.
- Detecção automática de abas e colunas em português e inglês.
- Normalização de preços, quantidades, unidades e condições comerciais.
- Comparação entre o item solicitado e o item ofertado.
- Identificação de itens não cotados, divergências e propostas inelegíveis.
- Recomendação de um fornecedor por item quando existe uma opção elegível.
- Consideração conjunta de preço, similaridade, atributos e condições comerciais.
- Análise do prazo de entrega, prazo de pagamento, frete e pedido mínimo.
- Interface web local para upload da planilha e download do relatório.
- Execução por linha de comando para automação e processamento sem navegador.
- Relatório Excel com mapa comparativo, ranking, recomendações, alertas e análise da fonte.

## Regra de recomendação
O score final usa os pesos definidos em `src/equalizador/config.py`:

```text
Score Recomendação =
    30% x Score Preço
  + 20% x Score Similaridade
  + 20% x Score Atributos
  + 30% x Score Comercial
```

O fornecedor recomendado precisa atender aos critérios de elegibilidade técnica e possuir preço válido. O menor prazo de entrega melhora o score comercial; entrega imediata recebe a melhor pontuação de prazo quando essa informação está disponível. O prazo não substitui o preço: a escolha considera o conjunto dos critérios e seus pesos.

O score comercial combina prazo de pagamento, prazo de entrega e frete. Um critério que a planilha não informa é tratado como neutro (peso zero na média), e não como penalidade; quando nenhuma dimensão comercial foi informada, o fornecedor recebe o valor neutro de 50 pontos. Frete ausente também não é confundido com frete negado: o relatório distingue "frete não informado" de "frete não incluso por conta do comprador".

Em caso de empate técnico, o sistema aplica desempates determinísticos por score, preço, similaridade, atributos, condições comerciais e nome do fornecedor.

## Requisitos

- Windows, Linux ou macOS.
- Python 3.10 ou superior.
- Acesso para instalar as dependências do projeto.

## Instalação

```bash
git clone https://github.com/<JonasMenezes-Dev>/equalizador-propostas.git
cd equalizador-propostas
```

Crie e ative um ambiente virtual:

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Linux ou macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Execução
### Interface web
Inicie o servidor na raiz do projeto:

```bash
python -m uvicorn app:app --reload
```

Abra `http://127.0.0.1:8000` no navegador. A interface permite selecionar uma planilha, informar opcionalmente o nome da aba e baixar o relatório processado.

No Windows, também é possível dar duplo clique em `abrir_app.bat`. O inicializador cria o ambiente virtual quando necessário, instala as dependências, sobe o servidor e abre o navegador automaticamente.

### Linha de comando
Sem argumentos, o comando processa o cenário de demonstração (não exige nenhuma planilha de entrada):

```bash
python main.py
```

Para processar uma planilha:

```bash
python main.py caminho/para/propostas.xlsx --saida output/relatorio.xlsx
```

Para selecionar uma aba específica:

```bash
python main.py caminho/para/propostas.xlsx --aba Cotacao --saida output/relatorio.xlsx
```

Se `--saida` não for informado, o relatório será salvo na pasta `output/`.

## Formato da planilha

O ingestor procura semanticamente campos equivalentes aos seguintes dados:

- identificador do item;
- descrição do item;
- quantidade;
- unidade;
- preço unitário;
- fornecedor;
- prazo de entrega;
- prazo de pagamento;
- frete;
- pedido mínimo;
- atributos técnicos, quando existirem.

Os nomes das colunas não precisam ser idênticos. O detector semântico aceita variações comuns em português e inglês. Para arquivos com mais de uma aba ou estrutura incomum, informe a aba pela interface ou pelo argumento `--aba`.

Arquivos de entrada de uso local podem ser colocados em `data/propostas/`. Essa pasta é ignorada pelo Git para evitar o envio de dados comerciais, mantendo apenas o arquivo `.gitkeep`.

## Saídas
Os relatórios são gerados em `output/`, que também é ignorada pelo Git. O arquivo Excel entregue é tabular (sem gráficos embutidos) e contém as seguintes leituras:

- Dashboard;
- Resumo e análise executiva;
- Ranking executivo;
- Mapa comparativo;
- Preços por fornecedor;
- Fornecedores;
- Condições comerciais;
- Recomendações;
- Base da recomendação;
- Alertas e insights;
- Perfil da fonte;
- Produtos e fornecedores analisados;
- Linhas descartadas (com o motivo de cada linha ignorada);
- Referência da matriz, quando identificada.

As leituras visuais (gráficos) ficam na interface web, não no arquivo Excel. O relatório exportado prioriza tabelas auditáveis e reutilizáveis.

## Arquitetura

```text
app.py                         API FastAPI e arquivos estáticos
main.py                        entrada da linha de comando
iniciar_app.py                 inicializador local para Windows
web/                           interface web
src/equalizador/
  config.py                    pesos e limites do motor
  models.py                    modelos de domínio
  semantic_engine.py           classificação semântica de colunas
  structure_detector.py        detecção de estrutura das planilhas
  normalization.py             leitura e normalização do Excel
  equalization.py              equalização técnica
  commercial.py                indicadores e score comercial
  recommendation.py            elegibilidade, score e ranking
  analysis.py                  indicadores, alertas e insights
  source_analysis.py           análise de fontes e histórico
  excel.py                     relatório Excel (somente tabelas)
  pipeline.py                  orquestração do processamento
tests/                         testes automatizados
```

## API HTTP

| Método | Rota                                | Função                                                                                             |
| ------ | ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `GET`  | `/api/health`                       | Retorna `status`, `service: "equalizador"` e o `build` (hash da aplicação)                         |
| `POST` | `/api/process`                      | Recebe a planilha (`multipart`) e a aba opcional (`?sheet=`); devolve o payload completo da análise |
| `GET`  | `/api/reports/{result_id}/download` | Baixa o relatório Excel gerado                                                                     |

Limite de upload: 50 MB. Os relatórios ficam em memória e são descartados quando o servidor reinicia.

## Testes

Com o ambiente virtual ativado, execute:

```bash
pytest -q
```

Os testes verificam a fórmula do score, os limites dos componentes, a elegibilidade, o desempate, a normalização, a importação de Excel e o fluxo completo do pipeline.

## Desenvolvimento
Antes de propor uma alteração:

1. Crie um ambiente virtual e instale as dependências.
2. Execute a suíte de testes.
3. Teste a interface com uma planilha fictícia ou sem dados sensíveis.
4. Confirme que arquivos gerados, ambientes virtuais e dados comerciais permanecem ignorados pelo Git.

O projeto não deve receber arquivos reais de propostas, relatórios gerados, credenciais ou configurações locais.

## Licença
Distribuído sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para os termos completos. Os dados de propostas usados nas validações devem ser fictícios ou autorizados para uso no ambiente de desenvolvimento.
