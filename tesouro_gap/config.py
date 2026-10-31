"""Carregamento centralizado dos parâmetros de negócio da estratégia de quitação.

Os valores de negócio que antes estavam fixados ("hardcoded") no código-fonte —
saldo original do contrato, datas contratuais, taxas-padrão e aportes — foram
externalizados para o arquivo ``config.yaml`` na raiz do projeto. Isso permite
ajustar as premissas do plano sem alterar o código Python e reutilizar o painel
em diferentes contratos/cenários apenas editando o arquivo de configuração.

O módulo expõe a função :func:`carregar_config`, que lê o arquivo YAML, valida a
presença de todas as chaves obrigatórias, converte os tipos (datas para
``pandas.Timestamp``) e devolve uma instância imutável de
:class:`ConfiguracaoNegocio`. O resultado é memorizado em cache para que o
arquivo seja lido apenas uma vez por execução.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

# Caminho padrão do arquivo de configuração de negócio (raiz do projeto, um
# nível acima do pacote ``tesouro_gap``).
_CAMINHO_CONFIG_PADRAO = Path(__file__).resolve().parent.parent / "config.yaml"

# Chaves escalares obrigatórias esperadas no arquivo YAML.
_CHAVES_OBRIGATORIAS = (
    "saldo_contrato_inicial",
    "data_contrato",
    "data_limite_projecao",
    "taxa_patrimar_padrao_pct",
    "ipca_padrao_pct",
    "aporte_mensal_padrao",
    "aporte_extra_padrao",
    "datas_aporte_extra",
)


@dataclass(frozen=True, slots=True)
class ConfiguracaoNegocio:
    """Parâmetros de negócio parametrizáveis da estratégia de quitação.

    Attributes:
        saldo_contrato_inicial: Saldo devedor original (R$) na assinatura do
            contrato. Âncora de partida do cálculo do INCC implícito.
        data_contrato: Data de assinatura do contrato com a Patrimar.
        data_limite_projecao: Data de corte da projeção / entrega das chaves,
            também usada como vencimento da parcela balão de Poupança.
        taxa_patrimar_padrao_pct: Taxa anual padrão do INCC (% a.a.) usada como
            fallback quando não há dados históricos suficientes.
        ipca_padrao_pct: Estimativa anual padrão do IPCA (% a.a.).
        aporte_mensal_padrao: Aporte mensal padrão (R$) em NTN-B+ 2032.
        aporte_extra_padrao: Valor padrão (R$) de cada Saque-Aniversário do FGTS.
        datas_aporte_extra: Datas dos Saques-Aniversário do FGTS.
    """

    saldo_contrato_inicial: float
    data_contrato: pd.Timestamp
    data_limite_projecao: pd.Timestamp
    taxa_patrimar_padrao_pct: float
    ipca_padrao_pct: float
    aporte_mensal_padrao: float
    aporte_extra_padrao: float
    datas_aporte_extra: tuple[pd.Timestamp, ...]


def _para_timestamp(valor: object, campo: str) -> pd.Timestamp:
    """Converte um valor do YAML (date/datetime/str) em ``pandas.Timestamp``.

    Args:
        valor: Valor lido do arquivo de configuração.
        campo: Nome da chave, usado em mensagens de erro.

    Returns:
        O valor convertido em ``pandas.Timestamp``.

    Raises:
        ValueError: Se o valor não for uma data reconhecível.
    """
    if isinstance(valor, (date, datetime)):
        return pd.Timestamp(valor)
    if isinstance(valor, str):
        timestamp = pd.to_datetime(valor, errors="coerce")
        if pd.isna(timestamp):
            raise ValueError(
                f"Data inválida para {campo!r} em config.yaml: {valor!r}. "
                f"Use o formato ISO AAAA-MM-DD."
            )
        return timestamp
    raise ValueError(
        f"Valor inválido para {campo!r} em config.yaml: {valor!r}. "
        f"Esperava-se uma data no formato AAAA-MM-DD."
    )


@lru_cache(maxsize=None)
def carregar_config(caminho: Path | None = None) -> ConfiguracaoNegocio:
    """Carrega e valida os parâmetros de negócio a partir do arquivo YAML.

    O resultado é memorizado (cache) para que o arquivo seja lido apenas uma vez
    por processo. Em testes ou cenários alternativos, informe ``caminho`` para
    apontar para um arquivo de configuração específico.

    Args:
        caminho: Caminho opcional para o arquivo de configuração. Quando omitido,
            utiliza ``config.yaml`` na raiz do projeto.

    Returns:
        Instância imutável de :class:`ConfiguracaoNegocio` com os parâmetros.

    Raises:
        FileNotFoundError: Se o arquivo de configuração não existir.
        ValueError: Se houver chaves obrigatórias ausentes ou valores inválidos.
    """
    caminho_config = Path(caminho) if caminho is not None else _CAMINHO_CONFIG_PADRAO

    if not caminho_config.is_file():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {caminho_config}. "
            f"Crie um 'config.yaml' na raiz do projeto com os parâmetros de negócio."
        )

    with caminho_config.open("r", encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo) or {}

    if not isinstance(dados, dict):
        raise ValueError(
            f"Conteúdo inválido em {caminho_config.name}: esperava-se um mapeamento "
            f"de chaves/valores no topo do arquivo."
        )

    faltantes = [chave for chave in _CHAVES_OBRIGATORIAS if chave not in dados]
    if faltantes:
        raise ValueError(
            f"Chaves obrigatórias ausentes em {caminho_config.name}: "
            f"{', '.join(faltantes)}."
        )

    datas_extra_brutas = dados["datas_aporte_extra"]
    if not isinstance(datas_extra_brutas, (list, tuple)):
        raise ValueError(
            "A chave 'datas_aporte_extra' em config.yaml deve ser uma lista de "
            "datas no formato AAAA-MM-DD."
        )
    datas_aporte_extra = tuple(
        _para_timestamp(item, "datas_aporte_extra") for item in datas_extra_brutas
    )

    return ConfiguracaoNegocio(
        saldo_contrato_inicial=float(dados["saldo_contrato_inicial"]),
        data_contrato=_para_timestamp(dados["data_contrato"], "data_contrato"),
        data_limite_projecao=_para_timestamp(
            dados["data_limite_projecao"], "data_limite_projecao"
        ),
        taxa_patrimar_padrao_pct=float(dados["taxa_patrimar_padrao_pct"]),
        ipca_padrao_pct=float(dados["ipca_padrao_pct"]),
        aporte_mensal_padrao=float(dados["aporte_mensal_padrao"]),
        aporte_extra_padrao=float(dados["aporte_extra_padrao"]),
        datas_aporte_extra=datas_aporte_extra,
    )
