# -*- coding: utf-8 -*-
"""Aplicativo Streamlit: Gap Tesouro Direto × Patrimar.

Dashboard financeiro interativo para acompanhamento diário e projeção temporal
da estratégia de quitação imobiliária à vista.

Mecanismo central:
- Compara diariamente o valor líquido de resgate acumulado em títulos do
  Tesouro Direto (NTN-B / Tesouro IPCA+) com o saldo devedor total corrigido
  do financiamento da construtora Patrimar (reajustado pelo INCC).
- O Gap é definido como o montante residual que ainda falta acumular:
      Gap = Saldo devedor - Valor líquido
- Permite simular a evolução patrimonial e da dívida até a data de entrega das
  chaves (parametrizável), ajustando taxas de inflação (IPCA), correção da obra
  (INCC), aportes mensais recorrentes e saques-aniversário anuais do FGTS.

Parametrização:
- Os valores de negócio (saldo original do contrato, datas contratuais,
  taxas-padrão, data-limite da projeção e aportes) não ficam fixos no código:
  são carregados do arquivo ``config.yaml`` na raiz do projeto, via
  :func:`tesouro_gap.config.carregar_config`. Edite esse arquivo para adaptar o
  painel a outro contrato/cenário.

Modo de uso:
- Adicione novos arquivos às pastas correspondentes (XLSX para Tesouro e CSV para Patrimar)
  dentro do diretório ``arquivos/`` e recarregue a página (F5) para recalcular toda a série.
- Ajuste as premissas de negócio em ``config.yaml`` quando necessário.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tesouro_gap.config import carregar_config
from tesouro_gap.processor import GapProcessor
from tesouro_gap.utils import formatar_moeda

# ============================================================================
# CONSTANTES E CONFIGURAÇÕES DO SISTEMA
# ============================================================================

# Parâmetros de negócio carregados do arquivo de configuração externo
# (``config.yaml`` na raiz do projeto). Centraliza os valores que antes eram
# fixos no código, permitindo adaptar o painel sem editar o Python.
_CONFIG = carregar_config()

# Caminho absoluto para a pasta de arquivos brutos (XLSX do Tesouro e CSV da Patrimar)
DIRETORIO_DADOS = Path(__file__).resolve().parent / "arquivos"

# Paleta de cores oficial para as séries do gráfico principal (formato hexadecimal)
COR_VALOR_LIQUIDO = "#1f77b4"  # Azul clássico para o patrimônio investido no Tesouro
COR_SALDO_DEVEDOR = "#d62728"  # Vermelho para a dívida imobiliária da Patrimar
COR_GAP = "#2ca02c"            # Verde para o Gap residual / progresso positivo

# Cores semânticas dedicadas aos indicadores analíticos (Gauge, Waterfall e Áreas)
COR_GAUGE_VERMELHO = "#C0392B"  # Vermelho escuro: progresso inicial baixo (< 30%)
COR_GAUGE_AMARELO = "#D4A017"   # Âmbar/Amarelo: progresso intermediário (30% a 70%)
COR_GAUGE_VERDE = "#6AAF3D"     # Verde oliva/folha: progresso avançado (> 70%)
COR_GAUGE_ESCURA = "#1A3A1A"    # Verde escuro/cinza chumbo para linha de saldo total

# ----------------------------------------------------------------------------
# Parâmetros de negócio (parametrizados em ``config.yaml``)
# ----------------------------------------------------------------------------
# Os valores abaixo são lidos do arquivo de configuração externo e deixaram de
# ser constantes fixas no código. Para alterá-los, edite ``config.yaml``.

# Data de corte contratual e término da projeção (previsão de entrega das chaves)
DATA_LIMITE_PROJECAO = _CONFIG.data_limite_projecao

# Premissa padrão da taxa anual do INCC (% a.a.) para projeção do saldo devedor.
# Usada como fallback quando não há dados históricos suficientes para inferir a taxa real.
TAXA_PATRIMAR_PADRAO_PCT = _CONFIG.taxa_patrimar_padrao_pct

# Saldo devedor original na data de assinatura do contrato com a Patrimar (R$).
# Serve de âncora para o cálculo do INCC implícito mesmo com apenas um extrato carregado.
SALDO_CONTRATO_INICIAL = _CONFIG.saldo_contrato_inicial

# Data de assinatura do contrato com a Patrimar
DATA_CONTRATO = _CONFIG.data_contrato

# Premissa padrão da taxa anual do IPCA (% a.a.) para títulos Tesouro IPCA+.
# Os títulos NTN-B rendem o spread contratado composto com a inflação: (1 + spread) * (1 + IPCA) - 1
IPCA_PADRAO_PCT = _CONFIG.ipca_padrao_pct

# Montante financeiro mensal padrão (R$) destinado a novos aportes em NTN-B+ 2032
APORTE_MENSAL_PADRAO = _CONFIG.aporte_mensal_padrao

# Cronograma de aportes extraordinários de Saque-Aniversário do FGTS
DATAS_APORTE_EXTRA = _CONFIG.datas_aporte_extra

# Valor padrão (R$) de cada saque-aniversário anual do FGTS projetado
APORTE_EXTRA_PADRAO = _CONFIG.aporte_extra_padrao


# ============================================================================
# FUNÇÕES MATEMÁTICAS E DE FORMATAÇÃO
# ============================================================================

def _formatar_taxa(taxa: float) -> str:
    """Formata uma taxa decimal anual no padrão de percentual brasileiro.

    Exemplo:
        0.0825 -> "8,25% a.a."

    Args:
        taxa: Fração decimal representando a taxa anual (ex.: 0.0825).

    Returns:
        String formatada com 2 casas decimais e separador decimal de vírgula.
    """
    return f"{taxa * 100:.2f}".replace(".", ",") + "% a.a."


def _crescer(valor_inicial: float, taxa_anual: float, dias: int) -> float:
    """Aplica o regime de capitalização composta por dias corridos.

    Utiliza a convenção de dias corridos sobre ano comercial médio considerando
    bissextos:
        V = V0 * (1 + taxa_anual) ^ (dias / 365.25)

    Args:
        valor_inicial: Montante base de partida em reais (R$).
        taxa_anual: Taxa anual expressa como fração decimal (ex.: 0.08 para 8% a.a.).
        dias: Número de dias corridos decorridos no intervalo.

    Returns:
        Montante capitalizado ao final do período de dias.
    """
    return valor_inicial * (1.0 + taxa_anual) ** (dias / 365.25)


# ============================================================================
# MOTOR DE PROJEÇÃO FINANCEIRA
# ============================================================================

def _construir_projecao(
    df: pd.DataFrame,
    taxa_tesouro: float | None,
    taxa_patrimar: float,
    data_limite: pd.Timestamp,
    aporte_mensal: float = 0.0,
    aporte_extra: float = 0.0,
    datas_aporte_extra: tuple[pd.Timestamp, ...] = (),
) -> pd.DataFrame:
    """Projeta a trajetória futura do Valor Líquido e do Saldo Devedor até a data-limite.

    Metodologia de projeção:
    1. **Âncora temporal**: Utiliza a última observação real de cada série como ponto
       inicial de partida.
    2. **Saldo devedor**: Evolui via juros compostos com base na taxa anual projetada
       do INCC.
    3. **Valor líquido**:
       - O capital inicial acumulado rende à taxa efetiva do Tesouro IPCA+;
       - A cada mês decorrido, é adicionado o ``aporte_mensal``, que passa a capitalizar
         a partir de sua inserção;
       - Nas datas de aniversário do FGTS contidas no intervalo, é creditado o
         ``aporte_extra``, capitalizando até a data de encerramento da projeção.
    4. **Gap projetado**: Apurado a cada marco mensal pela diferença
       ``saldo_devedor - valor_liquido``.

    Args:
        df: DataFrame da série histórica real consolidada.
        taxa_tesouro: Taxa anual efetiva do Tesouro (fração decimal) ou None caso indisponível.
        taxa_patrimar: Taxa anual projetada para correção pelo INCC (fração decimal).
        data_limite: Marco temporal final da projeção (31/07/2030).
        aporte_mensal: Montante mensal aportado em reais.
        aporte_extra: Montante do saque anual de FGTS em reais.
        datas_aporte_extra: Tupla com os timestamps das liberações do FGTS.

    Returns:
        DataFrame com as colunas ``data``, ``valor_liquido``, ``saldo_devedor``
        e ``gap`` referente estritamente aos períodos futuros projetados.
    """
    colunas = ["data", "valor_liquido", "saldo_devedor", "gap"]

    # Isola as observações válidas (não-nulas) de cada série para obter a âncora
    serie_vl = df.dropna(subset=["valor_liquido"])
    serie_sd = df.dropna(subset=["saldo_devedor"])

    # Se qualquer uma das séries estiver desprovida de dados reais, aborta a projeção
    if serie_vl.empty or serie_sd.empty:
        return pd.DataFrame(columns=colunas)

    # Identifica a data e o valor do último ponto observado de cada série
    ancora_vl_data = serie_vl["data"].iloc[-1]
    ancora_vl = float(serie_vl["valor_liquido"].iloc[-1])
    ancora_sd_data = serie_sd["data"].iloc[-1]
    ancora_sd = float(serie_sd["saldo_devedor"].iloc[-1])

    ultima_data = df["data"].max()
    # Se a série real já tiver alcançado ou ultrapassado a meta, não projeta
    if ultima_data >= data_limite:
        return pd.DataFrame(columns=colunas)

    # Constrói a lista sequencial de datas mensais de projeção até data_limite
    datas: list[pd.Timestamp] = []
    cursor = ultima_data
    while True:
        cursor = cursor + pd.DateOffset(months=1)
        if cursor >= data_limite:
            break
        datas.append(cursor)
    datas.append(data_limite)

    registros = []
    aporte_acumulado = 0.0  # Acumulador com juros de todos os aportes (mensais e FGTS)
    data_anterior = ultima_data

    # Itera sobre cada data mensal futura calculando os rendimentos acumulados
    for data_ponto in datas:
        if taxa_tesouro is None:
            # Caso a taxa do Tesouro não tenha sido obtida, invalida o valor líquido
            valor_liquido = float("nan")
        else:
            # Projeta o estoque de capital já existente até a nova data
            base_vl = _crescer(
                ancora_vl, taxa_tesouro, (data_ponto - ancora_vl_data).days
            )
            # Rende os aportes anteriores acumulados e soma o novo aporte mensal
            aporte_acumulado = _crescer(
                aporte_acumulado,
                taxa_tesouro,
                (data_ponto - data_anterior).days,
            ) + aporte_mensal

            # Verifica e incorpora eventuais aportes extraordinários de FGTS no intervalo
            for data_extra in datas_aporte_extra:
                if data_anterior < data_extra <= data_ponto:
                    aporte_acumulado += _crescer(
                        aporte_extra,
                        taxa_tesouro,
                        (data_ponto - data_extra).days,
                    )
            valor_liquido = base_vl + aporte_acumulado

        # Projeta a dívida imobiliária com a taxa do INCC desde sua última âncora real
        saldo_devedor = _crescer(
            ancora_sd, taxa_patrimar, (data_ponto - ancora_sd_data).days
        )

        # Gap = valor que ainda falta acumular (positivo até a quitação integral)
        registros.append(
            {
                "data": data_ponto,
                "valor_liquido": valor_liquido,
                "saldo_devedor": saldo_devedor,
                "gap": saldo_devedor - valor_liquido,
            }
        )
        data_anterior = data_ponto

    return pd.DataFrame(registros, columns=colunas)


# ============================================================================
# COMPONENTES VISUAIS: GRÁFICOS E TABELAS
# ============================================================================

def _construir_grafico(df: pd.DataFrame, projecao: pd.DataFrame) -> go.Figure:
    """Monta o gráfico principal Plotly com as curvas históricas e projetadas.

    Apresenta três séries fundamentais e uma linha de meta:
    1. **Valor líquido** (azul): Estoque financeiro real e projetado em NTN-B.
    2. **Saldo devedor** (vermelho): Dívida com a Patrimar real e projetada via INCC.
    3. **Gap (a acumular)** (verde): Montante faltante até a quitação.
    4. **Linha de Meta**: Marcação pontilhada horizontal em Gap = 0 na data de entrega.

    Args:
        df: DataFrame da série histórica real consolidada.
        projecao: DataFrame contendo a projeção mensal futura.

    Returns:
        Objeto go.Figure configurado com temas, tooltips e marcadores.
    """
    fig = go.Figure()

    # Configuração dos pares de séries a exibir: (nome_coluna, rótulo_legenda, cor_hex)
    series = (
        ("valor_liquido", "Valor líquido", COR_VALOR_LIQUIDO),
        ("saldo_devedor", "Saldo devedor", COR_SALDO_DEVEDOR),
        ("gap", "Gap (a acumular)", COR_GAP),
    )

    # Plota as curvas dos dados históricos reais (linhas sólidas com marcadores circulares)
    for coluna, rotulo, cor in series:
        y = df[coluna]
        fig.add_trace(
            go.Scatter(
                x=df["data"],
                y=y,
                name=rotulo,
                mode="lines+markers",
                line={"color": cor, "width": 2},
                marker={"size": 7},
                hovertemplate=f"{rotulo}: R$ %{{y:,.2f}}<extra></extra>",
            )
        )

    # Se houver dados de projeção, anexa as extensões tracejadas conectadas ao último dado real
    if not projecao.empty:
        for coluna, rotulo, cor in series:
            _adicionar_linha_projecao(fig, df, projecao, coluna, rotulo, cor)

    # Linha de Meta Zero (Gap = 0 em julho de 2030)
    fig.add_hline(
        y=0,
        line_dash="dot",
        line_color="orange",
        line_width=1.5,
        annotation_text="Meta: Gap = 0 (jul/2030)",
        annotation_position="bottom right",
        annotation_font_color="orange",
        annotation_font_size=11,
    )

    # Estilização profissional do layout Plotly
    fig.update_layout(
        title=(
            "Gap: aplicação no Tesouro IPCA+ 2032 × Saldo Devedor Patrimar "
            "(calculado pelo INCC)"
        ),
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        xaxis_title="Data",
        yaxis_title="Valor (R$)",
        template="plotly_white",
    )
    # Grades sutis para facilitar a leitura dos eixos
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,0.06)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0,0,0,0.06)", rangemode="tozero")

    return fig


def _adicionar_linha_projecao(
    fig: go.Figure,
    df: pd.DataFrame,
    projecao: pd.DataFrame,
    coluna: str,
    rotulo: str,
    cor: str,
) -> None:
    """Anexa ao gráfico a trajetória tracejada da projeção conectada ao último dado real.

    Para assegurar continuidade visual, o primeiro vértice da projeção parte exatamente
    do último ponto observado na série histórica.

    Args:
        fig: Objeto go.Figure em estruturação.
        df: Série histórica real.
        projecao: Série mensal projetada.
        coluna: Nome da coluna a ser desenhada (ex.: "gap", "valor_liquido").
        rotulo: Texto descritivo para a legenda.
        cor: Cor da linha (idêntica à série real correspondente).
    """
    serie_real = df.dropna(subset=[coluna])
    projecao_valida = projecao.dropna(subset=[coluna])
    if serie_real.empty or projecao_valida.empty:
        return

    # Une o último ponto real aos pontos futuros
    x = [serie_real["data"].iloc[-1], *projecao_valida["data"]]
    y = [float(serie_real[coluna].iloc[-1]), *projecao_valida[coluna]]

    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            name=f"{rotulo} (projeção)",
            mode="lines",
            line={"color": cor, "width": 2, "dash": "dash"},
            hovertemplate=f"{rotulo} (projeção): R$ %{{y:,.2f}}<extra></extra>",
        )
    )


def _formatar_tabela(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara o DataFrame unificado para renderização na tabela histórica e projetada.

    Converte carimbos datetime para o padrão brasileiro (DD/MM/AAAA) e formata valores
    monetários com pontuação pt-BR ou traço ('—') caso ausentes.

    Args:
        df: DataFrame com a série temporal combinada e a coluna discriminatória 'tipo'.

    Returns:
        DataFrame com colunas e dados amigáveis para visualização no Streamlit.
    """
    return pd.DataFrame(
        {
            "Data": df["data"].dt.strftime("%d/%m/%Y"),
            "Tipo": df["tipo"],
            "Valor líquido": df["valor_liquido"].map(_moeda_ou_traco),
            "Saldo devedor": df["saldo_devedor"].map(_moeda_ou_traco),
            "Falta acumular": df["gap"].map(_moeda_ou_traco),
        }
    )


