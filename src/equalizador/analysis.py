import numpy as np
import pandas as pd


def criar_mapa_comparativo(resultado_motor: pd.DataFrame, cotacao) -> pd.DataFrame:
    fornecedores = [f.nome for f in cotacao.fornecedores]
    registros_por_chave = resultado_motor.set_index(
        ["ID", "Fornecedor"]
    ).to_dict(orient="index")
    linhas = []

    for item in cotacao.itens:
        linha = {
            "ID": item.id_item,
            "Descrição Solicitada": item.descricao,
            "Quantidade": item.quantidade,
            "Unidade": item.unidade,
        }

        precos_validos = {}
        status = []
        for fornecedor in fornecedores:
            registro = registros_por_chave.get((item.id_item, fornecedor))
            if registro is None:
                preco = np.nan
            else:
                preco = registro["Valor Unitário"] if bool(registro["Preço Elegível"]) else np.nan
                status.append(f"{fornecedor}: {registro['Status Equalização']}")

            linha[fornecedor] = preco
            if pd.notna(preco):
                precos_validos[fornecedor] = float(preco)

        if precos_validos:
            menor = min(precos_validos.values())
            maior = max(precos_validos.values())
            linha["Menor Preço"] = menor
            linha["Maior Preço"] = maior
            linha["Diferença %"] = ((maior - menor) / menor * 100) if menor > 0 else np.nan
            linha["Melhor Fornecedor"] = ", ".join(
                f for f, p in precos_validos.items() if np.isclose(p, menor)
            )
        else:
            linha["Menor Preço"] = np.nan
            linha["Maior Preço"] = np.nan
            linha["Diferença %"] = np.nan
            linha["Melhor Fornecedor"] = "Nenhum preço elegível"

        linha["Status Equalização"] = " | ".join(status)
        linhas.append(linha)

    return pd.DataFrame(linhas)


def gerar_resumo_fornecedores(mapa_final, resultado_motor, indicadores_comerciais, cotacao):
    resumo = []

    for fornecedor in sorted(resultado_motor["Fornecedor"].dropna().unique()):
        dados = resultado_motor[resultado_motor["Fornecedor"].eq(fornecedor)]
        elegiveis = dados[dados["Preço Elegível"].eq(True)].copy()

        total = (
            elegiveis["Valor Unitário"] * elegiveis["Quantidade Cotada"]
        ).sum() if not elegiveis.empty else 0.0

        menores = mapa_final["Melhor Fornecedor"].fillna("").apply(
            lambda x: fornecedor in [p.strip() for p in str(x).split(",")]
        ).sum()

        itens_cotados = int((dados["Status Equalização"] != "NÃO COTADO").sum())
        resumo.append({
            "Fornecedor": fornecedor,
            "Itens Cotados": itens_cotados,
            "Itens Não Cotados": int((dados["Status Equalização"] == "NÃO COTADO").sum()),
            "Itens Equivalentes": int((dados["Status Equalização"] == "EQUIVALENTE").sum()),
            "Itens com Divergência": int(
                dados["Status Equalização"].isin(["DIVERGÊNCIA", "DIVERGÊNCIA ESTRUTURAL"]).sum()
            ),
            "Preços Elegíveis": int(len(elegiveis)),
            "Menores Preços": int(menores),
            # Percentual sobre os itens que o fornecedor realmente cotou, não
            # sobre o total da cotação (que diluía quem não participou do item).
            "Percentual Menores Preços": (
                float(menores / itens_cotados * 100) if itens_cotados else 0.0
            ),
            "Total Proposta Elegível": float(total),
        })

    return pd.DataFrame(resumo)


