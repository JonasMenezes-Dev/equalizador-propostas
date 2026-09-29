import numpy as np
import pandas as pd

from .commercial import adicionar_score_comercial
from .config import EngineConfig


REQUIRED = [
    "ID", "Fornecedor", "Valor Unitário",
    "Similaridade (%)", "Score Atributos (%)",
    "Validação Quantidade", "Validação Unidade",
    "Status Equalização", "Preço Elegível",
]


def definir_elegibilidade_preco(row) -> bool:
    if row["Status Equalização"] == "NÃO COTADO":
        return False
    if row["Validação Quantidade"] != "OK":
        return False
    if row["Validação Unidade"] != "OK":
        return False
    if row["Divergências Atributos"] > 0:
        return False

    valor = pd.to_numeric(row["Valor Unitário"], errors="coerce")
    return pd.notna(valor) and valor > 0


def preparar_base(resultado_motor: pd.DataFrame, indicadores_comerciais: pd.DataFrame) -> pd.DataFrame:
    faltantes = [c for c in REQUIRED if c not in resultado_motor.columns]
    if faltantes:
        raise ValueError(f"Colunas ausentes: {faltantes}")

    df = resultado_motor.copy()

    for col in ["Valor Unitário", "Similaridade (%)", "Score Atributos (%)"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    comerciais = indicadores_comerciais.copy()
    comerciais.columns = comerciais.columns.astype(str).str.strip()

    cols = [
        "Fornecedor", "Dias para Pagamento", "Dias para Entrega",
        "Frete Incluso", "Frete Informado", "Sem Pedido Mínimo",
    ]
    comerciais = comerciais[[c for c in cols if c in comerciais.columns]]

    if comerciais["Fornecedor"].duplicated().any():
        raise ValueError("Fornecedor duplicado em indicadores comerciais.")

    df = df.merge(comerciais, on="Fornecedor", how="left", validate="many_to_one")

    df["Elegível para Recomendação"] = (
        df["Preço Elegível"].fillna(False).astype(bool)
        & df["Status Equalização"].eq("EQUIVALENTE")
        & df["Validação Quantidade"].eq("OK")
        & df["Validação Unidade"].eq("OK")
    )

    df.loc[df["Status Equalização"].eq("NÃO COTADO"), "Elegível para Recomendação"] = False

    return df


def calcular_componentes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["Score Preço", "Score Similaridade", "Score Atributos", "Score Comercial"]:
        df[col] = 0.0

    elegiveis = df["Elegível para Recomendação"]
    precos = pd.to_numeric(df["Valor Unitário"], errors="coerce")
    menor_preco = precos.where(elegiveis).groupby(df["ID"], sort=False).transform("min")
    validos = elegiveis & menor_preco.gt(0) & precos.gt(0)
    df.loc[validos, "Score Preço"] = menor_preco[validos] / precos[validos] * 100
    df.loc[elegiveis, "Score Similaridade"] = df.loc[elegiveis, "Similaridade (%)"].fillna(0)
    df.loc[elegiveis, "Score Atributos"] = df.loc[elegiveis, "Score Atributos (%)"].fillna(0)

    return adicionar_score_comercial(df)


def calcular_score(df: pd.DataFrame, config: EngineConfig) -> pd.DataFrame:
    config.validar()
    df = df.copy()
    pesos = config.pesos_score

    df["Score Recomendação"] = (
        df["Score Preço"] * pesos["Score Preço"]
        + df["Score Similaridade"] * pesos["Score Similaridade"]
        + df["Score Atributos"] * pesos["Score Atributos"]
        + df["Score Comercial"] * pesos["Score Comercial"]
    )

    df["Score Recomendação"] = df["Score Recomendação"].clip(0, 100)
    df.loc[~df["Elegível para Recomendação"], "Score Recomendação"] = 0.0

    condicoes = [
        df["Elegível para Recomendação"] & (df["Score Recomendação"] >= 90),
        df["Elegível para Recomendação"] & (df["Score Recomendação"] >= 75),
        df["Elegível para Recomendação"] & (df["Score Recomendação"] >= 60),
    ]
    valores = ["EXCELENTE", "BOA", "ACEITÁVEL"]

    df["Classificação Recomendação"] = np.select(
        condicoes, valores, default="NÃO RECOMENDADO"
    )

    return df


def criar_ranking(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_score"] = df["Score Recomendação"].fillna(0)

    # Critério principal + desempates determinísticos.
    df = df.sort_values(
        ["ID", "_score", "Valor Unitário", "Score Similaridade",
         "Score Atributos", "Score Comercial", "Fornecedor"],
        ascending=[True, False, True, False, False, False, True],
        kind="mergesort",
    )

    df["Ranking"] = df.groupby("ID")["_score"].rank(
        method="first", ascending=False
    ).astype("Int64")

    df.loc[~df["Elegível para Recomendação"], "Ranking"] = pd.NA
    return df.drop(columns="_score")


def gerar_recomendacoes(df: pd.DataFrame, config: EngineConfig) -> pd.DataFrame:
    registros = []

    for item_id, grupo in df.groupby("ID", sort=True):
        elegiveis = grupo[grupo["Elegível para Recomendação"]].copy()

        if elegiveis.empty:
            registros.append({
                "ID": item_id,
                "Fornecedor Recomendado": "NENHUM",
                "Score Recomendação": 0.0,
                "Valor Unitário": np.nan,
                "Classificação": "SEM OPÇÃO ELEGÍVEL",
                "Empate Técnico": False,
                "Fornecedores Empatados": "",
                "Motivo": "Nenhum fornecedor atende aos critérios mínimos.",
            })
            continue

        elegiveis = elegiveis.sort_values(
            ["Score Recomendação", "Valor Unitário", "Score Similaridade",
             "Score Atributos", "Score Comercial", "Fornecedor"],
            ascending=[False, True, False, False, False, True],
            kind="mergesort",
        )

        melhor = elegiveis.iloc[0]
        empatados = elegiveis[
            (melhor["Score Recomendação"] - elegiveis["Score Recomendação"])
            <= config.limite_empate_tecnico
        ]
        fornecedores_empatados = empatados["Fornecedor"].tolist()
        empate_tecnico = len(fornecedores_empatados) > 1
        motivo = []

        if np.isclose(melhor["Score Preço"], 100):
            motivo.append("menor preço")
        elif melhor["Score Preço"] >= 90:
            motivo.append("preço muito competitivo")

        if melhor["Score Similaridade"] >= 99.99:
            motivo.append("descrição equivalente")
        elif melhor["Score Similaridade"] >= config.limite_similaridade:
            motivo.append("descrição altamente similar")

        if melhor["Score Atributos"] >= 99.99:
            motivo.append("atributos equivalentes")
        elif melhor["Score Atributos"] >= 80:
            motivo.append("atributos compatíveis")

        if melhor["Score Comercial"] >= 90:
            motivo.append("excelentes condições comerciais")
        elif melhor["Score Comercial"] >= 70:
            motivo.append("condições comerciais adequadas")

        if empate_tecnico:
            motivo.append("empate técnico: " + ", ".join(fornecedores_empatados))

        registros.append({
            "ID": item_id,
            "Fornecedor Recomendado": melhor["Fornecedor"],
            "Score Recomendação": melhor["Score Recomendação"],
            "Valor Unitário": melhor["Valor Unitário"],
            "Classificação": melhor["Classificação Recomendação"],
            "Empate Técnico": empate_tecnico,
            "Fornecedores Empatados": ", ".join(fornecedores_empatados),
            "Motivo": ", ".join(motivo) or "melhor score geral",
        })

    return pd.DataFrame(registros)