def _moeda_ou_traco(valor: float) -> str:
    """Formata valor em moeda brasileira ou devolve travessão caso seja nulo (NaN).

    Args:
        valor: Valor numérico float ou NaN.

    Returns:
        String monetária (ex.: "R$ 1.000,00") ou "—".
    """
    if pd.isna(valor):
        return "—"
    return formatar_moeda(float(valor))


# ============================================================================
# COMPONENTES ANALÍTICOS ESPECÍFICOS (ABAS 1 A 4)
# ============================================================================

def _construir_gauge(
    df: pd.DataFrame,
    projecao: pd.DataFrame,
    data_inicio: pd.Timestamp,
    data_limite: pd.Timestamp,
) -> None:
    """Renderiza o velocímetro (Gauge) de progresso do plano de quitação integral.

    Métricas calculadas e exibidas:
    1. **% Fechado**: Percentual do gap inicial já amortizado pelo patrimônio:
       ``((gap_inicial - gap_atual) / gap_inicial) * 100``
    2. **Delta comparativo**: Variação percentual em relação ao ponto anterior.
    3. **Threshold de tempo**: Linha de referência cinza indicando onde o progresso
       deveria estar sob a hipótese de amortização temporal linear:
       ``(dias_decorridos / dias_totais) * 100``
    4. **Cards complementares**: Redução total em reais (R$) e meta de período.

    Args:
        df: Série histórica real.
        projecao: Série projetada (preservada para paridade de interface).
        data_inicio: Data da primeira observação registrada na série histórica.
        data_limite: Data de encerramento do plano (31/07/2030).
    """
    # Proteção para séries históricas vazias
    if df.empty:
        gap_inicial = 0.0
        gap_atual = 0.0
    else:
        gap_inicial = float(df["gap"].iloc[0])
        gap_atual = float(df["gap"].iloc[-1])

    # Percentual do gap já encolhido em relação ao valor de largada
    pct_fechado = (
        ((gap_inicial - gap_atual) / gap_inicial) * 100 if gap_inicial != 0 else 0.0
    )

    # Percentual fechado no registro imediatamente anterior para cálculo do delta
    if len(df) >= 2 and gap_inicial != 0:
        gap_penultimo = float(df["gap"].iloc[-2])
        pct_fechado_anterior = ((gap_inicial - gap_penultimo) / gap_inicial) * 100
    else:
        pct_fechado_anterior = pct_fechado

    # Montante total já reduzido em reais (R$)
    reducao_reais = gap_inicial - gap_atual

    # Faixas semânticas do velocímetro (Vermelho < 30%, Amarelo 30-70%, Verde > 70%)
    steps = [
        {"range": [0, 30], "color": COR_GAUGE_VERMELHO},
        {"range": [30, 70], "color": COR_GAUGE_AMARELO},
        {"range": [70, 100], "color": COR_GAUGE_VERDE},
    ]

    # Cálculo da meta de tempo decorrido linear entre a data de início e a meta de 2030
    hoje = pd.Timestamp.now().normalize()
    dias_decorridos = (hoje - data_inicio).days
    dias_totais = (data_limite - data_inicio).days
    progresso_tempo = (
        (dias_decorridos / dias_totais) * 100 if dias_totais != 0 else 0.0
    )

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=pct_fechado,
            number={"suffix": "%", "valueformat": ".2f"},
            delta={
                "reference": pct_fechado_anterior,
                "valueformat": ".2f",
                "suffix": "%",
                "increasing": {"color": COR_GAUGE_VERDE},
                "decreasing": {"color": COR_GAUGE_VERMELHO},
            },
            gauge={
                "axis": {"range": [0, 100]},
                "steps": steps,
                "threshold": {
                    "line": {"color": "gray", "width": 4},
                    "thickness": 0.75,
                    "value": progresso_tempo,
                },
            },
        )
    )
    fig.update_layout(
        height=350,
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
        template="plotly_white",
    )

    # Renderiza diretamente no Streamlit
    st.plotly_chart(fig, use_container_width=True)

    # Exibe métricas financeiras complementares abaixo do gauge
    col_r1, col_r2 = st.columns(2)
    col_r1.metric(
        "Gap reduzido (R$)",
        formatar_moeda(reducao_reais),
        help="Montante em reais que o gap encolheu desde a largada do plano.",
    )
    col_r2.metric(
        "Meta do período (tempo)",
        f"{progresso_tempo:.1f}%".replace(".", ","),
        help=(
            "Progresso esperado sob redução linear no tempo entre a data de "
            "início e 31/07/2030 (representado pelo marcador cinza no gauge)."
        ),
    )


