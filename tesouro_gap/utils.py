"""Funções utilitárias compartilhadas pelo projeto.

Reúne rotinas auxiliares essenciais para:
- Extração de data e horário a partir dos nomes padronizados dos arquivos;
- Formatação de valores numéricos em moeda no padrão brasileiro (R$ 1.234,56).
"""

from __future__ import annotations

import re
from datetime import date, datetime

# Expressão regular para capturar o carimbo de data e hora no final do nome do arquivo.
# Padrão esperado: AAAA-MM-DD_HH-MM (ex.: "2026-09-17_11-32")
# Grupo 1 captura a data (AAAA-MM-DD) e Grupo 2 captura a hora/minuto (HH-MM).
_TIMESTAMP_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2})")


def extrair_data_hora(nome_arquivo: str) -> tuple[date, datetime]:
    """Extrai a data (sem horário) e o carimbo cronológico completo do nome do arquivo.

    A data isolada é utilizada como chave principal para consolidação diária dos
    dados, ignorando variações de minutos/horas. Já o carimbo completo (datetime)
    é preservado exclusivamente para desempatar quando existirem dois ou mais
    arquivos do mesmo tipo referentes à mesma data (prevalecendo o mais recente).

    Args:
        nome_arquivo: Nome do arquivo (string), podendo conter o caminho completo
            ou apenas o nome base com ou sem extensão. Exemplo:
            "ExtratoAnalitico_..._2026-09-17_11-32.xlsx" ou
            "resumo_financeiro-2026-09-17_11-33.csv".

    Returns:
        Tupla ``(data, timestamp)``, onde:
        - ``data``: Objeto ``datetime.date`` contendo apenas o dia/mês/ano.
        - ``timestamp``: Objeto ``datetime.datetime`` com precisão de minutos.

    Raises:
        ValueError: Se o nome do arquivo não apresentar o padrão cronológico
            esperado (AAAA-MM-DD_HH-MM).
    """
    correspondencia = _TIMESTAMP_PATTERN.search(nome_arquivo)
    if correspondencia is None:
        raise ValueError(
            f"Não foi possível extrair data/hora do arquivo: {nome_arquivo!r}. "
            f"Certifique-se de que o nome termine no formato 'AAAA-MM-DD_HH-MM'."
        )

    parte_data, parte_hora = correspondencia.groups()
    timestamp = datetime.strptime(f"{parte_data}_{parte_hora}", "%Y-%m-%d_%H-%M")
    return timestamp.date(), timestamp


def formatar_moeda(valor: float) -> str:
    """Formata um número de ponto flutuante no padrão monetário brasileiro.

    Converte valores decimais para o formato ``R$ 1.234,56``, aplicando ponto (.)
    como separador de milhares e vírgula (,) como separador de centavos.
    Valores negativos mantêm o sinal antes do símbolo da moeda (ex.: ``-R$ 8.634,25``).

    Args:
        valor: Valor numérico (float ou int) a ser formatado.

    Returns:
        String formatada em moeda brasileira (ex.: ``R$ 129.468,08`` ou ``-R$ 500,00``).
    """
    # Define o prefixo de sinal para números negativos
    sinal = "-" if valor < 0 else ""
    # Converte para string com duas casas decimais e separador padrão americano (,)
    inteiro, decimal = f"{abs(valor):,.2f}".split(".")
    # Substitui a vírgula de milhar pelo ponto no padrão brasileiro
    inteiro = inteiro.replace(",", ".")
    return f"{sinal}R$ {inteiro},{decimal}"
