import pytest
import numpy as np
import pandas as pd
import json
from openpyxl import load_workbook

from equalizador.analysis import gerar_indicadores, gerar_insights
from equalizador.commercial import criar_indicadores_comerciais, extrair_dias
from equalizador.config import EngineConfig
from equalizador.demo import criar_cotacao_demo
from equalizador.equalization import executar_equalizacao
from equalizador.models import (
    CondicoesComerciais,
    Cotacao,
    Fornecedor,
    ItemProposta,
    ItemSolicitado,
)
from equalizador.normalization import converter_numero, normalizar_excel
from equalizador.pipeline import executar_pipeline, executar_pipeline_de_excel
from equalizador.semantic_engine import SemanticEngine
from equalizador.source_analysis import analisar_fonte
from equalizador.web_service import _jsonable


def test_pesos_oficiais():
    config = EngineConfig()
    assert sum(config.pesos_score.values()) == 1.0


def test_interpreta_formatos_comerciais_comuns():
    assert extrair_dias("30") == 30.0
    assert extrair_dias("Entrega imediata") == 0.0
    assert extrair_dias("à vista") == 0.0
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        fornecedores=[
            Fornecedor(
                "Fornecedor A",
                condicoes=CondicoesComerciais(
                    pedido_minimo="Não há pedido mínimo",
                    frete="CIF",
                ),
            ),
            Fornecedor(
                "Fornecedor B",
                condicoes=CondicoesComerciais(
                    pedido_minimo="0",
                    frete="Frete por conta do fornecedor",
                ),
            ),
        ],
    )

    indicadores = criar_indicadores_comerciais(cotacao)

    assert indicadores["Sem Pedido Mínimo"].tolist() == [True, True]
    assert indicadores["Frete Incluso"].tolist() == [True, True]


def test_pipeline_demo():
    resultado = executar_pipeline(criar_cotacao_demo())

    base = resultado["base_recomendacao"]

    assert len(base) == 150 * 5
    assert base["Score Preço"].between(0, 100).all()
    assert base["Score Similaridade"].between(0, 100).all()
    assert base["Score Atributos"].between(0, 100).all()
    assert base["Score Comercial"].between(0, 100).all()
    assert base["Score Recomendação"].between(0, 100).all()


def test_prazo_imediato_nao_produz_infinito():
    resultado = executar_pipeline(criar_cotacao_demo(quantidade_itens=1, quantidade_fornecedores=2))
    score = resultado["base_recomendacao"]["Score Comercial"]

    assert np.isfinite(score).all()
    assert score.between(0, 100).all()


def test_atributo_solicitado_ausente_e_divergencia():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Papel A4 75g", 1, "UN")],
        fornecedores=[Fornecedor(
            "Fornecedor A",
            itens=[ItemProposta("1", "Papel A4", 1, "UN", 10.0)],
        )],
    )

    resultado = executar_pipeline(cotacao)
    linha = resultado["base_recomendacao"].iloc[0]

    assert linha["Status Equalização"] == "DIVERGÊNCIA"
    assert not linha["Elegível para Recomendação"]


def test_quantidade_com_pequena_diferenca_numerica_e_aceita():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Item A", 0.3, "UN")],
        fornecedores=[Fornecedor(
            "Fornecedor A",
            itens=[ItemProposta("1", "Item A", 0.1 + 0.2, "UN", 10.0)],
        )],
    )

    resultado = executar_equalizacao(cotacao, EngineConfig())

    assert resultado.loc[0, "Validação Quantidade"] == "OK"


def test_formula_do_score():
    resultado = executar_pipeline(criar_cotacao_demo())
    base = resultado["base_recomendacao"]

    esperado = (
        base["Score Preço"] * 0.30
        + base["Score Similaridade"] * 0.20
        + base["Score Atributos"] * 0.20
        + base["Score Comercial"] * 0.30
    )

    erro = (
        esperado - base["Score Recomendação"]
    ).abs()

    assert erro.max() < 1e-9


def test_um_vencedor_por_item():
    resultado = executar_pipeline(criar_cotacao_demo())
    rec = resultado["recomendacoes"]

    assert len(rec) == 150
    assert rec["ID"].nunique() == 150


def test_empate_tecnico_e_sinalizado_com_desempate_deterministico():
    cotacao = criar_cotacao_demo(quantidade_itens=1, quantidade_fornecedores=2)
    resultado = executar_pipeline(cotacao, EngineConfig(limite_empate_tecnico=100))
    recomendacao = resultado["recomendacoes"].iloc[0]

    assert recomendacao["Empate Técnico"]
    assert recomendacao["Fornecedores Empatados"]
    assert recomendacao["Fornecedor Recomendado"] == "Fornecedor A"


