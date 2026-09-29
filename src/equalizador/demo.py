from .models import (
    CondicoesComerciais,
    Cotacao,
    Fornecedor,
    ItemProposta,
    ItemSolicitado,
)


def criar_cotacao_demo(
    quantidade_itens: int = 150,
    quantidade_fornecedores: int = 5,
) -> Cotacao:
    produtos = [
        ("Caneta azul ponta fina", "Caixa"),
        ("Caneta preta ponta fina", "Caixa"),
        ("Papel A4 75g", "Caixa"),
        ("Papel A4 90g", "Caixa"),
        ("Grampeador médio", "Unidade"),
        ("Pasta suspensa", "Unidade"),
        ("Lápis preto HB", "Caixa"),
        ("Borracha branca escolar", "Unidade"),
        ("Marcador permanente preto", "Unidade"),
        ("Clips galvanizado nº 2", "Caixa"),
        ("Envelope pardo A4", "Pacote"),
        ("Tesoura escolar 21cm", "Unidade"),
        ("Caderno universitário", "Unidade"),
        ("Pasta catálogo", "Unidade"),
        ("Régua 30cm", "Unidade"),
        ("Cola branca 90g", "Unidade"),
        ("Fita adesiva transparente", "Unidade"),
        ("Corretivo líquido", "Unidade"),
        ("Apontador plástico", "Unidade"),
        ("Calculadora de mesa", "Unidade"),
    ]

    quantidades = {"Caixa": 10, "Unidade": 20, "Pacote": 10}

    itens = [
        ItemSolicitado(
            id_item=f"{i+1:03d}",
            descricao=produtos[i % len(produtos)][0],
            quantidade=quantidades[produtos[i % len(produtos)][1]] + (i % 5) * 5,
            unidade=produtos[i % len(produtos)][1],
        )
        for i in range(quantidade_itens)
    ]

    fornecedores = []
    for idx in range(quantidade_fornecedores):
        nome = f"Fornecedor {chr(65 + idx)}"
        propostas = []

        for i, item in enumerate(itens):
            descricao = item.descricao
            unidade = item.unidade

            if i % 37 == 0 and idx == 1:
                descricao = descricao.replace("escolar", "")

            if i % 53 == 0 and idx == 2 and "ponta fina" in descricao:
                descricao = descricao.replace("ponta fina", "ponta média")

            if i % 61 == 0 and idx == 3 and unidade == "Unidade":
                unidade = "Caixa"

            if i % 47 == 0 and idx == 4:
                continue

            preco_base = 5 + (i % 20) * 1.35
            preco = round(preco_base * (0.85 + idx * 0.07), 2)

            propostas.append(
                ItemProposta(
                    id_item=item.id_item,
                    descricao=descricao,
                    quantidade=item.quantidade,
                    unidade=unidade,
                    valor_unitario=preco,
                )
            )

        fornecedores.append(
            Fornecedor(
                nome=nome,
                itens=propostas,
                condicoes=CondicoesComerciais(
                    pagamento=f"{30 + idx * 15} dias",
                    prazo_entrega=f"{5 + idx * 2} dias",
                    pedido_minimo="Sem mínimo" if idx % 2 == 0 else "5 caixas",
                    frete="Incluso" if idx < 2 else "Não incluso",
                    validade_proposta=f"{30 + idx * 5} dias",
                ),
            )
        )

    return Cotacao(
        id_cotacao="COT-ESCALA-001",
        titulo="Teste de Escala — Material de Escritório",
        itens=itens,
        fornecedores=fornecedores,
    )