def gerar_indicadores(mapa_final, resultado_motor, cotacao):
    diferencas = mapa_final["Diferença %"].dropna()

    vencedores = mapa_final["Melhor Fornecedor"].fillna("").apply(
        lambda valor: {nome.strip() for nome in str(valor).split(",")}
    )
    contagem = {
        fornecedor.nome: sum(fornecedor.nome in nomes for nomes in vencedores)
        for fornecedor in cotacao.fornecedores
    }

    destaque = max(contagem, key=lambda nome: contagem[nome]) if contagem else None

    return {
        "Total de Itens": len(cotacao.itens),
        "Total de Fornecedores": len(cotacao.fornecedores),
        "Itens com Preço Elegível": int(mapa_final["Menor Preço"].notna().sum()),
        "Itens sem Preço Elegível": int(mapa_final["Menor Preço"].isna().sum()),
        "Itens com Divergência": int(
            resultado_motor["Status Equalização"].isin(
                ["DIVERGÊNCIA", "DIVERGÊNCIA ESTRUTURAL"]
            ).groupby(resultado_motor["ID"]).any().sum()
        ),
        "Itens com Não Cotação": int(
            resultado_motor["Status Equalização"].eq("NÃO COTADO")
            .groupby(resultado_motor["ID"]).any().sum()
        ),
        "Maior Diferença de Preço (%)": float(diferencas.max()) if not diferencas.empty else np.nan,
        "Fornecedor com Mais Menores Preços": destaque,
        "Quantidade de Menores Preços": int(contagem[destaque]) if destaque else 0,
    }


def gerar_alertas(resultado_motor, mapa_final, indicadores_comerciais):
    alertas = []

    for _, row in resultado_motor[
        resultado_motor["Status Equalização"].isin(["DIVERGÊNCIA", "DIVERGÊNCIA ESTRUTURAL"])
    ].iterrows():
        alertas.append({
            "Prioridade": "ALTA",
            "Tipo": "Divergência",
            "ID": row["ID"],
            "Descrição": row["Descrição Solicitada"],
            "Quantidade": row["Quantidade Solicitada"],
            "Unidade": row["Unidade Solicitada"],
            "Fornecedor": row["Fornecedor"],
            "Mensagem": (
                f"{row['Fornecedor']} apresenta {row['Status Equalização'].lower()} "
                f"no item {row['ID']} ({row['Descrição Solicitada']}): "
                f"{row['Quantidade Solicitada']} {row['Unidade Solicitada']}."
            ),
        })

    for _, row in resultado_motor[resultado_motor["Status Equalização"].eq("NÃO COTADO")].iterrows():
        alertas.append({
            "Prioridade": "ALTA",
            "Tipo": "Não cotado",
            "ID": row["ID"],
            "Descrição": row["Descrição Solicitada"],
            "Quantidade": row["Quantidade Solicitada"],
            "Unidade": row["Unidade Solicitada"],
            "Fornecedor": row["Fornecedor"],
            "Mensagem": (
                f"{row['Fornecedor']} não cotou o item {row['ID']} "
                f"({row['Descrição Solicitada']}), quantidade "
                f"{row['Quantidade Solicitada']} {row['Unidade Solicitada']}."
            ),
        })

    for _, row in mapa_final[mapa_final["Diferença %"].ge(30)].iterrows():
        alertas.append({
            "Prioridade": "MÉDIA",
            "Tipo": "Diferença de preço",
            "ID": row["ID"],
            "Descrição": row["Descrição Solicitada"],
            "Quantidade": row["Quantidade"],
            "Unidade": row["Unidade"],
            "Fornecedor": None,
            "Mensagem": (
                f"O item {row['ID']} ({row['Descrição Solicitada']}), "
                f"quantidade {row['Quantidade']} {row['Unidade']}, apresenta "
                f"diferença de {row['Diferença %']:.2f}% entre preços elegíveis."
            ),
        })

    for _, row in indicadores_comerciais.iterrows():
        if not bool(row.get("Sem Pedido Mínimo", False)):
            alertas.append({
                "Prioridade": "MÉDIA",
                "Tipo": "Pedido mínimo",
                "ID": None,
                "Descrição": None,
                "Quantidade": None,
                "Unidade": None,
                "Fornecedor": row["Fornecedor"],
                "Mensagem": f"{row['Fornecedor']} possui pedido mínimo informado: {row.get('Pedido Mínimo Original')}.",
            })
        frete_original = row.get("Frete Original")
        if "Frete Informado" in indicadores_comerciais.columns:
            frete_informado = bool(row.get("Frete Informado", False))
        else:
            frete_informado = pd.notna(frete_original)
        # Só alertamos quando o frete foi realmente declarado como não incluso.
        # Ausência de informação gera um alerta mais leve e distinto.
        if frete_informado and not bool(row.get("Frete Incluso", False)):
            alertas.append({
                "Prioridade": "MÉDIA",
                "Tipo": "Frete",
                "ID": None,
                "Descrição": None,
                "Quantidade": None,
                "Unidade": None,
                "Fornecedor": row["Fornecedor"],
                "Mensagem": f"{row['Fornecedor']} não apresenta frete incluso ({frete_original}).",
            })
        elif not frete_informado:
            alertas.append({
                "Prioridade": "BAIXA",
                "Tipo": "Frete",
                "ID": None,
                "Descrição": None,
                "Quantidade": None,
                "Unidade": None,
                "Fornecedor": row["Fornecedor"],
                "Mensagem": f"{row['Fornecedor']} não informou a condição de frete.",
            })

    return pd.DataFrame(alertas)


