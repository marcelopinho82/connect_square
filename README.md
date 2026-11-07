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
├── config.yaml                # Parâmetros de negócio parametrizáveis (contrato, taxas, aportes)
├── README.md                  # Documentação completa da aplicação
├── requirements.txt           # Dependências do projeto (streamlit, pandas, plotly, openpyxl, pyyaml)
├── arquivos/                  # Diretório de entrada dos arquivos XLSX (Tesouro) e CSV (Patrimar)
└── tesouro_gap/
    ├── __init__.py            # Exportação das classes, modelos e funções centrais do pacote
    ├── config.py              # Carregamento/validação dos parâmetros de negócio (config.yaml)
    ├── models.py              # Modelos de dados imutáveis (RegistroDiario, PontoHistorico)
    ├── processor.py           # GapProcessor: deduplicação diária, consolidação e cálculo do Gap
    ├── requirements.txt       # Espelho de dependências do subpacote de processamento
    ├── utils.py               # Extração de data/hora via regex e formatação monetária (pt-BR)
    └── readers/
        ├── __init__.py        # Exportação dos leitores de arquivos
        ├── tesouro_reader.py  # TesouroReader: leitura de extratos XLSX e rentabilidade ponderada
        └── patrimar_reader.py # PatrimarReader: leitura de CSVs e composição do saldo devedor
