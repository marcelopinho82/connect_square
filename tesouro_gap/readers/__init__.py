"""Subpacote de leitores e extratores de dados financeiros.

Disponibiliza as classes responsáveis pela leitura, validação e interpretação
dos arquivos brutos de entrada:
- ``TesouroReader``: Extração de valores líquidos e rentabilidades contratadas
  a partir de planilhas Excel (.xlsx) do Tesouro Direto.
- ``PatrimarReader``: Extração do saldo devedor consolidado a partir de
  extratos analíticos (.csv) do financiamento da construtora Patrimar.
"""

from tesouro_gap.readers.patrimar_reader import PatrimarReader
from tesouro_gap.readers.tesouro_reader import TesouroReader

__all__ = ["TesouroReader", "PatrimarReader"]