def gerar_insights(mapa_final, resultado_motor, indicadores_comerciais, cotacao):
    insights = [
        f"A cotação possui {len(cotacao.itens)} itens e {len(cotacao.fornecedores)} fornecedores participantes."
    ]

    divergentes = resultado_motor[
        resultado_motor["Status Equalização"].isin(["DIVERGÊNCIA", "DIVERGÊNCIA ESTRUTURAL"])
    ]["ID"].nunique()

    insights.append(
        f"Foram identificados {divergentes} item(ns) com divergências."
        if divergentes else "Não foram identificadas divergências."
    )

    nao_cotados = resultado_motor[
        resultado_motor["Status Equalização"].eq("NÃO COTADO")
    ]["ID"].nunique()

    if nao_cotados:
        insights.append(f"Existem {nao_cotados} item(ns) não cotados por pelo menos um fornecedor.")

    diferencas = mapa_final["Diferença %"].dropna()
    if not diferencas.empty:
        maior = diferencas.idxmax()
        if pd.notna(maior):
            insights.append(
                f"A maior diferença de preço entre propostas elegíveis foi de "
                f"{mapa_final.loc[maior, 'Diferença %']:.2f}% no item {mapa_final.loc[maior, 'ID']}."
            )

    pagamentos = indicadores_comerciais["Dias para Pagamento"].dropna()
    if not pagamentos.empty:
        idx = pagamentos.idxmax()
        insights.append(
            f"{indicadores_comerciais.loc[idx, 'Fornecedor']} apresenta o maior prazo de pagamento identificado: "
            f"{indicadores_comerciais.loc[idx, 'Dias para Pagamento']:.0f} dias."
        )

    entregas = indicadores_comerciais["Dias para Entrega"].dropna()
    if not entregas.empty:
        idx = entregas.idxmin()
        insights.append(
            f"{indicadores_comerciais.loc[idx, 'Fornecedor']} apresenta o menor prazo de entrega identificado: "
            f"{indicadores_comerciais.loc[idx, 'Dias para Entrega']:.0f} dias."
        )

    return insights


def gerar_analise_executiva(mapa_final, resultado_motor, resumo_fornecedores):
    economia = 0.0
    total_menores = 0.0

    for _, row in mapa_final.iterrows():
        if pd.notna(row["Menor Preço"]) and pd.notna(row["Maior Preço"]):
            economia += (row["Maior Preço"] - row["Menor Preço"]) * row["Quantidade"]
        if pd.notna(row["Menor Preço"]):
            total_menores += row["Menor Preço"] * row["Quantidade"]

    ranking = (
        resumo_fornecedores[["Fornecedor", "Total Proposta Elegível"]]
        .sort_values("Total Proposta Elegível")
        .reset_index(drop=True)
        if not resumo_fornecedores.empty else pd.DataFrame()
    )

    return {
        "Itens da Cotação": len(mapa_final),
        "Fornecedores Participantes": resultado_motor["Fornecedor"].nunique(),
        "Itens com Divergência": int(
            resultado_motor["Status Equalização"].isin(
                ["DIVERGÊNCIA", "DIVERGÊNCIA ESTRUTURAL"]
            ).groupby(resultado_motor["ID"]).any().sum()
        ),
        "Itens Não Cotados": int(
            resultado_motor["Status Equalização"].eq("NÃO COTADO")
            .groupby(resultado_motor["ID"]).any().sum()
        ),
        "Economia Potencial": round(economia, 2),
        "Total Comprando pelo Menor Preço": round(total_menores, 2),
        "Ranking por Valor": ranking,
    }