def test_nao_cotado_nao_elegivel():
    resultado = executar_pipeline(criar_cotacao_demo())
    base = resultado["base_recomendacao"]

    nao_cotados = base[base["Status Equalização"] == "NÃO COTADO"]

    assert not nao_cotados["Elegível para Recomendação"].any()
    assert (nao_cotados["Score Recomendação"] == 0).all()


def test_classificador_nao_confunde_colunas_de_resultado_com_campos_de_proposta():
    engine = SemanticEngine()

    for header in [
        "Similaridade (%)",
        "Score Similaridade",
        "Score Atributos",
        "Score Preço",
        "Elegível para Recomendação",
        "Classificação Recomendação",
        "Divergências Atributos",
    ]:
        assert engine.classify(header).concept is None


def test_classificador_preserva_campos_reais_de_proposta():
    engine = SemanticEngine()

    assert engine.classify("ID do item").concept == "ID"
    assert engine.classify("Descrição do item").concept == "DESCRIPTION"
    assert engine.classify("Preço unitário").concept == "UNIT_PRICE"


def test_classificador_respeita_limites_configurados():
    engine = SemanticEngine(high_threshold=99, medium_threshold=90, low_threshold=80)

    assert engine._confidence(95) == "MEDIUM"
    assert engine._confidence(85) == "LOW"


def test_classificador_separa_metadados_de_fornecedor_e_cotacao():
    engine = SemanticEngine()

    assert engine.classify("ID_Fornecedor").concept == "SUPPLIER_ID"
    assert engine.classify("Codigo_Cotacao").concept == "QUOTE_ID"
    assert engine.classify("Moeda").concept == "CURRENCY"
    assert engine.classify("Data_Cotacao").concept == "QUOTE_DATE"
    assert engine.classify("Quote Code").concept == "QUOTE_ID"
    assert engine.classify("Nome_Produto").concept == "DESCRIPTION"
    assert engine.classify("Condicoes_Entrega").concept == "DELIVERY_DAYS"


def test_equalizacao_rejeita_ids_duplicados_em_vez_de_descartar_item():
    cotacao = Cotacao(
        id_cotacao="COT-1",
        titulo="Teste",
        itens=[
            ItemSolicitado("1", "Item A", 1, "UN"),
            ItemSolicitado("1", "Item B", 1, "UN"),
        ],
        fornecedores=[Fornecedor("Fornecedor A")],
    )

    with pytest.raises(ValueError, match="IDs duplicados"):
        executar_equalizacao(cotacao, EngineConfig())


def test_equalizacao_aceita_ids_com_espacos_sem_perder_a_proposta():
    cotacao = Cotacao(
        id_cotacao="COT-1",
        titulo="Teste",
        itens=[ItemSolicitado("1", "Item A", 1, "UN")],
        fornecedores=[Fornecedor(
            "Fornecedor A",
            itens=[ItemProposta(" 1 ", "Item A", 1, "UN", 10.0)],
        )],
    )

    resultado = executar_equalizacao(cotacao, EngineConfig())

    assert resultado.loc[0, "Status Equalização"] == "EQUIVALENTE"


def test_indicadores_nao_contam_fornecedor_por_correspondencia_parcial():
    cotacao = criar_cotacao_demo(quantidade_itens=1, quantidade_fornecedores=2)
    cotacao.fornecedores[0].nome = "ACME"
    cotacao.fornecedores[1].nome = "ACME Brasil"
    resultado = executar_pipeline(cotacao)

    indicadores = gerar_indicadores(
        resultado["mapa_comparativo"], resultado["resultado_motor"], cotacao
    )

    assert indicadores["Quantidade de Menores Preços"] == 1


def test_insights_funcionam_quando_nao_ha_diferencas_de_preco():
    cotacao = criar_cotacao_demo(quantidade_itens=1, quantidade_fornecedores=1)
    resultado = executar_pipeline(cotacao)
    mapa = resultado["mapa_comparativo"].copy()
    mapa["Diferença %"] = np.nan

    insights = gerar_insights(
        mapa,
        resultado["resultado_motor"],
        resultado["indicadores_comerciais"],
        cotacao,
    )

    assert insights


def test_alerta_de_nao_cotacao_informa_item_fornecedor_e_quantidade():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Papel A4", 12, "CAIXA")],
        fornecedores=[Fornecedor("Fornecedor A")],
    )

    resultado = executar_pipeline(cotacao)
    alerta = resultado["alertas"].iloc[0]

    assert alerta["Tipo"] == "Não cotado"
    assert alerta["Fornecedor"] == "Fornecedor A"
    assert alerta["Descrição"] == "Papel A4"
    assert alerta["Quantidade"] == 12
    assert "12 CAIXA" in alerta["Mensagem"]