def _construir_area_empilhada(df: pd.DataFrame, projecao: pd.DataFrame) -> go.Figure:
    """Constrói o gráfico de área empilhada ilustrando a composição da dívida.

    Divide o Saldo Devedor total em dois blocos sobrepostos:
    - **Área Verde (NTN-B já acumulado)**: Cobertura patrimonial já líquida e disponível.
    - **Área Vermelha (Gap a acumular)**: O déficit restante que necessita de cobertura.
    - **Linha Pontilhada**: Trajetória do Saldo Devedor total.
    - **Linha Vertical 'Hoje'**: Marcação da transição entre os dados reais e a projeção.

    Args:
        df: Série histórica real.
        projecao: Série projetada.

    Returns:
        Figura Plotly pronta para renderização.
    """
    if projecao.empty:
        combinado = df.copy()
    else:
        combinado = pd.concat([df, projecao], ignore_index=True)
    combinado = combinado.sort_values("data")

    fig = go.Figure()

    # 1. Área verde: Valor líquido já acumulado
    fig.add_trace(
        go.Scatter(
            x=combinado["data"],
            y=combinado["valor_liquido"],
            name="NTN-B (já acumulado)",
            mode="none",
            fill="tozeroy",
            fillcolor="rgba(106,175,61,0.7)",
            stackgroup="one",
            connectgaps=True,
        )
    )

    # 2. Área vermelha: Gap a acumular preenchendo até o saldo devedor
    fig.add_trace(
        go.Scatter(
            x=combinado["data"],
            y=combinado["gap"],
            name="Gap (falta acumular)",
            mode="none",
            fill="tonexty",
            fillcolor="rgba(192,57,43,0.5)",
            stackgroup="one",
            connectgaps=True,
        )
    )

    # 3. Linha do saldo devedor total consolidado
    fig.add_trace(
        go.Scatter(
            x=combinado["data"],
            y=combinado["saldo_devedor"],
            name="Saldo devedor",
            mode="lines",
            line={"dash": "dot", "color": COR_GAUGE_ESCURA},
        )
    )

    # Marcação da linha vertical da data real mais recente
    ultima_data_real = df["data"].iloc[-1]
    fig.add_vline(
        x=ultima_data_real,
        line_dash="dash",
        line_color="gray",
    )
    fig.add_annotation(
        x=ultima_data_real,
        y=1,
        yref="paper",
        text="Hoje",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
    )

    # Anotação com destaque numérico do Gap atual
    gap_atual = float(df["gap"].iloc[-1])
    fig.add_annotation(
        x=ultima_data_real,
        y=gap_atual / 2,
        text=f"Gap atual<br>{formatar_moeda(gap_atual)}",
        showarrow=True,
    )

    fig.update_layout(
        height=400,
        xaxis_title="Data",
        yaxis_title="Valor (R$)",
        legend={"orientation": "h", "y": -0.15, "x": 0},
        template="plotly_white",
    )
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f")
    return fig


