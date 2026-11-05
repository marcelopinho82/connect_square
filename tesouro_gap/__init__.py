"""Pacote central de processamento e consolidação financeira: Gap Tesouro Direto × Patrimar.

Fornece módulos para carregamento de parâmetros de negócio, modelos de dados,
leitores de extratos bancários/imobiliários, funções utilitárias e o processador
central da série temporal do Gap.
"""

from __future__ import annotations

from tesouro_gap.config import ConfiguracaoNegocio, carregar_config
from tesouro_gap.models import PontoHistorico, RegistroDiario
from tesouro_gap.processor import GapProcessor
from tesouro_gap.utils import extrair_data_hora, formatar_moeda

__all__ = [
    "ConfiguracaoNegocio",
    "GapProcessor",
    "PontoHistorico",
    "RegistroDiario",
    "carregar_config",
    "extrair_data_hora",
    "formatar_moeda",
]