def test_analise_da_fonte_consolida_cotacoes_do_mesmo_produto():
    dados = pd.DataFrame([
        {
            "DESCRIPTION": "Cabo Cat6", "SUPPLIER": "Fornecedor A",
            "QUANTITY": 10, "UNIT": "UN", "UNIT_PRICE": 100,
            "CATEGORY": "TI", "CURRENCY": "BRL", "STATUS": "Aprovada",
        },
        {
            "DESCRIPTION": "Cabo Cat6", "SUPPLIER": "Fornecedor B",
            "QUANTITY": 12, "UNIT": "UN", "UNIT_PRICE": 120,
            "CATEGORY": "TI", "CURRENCY": "BRL", "STATUS": "Pendente",
        },
    ])

    analise = analisar_fonte(dados, [])
    produto = analise["produtos"].iloc[0]

    assert analise["perfil"]["qualidade"]["Linhas válidas"] == 2
    assert analise["perfil"]["qualidade"]["Produtos distintos"] == 1
    assert produto["Cotações"] == 2
    assert produto["Fornecedores"] == 2
    assert produto["Menor Preço"] == 100
    assert produto["Maior Preço"] == 120


@pytest.mark.parametrize(
    ("value", "expected"),
    [("R$ 1.234,56", 1234.56), ("1,234.56", 1234.56), (25, 25.0)],
)
def test_converte_numeros_de_planilhas(value, expected):
    assert converter_numero(value) == expected


def test_serializa_valores_temporais_e_nulos_para_json():
    payload = {
        "data": pd.Timestamp("2026-01-02T03:04:05"),
        "vazio": pd.NaT,
        "invalido": np.nan,
    }

    serialized = _jsonable(payload)

    assert serialized == {
        "data": "2026-01-02T03:04:05",
        "vazio": None,
        "invalido": None,
    }
    json.dumps(serialized)


def test_normaliza_excel_e_entrega_cotacao_para_pipeline(tmp_path):
    arquivo = tmp_path / "propostas.xlsx"
    pd.DataFrame([
        {
            "ID": "001", "Descrição": "Caneta azul ponta fina", "Quantidade": 10,
            "Unidade": "Caixa", "Fornecedor": "Fornecedor A",
            "Preço Unitário": "R$ 10,50", "Dias Pagamento": "30 dias",
            "Prazo Entrega": "5 dias", "Frete": "Incluso",
        },
        {
            "ID": "001", "Descrição": "Caneta azul ponta fina", "Quantidade": 10,
            "Unidade": "Caixa", "Fornecedor": "Fornecedor B",
            "Preço Unitário": "11,75", "Dias Pagamento": "45 dias",
            "Prazo Entrega": "8 dias", "Frete": "Não incluso",
        },
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)
    cotacao = dados.para_cotacao("COT-REAL-001", "Cotação importada")
    resultado = executar_pipeline(cotacao)
    resultado_excel = executar_pipeline_de_excel(
        arquivo, id_cotacao="COT-REAL-001", titulo="Cotação importada"
    )

    assert len(dados.itens) == 1
    assert len(dados.propostas) == 2
    assert dados.propostas.loc[0, "UNIT_PRICE"] == 10.5
    assert len(cotacao.fornecedores) == 2
    assert len(resultado["recomendacoes"]) == 1
    assert len(resultado_excel["dados_normalizados"].propostas) == 2

def test_normaliza_matriz_com_fornecedores_em_pares_de_colunas(tmp_path):
    arquivo = tmp_path / "matriz.xlsx"
    linhas = [
        [None, None, "Cotação", None, None, None, None, None, None, None],
        [None, None, None, None, None, "PROPOSTAS INICIAIS", None, None, None, None],
        [None, None, None, None, None, "Fornecedor A", None, "Fornecedor B", None, "TARGET"],
        ["ID", "Local", "Velocidade", "Unidade", "Qtde. (meses)", "Unitário", "Total", "", "Total", "Unitário"],
        ["1", "Escritório", "100 Mbps", "UN", 12, 100, 1200, 90, 1080, 80],
    ]
    pd.DataFrame(linhas).to_excel(arquivo, header=False, index=False)

    dados = normalizar_excel(arquivo)

    assert set(dados.propostas["SUPPLIER"]) == {"Fornecedor A", "Fornecedor B"}
    assert len(dados.itens) == 1
    assert dados.analise_fonte["matriz_referencia"]["tabela"].loc[0, "TARGET"] == 80


def test_matriz_respeita_analise_tecnica_e_importa_proposta_final(tmp_path):
    arquivo = tmp_path / "matriz_equalizada.xlsx"
    linhas = [
        [None] * 11,
        [None, None, None, None, None, "Fornecedor NOK", None, "Fornecedor OK", None, "Fornecedor Final", None],
        ["ID", "Local", "Velocidade", "Unidade", "Qtde. (meses)", "Unitário", "Total", "Unitário", "Total", "Unitário", "Total"],
        ["1", "Escritório", "100 Mbps", "UN", 12, 100, 1200, 80, 960, 70, 840],
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None] * 11,
        [None, None, None, None, None, "NOK", None, "OK", None, "OK", None],
    ]
    pd.DataFrame(linhas).to_excel(arquivo, header=False, index=False)

    dados = normalizar_excel(arquivo)

    assert set(dados.propostas["SUPPLIER"]) == {
        "Fornecedor NOK", "Fornecedor OK", "Fornecedor Final"
    }