def _construir_waterfall(df: pd.DataFrame) -> go.Figure | None:
    """Gera o gráfico cascata (Waterfall) com o impacto mensal no fechamento do Gap.

    Calcula a redução (positiva) ou expansão (negativa) do gap a cada mês
    e encerra com uma barra total expressando o saldo atual de gap.

    Args:
        df: Série histórica consolidada.

    Returns:
        Figura Plotly Waterfall ou None se houver menos de 2 observações mensais.
    """
    df_real = df.dropna(subset=["gap"]).reset_index(drop=True)
    if len(df_real) < 2:
        return None

    variacoes_gap: list[float] = []
    labels: list[str] = []

    # Calcula as variações mês a mês (redução do gap = positivo)
    for i in range(1, len(df_real)):
        gap_anterior = float(df_real["gap"].iloc[i - 1])
        gap_atual = float(df_real["gap"].iloc[i])
        variacao = gap_anterior - gap_atual
        variacoes_gap.append(variacao)
        labels.append(df_real["data"].iloc[i].strftime("%m/%Y"))

    # Barra de totalização do gap residual atual
    gap_atual = float(df_real["gap"].iloc[-1])
    labels.append("Atual")
    y = variacoes_gap + [gap_atual]
    measure = ["relative"] * len(variacoes_gap) + ["total"]

    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measure,
            x=labels,
            y=y,
            text=[formatar_moeda(v) for v in y],
            textposition="outside",
            connector={"line": {"color": "#888888", "width": 1}},
            increasing={"marker": {"color": "#6AAF3D"}},
            decreasing={"marker": {"color": "#C0392B"}},
            totals={"marker": {"color": "#1A3A1A"}},
        )
    )
    fig.update_layout(height=400, template="plotly_white", showlegend=False)
    fig.add_hline(
        y=0,
        line_dash="dot",
        line_color="orange",
        annotation_text="Meta: Gap = 0",
        annotation_position="bottom right",
    )
    return fig


