"""Análise aprofundada de exportações brutas de cotações.

Esta camada não substitui a equalização tradicional. Ela interpreta bases em
que cada linha é uma cotação independente e o mesmo produto aparece em várias
cotações, evitando tratar o código da cotação como identificador do produto.
"""

from __future__ import annotations

import pandas as pd


_SOURCE_COLUMNS = [
    "DESCRIPTION", "SUPPLIER", "QUANTITY", "UNIT", "UNIT_PRICE",
    "CATEGORY", "CURRENCY", "STATUS", "DELIVERY_DAYS", "QUOTE_DATE", "ID",
]


def _join_unique(values: pd.Series) -> str:
    items = sorted({str(value).strip() for value in values if pd.notna(value) and str(value).strip()})
    return ", ".join(items)


def _numeric_summary(group: pd.DataFrame, column: str) -> tuple[float | None, float | None, float | None]:
    values = pd.to_numeric(group[column], errors="coerce").dropna()
    if values.empty:
        return None, None, None
    return float(values.min()), float(values.mean()), float(values.max())


def _variacao_percentual(minimo: float | None, maximo: float | None) -> float | None:
    """Variação percentual entre o menor e o maior preço.

    Sem base positiva não existe percentual matematicamente válido; preço
    zerado ou ausente devolve ``None`` em vez de erro ou ``inf``.
    """
    if minimo is None or maximo is None or minimo <= 0:
        return None
    return round((maximo - minimo) / minimo * 100, 2)


def analisar_fonte(
    normalized: pd.DataFrame,
    avisos: list[str],
    *,
    linhas_importadas: int | None = None,
    linhas_descartadas: int = 0,
) -> dict:
    """Retorna perfil, qualidade e comparativos da exportação original."""
    data = normalized.copy()
    for column in _SOURCE_COLUMNS:
        if column not in data:
            data[column] = None

    data["DESCRIPTION"] = data["DESCRIPTION"].fillna("Sem descrição").astype(str).str.strip()
    data["SUPPLIER"] = data["SUPPLIER"].fillna("Sem fornecedor").astype(str).str.strip()

    products = []
    for product, group in data.groupby("DESCRIPTION", sort=True):
        minimum, average, maximum = _numeric_summary(group, "UNIT_PRICE")
        suppliers = group["SUPPLIER"].dropna().nunique()
        variacao = _variacao_percentual(minimum, maximum)
        products.append({
            "Produto": product,
            "Categoria": _join_unique(group["CATEGORY"]),
            "Cotações": int(len(group)),
            "Fornecedores": int(suppliers),
            "Quantidade Total": float(pd.to_numeric(group["QUANTITY"], errors="coerce").sum()),
            "Menor Preço": minimum,
            "Preço Médio": average,
            "Maior Preço": maximum,
            "Variação de Preço %": variacao,
            "Unidades": _join_unique(group["UNIT"]),
            "Moedas": _join_unique(group["CURRENCY"]),
            "Status": _join_unique(group["STATUS"]),
            "Condições de Entrega": _join_unique(group["DELIVERY_DAYS"]),
        })

    suppliers = []
    for supplier, group in data.groupby("SUPPLIER", sort=True):
        minimum, average, maximum = _numeric_summary(group, "UNIT_PRICE")
        suppliers.append({
            "Fornecedor": supplier,
            "Produtos Cotados": int(group["DESCRIPTION"].nunique()),
            "Cotações": int(len(group)),
            "Preço Mínimo": minimum,
            "Preço Médio": average,
            "Preço Máximo": maximum,
            "Categorias": _join_unique(group["CATEGORY"]),
            "Moedas": _join_unique(group["CURRENCY"]),
            "Status": _join_unique(group["STATUS"]),
            "Condições de Entrega": _join_unique(group["DELIVERY_DAYS"]),
        })

    price = pd.to_numeric(data["UNIT_PRICE"], errors="coerce")
    quality = {
        "Linhas físicas analisadas": int(linhas_importadas or len(data)),
        "Linhas válidas": int(len(data)),
        "Linhas descartadas": int(linhas_descartadas),
        "Produtos distintos": int(data["DESCRIPTION"].nunique()),
        "Fornecedores distintos": int(data["SUPPLIER"].nunique()),
        "Linhas com preço": int(price.notna().sum()),
        "Linhas sem preço": int(price.isna().sum()),
        "Linhas com condição de entrega": int(data["DELIVERY_DAYS"].notna().sum()),
        "Linhas com status": int(data["STATUS"].notna().sum()),
        "Linhas com moeda": int(data["CURRENCY"].notna().sum()),
        "Avisos de importação": len(avisos),
    }

    return {
        "perfil": {
            "tipo": "Exportação bruta de cotações" if data["DESCRIPTION"].nunique() < len(data) else "Base tabular de propostas",
            "observacao": "Produtos foram agrupados pela descrição para comparação entre cotações.",
            "qualidade": quality,
        },
        "produtos": pd.DataFrame(products),
        "fornecedores": pd.DataFrame(suppliers),
    }