def test_matriz_identifica_final_de_qualquer_fornecedor_repetido(tmp_path):
    arquivo = tmp_path / "matriz_fornecedor_final.xlsx"
    linhas = [
        [None] * 11,
        [None, None, None, None, None, "Fornecedor A", None, "Fornecedor B", None, "Fornecedor A", None],
        ["ID", "Local", "Velocidade", "Unidade", "Qtde. (meses)", "Unitário", "Total", "Unitário", "Total", "Unitário", "Total"],
        ["1", "Escritório", "100 Mbps", "UN", 12, 100, 1200, 90, 1080, 80, 960],
    ]
    pd.DataFrame(linhas).to_excel(arquivo, header=False, index=False)

    dados = normalizar_excel(arquivo)

    assert set(dados.propostas["SUPPLIER"]) == {
        "Fornecedor A", "Fornecedor B", "Fornecedor A (Final)"
    }
    assert dados.analise_fonte["matriz_referencia"]["fornecedor_final"] == "Fornecedor A (Final)"
    assert dados.analise_fonte["matriz_referencia"]["tabela"].loc[0, "VIVO FINAL"] == 80


def test_normaliza_excel_avisa_total_inconsistente_sem_alterar_preco(tmp_path):
    arquivo = tmp_path / "totais.xlsx"
    pd.DataFrame([
        {
            "ID": "1", "Descrição": "Item A", "Quantidade": 10,
            "Unidade": "UN", "Fornecedor": "Fornecedor A",
            "Preço Unitário": "10,00", "Preço Total": "50,00",
        },
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)

    assert dados.propostas.loc[0, "UNIT_PRICE"] == 10.0
    assert dados.propostas.loc[0, "TOTAL_PRICE"] == 50.0
    assert any("total(is) informado(s) divergem" in aviso for aviso in dados.avisos)


def test_normaliza_exportacao_com_codigo_cotacao_e_descarta_linhas_incompletas(tmp_path):
    arquivo = tmp_path / "exportacao.xlsx"
    pd.DataFrame([
        {
            "ID_Fornecedor": "FOR-1", "Fornecedor": "Fornecedor A",
            "Codigo_Cotacao": "COT-1", "Nome_Produto": "Produto A",
            "Quantidade": 5, "Unidade": "UN", "Preco_Unitario": "R$ 12,50",
            "Moeda": "BRL", "Condicoes_Entrega": "Entrega em 10 dias",
        },
        {
            "ID_Fornecedor": "FOR-2", "Fornecedor": "Fornecedor B",
            "Codigo_Cotacao": "COT-1", "Nome_Produto": "Produto B",
            "Quantidade": 3, "Unidade": "UN", "Preco_Unitario": 20,
            "Moeda": "BRL", "Condicoes_Entrega": "Sob consulta",
        },
        {
            "ID_Fornecedor": "FOR-3", "Fornecedor": "Fornecedor C",
            "Codigo_Cotacao": "COT-3", "Nome_Produto": "Produto C",
            "Quantidade": 1, "Unidade": "UN", "Preco_Unitario": None,
            "Moeda": "BRL", "Condicoes_Entrega": "Entrega imediata",
        },
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)

    assert len(dados.propostas) == 2
    assert dados.propostas["ID"].nunique() == 2
    assert dados.propostas["ID"].str.startswith("COT-1-L").all()
    assert any("foram ignorados" in aviso for aviso in dados.avisos)
    assert any("Códigos de cotação repetidos" in aviso for aviso in dados.avisos)


def test_normaliza_exportacao_com_codigo_quase_unico_agrupa_por_produto(tmp_path):
    arquivo = tmp_path / "cotacoes_por_produto.xlsx"
    pd.DataFrame([
        {
            "ID_Fornecedor": "A", "Fornecedor": "Fornecedor A",
            "Codigo_Cotacao": "COT-1", "Nome_Produto": "Produto A",
            "Quantidade": 1, "Unidade": "UN", "Preco_Unitario": 12,
        },
        {
            "ID_Fornecedor": "B", "Fornecedor": "fornecedor a",
            "Codigo_Cotacao": "COT-2", "Nome_Produto": "Produto A",
            "Quantidade": 1, "Unidade": "un", "Preco_Unitario": 10,
        },
        {
            "ID_Fornecedor": "C", "Fornecedor": "Fornecedor B",
            "Codigo_Cotacao": "COT-3", "Nome_Produto": "Produto A",
            "Quantidade": 1, "Unidade": "UN", "Preco_Unitario": 11,
        },
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)

    assert len(dados.itens) == 1
    assert len(dados.propostas) == 2
    assert dados.propostas["SUPPLIER"].tolist() == ["Fornecedor A", "Fornecedor B"]
    assert dados.propostas["UNIT_PRICE"].tolist() == [10.0, 11.0]
    assert any("agrupados por descrição e unidade" in aviso for aviso in dados.avisos)


def test_normaliza_planilha_com_cabecalhos_genericos_pelo_conteudo(tmp_path):
    arquivo = tmp_path / "cabecalhos_genericos.xlsx"
    pd.DataFrame([
        {"Campo A": "SKU-001", "Campo B": "Caneta azul", "Campo C": "UN", "Campo D": 10, "Campo E": "Empresa A", "Campo F": 2.5},
        {"Campo A": "SKU-002", "Campo B": "Papel A4", "Campo C": "PCT", "Campo D": 5, "Campo E": "Empresa A", "Campo F": 18.0},
        {"Campo A": "SKU-003", "Campo B": "Grampeador", "Campo C": "UN", "Campo D": 2, "Campo E": "Empresa B", "Campo F": 25.0},
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)

    assert len(dados.itens) == 3
    assert len(dados.propostas) == 3
    assert dados.propostas["DESCRIPTION"].tolist() == ["Caneta azul", "Papel A4", "Grampeador"]
    assert dados.propostas["UNIT_PRICE"].tolist() == [2.5, 18.0, 25.0]
    assert any("Campos inferidos" in aviso for aviso in dados.avisos)


def test_normaliza_layout_generico_com_ruido_antes_do_cabecalho(tmp_path):
    arquivo = tmp_path / "generico_com_ruido.xlsx"
    pd.DataFrame([
        ["MAPA COMPARATIVO DE TESTE", None, None, None, None, None],
        ["Arquivo fictício", None, None, None, None, None],
        ["Campo A", "Campo B", "Campo C", "Campo D", "Campo E", "Campo F"],
        ["ITEM-1", "Produto A", "UN", 2, "Fornecedor A", 10.0],
    ]).to_excel(arquivo, header=False, index=False)

    dados = normalizar_excel(arquivo)

    assert len(dados.itens) == 1
    assert dados.propostas.loc[0, "DESCRIPTION"] == "Produto A"
    assert dados.propostas.loc[0, "UNIT_PRICE"] == 10.0


def test_relatorio_tem_mapa_compacto_sem_graficos_embutidos(tmp_path):
    arquivo = tmp_path / "relatorio.xlsx"
    executar_pipeline(
        criar_cotacao_demo(quantidade_itens=3, quantidade_fornecedores=3),
        output_path=arquivo,
    )

    workbook = load_workbook(arquivo)
    assert workbook["Mapa Comparativo"].max_column == 9
    assert workbook["Preços por Fornecedor"].max_column == 4
    # As leituras visuais ficam na interface web; o Excel entregue é tabular.
    assert getattr(workbook["Dashboard"], "_charts", []) == []
    assert all(
        not getattr(sheet, "_charts", [])
        for sheet in workbook.worksheets
    )
    assert workbook["Mapa Comparativo"]["F2"].number_format == 'R$ #,##0.00'
# --- Regressões da auditoria -------------------------------------------------


def test_frete_nao_informado_nao_conta_como_frete_negado():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        fornecedores=[
            Fornecedor("Fornecedor A"),
            Fornecedor("Fornecedor B", condicoes=CondicoesComerciais(frete="Não incluso")),
        ],
    )

    indicadores = criar_indicadores_comerciais(cotacao)

    assert indicadores["Frete Informado"].tolist() == [False, True]
    assert indicadores["Frete Incluso"].tolist() == [False, False]


def test_condicao_comercial_ausente_e_neutra_e_nao_zera_o_score():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Item A", 1, "UN")],
        fornecedores=[
            Fornecedor("Fornecedor A", itens=[ItemProposta("1", "Item A", 1, "UN", 10.0)]),
            Fornecedor(
                "Fornecedor B",
                itens=[ItemProposta("1", "Item A", 1, "UN", 10.0)],
                condicoes=CondicoesComerciais(
                    pagamento="0 dias", prazo_entrega="90 dias", frete="Não incluso"
                ),
            ),
            Fornecedor(
                "Fornecedor C",
                itens=[ItemProposta("1", "Item A", 1, "UN", 10.0)],
                condicoes=CondicoesComerciais(
                    pagamento="60 dias", prazo_entrega="5 dias", frete="Incluso"
                ),
            ),
        ],
    )

    resultado = executar_pipeline(cotacao)
    base = resultado["base_recomendacao"].set_index("Fornecedor")

    # Sem informação comercial o fornecedor recebe score neutro (50), não zero.
    assert base.loc["Fornecedor A", "Score Comercial"] == 50.0
    # Quem declara condições piores fica abaixo do neutro; o melhor acima dele.
    assert base.loc["Fornecedor B", "Score Comercial"] < 50.0
    assert base.loc["Fornecedor C", "Score Comercial"] > 50.0


def test_alertas_distinguem_frete_negado_de_frete_nao_informado():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Item A", 1, "UN")],
        fornecedores=[
            Fornecedor("Fornecedor A", itens=[ItemProposta("1", "Item A", 1, "UN", 10.0)]),
            Fornecedor(
                "Fornecedor B",
                itens=[ItemProposta("1", "Item A", 1, "UN", 11.0)],
                condicoes=CondicoesComerciais(frete="FOB"),
            ),
        ],
    )

    resultado = executar_pipeline(cotacao)
    alertas_frete = resultado["alertas"][resultado["alertas"]["Tipo"] == "Frete"]

    por_fornecedor = {
        row["Fornecedor"]: row for _, row in alertas_frete.iterrows()
    }
    assert por_fornecedor["Fornecedor A"]["Prioridade"] == "BAIXA"
    assert "não informou" in por_fornecedor["Fornecedor A"]["Mensagem"]
    assert por_fornecedor["Fornecedor B"]["Prioridade"] == "MÉDIA"
    assert "não apresenta frete incluso" in por_fornecedor["Fornecedor B"]["Mensagem"]


def test_recomendacoes_sem_opcao_elegivel_tem_esquema_estavel():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Item A", 1, "UN")],
        fornecedores=[Fornecedor("Fornecedor A")],
    )

    recomendacoes = executar_pipeline(cotacao)["recomendacoes"]

    assert recomendacoes.loc[0, "Fornecedor Recomendado"] == "NENHUM"
    assert "Empate Técnico" in recomendacoes.columns
    assert "Fornecedores Empatados" in recomendacoes.columns