def _exibir_resumo_waterfall(df: pd.DataFrame) -> None:
    """Exibe tabela explicativa detalhando a decomposição das forças sobre o gap.

    Decompõe a variação líquida do Gap em dois vetores fundamentais:
    - **Crescimento da NTN-B** (força favorável que encolhe o gap);
    - **Crescimento pelo INCC** (força desfavorável que amplia o gap).

    Args:
        df: Série histórica consolidada com ao menos dois pontos.
    """
    df_real = df.dropna(subset=["gap"]).reset_index(drop=True)
    if len(df_real) < 2:
        return

    rows = []
    for i in range(1, len(df_real)):
        mes = df_real["data"].iloc[i].strftime("%m/%Y")
        ntnb_cresceu = df_real["valor_liquido"].iloc[i] - df_real["valor_liquido"].iloc[i - 1]
        incc_cresceu = df_real["saldo_devedor"].iloc[i] - df_real["saldo_devedor"].iloc[i - 1]
        gap_variou = df_real["gap"].iloc[i - 1] - df_real["gap"].iloc[i]
        saldo_gap = df_real["gap"].iloc[i]
        rows.append(
            {
                "Mês": mes,
                "NTN-B cresceu": ntnb_cresceu,
                "INCC cresceu": incc_cresceu,
                "Gap variou": gap_variou,
                "Saldo gap": saldo_gap,
            }
        )
    resumo = pd.DataFrame(rows)

    fmt = {
        "NTN-B cresceu": lambda x: formatar_moeda(x),
        "INCC cresceu": lambda x: formatar_moeda(x),
        "Gap variou": lambda x: formatar_moeda(x),
        "Saldo gap": lambda x: formatar_moeda(x),
    }

    # Aplicação de estilo condicional verde para redução e vermelho para aumento do gap
    def _color_gap(val):     
        if pd.isna(val):
            return ""
        if val > 0:
            # Verde claro com fonte verde escura
            return "background-color: #E8F5E9; color: #1B5E20;"
        elif val < 0:
            # Vermelho claro com fonte vermelha escura
            return "background-color: #FDECEA; color: #B71C1C;"
        # Valores zerados: fundo neutro e fonte escura
        return "background-color: #F5F5F5; color: #212121;"

    styled = resumo.style.format(fmt).applymap(_color_gap, subset=["Gap variou"])
    st.write(styled)


