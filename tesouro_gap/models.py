"""Modelos de dados imutáveis usados no fluxo de processamento do Gap.

Define as estruturas de dados fundamentais para representar as leituras diárias
individuais e os pontos consolidados da série temporal histórica e de projeção.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class RegistroDiario:
    """Representa a leitura bruta de um único arquivo em uma data específica.

    Utilizado como estrutura intermediária pelos leitores (TesouroReader e
    PatrimarReader) antes da consolidação e resolução de eventuais conflitos
    de duplicidade no mesmo dia.

    Attributes:
        data: Data de referência (sem horário) extraída do padrão do nome do
            arquivo (ex.: 2026-09-17). Utilizada como chave principal de
            agrupamento diário.
        valor: Valor monetário apurado do arquivo em reais (R$). Pode representar
            o valor líquido total do Tesouro Direto ou o saldo devedor ajustado
            do financiamento Patrimar.
        timestamp: Carimbo de data e hora completo extraído do nome do arquivo
            (ex.: 2026-09-17 11:32:00). Utilizado exclusivamente como critério
            de desempate quando houver mais de um arquivo do mesmo tipo na
            mesma data (o de maior timestamp prevalece).
    """

    data: date
    valor: float
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class PontoHistorico:
    """Ponto diário consolidado da série temporal.

    Representa o fechamento diário combinando a posição no Tesouro Direto e a
    dívida imobiliária da Patrimar, calculando o gap residual para quitação.

    Attributes:
        data: Data de referência consolidada do ponto.
        valor_liquido: Valor líquido apurado no Tesouro Direto (quanto o titular
            receberia hoje vendendo toda a sua posição em títulos).
        saldo_devedor: Saldo devedor consolidado do financiamento Patrimar
            (incluindo a parcela de financiamento e eventual parcela balão de
            poupança ajustadas pelo INCC).
        gap: Valor residual a ser acumulado até a quitação integral, calculado
            pela fórmula ``saldo_devedor - valor_liquido``. Quando o gap atinge
            zero ou valores negativos, o patrimônio investido é suficiente para
            liquidar o financiamento.
    """

    data: date
    valor_liquido: float
    saldo_devedor: float
    gap: float