def test_percentual_menores_precos_usa_itens_cotados_pelo_fornecedor():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[
            ItemSolicitado("1", "Item A", 1, "UN"),
            ItemSolicitado("2", "Item B", 1, "UN"),
            ItemSolicitado("3", "Item C", 1, "UN"),
            ItemSolicitado("4", "Item D", 1, "UN"),
        ],
        fornecedores=[
            Fornecedor(
                "Fornecedor A",
                itens=[
                    ItemProposta("1", "Item A", 1, "UN", 10.0),
                    ItemProposta("2", "Item B", 1, "UN", 20.0),
                ],
            ),
            Fornecedor(
                "Fornecedor B",
                itens=[
                    ItemProposta("3", "Item C", 1, "UN", 30.0),
                    ItemProposta("4", "Item D", 1, "UN", 40.0),
                ],
            ),
        ],
    )

    resultado = executar_pipeline(cotacao)
    resumo = resultado["resumo_fornecedores"].set_index("Fornecedor")

    # Cada fornecedor venceu todos os seus itens cotados: 100%, não 50%.
    assert resumo.loc["Fornecedor A", "Percentual Menores Preços"] == 100.0
    assert resumo.loc["Fornecedor B", "Percentual Menores Preços"] == 100.0


def test_variacao_de_preco_nao_quebra_com_minimo_zero():
    dados = pd.DataFrame([
        {
            "DESCRIPTION": "Item A", "SUPPLIER": "Fornecedor A",
            "QUANTITY": 1, "UNIT": "UN", "UNIT_PRICE": 0,
        },
        {
            "DESCRIPTION": "Item A", "SUPPLIER": "Fornecedor B",
            "QUANTITY": 1, "UNIT": "UN", "UNIT_PRICE": 10,
        },
    ])

    analise = analisar_fonte(dados, [])
    variacao = analise["produtos"].iloc[0]["Variação de Preço %"]

    assert variacao is None


