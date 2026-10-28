"""Consolidação da série histórica temporal e cálculo do Gap de quitação.

Este módulo orquestra a leitura conjunta dos extratos do Tesouro Direto e da
Patrimar, executando a deduplicação de múltiplos arquivos diários, a unificação
das datas em uma série temporal contínua e o cálculo do Gap residual para a
quitação integral do imóvel.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tesouro_gap.models import RegistroDiario
from tesouro_gap.readers import PatrimarReader, TesouroReader


def _deduplicar_por_data(registros: list[RegistroDiario]) -> dict:
    """Consolida os registros por data, mantendo apenas o mais recente de cada dia.

    Quando múltiplos arquivos do mesmo tipo (XLSX ou CSV) forem gerados no mesmo
    dia com horários distintos, este método compara os timestamps completos e
    mantém estritamente o valor do arquivo com maior carimbo de horário.

    Args:
        registros: Lista de instâncias de :class:`RegistroDiario` lidas dos arquivos.

    Returns:
        Dicionário mapeando ``{datetime.date: float}`` contendo exclusivamente
        o valor monetário do registro vencedor para cada data observada.
    """
    vencedores: dict = {}
    for registro in registros:
        atual = vencedores.get(registro.data)
        # Se for a primeira ocorrência do dia ou se o novo registro for mais recente, substitui
        if atual is None or registro.timestamp > atual.timestamp:
            vencedores[registro.data] = registro
    return {data: reg.valor for data, reg in vencedores.items()}


def _somar_por_data(registros: list[RegistroDiario]) -> dict:
    """Consolida os registros por data somando os valores de todos os arquivos do dia.

    Diferentemente de :func:`_deduplicar_por_data`, que mantém apenas o registro
    de horário mais recente, esta função soma os valores de todos os registros
    referentes à mesma data. É utilizada para os extratos do Tesouro Direto,
    permitindo consolidar múltiplas corretoras (um arquivo ``ExtratoAnalitico_*``
    por corretora) em um único saldo total de NTN-B para cada data observada.

    Se a lista de registros estiver vazia, retorna um dicionário vazio — tratado
    adiante como ausência de dados do Tesouro (mesmo comportamento de quando
    nenhum arquivo está presente).

    Args:
        registros: Lista de instâncias de :class:`RegistroDiario` lidas dos arquivos.

    Returns:
        Dicionário mapeando ``{datetime.date: float}`` com a soma dos valores
        líquidos de todos os arquivos de cada data.
    """
    totais: dict = {}
    for registro in registros:
        totais[registro.data] = totais.get(registro.data, 0.0) + registro.valor
    return totais


class GapProcessor:
    """Processador central de consolidação entre Tesouro Direto e Patrimar."""

    def __init__(self, diretorio: Path) -> None:
        """Inicializa o processador com o diretório dos arquivos de dados.

        Args:
            diretorio: Objeto Path apontando para o diretório contendo os
                arquivos brutos (.xlsx e .csv).
        """
        self._tesouro = TesouroReader(diretorio)
        self._patrimar = PatrimarReader(diretorio)

    def construir_serie(self) -> pd.DataFrame:
        """Constrói o DataFrame da série histórica consolidada e calcula o Gap.

        Regras de negócio implementadas:
        1. **Agrupamento diário**: Variações de horário não geram linhas adicionais;
           a chave temporal de consolidação é a data civil (dia/mês/ano).
        2. **Consolidação do Tesouro (soma por corretora)**: Quando houver mais de
           um extrato ``ExtratoAnalitico_*`` para a mesma data (um por corretora),
           os valores líquidos de todos são somados, resultando no saldo total de
           NTN-B daquele mês.
        3. **Deduplicação intradia da Patrimar**: Se houver mais de um arquivo da
           Patrimar para a mesma data, prevalece o de horário mais recente (pelo
           timestamp extraído do nome).
        4. **Fórmula do Gap**: ``Gap = Saldo devedor - Valor líquido``
           Representa o montante que ainda falta acumular em investimentos para que
           seja possível quitar a dívida integralmente à vista.
        5. **Ordenação cronológica**: Os registros são dispostos em ordem crescente
           de data (do mais antigo para o mais recente).
        6. **Tratamento de assimetrias**: Datas presentes apenas em um dos extratos
           recebem ``NaN`` na contraparte ausente e também na coluna ``gap``.

        Returns:
            DataFrame com as colunas:
            - ``data`` (datetime64): Data de referência da observação;
            - ``valor_liquido`` (float): Valor líquido total de resgate do Tesouro;
            - ``saldo_devedor`` (float): Saldo devedor total corrigido da Patrimar;
            - ``gap`` (float): Montante residual a acumular (saldo_devedor - valor_liquido).
        """
        # Extrai os registros de cada fonte.
        # Tesouro: soma todos os arquivos da mesma data (uma corretora por arquivo),
        # consolidando o saldo total de NTN-B daquele mês.
        # Patrimar: mantém apenas o arquivo mais recente de cada data (deduplicação).
        valor_liquido_por_data = _somar_por_data(
            self._tesouro.coletar_registros()
        )
        saldo_devedor_por_data = _deduplicar_por_data(
            self._patrimar.coletar_registros()
        )

        # Une todas as datas presentes em ao menos uma das fontes
        datas = sorted(set(valor_liquido_por_data) | set(saldo_devedor_por_data))
        if not datas:
            return pd.DataFrame(
                columns=["data", "valor_liquido", "saldo_devedor", "gap"]
            )

        # Monta a estrutura tabular da série
        df = pd.DataFrame(
            {
                "data": pd.to_datetime(datas),
                "valor_liquido": [valor_liquido_por_data.get(d) for d in datas],
                "saldo_devedor": [saldo_devedor_por_data.get(d) for d in datas],
            }
        )

        # Cálculo do Gap: valor que ainda falta acumular para quitar o imóvel.
        # Inicialmente positivo, este valor deve encolher ao longo do tempo até a meta 0.
        df["gap"] = df["saldo_devedor"] - df["valor_liquido"]

        return df.sort_values("data").reset_index(drop=True)

    def calcular_incc_implicito(
        self,
        df: pd.DataFrame,
        saldo_contrato: float | None = None,
        data_contrato: pd.Timestamp | None = None,
    ) -> float | None:
        """Infere a taxa INCC anual equivalente a partir dos saldos devedores históricos.

        Utiliza os valores mensais do saldo devedor (corrigidos pelo INCC real) para
        calcular a taxa anual implícita via capitalização composta:

            taxa_anual = (SD_final / SD_inicial) ^ (12 / n_meses) - 1

        Quando ``saldo_contrato`` e ``data_contrato`` são fornecidos, o saldo original
        da assinatura do contrato é usado como âncora de partida (``SD_inicial``), e
        ``n_meses`` é calculado pelo número de meses de calendário decorridos entre
        a data do contrato e a data do último saldo devedor real. Isso permite obter
        uma taxa significativa mesmo com apenas um único arquivo carregado.

        Sem a âncora do contrato, o método requer ao menos dois pontos mensais na
        série histórica e utiliza o primeiro e o último como extremidades.

        Pressuposto: cada registro corresponde a exatamente um mês de correção
        (ex.: extrato obtido sempre no mesmo dia do mês).

        Args:
            df: DataFrame consolidado retornado por :meth:`construir_serie`, com
                ao menos um ponto válido na coluna ``saldo_devedor``.
            saldo_contrato: Valor do saldo devedor original na data de assinatura do
                contrato (R$). Quando fornecido junto com ``data_contrato``, é usado
                como ``SD_inicial`` da fórmula.
            data_contrato: Data de assinatura do contrato. Usada para calcular o
                número de meses entre a origem e o último saldo real disponível.

        Returns:
            Taxa anual expressa em fração decimal (ex.: ``0.0812`` para 8,12% a.a.),
            ou ``None`` se não houver dados suficientes para o cálculo.
        """
        serie = df.dropna(subset=["saldo_devedor"]).sort_values("data").reset_index(drop=True)
        if serie.empty:
            return None

        sd_final = float(serie["saldo_devedor"].iloc[-1])
        data_final = serie["data"].iloc[-1]

        # --- Modo âncora de contrato -------------------------------------------
        # Usa o saldo original do contrato como SD_inicial e calcula n_meses pela
        # diferença de calendário entre a data do contrato e a data do último extrato.
        if saldo_contrato is not None and data_contrato is not None:
            sd_inicial = float(saldo_contrato)
            if sd_inicial <= 0:
                return None
            n_meses = (
                (data_final.year - data_contrato.year) * 12
                + (data_final.month - data_contrato.month)
            )
            if n_meses <= 0:
                return None
            taxa_anual = (sd_final / sd_inicial) ** (12 / n_meses) - 1
            return taxa_anual

        # --- Modo série histórica (sem âncora de contrato) ---------------------
        # Requer ao menos dois pontos mensais na série.
        if len(serie) < 2:
            return None

        sd_inicial = float(serie["saldo_devedor"].iloc[0])
        if sd_inicial <= 0:
            return None
        n_meses = len(serie) - 1  # número de intervalos mensais entre arquivos

        # Fórmula de taxa anual equivalente por capitalização composta mensal
        taxa_anual = (sd_final / sd_inicial) ** (12 / n_meses) - 1
        return taxa_anual

    def obter_taxa_tesouro(self) -> float | None:
        """Obtém a taxa anual média contratada do Tesouro a partir do arquivo mais recente.

        Utilizada como premissa de rendimento na projeção patrimonial futura.

        Returns:
            Taxa anual expressa em fração decimal (ex.: ``0.0825`` para 8,25% a.a.),
            ou ``None`` se não houver extratos válidos do Tesouro Direto.
        """
        return self._tesouro.obter_taxa_media_mais_recente()
