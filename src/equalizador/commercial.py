import re
import pandas as pd


def extrair_dias(texto) -> float | None:
    if texto is None or pd.isna(texto):
        return None

    valor = str(texto).strip().lower()
    if any(
        termo in valor
        for termo in ("imediato", "imediata", "à vista", "a vista", "avista")
    ):
        return 0.0

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:dias?|d)?\b", valor)
    if not match:
        return None

    return float(match.group(1).replace(",", "."))


def criar_indicadores_comerciais(cotacao) -> pd.DataFrame:
    registros = []

    for fornecedor in cotacao.fornecedores:
        cond = fornecedor.condicoes
        frete_texto = str(cond.frete or "").strip().lower()
        minimo_texto = str(cond.pedido_minimo or "").strip().lower()
        # Frete é um estado de três valores: incluso, por conta do comprador ou
        # não informado. Tratar o silêncio como "não incluso" penalizava planilhas
        # que simplesmente não preencheram a coluna de frete.
        frete_informado = bool(frete_texto)
        frete_negado = any(
            termo in frete_texto
            for termo in ("não", "nao", "fob", "cliente", "comprador")
        )
        frete_incluso = any(
            termo in frete_texto
            for termo in ("inclus", "cif", "fornecedor")
        ) and not frete_negado
        # Sem informação de pedido mínimo não é o mesmo que exigir um mínimo.
        minimo_informado = bool(minimo_texto)
        sem_minimo = (
            not minimo_informado
            or any(
                termo in minimo_texto
                for termo in (
                    "sem mínimo", "sem minimo", "não há", "nao ha",
                    "não se aplica", "nao se aplica", "nenhum", "isento",
                )
            )
            or minimo_texto in {"0", "0,00", "0.00"}
        )

        registros.append({
            "Fornecedor": fornecedor.nome,
            "Pagamento Original": cond.pagamento,
            "Dias para Pagamento": extrair_dias(cond.pagamento),
            "Prazo Original": cond.prazo_entrega,
            "Dias para Entrega": extrair_dias(cond.prazo_entrega),
            "Pedido Mínimo Original": cond.pedido_minimo,
            "Sem Pedido Mínimo": sem_minimo,
            "Frete Original": cond.frete,
            "Frete Incluso": frete_incluso,
            "Frete Informado": frete_informado,
            "Validade": cond.validade_proposta,
        })

    return pd.DataFrame(registros)


def adicionar_score_comercial(df: pd.DataFrame) -> pd.DataFrame:
    """Score comercial por item/fornecedor, usando condições do fornecedor.

    Política: pagamento maior é melhor, entrega menor é melhor, frete incluso é
    melhor. Uma condição não informada é neutra (peso zero) em vez de zero
    ponto, para não punir planilhas que deixaram a coluna em branco.
    """
    df = df.copy()

    for _, grupo in df.groupby("ID", sort=False):
        elegiveis = grupo[grupo["Elegível para Recomendação"]].copy()

        if elegiveis.empty:
            continue

        pagamento = pd.to_numeric(elegiveis["Dias para Pagamento"], errors="coerce")
        entrega = pd.to_numeric(elegiveis["Dias para Entrega"], errors="coerce")
        if "Frete Informado" in elegiveis.columns:
            frete_informado = elegiveis["Frete Informado"].fillna(False).astype(bool)
        else:
            frete_informado = elegiveis["Frete Incluso"].notna()
        frete_incluso = elegiveis["Frete Incluso"].fillna(False).astype(bool)

        max_pag = pagamento.max()
        min_ent = entrega[entrega > 0].min()

        if pd.notna(max_pag) and max_pag > 0:
            pag_score = (pagamento / max_pag * 100).where(pagamento.notna(), other=pd.NA)
        else:
            # Sem prazo de pagamento utilizável a dimensão é descartada.
            pag_score = pd.Series(pd.NA, index=pagamento.index, dtype="Float64")

        if pd.notna(min_ent):
            ent_score = pd.Series(pd.NA, index=entrega.index, dtype="Float64")
            positivos = entrega > 0
            ent_score.loc[positivos] = min_ent / entrega.loc[positivos] * 100
            ent_score.loc[entrega.eq(0)] = 100.0
        else:
            ent_score = pd.Series(pd.NA, index=entrega.index, dtype="Float64")

        if frete_informado.any():
            frete_score = pd.Series(pd.NA, index=elegiveis.index, dtype="Float64")
            frete_score.loc[frete_informado] = (
                frete_incluso.loc[frete_informado].astype(float) * 100
            )
        else:
            frete_score = pd.Series(pd.NA, index=elegiveis.index, dtype="Float64")

        comercial = pd.concat(
            [pag_score.rename("pag"), ent_score.rename("ent"), frete_score.rename("frete")],
            axis=1,
        ).mean(axis=1, skipna=True)

        # Todos os componentes ausentes: condição totalmente desconhecida é neutra.
        df.loc[elegiveis.index, "Score Comercial"] = comercial.fillna(50.0)

    return df