def test_normalizar_texto_preserva_separador_decimal():
    from equalizador.text import normalizar_texto

    assert "1.5" in normalizar_texto("Papel 1.5 cm")
    assert normalizar_texto("1.5 cm") != normalizar_texto("15 cm")


def test_decisao_humana_preenche_valor_total_da_recomendacao():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[ItemSolicitado("1", "Item A", 4, "UN")],
        fornecedores=[
            Fornecedor("Fornecedor A", itens=[ItemProposta("1", "Item A", 4, "UN", 10.0)]),
            Fornecedor("Fornecedor B", itens=[ItemProposta("1", "Item A", 4, "UN", 12.0)]),
        ],
    )
    analise_fonte = {
        "matriz_referencia": {
            "fornecedor_final": "Fornecedor A",
            "tabela": pd.DataFrame([{"ID": "1", "VIVO FINAL": 10.0}]),
        }
    }

    resultado = executar_pipeline(cotacao, analise_fonte=analise_fonte)
    recomendacao = resultado["recomendacoes"].iloc[0]

    assert recomendacao["Fornecedor Recomendado"] == "Fornecedor A"
    assert recomendacao["Valor Unitário"] == 10.0
    assert recomendacao["Valor Total"] == 40.0
    assert recomendacao["Motivo"] == "decisão final preservada da planilha"


