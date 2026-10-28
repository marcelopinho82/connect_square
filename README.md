# Gap Tesouro Direto × Patrimar

Aplicativo analítico interativo desenvolvido em **Streamlit** e **Plotly** para acompanhamento contínuo e projeção da estratégia de quitação imobiliária à vista do financiamento da construtora **Patrimar** através de aplicações no **Tesouro Direto (Tesouro IPCA+ / NTN-B)**.

O objetivo financeiro é alcançar o ponto de neutralidade da dívida (**Gap = 0**) na data prevista para a entrega das chaves (**31/07/2030**):

```
Gap = Saldo devedor − Valor líquido
```

- **Gap positivo**: Montante que ainda **falta acumular** em investimentos para quitar a dívida integralmente à vista.
- **Gap zero ou negativo**: Patrimônio líquido suficiente para quitação integral da dívida imobiliária.

A série histórica é construída automaticamente a partir da leitura e consolidação dos arquivos brutos depositados na pasta `arquivos/`.

---

## 📁 Estrutura do Projeto

```
Downloads/
├── app.py                     # Interface gráfica Streamlit, KPIs, gráficos e abas analíticas
├── README.md                  # Documentação completa da aplicação
├── arquivos/                  # Diretório de entrada dos arquivos XLSX (Tesouro) e CSV (Patrimar)
└── tesouro_gap/
    ├── __init__.py
    ├── models.py              # Modelos de dados imutáveis (RegistroDiario, PontoHistorico)
    ├── processor.py           # GapProcessor: deduplicação diária, consolidação e cálculo do Gap
    ├── utils.py               # Extração de data/hora via regex e formatação monetária (pt-BR)
    ├── readers/
    │   ├── __init__.py        # Exportação de leitores
    │   ├── tesouro_reader.py  # TesouroReader: leitura de extratos XLSX e rentabilidade ponderada
    │   └── patrimar_reader.py # PatrimarReader: leitura de CSVs e composição do saldo devedor
    └── requirements.txt       # Dependências do projeto (streamlit, pandas, plotly, openpyxl)
```

---

## ⚙️ Regras de Negócio e Processamento de Dados

### 1. Tesouro Direto (`ExtratoAnalitico_*.xlsx`)
- **Identificação**: Lê todas as planilhas iniciadas pelo prefixo `ExtratoAnalitico_`.
- **Cabeçalho dinâmico**: Localiza a linha do cabeçalho que contém `Valor líquido` inspecionando as primeiras 20 linhas e unificando cabeçalhos multi-nível (*multi-index*).
- **Valor Líquido Oficial**: A linha identificada como **`TOTAL`** (ou a última linha da planilha) expressa a posição consolidada líquida da custódia, já com dedução automática de taxas da B3 e provisão de Imposto de Renda. Não é feita a soma das linhas de títulos individuais para evitar divergências de arredondamento.
- **Taxa Média Contratada**: Extrai o *spread* anual dos títulos IPCA+ (ex.: `7,61% a.a.` em `"IPCA + 7,61%"`) e calcula a média ponderada pelo **`Valor investido`** de cada papel. Essa taxa alimenta as premissas de projeção futura.

### 2. Financiamento Patrimar (`resumo_financeiro-*.csv`)
- **Identificação**: Lê todos os arquivos CSV iniciados pelo prefixo `resumo_financeiro-`.
- **Saldo Devedor de Financiamento**: Extrai a coluna `valorParcelaAtualizada` da linha em que `nomeTipoParcela == "Financiamento"`.
- **Parcela Balão de Poupança (2030-07-31)**: Se houver linha do tipo `Poupança` com `dataVencimento == "2030-07-31"`, seu valor é somado ao saldo devedor. Como essa parcela vence exatamente na data de entrega das chaves, ela continuará sendo corrigida mensalmente pelo INCC e compõe a dívida total a ser quitada.

### 3. Deduplicação e Consolidação Diária
- **Carimbo temporal**: A data e o horário são extraídos do final do nome de cada arquivo através da expressão regular `AAAA-MM-DD_HH-MM`.
- **Chave de consolidação**: A data civil (`AAAA-MM-DD`) é a chave de unificação; horários distintos não criam registros adicionais.
- **Desempate intradia**: Existindo mais de um arquivo da mesma fonte na mesma data, utiliza-se exclusivamente o arquivo de horário mais recente.
- **Assimetrias**: Caso uma data possua extrato de apenas uma das fontes, o lado ausente é registrado como `NaN` e o Gap não é computado nessa data.
- **Ordenação cronológica**: A série final é estritamente ordenada da data mais antiga para a mais recente.

---

## 📈 Motor de Projeção Financeira (Até 31/07/2030)

A projeção simula mês a mês a trajetória do patrimônio e da dívida até **31 de julho de 2030**:

1. **Saldo Devedor (INCC)**:
   - Evolui sob regime de juros compostos diários à taxa anual parametrizada do INCC (padrão: `8,0% a.a.`):
     $$V = V_0 \times (1 + \text{taxa})^{\frac{\text{dias}}{365.25}}$$
2. **Valor Líquido (Tesouro IPCA+)**:
   - **Taxa Efetiva Híbrida**: Como os títulos IPCA+ são híbridos, a rentabilidade nominal projeta o spread médio contratado composto com a estimativa de inflação (IPCA):
     $$\text{Taxa Efetiva} = (1 + \text{Spread}) \times (1 + \text{IPCA}) - 1$$
   - **Aporte Mensal**: Aporte programado (padrão: `R$ 1.000,00/mês`) adicionado a cada mês na NTN-B+ 2032, capitalizando à taxa efetiva.
   - **Aportes Extraordinários (FGTS)**: Crédito do Saque-Aniversário do FGTS (padrão: `R$ 10.000,00`) nas datas contratuais:
     - 10/07/2027
     - 10/07/2028
     - 10/07/2029
     - 10/07/2030

---

## 🖥️ Painéis e Recursos da Interface Streamlit

### Barra Lateral (Parâmetros da Projeção)
- **INCC (% a.a.)**: Ajuste fino da taxa de correção da dívida da Patrimar.
- **IPCA (% a.a.)**: Estimativa de inflação para compor o rendimento do Tesouro IPCA+.
- **Aporte mensal na NTN-B+ 2032 (R$)**: Simulação de aportes mensais recorrentes.
- **Saque-Aniversário do FGTS (R$)**: Montante creditado anualmente em cada 10 de julho.

### Painel Superior de KPIs
1. **Valor líquido atual**: Posição consolidada mais recente em títulos do Tesouro.
2. **Saldo devedor atual**: Montante atualizado da dívida imobiliária.
3. **Falta acumular (Gap)**: Montante residual para quitação integral com indicador dinâmico de cor:
   - **Verde**: O gap encolheu em relação ao período anterior (evolução favorável).
   - **Vermelho**: O gap aumentou (alerta).
4. **Gap reduzido desde o início**: Montante em reais (R$) e percentual amortizado do gap desde o primeiro registro da série histórica, com indicação da data base.

### Gráfico Principal Plotly
- Curvas históricas contínuas com marcadores: Valor Líquido (azul), Saldo Devedor (vermelho) e Gap (verde).
- Extensões tracejadas conectadas suavemente ao último dado real demonstrando a trajetória projetada.
- Linha de meta horizontal pontilhada em **Gap = 0 (jul/2030)**.
- Tooltips unificados e interativos formatados em moeda (R$).

### Abas Analíticas Avançadas
- 🎯 **Estou no caminho?**:
  - Velocímetro (*Gauge*) com percentual do gap já fechado, zonas de cor (vermelho/amarelo/verde) e comparação *delta* com o mês anterior;
  - Linha cinza de referência temporal indicando o progresso linear esperado entre o início do plano e julho/2030;
  - Cards de métricas com gap inicial, gap atual e meta zero.
- 📈 **Como evoluiu?**:
  - Gráfico de área empilhada ilustrando a composição da dívida (cobertura líquida em verde sobreposta pelo gap faltante em vermelho até a linha de saldo total);
  - Linha vertical marcando a transição entre dados reais e projeção ("Hoje").
- 🌊 **O que moveu o gap?**:
  - Gráfico cascata (*Waterfall*) mostrando o ganho/perda líquido mensal do gap;
  - Tabela resumo de forças decompondo quanto o Tesouro cresceu, quanto o INCC cresceu e a variação líquida do gap com estilo condicional.
- 📋 **Evolução mensal**:
  - Tabela detalhada mês a mês calculando o $\Delta \text{ Gap (R\$)}$ e $\Delta \% \text{ no mês}$;
  - Identificação clara entre períodos Reais e Projetados;
  - Linha final de totalização acumulada.

### Tabela Histórica e Projeção
- Listagem completa e formatada de todas as datas, discriminando dados reais e projetados no padrão monetário brasileiro (`R$ 1.234,56`).

---

## 🚀 Instalação e Execução

### Requisitos
- **Python 3.10+** (recomendado Python 3.10 ou superior)

### 1. Criar ambiente virtual e instalar dependências

```bash
cd Downloads
python3 -m venv .venv
source .venv/bin/activate      # No Windows: .venv\Scripts\activate
pip install -r tesouro_gap/requirements.txt
```

### 2. Executar a aplicação

Adicione os extratos `.xlsx` e `.csv` na pasta `arquivos/` e execute:

```bash
streamlit run app.py
```

Ao adicionar novos arquivos à pasta `arquivos/`, basta pressionar **F5** no navegador para recalcular instantaneamente toda a série histórica e as projeções.