```

---

## ⚙️ Regras de Negócio e Processamento de Dados

### 1. Tesouro Direto (`ExtratoAnalitico_*.xlsx`)
- **Identificação**: Lê todas as planilhas iniciadas pelo prefixo `ExtratoAnalitico_`.
- **Cabeçalho dinâmico**: Localiza a linha do cabeçalho que contém `Valor líquido` inspecionando as primeiras 20 linhas e unificando cabeçalhos multi-nível (*multi-index*).
- **Valor Líquido Oficial**: A linha identificada como **`TOTAL`** (ou a última linha da planilha) expressa a posição consolidada líquida da custódia, já com dedução automática de taxas da B3 e provisão de Imposto de Renda. Não é feita a soma das linhas de títulos individuais para evitar divergências de arredondamento.
- **Taxa Média Contratada**: Extrai o *spread* anual dos títulos IPCA+ (ex.: `7,61% a.a.` em `"IPCA + 7,61%"`) e calcula a média ponderada pelo **`Valor investido`** de cada papel. Existindo mais de um extrato para a data mais recente (ex.: custódia em múltiplas corretoras), o sistema consolida todos os papéis e pondera o spread pelo valor investido global. Essa taxa alimenta as premissas de projeção futura.

### 2. Financiamento Patrimar (`resumo_financeiro-*.csv`)
- **Identificação**: Lê todos os arquivos CSV iniciados pelo prefixo `resumo_financeiro-`.
- **Saldo Devedor de Financiamento**: Extrai a coluna `valorParcelaAtualizada` da linha em que `nomeTipoParcela == "Financiamento"`.
- **Parcela Balão de Poupança (data-limite da projeção)**: Se houver linha do tipo `Poupança` com `dataVencimento` igual à data-limite configurada (`data_limite_projecao` em `config.yaml`, por padrão `2030-07-31`), seu valor é somado ao saldo devedor. Como essa parcela vence exatamente na data de entrega das chaves, ela continuará sendo corrigida mensalmente pelo INCC e compõe a dívida total a ser quitada.

### 3. Deduplicação, Consolidação Diária e Resiliência
- **Carimbo temporal**: A data e o horário são extraídos do final do nome de cada arquivo através da expressão regular `AAAA-MM-DD_HH-MM`.
- **Chave de consolidação**: A data civil (`AAAA-MM-DD`) é a chave de unificação; variações de horário não criam registros adicionais.
- **Tesouro Direto (soma por corretora)**: Existindo mais de um arquivo `ExtratoAnalitico_*` para a mesma data (por exemplo, custódias em corretoras distintas), os valores líquidos de todos são **somados**, consolidando a posição global de NTN-B naquele fechamento.
- **Patrimar (desempate intradia)**: Existindo mais de um arquivo CSV para a mesma data civil, prevalece estritamente o arquivo de horário mais recente (maior timestamp).
- **Assimetrias pontuais**: Caso uma data isolada possua extrato de apenas uma das fontes no histórico, o lado ausente é registrado como `NaN` e o Gap não é computado nessa data específica.
- **Resiliência e Ausência Total de Extratos (Modo Simulação)**:
  - *Sem extratos da Patrimar*: A aplicação não bloqueia. O saldo devedor é ancorado no **Saldo inicial do contrato** (configurado em `config.yaml` e ajustável na barra lateral) e projetado via juros compostos pelo INCC.
  - *Sem extratos do Tesouro Direto*: O valor líquido acumulado assume R$ 0,00 por padrão ou o montante informado no campo interativo **"Valor líquido atual"** da barra lateral. A taxa efetiva futura assume `taxa_tesouro_efetiva = ipca`, permitindo projetar a curva de novos aportes mesmo antes do primeiro extrato ser adicionado.
- **Ordenação cronológica**: A série final é estritamente ordenada da data mais antiga para a mais recente.

---

## 📈 Motor de Projeção Financeira (Até 31/07/2030)

A projeção simula mês a mês a trajetória do patrimônio e da dívida até **31 de julho de 2030**:

1. **Saldo Devedor (INCC) e Taxa Implícita**:
   - **Cálculo automático do INCC Implícito**: O sistema infere a taxa anual equivalente do INCC a partir do saldo histórico usando capitalização composta:
     $$\text{INCC Implícito} = \left(\frac{SD_{\text{final}}}{SD_{\text{inicial}}}\right)^{\frac{12}{n_{\text{meses}}}} - 1$$
     O cálculo utiliza como âncora de partida o contrato original (parâmetros `data_contrato` e `saldo_contrato_inicial` em `config.yaml`, por padrão assinado em **02/07/2026** no valor de **R$ 239.616,00** e reajustável na barra lateral), permitindo apurar a taxa real de correção da construtora mesmo com apenas um extrato carregado.
   - **Evolução projetada**: O saldo devedor evolui sob regime de juros compostos diários à taxa anual parametrizada (padrão alimentado pelo INCC implícito ou fallback de `taxa_patrimar_padrao_pct`, por padrão `8,0% a.a.`):
     $$V = V_0 \times (1 + \text{taxa})^{\frac{\text{dias}}{365.25}}$$
2. **Valor Líquido (Tesouro IPCA+)**:
   - **Taxa Efetiva Híbrida**: Como os títulos IPCA+ são híbridos, a rentabilidade nominal projeta o spread médio contratado composto com a estimativa de inflação (IPCA):
     $$\text{Taxa Efetiva} = (1 + \text{Spread}) \times (1 + \text{IPCA}) - 1$$
     *(Quando não há extratos do Tesouro, adota spread zero e rentabilidade igual ao IPCA).*
   - **Aporte Mensal**: Aporte programado (padrão configurável em `aporte_mensal_padrao`: `R$ 1.500,00/mês`) adicionado a cada mês na NTN-B+ 2032, capitalizando à taxa efetiva.
   - **Aportes Extraordinários (FGTS)**: Crédito do Saque-Aniversário do FGTS (padrão configurável em `aporte_extra_padrao`: `R$ 10.000,00`) nas datas contratuais definidas em `datas_aporte_extra` (padrão):
     - 10/07/2027
     - 10/07/2028
     - 10/07/2029
     - 10/07/2030

---

## ⚙️ Arquivo de Configuração (`config.yaml`)

Todos os **valores de negócio críticos** foram extraídos do código-fonte e centralizados no arquivo `config.yaml`, na raiz do projeto. Edite esse arquivo para adaptar o painel a outro contrato/cenário **sem alterar o código Python** — após salvar, pressione **F5** no navegador para recalcular.

| Chave | Descrição | Padrão |
|---|---|---|
| `saldo_contrato_inicial` | Saldo devedor original (R$) na assinatura do contrato; âncora do INCC implícito. | `239616.0` |
| `data_contrato` | Data de assinatura do contrato (AAAA-MM-DD). | `2026-07-02` |
| `data_limite_projecao` | Data de corte da projeção / entrega das chaves e vencimento da parcela balão. | `2030-07-31` |
| `taxa_patrimar_padrao_pct` | Taxa anual padrão do INCC (% a.a.), usada como fallback. | `8.0` |
| `ipca_padrao_pct` | Estimativa anual padrão do IPCA (% a.a.). | `0.0` |
| `aporte_mensal_padrao` | Aporte mensal padrão (R$) em NTN-B+ 2032. | `1500.0` |
| `aporte_extra_padrao` | Valor padrão (R$) de cada Saque-Aniversário do FGTS. | `10000.0` |
| `datas_aporte_extra` | Lista de datas (AAAA-MM-DD) dos Saques-Aniversário do FGTS. | `2027-07-10 … 2030-07-10` |

O carregamento e a validação das chaves são feitos por `tesouro_gap/config.py` (`carregar_config`), que converte datas para `pandas.Timestamp` e sinaliza erros claros caso alguma chave obrigatória esteja ausente ou inválida.

---

## 🖥️ Painéis e Recursos da Interface Streamlit

### Barra Lateral (Parâmetros da Projeção)
> Os valores padrão abaixo são carregados do arquivo [`config.yaml`](#️-arquivo-de-configuração-configyaml) e podem ser ajustados dinamicamente na barra lateral para simulação instantânea de cenários:
- **Saldo inicial do contrato (R$)**: Saldo devedor original na data de assinatura com a Patrimar. Serve de âncora para inferir o INCC anual implícito e permite ao usuário recalibrar a taxa padrão ao ajustar o montante de origem.
- **Valor líquido atual (R$)** *(exibido condicionalmente quando não há extratos do Tesouro)*: Permite informar um montante já acumulado para simular a projeção partindo de um patrimônio inicial diferente de zero.
- **INCC (% a.a.)**: Taxa anual de correção da dívida da Patrimar. Pré-preenchida automaticamente com o INCC implícito calculado do histórico real (ou o padrão de fallback `taxa_patrimar_padrao_pct`), com ajuste manual permitido (0 a 50%).
- **IPCA (% a.a.)**: Estimativa anual de inflação (padrão `ipca_padrao_pct`, slider de 0 a 50%) para compor com o spread real do Tesouro IPCA+.
- **Aporte mensal na NTN-B+ 2032 (R$)**: Simulação de aportes mensais regulares (padrão `aporte_mensal_padrao`, por padrão `R$ 1.500,00`).
- **Saque-Aniversário do FGTS (R$)**: Montante creditado anualmente em cada 10 de julho (padrão `aporte_extra_padrao`, por padrão `R$ 10.000,00`).

### Painel Superior de KPIs
1. **Valor líquido atual**: Posição consolidada mais recente em títulos do Tesouro.
2. **Saldo devedor atual**: Montante atualizado da dívida imobiliária.
3. **Falta acumular (Gap)**: Montante residual para quitação integral com semáforo dinâmico de tendência:
   - **Verde**: O gap encolheu em relação ao período anterior (evolução favorável).
   - **Vermelho**: O gap aumentou (alerta).
4. **Gap reduzido desde o início**: Indicador bidirecional da evolução acumulada do Gap desde o marco zero da série histórica:
   - **Redução efetiva (favorável)**: Exibido em **verde** com seta **▼** e legenda com o percentual amortizado do gap inicial (`X,X% do gap inicial`).
   - **Aumento do gap (alerta)**: Caso o saldo devedor corrigido pelo INCC supere a evolução patrimonial (ou na ausência de patrimônio investido), o valor exibe sinal negativo/neutro em **vermelho** com seta **▲** e legenda (`X,X% de aumento no gap`).

### Gráfico Principal Plotly
- Curvas históricas contínuas com marcadores: Valor Líquido (azul), Saldo Devedor (vermelho) e Gap (verde).
- Extensões tracejadas conectadas suavemente ao último dado real demonstrando a trajetória projetada.
- Linha de meta horizontal pontilhada em **Gap = 0 (jul/2030)**.
- Tooltips unificados e interativos formatados em moeda brasileira (R$).

### Abas Analíticas Avançadas
- 🎯 **Estou no caminho?**:
  - Velocímetro (*Gauge*) com percentual do gap já fechado, zonas de cor (vermelho `< 30%`, amarelo `30% a 70%` e verde `> 70%`) e comparação *delta* com o mês anterior;
  - Linha cinza de referência temporal (*threshold*) indicando o progresso linear esperado entre o início do plano e julho/2030;
  - Cards complementares do velocímetro: **Gap reduzido (R$)** e **Meta do período (tempo)**;
  - Cards inferiores de fechamento: gap inicial, gap atual e meta zero em julho/2030.
- 📈 **Como evoluiu?**:
  - Gráfico de área empilhada ilustrando a composição da dívida (cobertura líquida em verde sobreposta pelo gap faltante em vermelho até a linha de saldo total);
  - Linha vertical marcando a transição entre dados reais e projeção ("Hoje").
- 🌊 **O que moveu o gap?**:
  - Gráfico cascata (*Waterfall*) mostrando o ganho/perda líquido mensal do gap;
  - Tabela resumo de forças decompondo quanto o Tesouro cresceu, quanto o INCC cresceu e a variação líquida do gap com estilo condicional.
- 📋 **Evolução mensal**:
  - Tabela detalhada mês a mês calculando o $\Delta$ Gap (R\$) e o $\Delta\%$ no mês;
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
pip install -r requirements.txt
```

### 2. Executar a aplicação

Adicione os extratos `.xlsx` e `.csv` na pasta `arquivos/` e execute:

```bash
streamlit run app.py
```

Ao adicionar novos arquivos à pasta `arquivos/`, basta pressionar **F5** no navegador para recalcular instantaneamente toda a série histórica e as projeções.