def test_decisao_humana_ignora_item_ausente_na_referencia():
    cotacao = Cotacao(
        "COT-1",
        "Teste",
        itens=[
            ItemSolicitado("1", "Item A", 1, "UN"),
            ItemSolicitado("2", "Item B", 1, "UN"),
        ],
        fornecedores=[
            Fornecedor(
                "Fornecedor A",
                itens=[
                    ItemProposta("1", "Item A", 1, "UN", 10.0),
                    ItemProposta("2", "Item B", 1, "UN", 10.0),
                ],
            ),
        ],
    )
    analise_fonte = {
        "matriz_referencia": {
            "fornecedor_final": "Fornecedor A",
            "tabela": pd.DataFrame([{"ID": "1", "VIVO FINAL": 10.0}]),
        }
    }

    resultado = executar_pipeline(cotacao, analise_fonte=analise_fonte)
    recomendacoes = resultado["recomendacoes"].set_index("ID")

    assert recomendacoes.loc["1", "Motivo"] == "decisão final preservada da planilha"
    # O item fora da referência mantém o motivo calculado pelo motor.
    assert recomendacoes.loc["2", "Motivo"] != "decisão final preservada da planilha"# --- Diagnóstico de falhas de leitura ----------------------------------------


def test_planilha_sem_colunas_reconheciveis_explica_o_que_faltou(tmp_path):
    from equalizador.diagnostics import DiagnosticoPlanilha

    arquivo = tmp_path / "sem_colunas.xlsx"
    pd.DataFrame([
        {"A": 1, "B": 2, "C": 3},
        {"A": 4, "B": 5, "C": 6},
    ]).to_excel(arquivo, index=False)

    with pytest.raises(DiagnosticoPlanilha) as info:
        normalizar_excel(arquivo)

    payload = info.value.para_payload()
    assert payload["codigo"]
    assert payload["titulo"]
    assert payload["mensagem"]
    assert payload["dicas"]
    json.dumps(payload)


def test_planilha_com_valores_invalidos_aponta_os_campos(tmp_path):
    from equalizador.diagnostics import DiagnosticoPlanilha

    arquivo = tmp_path / "valores_invalidos.xlsx"
    pd.DataFrame([
        {"Descrição": "Item", "Quantidade": 0, "Unidade": "UN",
         "Fornecedor": "A", "Preço Unitário": 0},
    ]).to_excel(arquivo, index=False)

    with pytest.raises(DiagnosticoPlanilha) as info:
        normalizar_excel(arquivo)

    payload = info.value.para_payload()
    assert payload["codigo"] == "sem_propostas_validas"
    assert "preço unitário" in payload["faltando"]


def test_aba_inexistente_lista_as_abas_disponiveis(tmp_path):
    from equalizador.diagnostics import DiagnosticoPlanilha

    arquivo = tmp_path / "aba.xlsx"
    pd.DataFrame([
        {"ID": "1", "Descrição": "Item", "Quantidade": 1, "Unidade": "UN",
         "Fornecedor": "A", "Preço Unitário": 10},
    ]).to_excel(arquivo, index=False)

    with pytest.raises(DiagnosticoPlanilha) as info:
        normalizar_excel(arquivo, aba="NaoExiste")

    payload = info.value.para_payload()
    assert payload["codigo"] == "aba_inexistente"
    assert payload["abas_analisadas"]
    assert "NaoExiste" in payload["mensagem"]


def test_formato_nao_suportado_e_diagnosticado(tmp_path):
    from equalizador.diagnostics import DiagnosticoPlanilha

    arquivo = tmp_path / "dados.csv"
    arquivo.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(DiagnosticoPlanilha) as info:
        normalizar_excel(arquivo)

    assert info.value.codigo == "formato_nao_suportado"


def test_diagnostico_e_um_value_error_para_compatibilidade(tmp_path):
    from equalizador.diagnostics import DiagnosticoPlanilha

    arquivo = tmp_path / "dados.xls"
    arquivo.write_bytes(b"not a spreadsheet")

    with pytest.raises(ValueError):
        normalizar_excel(arquivo)