def _construir_tabela_delta(df: pd.DataFrame, projecao: pd.DataFrame) -> None:
    """Renderiza a tabela analítica completa de evolução mensal do gap com Δ e Δ%.

    Apresenta a série mês a mês combinando o histórico real e os pontos futuros,
    calculando a variação absoluta (R$) e percentual (%) do gap em relação ao mês
    anterior, acrescida de uma linha de totalização no encerramento.

    Args:
        df: Série histórica real.
        projecao: Série projetada.
    """
    df_real = df.copy()
    df_real["tipo"] = "Real"
    if projecao.empty:
        combinado = df_real
    else:
        proj = projecao.copy()
        proj["tipo"] = "Projeção"
        combinado = pd.concat([df_real, proj], ignore_index=True)
    combinado = combinado.sort_values("data").reset_index(drop=True)

    # Variação absoluta e relativa do gap entre meses consecutivos
    combinado["Δ Gap no mês"] = combinado["gap"].shift(1) - combinado["gap"]
    combinado["Δ %"] = (combinado["Δ Gap no mês"] / combinado["gap"].shift(1)) * 100

    tabela = pd.DataFrame(
        {
            "Data": combinado["data"].dt.strftime("%d/%m/%Y"),
            "NTN‑B líquida": combinado["valor_liquido"],
            "Saldo devedor": combinado["saldo_devedor"],
            "Gap": combinado["gap"],
            "Δ Gap no mês": combinado["Δ Gap no mês"],
            "Δ %": combinado["Δ %"],
            "Tipo": combinado["tipo"],
        }
    )

    # Linha final de totalização acumulada
    total_gap = combinado["Δ Gap no mês"].sum(skipna=True)
    total_pct = (
        (total_gap / combinado["gap"].iloc[0]) * 100
        if not combinado.empty and combinado["gap"].iloc[0] != 0
        else 0
    )
    total_row = {
        "Data": "TOTAL",
        "NTN‑B líquida": pd.NA,
        "Saldo devedor": pd.NA,
        "Gap": pd.NA,
        "Δ Gap no mês": total_gap,
        "Δ %": total_pct,
        "Tipo": pd.NA,
    }
    tabela = pd.concat([tabela, pd.DataFrame([total_row])], ignore_index=True)

    formatter = {
        "NTN‑B líquida": lambda x: formatar_moeda(x) if pd.notna(x) else "—",
        "Saldo devedor": lambda x: formatar_moeda(x) if pd.notna(x) else "—",
        "Gap": lambda x: formatar_moeda(x) if pd.notna(x) else "—",
        "Δ Gap no mês": lambda x: formatar_moeda(x) if pd.notna(x) else "—",
        "Δ %": lambda x: f"{x:.2f}%".replace(".", ",") if pd.notna(x) else "—",
    }


    def _color_delta(val):
        if pd.isna(val):
            return ""
        if val > 0:
            # Verde claro com fonte verde escura
            return "background-color: #E8F5E9; color: #1B5E20;"
        elif val < 0:
            # Vermelho claro com fonte vermelha escura
            return "background-color: #FDECEA; color: #B71C1C;"
        # Valores zerados: fundo neutro e fonte escura
        return "background-color: #F5F5F5; color: #212121;"


    styled = tabela.style.format(formatter).applymap(_color_delta, subset=["Δ Gap no mês"])
    st.write(styled)
    st.caption("Verde = gap encolheu (positivo) · Vermelho = gap cresceu (atenção)")


# ============================================================================
# PONTO DE ENTRADA PRINCIPAL DA APLICAÇÃO STREAMLIT
# ============================================================================

