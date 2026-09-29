from dataclasses import dataclass
import math

import pandas as pd
from rapidfuzz import fuzz

from .config import EngineConfig
from .diagnostics import DiagnosticoPlanilha
from .models import ItemProposta, ItemSolicitado
from .text import extrair_atributos, normalizar_texto


@dataclass(frozen=True)
class AttributeComparison:
    score: float
    avaliados: int
    compativeis: int
    divergencias: int
    detalhes: dict[str, str]


def validar_cotacao(cotacao) -> None:
    """Valida identificadores antes de equalizar para evitar perda silenciosa de dados."""
    if not cotacao.itens:
        raise DiagnosticoPlanilha(
            mensagem="Nenhum item solicitado foi encontrado na planilha.",
            codigo="sem_itens",
            titulo="Nenhum item encontrado",
            dicas=["Cada linha deve representar um item cotado por um fornecedor."],
        )
    if not cotacao.fornecedores:
        raise DiagnosticoPlanilha(
            mensagem="Nenhum fornecedor foi identificado na planilha.",
            codigo="sem_fornecedores",
            titulo="Nenhum fornecedor identificado",
            faltando=["SUPPLIER"],
            dicas=["Inclua uma coluna com o nome do fornecedor ou a empresa que enviou a proposta."],
        )

    ids_solicitados = [
        str(item.id_item).strip() if item.id_item is not None else ""
        for item in cotacao.itens
    ]
    if any(not item_id for item_id in ids_solicitados):
        raise DiagnosticoPlanilha(
            mensagem="Existem itens sem identificador.",
            codigo="itens_sem_id",
            titulo="Itens sem identificador",
            dicas=[
                "Inclua uma coluna de ID do item, ou deixe o motor agrupar por descrição e unidade.",
            ],
        )
    if len(ids_solicitados) != len(set(ids_solicitados)):
        duplicados = sorted({
            item_id for item_id in ids_solicitados
            if ids_solicitados.count(item_id) > 1
        })
        raise DiagnosticoPlanilha(
            mensagem=(
                "Existem IDs duplicados entre os itens do catálogo: "
                f"{', '.join(duplicados[:10])}."
            ),
            codigo="ids_duplicados",
            titulo="Identificadores duplicados",
            dicas=[
                "Cada item do catálogo deve ter um ID único.",
                "Se a planilha lista o mesmo item para vários fornecedores, o ID deve se repetir apenas nas linhas de fornecedor.",
            ],
        )

    nomes_fornecedores = [
        str(fornecedor.nome).strip() if fornecedor.nome is not None else ""
        for fornecedor in cotacao.fornecedores
    ]
    if any(not nome for nome in nomes_fornecedores):
        raise DiagnosticoPlanilha(
            mensagem="Existem fornecedores sem nome.",
            codigo="fornecedor_sem_nome",
            titulo="Fornecedor sem nome",
            faltando=["SUPPLIER"],
            dicas=["Preencha a coluna de fornecedor em todas as linhas."],
        )
    if len(nomes_fornecedores) != len(set(nomes_fornecedores)):
        raise DiagnosticoPlanilha(
            mensagem=(
                "Existem fornecedores com o mesmo nome, o que torna a comparação ambígua: "
                f"{', '.join(sorted(nomes_fornecedores))}."
            ),
            codigo="fornecedores_duplicados",
            titulo="Fornecedores duplicados",
            dicas=["Diferencie cada fornecedor com um nome único na coluna de fornecedor."],
        )

    ids_esperados = set(ids_solicitados)
    for fornecedor in cotacao.fornecedores:
        ids_propostos = [
            str(item.id_item).strip() if item.id_item is not None else ""
            for item in fornecedor.itens
        ]
        if len(ids_propostos) != len(set(ids_propostos)):
            repetidos = sorted({
                item_id for item_id in ids_propostos
                if ids_propostos.count(item_id) > 1
            })
            raise DiagnosticoPlanilha(
                mensagem=(
                    f"O fornecedor '{fornecedor.nome}' aparece mais de uma vez "
                    f"para o mesmo item: {', '.join(repetidos[:10])}."
                ),
                codigo="propostas_duplicadas",
                titulo="Propostas duplicadas",
                dicas=[
                    "Cada fornecedor deve ter uma única linha por item.",
                    "Remova as linhas repetidas antes de enviar a planilha.",
                ],
            )
        desconhecidos = sorted(set(ids_propostos) - ids_esperados)
        if desconhecidos:
            raise DiagnosticoPlanilha(
                mensagem=(
                    f"O fornecedor '{fornecedor.nome}' cotou itens que não existem "
                    f"no catálogo: {', '.join(desconhecidos[:10])}."
                ),
                codigo="ids_inexistentes",
                titulo="Itens fora do catálogo",
                encontrado={fornecedor.nome: ", ".join(desconhecidos[:10])},
                dicas=[
                    "Os itens cotados devem fazer parte da lista de itens do catálogo.",
                    "Confira se a coluna de ID do item está consistente entre as linhas.",
                ],
            )


