"""Leitor dos resumos financeiros do financiamento imobiliário Patrimar (arquivos CSV).

Este módulo localiza, valida e extrai os dados dos arquivos emitidos pelo portal
da construtora Patrimar, responsáveis por informar o saldo devedor atualizado
do financiamento e de parcelas intermediárias/balão sujeitas a correção pelo INCC.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from tesouro_gap.models import RegistroDiario
from tesouro_gap.utils import extrair_data_hora

# Prefixo padrão obrigatório para identificação dos arquivos CSV da Patrimar.
PREFIXO = "resumo_financeiro-"

# Nome da coluna que categoriza o tipo da obrigação/parcela (ex.: Financiamento, Poupança).
COLUNA_TIPO = "nomeTipoParcela"

# Nome da coluna que armazena o valor monetário atualizado da parcela.
COLUNA_VALOR = "valorParcelaAtualizada"

# Identificador da linha principal do saldo devedor de financiamento.
TIPO_FINANCIAMENTO = "Financiamento"

# Identificador da parcela intermediária balão (Poupança) concomitante à quitação.
TIPO_POUPANCA = "Poupança"

# Data limite padrão da projeção e vencimento da parcela balão da Poupança.
DATA_LIMITE_POUPANCA = pd.Timestamp("2030-07-31")


class PatrimarReader:
    """Localiza, interpreta e consolida os dados de saldo devedor da Patrimar.

    O saldo devedor total consolidado para fins de quitação é composto por:
    1. O ``valorParcelaAtualizada`` da linha onde ``nomeTipoParcela == "Financiamento"``;
    2. Somado ao ``valorParcelaAtualizada`` da linha onde ``nomeTipoParcela == "Poupança"``
       cujo vencimento (``dataVencimento``) seja exatamente a data limite do plano
       (31/07/2030), pois essa parcela continuará sendo reajustada pelo INCC até a entrega
       das chaves / quitação definitiva.
    """

    def __init__(self, diretorio: Path) -> None:
        """Inicializa o leitor de arquivos da Patrimar.

        Args:
            diretorio: Objeto Path apontando para o diretório onde os arquivos
                ``resumo_financeiro-*.csv`` estão armazenados.
        """
        self._diretorio = diretorio

    def localizar_arquivos(self) -> list[Path]:
        """Localiza todos os arquivos CSV da Patrimar no diretório configurado.

        Busca por arquivos correspondentes ao padrão ``resumo_financeiro-*.csv``,
        ordenando-os alfabeticamente pelo nome para consistência temporal inicial.

        Returns:
            Lista de objetos Path com os arquivos CSV encontrados.
        """
        return sorted(self._diretorio.glob(f"{PREFIXO}*.csv"))

    def extrair_data(self, arquivo: Path) -> tuple[date, datetime]:
        """Extrai a data e o carimbo de data/hora a partir do nome do arquivo.

        Utiliza a função utilitária compartilhada ``extrair_data_hora``, baseada
        na regex de carimbo final.

        Args:
            arquivo: Caminho do arquivo CSV analisado.

        Returns:
            Tupla contendo a data (date) para consolidação e o carimbo (datetime)
            para desempate de versões do mesmo dia.
        """
        return extrair_data_hora(arquivo.name)

    def ler_csv(self, arquivo: Path) -> pd.DataFrame:
        """Carrega e valida o conteúdo do arquivo CSV da Patrimar.

        Verifica a existência das colunas essenciais para o cálculo financeiro
        (tipo de parcela e valor atualizado).

        Args:
            arquivo: Caminho do arquivo CSV a ser carregado.

        Returns:
            DataFrame pandas com o conteúdo integral do arquivo.

        Raises:
            ValueError: Se alguma das colunas obrigatórias não estiver presente.
        """
        df = pd.read_csv(arquivo)
        for coluna in (COLUNA_TIPO, COLUNA_VALOR):
            if coluna not in df.columns:
                raise ValueError(
                    f"Coluna obrigatória {coluna!r} não foi encontrada em {arquivo.name}. "
                    f"Colunas disponíveis no arquivo: {list(df.columns)}"
                )
        return df

    def obter_saldo_devedor(self, arquivo: Path) -> float:
        """Calcula o saldo devedor total corrigido a partir do CSV.

        Regras de composição da dívida:
        1. Localiza a linha obrigatória de financiamento (``nomeTipoParcela == "Financiamento"``)
           e extrai seu ``valorParcelaAtualizada``.
        2. Verifica se existe parcela adicional do tipo ``"Poupança"`` com vencimento
           exatamente em ``2030-07-31`` (data final da projeção/entrega). Em caso positivo,
           soma seu valor ao saldo devedor, pois ambas compõem a dívida total corrigida pelo
           INCC até a quitação final.

        Args:
            arquivo: Caminho do arquivo CSV a ser processado.

        Returns:
            Saldo devedor total em reais (float), combinando financiamento e parcela
            balão de poupança aplicável.

        Raises:
            ValueError: Se a linha de financiamento estiver ausente ou se seu valor
                numérico for inválido/ilegível.
        """
        df = self.ler_csv(arquivo)

        # 1. Componente obrigatório: Parcela de Financiamento
        financiamento = df[df[COLUNA_TIPO] == TIPO_FINANCIAMENTO]
        if financiamento.empty:
            raise ValueError(
                f"Nenhuma linha com {COLUNA_TIPO} == {TIPO_FINANCIAMENTO!r} "
                f"encontrada em {arquivo.name}."
            )

        valor_bruto = financiamento[COLUNA_VALOR].iloc[0]
        valor = pd.to_numeric(valor_bruto, errors="coerce")
        if pd.isna(valor):
            raise ValueError(
                f"Saldo devedor inválido na linha de financiamento de "
                f"{arquivo.name}: {valor_bruto!r}"
            )
        saldo = float(valor)

        # 2. Componente complementar: Parcela de Poupança com vencimento na data final (2030-07-31)
        if "dataVencimento" in df.columns:
            # Converte a coluna de vencimento em Timestamp para comparação precisa
            vencimentos = pd.to_datetime(df["dataVencimento"], errors="coerce")
            # Filtra parcelas do tipo Poupança que vencem exatamente em 31/07/2030
            poupanca_target = df[
                (df[COLUNA_TIPO] == TIPO_POUPANCA) & (vencimentos == DATA_LIMITE_POUPANCA)
            ]
            if not poupanca_target.empty:
                valor_poupanca_bruto = poupanca_target[COLUNA_VALOR].iloc[0]
                valor_poupanca = pd.to_numeric(valor_poupanca_bruto, errors="coerce")
                if not pd.isna(valor_poupanca):
                    saldo += float(valor_poupanca)

        return saldo

    def coletar_registros(self) -> list[RegistroDiario]:
        """Processa todos os arquivos CSV encontrados e gera registros individuais diários.

        Para cada arquivo da pasta, extrai a data de referência, o timestamp de
        modificação/emissão e o saldo devedor consolidado.

        Returns:
            Lista de instâncias de :class:`RegistroDiario`, uma para cada arquivo válido.
        """
        registros: list[RegistroDiario] = []
        for arquivo in self.localizar_arquivos():
            data_ref, timestamp = self.extrair_data(arquivo)
            valor = self.obter_saldo_devedor(arquivo)
            registros.append(
                RegistroDiario(data=data_ref, valor=valor, timestamp=timestamp)
            )
        return registros
