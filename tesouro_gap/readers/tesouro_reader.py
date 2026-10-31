"""Leitor dos extratos analíticos do Tesouro Direto (arquivos XLSX).

Este módulo localiza, analisa e extrai informações das planilhas de extrato
analítico emitidas pelo portal do Tesouro Direto. Suporta a interpretação de
cabeçalhos multi-nível (multi-index), detecção da linha de totalização,
conversão de moeda e cálculo da taxa média contratada da carteira ponderada
pelo valor investido em cada título.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
import unicodedata

import pandas as pd
from openpyxl import load_workbook

from tesouro_gap.models import RegistroDiario
from tesouro_gap.utils import extrair_data_hora

# Prefixo padrão obrigatório dos arquivos de extrato do Tesouro Direto.
PREFIXO = "ExtratoAnalitico_"

# Identificador em texto normalizado da coluna que expressa o valor líquido de resgate.
COLUNA_VALOR_LIQUIDO = "valor liquido"

# Identificador em texto normalizado da coluna que contém a taxa/rentabilidade pactuada (ex.: "IPCA + 7,61%").
COLUNA_RENTABILIDADE = "rentabilidade contratada"

# Identificador em texto normalizado da coluna com o montante investido, usada para ponderação da taxa.
COLUNA_VALOR_INVESTIDO = "valor investido"

# Expressão regular para capturar percentuais anuais em formatos como "IPCA + 7,61%" ou "12,50%".
_PERCENTUAL_PATTERN = re.compile(r"([\d.,]+)\s*%")


def _normalizar_texto(valor: object) -> str:
    """Normaliza uma string removendo acentuação gráfica, quebras de linha e espaços extras.

    Facilita a comparação insensível a maiúsculas/minúsculas e acentos em nomes de
    colunas e valores do Excel que costumam variar entre exportações.

    Args:
        valor: Valor ou texto a ser normalizado.

    Returns:
        String limpa, sem acentos, em minúsculas e com espaçamento simples.
    """
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().lower()


def _flatten_column_name(coluna: object) -> str:
    """Converte tuplas de cabeçalhos multi-nível do Excel em uma única string normalizada.

    Planilhas do Tesouro Direto frequentemente exportam cabeçalhos distribuídos em
    duas ou mais linhas mescladas. Esta função combina as partes não-vazias da tupla.

    Args:
        coluna: Tupla representando os níveis da coluna ou valor simples.

    Returns:
        Nome da coluna unificado e normalizado.
    """
    if isinstance(coluna, tuple):
        partes = [parte for parte in coluna if parte is not None and str(parte).strip()]
        return _normalizar_texto(" ".join(str(parte) for parte in partes))
    return _normalizar_texto(coluna)


def _linha_eh_total(linha: pd.Series) -> bool:
    """Determina se uma linha da planilha representa o sumário/TOTAL do extrato.

    Verifica se alguma das células preenchidas da linha contém a palavra 'total'
    após a normalização.

    Args:
        linha: Série pandas representando uma linha da planilha.

    Returns:
        True se a linha for a linha de TOTAL consolidado; False caso contrário.
    """
    return any(_normalizar_texto(valor) == "total" for valor in linha.dropna().tolist())


def _converter_numero_br(valor: object) -> float:
    """Converte representações numéricas no padrão brasileiro (ex.: '129.468,08') para float.

    Trata strings numéricas com pontos como milhares e vírgula decimal, além de
    preservar tipos já numéricos (int/float) e lidar com valores nulos (NaN).

    Args:
        valor: Conteúdo numérico ou string a ser convertido.

    Returns:
        Número convertido em float, ou float('nan') caso não seja conversível.
    """
    if pd.isna(valor):
        return float("nan")
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip()
    if not texto:
        return float("nan")
    if "," in texto:
        # Remove separadores de milhar (.) e substitui separador decimal (,) por (.)
        texto = texto.replace(".", "").replace(",", ".")
    return pd.to_numeric(texto, errors="coerce")


def _extrair_percentual_ao_ano(valor: object) -> float:
    """Extrai a taxa percentual anual a partir de strings contratuais como 'IPCA + 7,61%'.

    No caso de títulos IPCA+, extrai apenas o spread contratado acima da inflação.
    Para títulos prefixados puros, extrai a taxa prefixada nominal.

    Args:
        valor: Conteúdo textual da célula de rentabilidade contratada.

    Returns:
        Taxa anual expressa como fração decimal (ex.: 0.0761 para 7,61% a.a.)
        ou NaN se nenhuma taxa puder ser identificada.
    """
    if pd.isna(valor):
        return float("nan")
    correspondencias = _PERCENTUAL_PATTERN.findall(str(valor))
    if not correspondencias:
        return float("nan")
    # Utiliza a última correspondência para garantir captura do spread (ex.: IPCA + 7,61%)
    numero = _converter_numero_br(correspondencias[-1])
    if pd.isna(numero):
        return float("nan")
    return float(numero) / 100.0


class TesouroReader:
    """Localiza, interpreta e extrai dados dos extratos analíticos do Tesouro Direto.

    Regra de ouro de negócio:
    A última linha da planilha representa o TOTAL geral da custódia.
    O sistema extrai exclusivamente a coluna 'Valor líquido' dessa última linha,
    garantindo que taxas da B3 e Imposto de Renda projetado estejam integralmente
    descontados conforme cálculo oficial do Tesouro Nacional.
    """

    def __init__(self, diretorio: Path) -> None:
        """Inicializa o leitor de arquivos do Tesouro Direto.

        Args:
            diretorio: Objeto Path apontando para a pasta onde residem os arquivos
                ``ExtratoAnalitico_*.xlsx``.
        """
        self._diretorio = diretorio

    def localizar_arquivos(self) -> list[Path]:
        """Localiza todos os arquivos XLSX do Tesouro Direto no diretório.

        Busca por arquivos com padrão ``ExtratoAnalitico_*.xlsx``, retornando a
        lista ordenada alfabeticamente.

        Returns:
            Lista de objetos Path com os arquivos Excel encontrados.
        """
        return sorted(self._diretorio.glob(f"{PREFIXO}*.xlsx"))

    def extrair_data(self, arquivo: Path) -> tuple[date, datetime]:
        """Extrai a data de referência e o carimbo cronológico completo do nome do arquivo.

        Args:
            arquivo: Caminho do arquivo XLSX.

        Returns:
            Tupla ``(data, timestamp)``, permitindo consolidação por data e
            desempate por timestamp.
        """
        return extrair_data_hora(arquivo.name)

    def _encontrar_linha_cabecalho(self, arquivo: Path) -> int:
        """Localiza dinamicamente a linha de cabeçalho que contém o 'Valor líquido'.

        Devido a variações de layout de exportação do portal do Tesouro Direto,
        o cabeçalho da tabela nem sempre inicia na linha 1. Este método inspeciona
        as primeiras 20 linhas via openpyxl em modo somente-leitura rápido.

        Args:
            arquivo: Caminho do arquivo Excel.

        Returns:
            Número da linha (1-indexado) onde o cabeçalho se encontra.

        Raises:
            ValueError: Se o cabeçalho de 'Valor líquido' não for identificado
                nas primeiras 20 linhas.
        """
        workbook = load_workbook(arquivo, read_only=True, data_only=True)
        planilha = workbook[workbook.sheetnames[0]]

        for numero_linha, linha in enumerate(planilha.iter_rows(values_only=True), start=1):
            if numero_linha > 20:
                break
            for celula in linha:
                texto = _normalizar_texto(celula)
                if "valor" in texto and "liquido" in texto:
                    return numero_linha

        raise ValueError(
            f"Não foi possível localizar o cabeçalho de valor líquido em {arquivo.name}."
        )

    def ler_planilha(self, arquivo: Path) -> pd.DataFrame:
        """Carrega a planilha Excel em um DataFrame pandas com cabeçalhos normalizados.

        Tenta inicialmente ler com cabeçalho de dois níveis (multi-index) e, caso
        haja inconsistência estrutural, recorre à leitura com linha única. Todos
        os nomes de colunas são achatados e normalizados.

        Args:
            arquivo: Caminho do arquivo XLSX a ser lido.

        Returns:
            DataFrame com as colunas normalizadas e dados da primeira aba.

        Raises:
            ValueError: Se a coluna normalizada 'valor liquido' não for encontrada.
        """
        linha_cabecalho = self._encontrar_linha_cabecalho(arquivo)

        try:
            df = pd.read_excel(
                arquivo,
                engine="openpyxl",
                header=[linha_cabecalho - 1, linha_cabecalho],
            )
        except ValueError:
            df = pd.read_excel(arquivo, engine="openpyxl", header=linha_cabecalho - 1)

        # Unifica e normaliza os nomes das colunas
        df.columns = [_flatten_column_name(coluna) for coluna in df.columns]

        # Valida a presença da coluna de valor líquido
        if not any(
            COLUNA_VALOR_LIQUIDO in _normalizar_texto(coluna)
            for coluna in df.columns
        ):
            raise ValueError(
                f"Coluna de valor líquido não encontrada em {arquivo.name}. "
                f"Colunas disponíveis: {list(df.columns)}"
            )
        return df

    def obter_valor_liquido_total(self, arquivo: Path) -> float:
        """Extrai o valor líquido da linha TOTAL da planilha do Tesouro.

        Localiza a linha que identifica o consolidado geral ('TOTAL') e obtém o
        valor líquido correspondente. Caso não encontre uma linha explicitamente
        marcada como TOTAL, utiliza a última linha da planilha.

        Args:
            arquivo: Caminho do arquivo XLSX do Tesouro.

        Returns:
            Valor líquido total em reais (float).

        Raises:
            ValueError: Se o arquivo estiver vazio ou contiver dados monetários ilegíveis.
        """
        df = self.ler_planilha(arquivo)
        if df.empty:
            raise ValueError(f"Planilha vazia: {arquivo.name}")

        coluna_valor = next(
            coluna
            for coluna in df.columns
            if COLUNA_VALOR_LIQUIDO in _normalizar_texto(coluna)
        )
        total_mask = df.apply(_linha_eh_total, axis=1)
        if total_mask.any():
            valor_bruto = df.loc[total_mask, coluna_valor].iloc[-1]
        else:
            valor_bruto = df[coluna_valor].iloc[-1]
        valor = _converter_numero_br(valor_bruto)
        if pd.isna(valor):
            raise ValueError(
                f"Valor líquido inválido na linha de totalização de {arquivo.name}: "
                f"{valor_bruto!r}"
            )
        return float(valor)

    def coletar_registros(self) -> list[RegistroDiario]:
        """Lê todos os extratos analíticos do Tesouro e gera os registros diários.

        Returns:
            Lista de instâncias de :class:`RegistroDiario`, uma para cada arquivo válido.
        """
        registros: list[RegistroDiario] = []
        for arquivo in self.localizar_arquivos():
            data_ref, timestamp = self.extrair_data(arquivo)
            valor = self.obter_valor_liquido_total(arquivo)
            registros.append(
                RegistroDiario(data=data_ref, valor=valor, timestamp=timestamp)
            )
        return registros

    def _extrair_taxas_e_pesos(
        self, arquivo: Path
    ) -> tuple[pd.Series, pd.Series]:
        """Extrai as taxas contratadas e os respectivos pesos (valor investido) de um arquivo.

        Retorna apenas as linhas de títulos individuais (exclui a linha de TOTAL)
        que possuam taxa contratada legível. O peso de cada título corresponde ao
        ``Valor investido``; quando a coluna de valor investido não existir ou for
        ilegível, o peso é preenchido com ``NaN`` para que a agregação recorra à
        média aritmética simples.

        Args:
            arquivo: Caminho do arquivo XLSX de onde extrair as taxas.

        Returns:
            Tupla ``(taxas, pesos)`` de séries pandas alinhadas por posição.

        Raises:
            ValueError: Se a coluna de rentabilidade não estiver disponível ou não
                houver taxas numéricas legíveis no arquivo.
        """
        df = self.ler_planilha(arquivo)

        coluna_rentabilidade = next(
            (
                coluna
                for coluna in df.columns
                if COLUNA_RENTABILIDADE in _normalizar_texto(coluna)
            ),
            None,
        )
        if coluna_rentabilidade is None:
            raise ValueError(
                f"Coluna de rentabilidade contratada não encontrada em "
                f"{arquivo.name}. Colunas disponíveis: {list(df.columns)}"
            )

        # Isola as linhas individuais de títulos excluindo a linha de total
        mask_total = df.apply(_linha_eh_total, axis=1)
        dados = df.loc[~mask_total]

        # Extrai os percentuais anuais e retém apenas as linhas com taxa legível
        taxas = dados[coluna_rentabilidade].map(_extrair_percentual_ao_ano)
        validos = taxas.notna()
        taxas = taxas[validos]
        if taxas.empty:
            raise ValueError(
                f"Nenhuma taxa contratada válida encontrada em {arquivo.name}."
            )

        # Associa o valor investido de cada título como peso (ou NaN se indisponível)
        coluna_investido = next(
            (
                coluna
                for coluna in df.columns
                if COLUNA_VALOR_INVESTIDO in _normalizar_texto(coluna)
            ),
            None,
        )
        if coluna_investido is not None:
            pesos = dados.loc[validos, coluna_investido].map(_converter_numero_br)
        else:
            pesos = pd.Series(float("nan"), index=taxas.index)

        return taxas.reset_index(drop=True), pesos.reset_index(drop=True)

    def _consolidar_taxa_media(self, arquivos: list[Path]) -> float:
        """Calcula a taxa média ponderada contratada agregando MÚLTIPLOS arquivos.

        Concatena os títulos de todos os arquivos informados (ex.: um extrato por
        conta/corretora referente à mesma data) e calcula a média das taxas anuais
        (spreads contratados) ponderada pelo ``Valor investido`` em cada papel.
        Dessa forma, quando há mais de um extrato para a mesma data de referência,
        todas as contas contribuem proporcionalmente ao capital investido — em
        consistência com a soma dos valores líquidos realizada na série histórica.

        Args:
            arquivos: Lista de caminhos de arquivos XLSX a consolidar.

        Returns:
            Taxa anual ponderada como fração decimal (ex.: 0.0784 para 7,84% a.a.).

        Raises:
            ValueError: Se nenhum dos arquivos fornecer taxas contratadas válidas.
        """
        taxas_partes: list[pd.Series] = []
        pesos_partes: list[pd.Series] = []
        for arquivo in arquivos:
            taxas, pesos = self._extrair_taxas_e_pesos(arquivo)
            taxas_partes.append(taxas)
            pesos_partes.append(pesos)

        taxas = pd.concat(taxas_partes, ignore_index=True)
        pesos = pd.concat(pesos_partes, ignore_index=True)

        # Pondera pelo valor investido total; se os pesos forem indisponíveis
        # (todos NaN/zero), recorre à média aritmética simples das taxas.
        pesos = pesos.fillna(0.0)
        if pesos.sum() > 0:
            return float((taxas * pesos).sum() / pesos.sum())
        return float(taxas.mean())

    def obter_taxa_media_contratada(self, arquivo: Path) -> float:
        """Calcula a taxa média ponderada contratada (a.a.) da carteira em um arquivo.

        Calcula a média ponderada das taxas anuais (spreads contratados) de cada título,
        utilizando como peso o ``Valor investido`` em cada aplicação. A linha de
        TOTAL é desconsiderada para não duplicar valores.

        Args:
            arquivo: Caminho do arquivo XLSX de onde calcular as taxas.

        Returns:
            Taxa anual ponderada como fração decimal (ex.: 0.0825 para 8,25% a.a.).

        Raises:
            ValueError: Se a coluna de rentabilidade não estiver disponível ou
                não houver taxas numéricas legíveis.
        """
        return self._consolidar_taxa_media([arquivo])

    def obter_taxa_media_mais_recente(self) -> float | None:
        """Obtém a taxa média ponderada contratada consolidando os extratos da data mais recente.

        Identifica a data de referência mais recente (ignorando o horário) entre
        todos os extratos e consolida a rentabilidade contratada de TODOS os
        arquivos dessa data — um por conta/corretora — ponderando pelo valor
        investido de cada título. Assim, quando há mais de um extrato para o
        mês/data vigente, todas as contas são consideradas no cálculo do spread,
        em consistência com a soma dos valores líquidos.

        Returns:
            Taxa anual média em fração decimal, ou ``None`` se nenhum arquivo existir.
        """
        arquivos = self.localizar_arquivos()
        if not arquivos:
            return None

        # Determina a data de referência mais recente (apenas dia/mês/ano)
        data_mais_recente = max(self.extrair_data(a)[0] for a in arquivos)

        # Seleciona todos os extratos dessa data (todas as contas/corretoras)
        arquivos_recentes = [
            a for a in arquivos if self.extrair_data(a)[0] == data_mais_recente
        ]
        return self._consolidar_taxa_media(arquivos_recentes)