def main() -> None:
    """Executa o fluxo principal da aplicação Streamlit.

    Etapas executadas:
    1. Define layout, ícone e configurações globais de página;
    2. Renderiza a barra lateral com controles paramétricos (INCC, IPCA, Aportes, FGTS);
    3. Carrega e consolida os extratos brutos com a classe ``GapProcessor``;
    4. Calcula a taxa média ponderada do Tesouro e a taxa efetiva anual composta;
    5. Projeta as curvas financeiras mensais até a data limite contratual;
    6. Exibe os KPIs superiores com métricas monetárias e percentuais de amortização;
    7. Plota o gráfico temporal interativo com linha de meta zero;
    8. Constrói as 4 abas analíticas avançadas (Gauge, Composição, Waterfall e Delta);
    9. Apresenta a tabela histórica detalhada combinando dados observados e projeções.
    """
    st.set_page_config(
        page_title="Gap Tesouro Direto × Patrimar",
        page_icon="📊",
        layout="wide",
    )

    st.title("Gap Tesouro Direto × Patrimar")
    st.caption("Evolução diária do patrimônio líquido versus saldo devedor.")

    # ------------------------------------------------------------------------
    # 1. CARREGAMENTO E PROCESSAMENTO DOS DADOS
    # ------------------------------------------------------------------------
    try:
        processador = GapProcessor(DIRETORIO_DADOS)
        df = processador.construir_serie()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Falha ao processar os arquivos de dados: {exc}")
        return

    # Validação de presença de dados consolidados
    if df.empty:
        st.warning(
            "Nenhum arquivo encontrado. Adicione os arquivos "
            "`ExtratoAnalitico_*.xlsx` e `resumo_financeiro-*.csv` na pasta "
            "`arquivos/` e pressione F5."
        )
        return

    # Inferência do INCC implícito a partir dos saldos devedores mensais históricos.
    # Usa o saldo original do contrato (jul/2026) como âncora, permitindo calcular
    # a taxa mesmo com apenas um único arquivo carregado.
    incc_implicito = processador.calcular_incc_implicito(
        df,
        saldo_contrato=SALDO_CONTRATO_INICIAL,
        data_contrato=DATA_CONTRATO,
    )
    incc_implicito_pct = (
        round(incc_implicito * 100, 2) if incc_implicito is not None else None
    )

    # ------------------------------------------------------------------------
    # 2. BARRA LATERAL: ENTRADA DE PARÂMETROS
    # ------------------------------------------------------------------------
    with st.sidebar:
        st.header("Parâmetros da projeção")

        # Valor padrão do INCC: usa a taxa implícita calculada dos saldos históricos
        # se disponível; caso contrário, recorre ao valor fixo de referência.
        _incc_default = (
            incc_implicito_pct
            if incc_implicito_pct is not None
            else TAXA_PATRIMAR_PADRAO_PCT
        )
        _incc_help_origem = (
            f"Valor padrão calculado automaticamente a partir dos "
            f"{len(df.dropna(subset=['saldo_devedor']))} saldos devedores históricos "
            f"(taxa INCC anual equivalente implícita). "
            if incc_implicito_pct is not None
            else "Valor padrão fixo de referência (dados históricos insuficientes). "
        )

        # Taxa de projeção do INCC para correção monetária da obra/saldo devedor
        taxa_patrimar_pct = st.number_input(
            "INCC (% a.a.)",
            min_value=0.0,
            max_value=50.0,
            value=_incc_default,
            step=0.25,
            help=(
                _incc_help_origem
                + "Taxa anual utilizada para projetar a evolução do saldo devedor "
                "da Patrimar até 31/07/2030. Ajuste manualmente se desejar simular "
                "cenários alternativos."
            ),
        )

        # Inflação projetada (IPCA) para compor a rentabilidade do Tesouro IPCA+
        ipca_pct = st.slider(
            "IPCA (% a.a.)",
            min_value=0.0,
            max_value=50.0,
            value=IPCA_PADRAO_PCT,
            step=0.1,
            help=(
                "Variação anual estimada do IPCA. Como o Tesouro IPCA+ é um título "
                "híbrido, o rendimento projeta o spread contratado composto com a "
                "inflação: (1 + spread) * (1 + IPCA) - 1."
            ),
        )

        # Aporte financeiro mensal regular em NTN-B+ 2032
        aporte_mensal = st.number_input(
            "Aporte mensal na NTN‑B+ 2032 (R$)",
            min_value=0.0,
            max_value=1_000_000.0,
            value=APORTE_MENSAL_PADRAO,
            step=100.0,
            help=(
                "Valor aportado todo mês na NTN‑B+ 2032 a partir da data de projeção. "
                "Cada aporte passa a render à taxa média ponderada do Tesouro."
            ),
        )

        # Aporte extraordinário anual do Saque-Aniversário do FGTS
        aporte_extra = st.number_input(
            "Saque‑Aniversário do FGTS (R$)",
            min_value=0.0,
            max_value=10_000_000.0,
            value=APORTE_EXTRA_PADRAO,
            step=1_000.0,
            help=(
                "Valor do Saque‑Aniversário do FGTS creditado no Valor líquido "
                "em 10/07 de 2027, 2028, 2029 e 2030. Cada saque passa a render "
                "à taxa média do Tesouro."
            ),
        )

    # Conversão de taxas percentuais em frações decimais
    taxa_patrimar = taxa_patrimar_pct / 100.0
    ipca = ipca_pct / 100.0

    # ------------------------------------------------------------------------
    # 3. CÁLCULO DAS TAXAS DO TESOURO
    # ------------------------------------------------------------------------
    # Cálculo da taxa média ponderada dos títulos do Tesouro
    try:
        taxa_tesouro = processador.obter_taxa_tesouro()
    except Exception as exc:  # noqa: BLE001
        taxa_tesouro = None
        st.warning(f"Não foi possível calcular a taxa média do Tesouro: {exc}")

    # Taxa efetiva do Tesouro IPCA+ composta com a inflação: (1 + spread) * (1 + IPCA) - 1
    taxa_tesouro_efetiva = (
        (1.0 + taxa_tesouro) * (1.0 + ipca) - 1.0
        if taxa_tesouro is not None
        else None
    )

    # ------------------------------------------------------------------------
    # 4. PROJEÇÃO PATRIMONIAL E DE DÍVIDA
    # ------------------------------------------------------------------------
    projecao = _construir_projecao(
        df,
        taxa_tesouro_efetiva,
        taxa_patrimar,
        DATA_LIMITE_PROJECAO,
        aporte_mensal,
        aporte_extra,
        DATAS_APORTE_EXTRA,
    )

    # ------------------------------------------------------------------------
    # 5. PAINEL SUPERIOR DE MÉTRICAS (KPIS)
    # ------------------------------------------------------------------------
    ultimo = df.iloc[-1]
    valor_liquido = ultimo["valor_liquido"]
    saldo_devedor = ultimo["saldo_devedor"]
    gap = ultimo["gap"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Valor líquido atual", _moeda_ou_traco(valor_liquido))
    col2.metric("Saldo devedor atual", _moeda_ou_traco(saldo_devedor))

    # KPI 3: Montante que falta acumular (Gap positivo) com semáforo de tendência
    if pd.isna(gap):
        col3.markdown("**Falta acumular**")
        col3.markdown("—")
    else:
        gaps_validos = df["gap"].dropna()
        gap_anterior = (
            float(gaps_validos.iloc[-2]) if len(gaps_validos) >= 2 else float(gap)
        )
        # Verde quando o gap encolhe (favorável); vermelho caso aumente
        cor = COR_GAP if float(gap) <= gap_anterior else COR_SALDO_DEVEDOR
        col3.markdown("**Falta acumular**")
        col3.markdown(
            f"<span style='font-size:1.9rem;font-weight:700;color:{cor}'>"
            f"{formatar_moeda(float(gap))}</span>",
            unsafe_allow_html=True,
        )

    # KPI 4: Redução acumulada desde o marco zero da série histórica
    gaps_serie = df.dropna(subset=["gap"])
    if gaps_serie.empty:
        col4.markdown("**Gap reduzido desde o início**")
        col4.markdown("—")
    else:
        primeiro_gap = float(gaps_serie["gap"].iloc[0])
        ultimo_gap = float(gaps_serie["gap"].iloc[-1])
        reducao_gap = primeiro_gap - ultimo_gap

        col4.markdown("**Gap reduzido desde o início**")
        col4.markdown(
            f"<span style='font-size:1.9rem;font-weight:700;color:{COR_GAP}'>"
            f"{formatar_moeda(reducao_gap)}</span>",
            unsafe_allow_html=True,
        )
        if primeiro_gap != 0:
            pct_reducao = (reducao_gap / primeiro_gap) * 100
            pct_txt = f"{pct_reducao:.1f}".replace(".", ",")
            col4.markdown(
                f"<span style='color:{COR_GAP};font-weight:600'>"
                f"▼ {pct_txt}% do gap inicial</span>",
                unsafe_allow_html=True,
            )
        data_inicio = gaps_serie["data"].iloc[0]
        col4.caption(f"Desde {data_inicio.strftime('%d/%m/%Y')}")

    # Legenda explicativa com todas as premissas vigentes
    taxa_tesouro_txt = (
        _formatar_taxa(taxa_tesouro) if taxa_tesouro is not None else "—"
    )
    taxa_efetiva_txt = (
        _formatar_taxa(taxa_tesouro_efetiva)
        if taxa_tesouro_efetiva is not None
        else "—"
    )
    st.caption(
        f"Projeção até **{DATA_LIMITE_PROJECAO.strftime('%d/%m/%Y')}** — "
        f"Valor líquido a **{taxa_efetiva_txt}** (spread contratado de "
        f"**{taxa_tesouro_txt}**, ponderado pelo valor investido, composto com "
        f"IPCA de **{_formatar_taxa(ipca)}**) · Saldo devedor a "
        f"**{_formatar_taxa(taxa_patrimar)}** (INCC, parametrizável) · "
        f"Aporte mensal de **{formatar_moeda(float(aporte_mensal))}** na NTN‑B+ 2032 · "
        f"Saque‑Aniversário do FGTS de **{formatar_moeda(float(aporte_extra))}** "
        f"em 10/07 de 2027, 2028, 2029 e 2030."
    )

    # ------------------------------------------------------------------------
    # 6. GRÁFICO PRINCIPAL TEMPORAL
    # ------------------------------------------------------------------------
    st.plotly_chart(_construir_grafico(df, projecao), width="stretch")

    # ------------------------------------------------------------------------
    # 7. ABAS ANALÍTICAS AVANÇADAS
    # ------------------------------------------------------------------------
    tab1, tab2, tab3, tab4 = st.tabs([
        "🎯 Estou no caminho?",
        "📈 Como evoluiu?",
        "🌊 O que moveu o gap?",
        "📋 Evolução mensal",
    ])

    # Aba 1: Velocímetro de progresso e alinhamento temporal
    with tab1:
        st.subheader("Progresso do Plano de Quitação")
        st.caption("Estou no caminho certo?")
        _construir_gauge(df, projecao, data_inicio=data_inicio, data_limite=DATA_LIMITE_PROJECAO)

        gap_inicial = float(df["gap"].iloc[0]) if not df.empty else 0.0
        gap_atual_v = float(df["gap"].iloc[-1]) if not df.empty else 0.0
        col_g1, col_g2, col_g3 = st.columns(3)
        col_g1.metric("Gap inicial", formatar_moeda(gap_inicial))
        col_g2.metric("Gap atual", formatar_moeda(gap_atual_v))
        col_g3.metric("Meta jul/2030", "R$ 0,00")

    # Aba 2: Composição visual em área empilhada
    with tab2:
        st.subheader("Composição do Saldo Devedor ao Longo do Tempo")
        st.caption("Como evoluiu ao longo do tempo?")
        area_fig = _construir_area_empilhada(df, projecao)
        st.plotly_chart(area_fig, use_container_width=True)

    # Aba 3: Cascata e decomposição das forças de variação
    with tab3:
        st.subheader("Contribuição Mensal para o Fechamento do Gap")
        st.caption("O que está movendo o gap a cada mês?")
        if len(df) < 2:
            st.info("O waterfall aparece a partir do segundo mês de dados.")
        else:
            wf_fig = _construir_waterfall(df)
            if wf_fig is not None:
                st.plotly_chart(wf_fig, use_container_width=True)
                _exibir_resumo_waterfall(df)

    # Aba 4: Tabela detalhada de variação mensal (Δ e Δ%)
    with tab4:
        st.subheader("Evolução Mensal do Gap")
        st.caption("Quanto o gap fechou a cada mês?")
        _construir_tabela_delta(df, projecao)

    # ------------------------------------------------------------------------
    # 8. TABELA HISTÓRICA CONSOLIDADA E PROJETADA
    # ------------------------------------------------------------------------
    st.subheader("Tabela histórica e projeção")
    df_real = df.copy()
    df_real["tipo"] = "Real"
    if projecao.empty:
        combinado = df_real
    else:
        projecao_tabela = projecao.copy()
        projecao_tabela["tipo"] = "Projeção"
        combinado = pd.concat([df_real, projecao_tabela], ignore_index=True)

    st.dataframe(
        _formatar_tabela(combinado),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
