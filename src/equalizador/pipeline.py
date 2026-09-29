from pathlib import Path
import math

import pandas as pd

from .analysis import (
    gerar_alertas,
    gerar_analise_executiva,
    gerar_indicadores,
    gerar_insights,
    criar_mapa_comparativo,
    gerar_resumo_fornecedores,
)
from .commercial import criar_indicadores_comerciais
from .config import EngineConfig
from .equalization import executar_equalizacao
from .excel import gerar_relatorio_excel
from .normalization import DadosNormalizados, normalizar_excel
from .recommendation import (
    calcular_componentes,
    calcular_score,
    criar_ranking,
    definir_elegibilidade_preco,
    gerar_recomendacoes,
    preparar_base,
)


def _respeitar_decisao_humana(
    recomendacoes,
    base,
    analise_fonte: dict | None,
):
    referencia = (analise_fonte or {}).get("matriz_referencia", {})
    fornecedor_final = referencia.get("fornecedor_final")
    tabela = referencia.get("tabela")
    if not fornecedor_final or tabela is None or tabela.empty:
        return recomendacoes

    resultado = recomendacoes.copy()
    for _, referencia_item in tabela.iterrows():
        valor_humano = referencia_item.get("VIVO FINAL")
        if valor_humano is None or not math.isfinite(float(valor_humano)):
            continue

        item_id = str(referencia_item.get("ID"))
        candidato = base[
            base["ID"].astype(str).eq(item_id)
            & base["Fornecedor"].eq(fornecedor_final)
        ]
        # A tabela de referência pode não conter todos os itens; sem uma linha
        # existente não há decisão a preservar.
        recomendada = resultado[resultado["ID"].astype(str).eq(item_id)]
        if candidato.empty or recomendada.empty:
            continue

        proposta_final = float(candidato.iloc[0]["Valor Unitário"])
        if not math.isclose(float(valor_humano), proposta_final, rel_tol=0.01, abs_tol=0.01):
            continue

        quantidade = candidato.iloc[0].get("Quantidade Cotada")
        indice = recomendada.index[0]
        resultado.loc[indice, "Fornecedor Recomendado"] = fornecedor_final
        resultado.loc[indice, "Valor Unitário"] = proposta_final
        if quantidade is not None and math.isfinite(float(quantidade)):
            resultado.loc[indice, "Valor Total"] = proposta_final * float(quantidade)
        resultado.loc[indice, "Classificação"] = candidato.iloc[0]["Classificação Recomendação"]
        resultado.loc[indice, "Motivo"] = "decisão final preservada da planilha"

    return resultado


def executar_pipeline(
    cotacao,
    config: EngineConfig | None = None,
    output_path: str | Path | None = None,
    analise_fonte: dict | None = None,
    descartes: list[dict] | None = None,
):
    config = config or EngineConfig()
    config.validar()

    resultado_motor = executar_equalizacao(cotacao, config)
    resultado_motor["Preço Elegível"] = resultado_motor.apply(
        definir_elegibilidade_preco, axis=1
    )

    mapa = criar_mapa_comparativo(resultado_motor, cotacao)
    comerciais = criar_indicadores_comerciais(cotacao)

    base = preparar_base(resultado_motor, comerciais)
    base = calcular_componentes(base)
    base = calcular_score(base, config)
    base = criar_ranking(base)

    recomendacoes = gerar_recomendacoes(base, config)
    recomendacoes = _respeitar_decisao_humana(
        recomendacoes, base, analise_fonte
    )

    resumo = gerar_resumo_fornecedores(mapa, resultado_motor, comerciais, cotacao)
    indicadores = gerar_indicadores(mapa, resultado_motor, cotacao)
    alertas = gerar_alertas(resultado_motor, mapa, comerciais)
    insights = gerar_insights(mapa, resultado_motor, comerciais, cotacao)
    executivo = gerar_analise_executiva(mapa, resultado_motor, resumo)

    arquivo = None
    if output_path is not None:
        arquivo = gerar_relatorio_excel(
            output_path,
            indicadores=indicadores,
            insights=insights,
            mapa_comparativo=mapa,
            resumo_fornecedores=resumo,
            alertas=alertas,
            indicadores_comerciais=comerciais,
            recomendacoes=recomendacoes,
            base_recomendacao=base,
            analise_executiva=executivo,
            analise_fonte=analise_fonte,
            descartes=descartes,
        )

    return {
        "resultado_motor": resultado_motor,
        "mapa_comparativo": mapa,
        "indicadores_comerciais": comerciais,
        "base_recomendacao": base,
        "recomendacoes": recomendacoes,
        "resumo_fornecedores": resumo,
        "indicadores": indicadores,
        "alertas": alertas,
        "insights": insights,
        "analise_executiva": executivo,
        "arquivo_relatorio": arquivo,
    }


def executar_pipeline_de_excel(
    arquivo: str | Path,
    *,
    id_cotacao: str | None = None,
    titulo: str | None = None,
    aba: str | None = None,
    column_mapping: dict[str, int | str] | None = None,
    config: EngineConfig | None = None,
    output_path: str | Path | None = None,
) -> dict:
    """Normaliza uma planilha de propostas e executa o fluxo completo."""
    path = Path(arquivo)
    dados: DadosNormalizados = normalizar_excel(
        path, aba=aba, column_mapping=column_mapping
    )
    cotacao = dados.para_cotacao(
        id_cotacao=id_cotacao or path.stem,
        titulo=titulo or path.stem,
    )
    resultado = executar_pipeline(
        cotacao,
        config=config,
        output_path=output_path,
        analise_fonte=dados.analise_fonte,
        descartes=dados.descartes,
    )
    resultado["dados_normalizados"] = dados
    return resultado