def comparar_atributos(
    atributos_solicitados: dict,
    atributos_cotados: dict,
) -> AttributeComparison:
    detalhes: dict[str, str] = {}
    avaliados = compativeis = divergencias = 0

    for atributo, solicitado in atributos_solicitados.items():
        cotado = atributos_cotados.get(atributo)

        if solicitado is None and cotado is None:
            detalhes[atributo] = "NÃO INFORMADO"
            continue

        # Informação adicional do fornecedor não é divergência.
        if solicitado is None and cotado is not None:
            detalhes[atributo] = "INFORMADO PELO FORNECEDOR"
            continue

        avaliados += 1

        if cotado is None:
            detalhes[atributo] = "NÃO INFORMADO PELO FORNECEDOR"
            divergencias += 1
            continue

        if normalizar_texto(solicitado) == normalizar_texto(cotado):
            detalhes[atributo] = "OK"
            compativeis += 1
        else:
            detalhes[atributo] = "DIVERGENTE"
            divergencias += 1

    score = (compativeis / avaliados * 100) if avaliados else 100.0

    return AttributeComparison(
        score=score,
        avaliados=avaliados,
        compativeis=compativeis,
        divergencias=divergencias,
        detalhes=detalhes,
    )


def classificar_equalizacao(
    similaridade: float,
    atributos: AttributeComparison,
    quantidade_ok: bool,
    unidade_ok: bool,
    config: EngineConfig,
) -> str:
    if similaridade == 0:
        return "NÃO COTADO"
    if not quantidade_ok or not unidade_ok:
        return "DIVERGÊNCIA ESTRUTURAL"
    if atributos.divergencias > 0:
        return "DIVERGÊNCIA"
    if similaridade >= 100:
        return "EQUIVALENTE"
    if similaridade >= config.limite_similaridade:
        return "EQUIVALENTE COM REVISÃO"
    if similaridade >= config.limite_similaridade_alerta:
        return "REVISAR"
    return "DIVERGENTE"


def analisar_item(
    item_solicitado: ItemSolicitado,
    item_proposta: ItemProposta | None,
    config: EngineConfig,
    preprocess_cache: dict[str, tuple[str, dict]] | None = None,
) -> dict:
    if item_proposta is None:
        return {
            "similaridade": 0.0,
            "atributos": AttributeComparison(0, 0, 0, 0, {}),
            "quantidade_ok": None,
            "unidade_ok": None,
            "status": "NÃO COTADO",
        }

    cache = preprocess_cache if preprocess_cache is not None else {}

    solicitada_key = str(item_solicitado.descricao)
    solicitada_normalizada, atributos_solicitados = cache.setdefault(
        solicitada_key,
        (
            normalizar_texto(item_solicitado.descricao),
            extrair_atributos(item_solicitado.descricao),
        ),
    )
    cotada_key = str(item_proposta.descricao)
    cotada_normalizada, atributos_cotados = cache.setdefault(
        cotada_key,
        (
            normalizar_texto(item_proposta.descricao),
            extrair_atributos(item_proposta.descricao),
        ),
    )

    if not solicitada_normalizada or not cotada_normalizada:
        similaridade = 0.0
    else:
        similaridade = float(
            fuzz.token_set_ratio(solicitada_normalizada, cotada_normalizada)
        )

    atributos = comparar_atributos(
        atributos_solicitados,
        atributos_cotados,
    )

    quantidade_ok = math.isclose(
        item_solicitado.quantidade,
        item_proposta.quantidade,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    unidade_ok = (
        normalizar_texto(item_solicitado.unidade)
        == normalizar_texto(item_proposta.unidade)
    )

    status = classificar_equalizacao(
        similaridade, atributos, quantidade_ok, unidade_ok, config
    )

    if (
        status == "EQUIVALENTE"
        and similaridade < 100
        and atributos.divergencias == 0
    ):
        status = "EQUIVALENTE COM REVISÃO"

    return {
        "similaridade": similaridade,
        "atributos": atributos,
        "quantidade_ok": quantidade_ok,
        "unidade_ok": unidade_ok,
        "status": status,
    }


def executar_equalizacao(cotacao, config: EngineConfig):
    config.validar()
    validar_cotacao(cotacao)
    registros = []
    preprocess_cache: dict[str, tuple[str, dict]] = {}

    for fornecedor in cotacao.fornecedores:
        itens = {str(item.id_item).strip(): item for item in fornecedor.itens}

        for solicitado in cotacao.itens:
            proposta = itens.get(str(solicitado.id_item).strip())
            analise = analisar_item(
                solicitado, proposta, config, preprocess_cache=preprocess_cache
            )

            if proposta is None:
                qtd_cotada = unidade_cotada = valor = None
                valid_qtd = valid_unidade = "NÃO COTADO"
            else:
                qtd_cotada = proposta.quantidade
                unidade_cotada = proposta.unidade
                valor = proposta.valor_unitario
                valid_qtd = "OK" if analise["quantidade_ok"] else "DIVERGENTE"
                valid_unidade = "OK" if analise["unidade_ok"] else "DIVERGENTE"

            registros.append({
                "ID": solicitado.id_item,
                "Fornecedor": fornecedor.nome,
                "Descrição Solicitada": solicitado.descricao,
                "Descrição Cotada": proposta.descricao if proposta else None,
                "Quantidade Solicitada": solicitado.quantidade,
                "Quantidade Cotada": qtd_cotada,
                "Unidade Solicitada": solicitado.unidade,
                "Unidade Cotada": unidade_cotada,
                "Valor Unitário": valor,
                "Similaridade (%)": analise["similaridade"],
                "Score Atributos (%)": analise["atributos"].score,
                "Divergências Atributos": analise["atributos"].divergencias,
                "Validação Quantidade": valid_qtd,
                "Validação Unidade": valid_unidade,
                "Status Equalização": analise["status"],
            })

    return pd.DataFrame(registros)