def test_api_devolve_diagnostico_estruturado_em_erro(tmp_path):
    import asyncio

    from fastapi import HTTPException, UploadFile

    from equalizador.web_service import process

    planilha = tmp_path / "ruim.xlsx"
    pd.DataFrame([{"A": 1, "B": 2, "C": 3}]).to_excel(planilha, index=False)

    upload = UploadFile(
        file=planilha.open("rb"),
        filename="ruim.xlsx",
    )

    with pytest.raises(HTTPException) as info:
        asyncio.run(process(file=upload, sheet=None))

    assert info.value.status_code == 422
    detail = info.value.detail
    assert isinstance(detail, dict)
    assert detail["codigo"]
    assert detail["titulo"]
    assert detail["mensagem"]
    assert isinstance(detail["dicas"], list)


def test_descartes_detalham_motivo_por_linha(tmp_path):
    """Cada linha ignorada deve aparecer no catálogo com o motivo específico."""
    arquivo = tmp_path / "com_falhas.xlsx"
    pd.DataFrame([
        {"ID": "A1", "Descrição": "Parafuso", "Quantidade": 100, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.5},
        {"ID": "A2", "Descrição": "Porca", "Quantidade": None, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 2.0},
        {"ID": "A3", "Descrição": "Arruela", "Quantidade": 0, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 0.5},
        {"ID": "A4", "Descrição": "Prego", "Quantidade": 300, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": -1},
        {"ID": "A5", "Descrição": "Bucha", "Quantidade": 80, "Unidade": "UN",
         "Fornecedor": None, "Preço Unitário": 3.0},
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)

    motivos = {d["Linha (Excel)"]: d["Motivo"] for d in dados.descartes}
    # Linhas 2..5 do Excel (o cabeçalho ocupa a linha 1).
    assert "quantidade ausente" in motivos[3]
    assert "quantidade inválida" in motivos[4]
    assert "preço unitário inválido" in motivos[5]
    assert "fornecedor ausente" in motivos[6]


def test_contagem_de_linhas_fecha_a_conta(tmp_path):
    arquivo = tmp_path / "contagem.xlsx"
    pd.DataFrame([
        {"ID": "A1", "Descrição": "Ok", "Quantidade": 10, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.0},
        {"ID": "A2", "Descrição": "Ruim", "Quantidade": None, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.0},
    ]).to_excel(arquivo, index=False)

    dados = normalizar_excel(arquivo)
    contagem = dados.contagem_linhas

    assert contagem["Linhas físicas analisadas"] == 2
    assert contagem["Linhas aproveitadas"] == 1
    assert contagem["Linhas descartadas"] == 1
    assert (
        contagem["Linhas aproveitadas"] + contagem["Linhas descartadas"]
        == contagem["Linhas físicas analisadas"]
    )


def test_relatorio_inclui_aba_de_linhas_descartadas(tmp_path):
    arquivo = tmp_path / "origem.xlsx"
    pd.DataFrame([
        {"ID": "A1", "Descrição": "Ok", "Quantidade": 10, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.0},
        {"ID": "A2", "Descrição": "Ruim", "Quantidade": None, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.0},
    ]).to_excel(arquivo, index=False)

    relatorio = tmp_path / "relatorio.xlsx"
    executar_pipeline_de_excel(arquivo, output_path=relatorio)

    wb = load_workbook(relatorio)
    assert "Linhas Descartadas" in wb.sheetnames
    ws = wb["Linhas Descartadas"]
    cabecalhos = [c.value for c in ws[1]]
    assert cabecalhos == ["Linha (Excel)", "Motivo", "Descrição encontrada", "Fornecedor encontrado"]
    assert ws.max_row >= 2, "a aba deve listar pelo menos uma linha descartada"


def test_api_expoe_descartes_e_contagem_de_linhas(tmp_path):
    import asyncio

    from fastapi import UploadFile

    from equalizador.web_service import process

    planilha = tmp_path / "origem.xlsx"
    pd.DataFrame([
        {"ID": "A1", "Descrição": "Ok", "Quantidade": 10, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.0},
        {"ID": "A2", "Descrição": "Ruim", "Quantidade": None, "Unidade": "UN",
         "Fornecedor": "Fornecedor A", "Preço Unitário": 1.0},
    ]).to_excel(planilha, index=False)

    upload = UploadFile(file=planilha.open("rb"), filename="origem.xlsx")
    resposta = asyncio.run(process(file=upload, sheet=None))
    payload = json.loads(resposta.body)

    assert isinstance(payload["descartes"], list)
    assert payload["descartes"][0]["Motivo"]
    assert payload["contagem_linhas"]["Linhas descartadas"] == 1