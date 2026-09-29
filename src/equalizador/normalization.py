"""Normalização de planilhas de propostas para os modelos do domínio.

O módulo recebe uma planilha no formato tabular (uma linha por item e
fornecedor), aproveita o detector estrutural e devolve tabelas limpas e uma
``Cotacao`` pronta para o motor de equalização.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
from typing import Any, Mapping, cast

import pandas as pd

from .diagnostics import (
    CONCEITOS_OBRIGATORIOS,
    CONCEITOS_OBRIGATORIOS_ITEM,
    DICAS_PADRAO,
    DiagnosticoPlanilha,
    rotular_conceito,
)
from .models import CondicoesComerciais, Cotacao, Fornecedor, ItemProposta, ItemSolicitado
from .source_analysis import analisar_fonte
from .structure_detector import SheetDetection, StructureDetector


# Fonte única em ``diagnostics``: evita que a definição de "obrigatório" divirja.
REQUIRED_CONCEPTS = set(CONCEITOS_OBRIGATORIOS_ITEM)
# Algumas bases transacionais não possuem um identificador de item, mas têm
# uma referência de cotação. Nesse caso ela é uma alternativa segura a ID;
# os demais campos continuam obrigatórios.
SOURCE_REQUIRED_CONCEPTS = set(CONCEITOS_OBRIGATORIOS)
COMMERCIAL_CONCEPTS = {
    "PAYMENT_DAYS": "pagamento",
    "DELIVERY_DAYS": "prazo_entrega",
    "MIN_ORDER": "pedido_minimo",
    "FREIGHT": "frete",
    "PROPOSAL_VALIDITY": "validade_proposta",
    "OBSERVATION": "observacao",
}
SOURCE_ANALYSIS_CONCEPTS = {"CATEGORY", "CURRENCY", "STATUS", "QUOTE_DATE"}


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str | None:
    if _is_empty(value):
        return None
    text = str(value).strip()
    return text or None


def _is_positive_number(value: Any) -> bool:
    """Verdadeiro apenas para números finitos maiores que zero."""
    if isinstance(value, bool) or _is_empty(value):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def converter_numero(value: Any) -> float | None:
    """Converte números nativos e textos nos formatos ``1.234,56``/``1,234.56``."""
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip()
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None

    comma, dot = text.rfind(","), text.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal = "," if comma > dot else "."
        thousand = "." if decimal == "," else ","
        text = text.replace(thousand, "").replace(decimal, ".")
    elif comma >= 0:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


@dataclass
class DadosNormalizados:
    itens: pd.DataFrame
    propostas: pd.DataFrame
    condicoes_comerciais: pd.DataFrame
    arquivo_origem: str
    aba_origem: str
    avisos: list[str] = field(default_factory=list)
    analise_fonte: dict = field(default_factory=dict)
    descartes: list[dict] = field(default_factory=list)
    contagem_linhas: dict = field(default_factory=dict)

    def para_cotacao(self, id_cotacao: str, titulo: str) -> Cotacao:
        # ``DataFrame.itertuples`` cria uma tupla dinâmica. Além de não ser
        # bem compreendida pelo verificador de tipos, atributos como ``ID``
        # podem deixar de ser válidos se um cabeçalho mudar. Registros nomeados
        # tornam o contrato desta fronteira explícito.
        item_records = cast(
            list[dict[str, Any]], self.itens.to_dict(orient="records")
        )
        itens = [
            ItemSolicitado(
                id_item=str(row["ID"]),
                descricao=str(row["DESCRIPTION"]),
                quantidade=float(row["QUANTITY"]),
                unidade=str(row["UNIT"]),
            )
            for row in item_records
        ]

        fornecedores = []
        for fornecedor, grupo in self.propostas.groupby("SUPPLIER", sort=True):
            condicoes_fornecedor = self.condicoes_comerciais[
                self.condicoes_comerciais["SUPPLIER"].eq(fornecedor)
            ]
            # ``_canonicalize_suppliers`` deve garantir uma linha por fornecedor,
            # mas uma fonte sem condições comerciais não pode derrubar a leitura.
            condicao = (
                condicoes_fornecedor.iloc[0]
                if not condicoes_fornecedor.empty
                else None
            )
            proposal_records = cast(
                list[dict[str, Any]], grupo.to_dict(orient="records")
            )
            fornecedores.append(Fornecedor(
                nome=str(fornecedor),
                itens=[
                    ItemProposta(
                        id_item=str(row["ID"]),
                        descricao=str(row["DESCRIPTION"]),
                        quantidade=float(row["QUANTITY"]),
                        unidade=str(row["UNIT"]),
                        valor_unitario=float(row["UNIT_PRICE"]),
                        valor_total=(
                            None if _is_empty(row["TOTAL_PRICE"])
                            else float(row["TOTAL_PRICE"])
                        ),
                        observacao=_text(row["OBSERVATION"]),
                    )
                    for row in proposal_records
                ],
                condicoes=CondicoesComerciais(
                    pagamento=condicao.PAYMENT_DAYS if condicao is not None else None,
                    prazo_entrega=condicao.DELIVERY_DAYS if condicao is not None else None,
                    pedido_minimo=condicao.MIN_ORDER if condicao is not None else None,
                    frete=condicao.FREIGHT if condicao is not None else None,
                    validade_proposta=condicao.PROPOSAL_VALIDITY if condicao is not None else None,
                    observacao=condicao.OBSERVATION if condicao is not None else None,
                ),
            ))

        return Cotacao(id_cotacao=id_cotacao, titulo=titulo, itens=itens, fornecedores=fornecedores)


def _diagnostico_colunas(
    detection: SheetDetection,
    missing: list[str],
    motivo: str,
    dicas: list[str] | None = None,
) -> DiagnosticoPlanilha:
    """Monta o diagnóstico de falha de mapeamento com o que foi encontrado."""
    encontrado: dict[str, str] = {}
    for column in detection.columns_detected:
        if column.concept and column.concept not in encontrado:
            encontrado[column.concept] = column.original_name

    return DiagnosticoPlanilha(
        mensagem=(
            f"Não foi possível reconhecer {motivo} na aba "
            f"'{detection.sheet_name}'. "
            f"Faltando: {', '.join(rotular_conceito(c) for c in missing)}."
        ),
        codigo="colunas_nao_reconhecidas",
        titulo="Colunas obrigatórias não reconhecidas",
        faltando=missing,
        encontrado=encontrado,
        aba_selecionada=detection.sheet_name,
        dicas=(dicas or []) + DICAS_PADRAO,
    )


def _column_positions(
    detection: SheetDetection,
    column_mapping: Mapping[str, int | str] | None,
) -> dict[str, int]:
    headers = detection.header_values
    positions: dict[str, int] = {}
    provided = {key.upper(): value for key, value in (column_mapping or {}).items()}

    generic_count = sum(
        bool(re.fullmatch(r"campo\s+[a-z]+", str(header), re.I))
        for header in headers
    )
    if generic_count >= 6 and len(headers) >= 6:
        generic_layout = {
            0: "ID", 1: "DESCRIPTION", 2: "UNIT", 3: "QUANTITY",
            4: "SUPPLIER", 5: "UNIT_PRICE", 6: "TOTAL_PRICE",
            7: "DELIVERY_DAYS", 8: "PAYMENT_DAYS", 9: "FREIGHT",
            10: "MIN_ORDER", 11: "OBSERVATION",
        }
        positions.update({
            concept: position
            for position, concept in generic_layout.items()
            if position < len(headers)
        })

    for concept in REQUIRED_CONCEPTS | set(COMMERCIAL_CONCEPTS) | SOURCE_ANALYSIS_CONCEPTS | {"TOTAL_PRICE"}:
        manual = provided.get(concept)
        if manual is not None:
            if isinstance(manual, int):
                if not 0 <= manual < len(headers):
                    raise DiagnosticoPlanilha(
                        mensagem=(
                            f"A posição {manual} informada para "
                            f"{rotular_conceito(concept)} não existe na aba "
                            f"'{detection.sheet_name}', que tem {len(headers)} coluna(s)."
                        ),
                        codigo="posicao_invalida",
                        titulo="Mapeamento manual inválido",
                        faltando=[concept],
                        aba_selecionada=detection.sheet_name,
                        dicas=[
                            "Use um índice de coluna entre 0 e o total de colunas menos um.",
                        ],
                    )
                positions[concept] = manual
            else:
                try:
                    positions[concept] = headers.index(manual)
                except ValueError as exc:
                    raise DiagnosticoPlanilha(
                        mensagem=(
                            f"A coluna '{manual}' informada para "
                            f"{rotular_conceito(concept)} não foi encontrada na aba "
                            f"'{detection.sheet_name}'."
                        ),
                        codigo="coluna_manual_inexistente",
                        titulo="Mapeamento manual inválido",
                        faltando=[concept],
                        encontrado={
                            column.concept: column.original_name
                            for column in detection.columns_detected
                            if column.concept
                        },
                        aba_selecionada=detection.sheet_name,
                        dicas=[
                            "Confira o nome exato do cabeçalho, incluindo acentos.",
                        ],
                    ) from exc
            continue

        if concept in positions:
            continue

        candidates = [column for column in detection.columns_detected if column.concept == concept]
        if len(candidates) == 1:
            positions[concept] = candidates[0].position
        elif len(candidates) > 1 and concept in REQUIRED_CONCEPTS:
            ranked = sorted(
                candidates,
                key=lambda column: (column.score + column.data_score, column.data_score),
                reverse=True,
            )
            if ranked[0].score + ranked[0].data_score >= ranked[1].score + ranked[1].data_score + 4:
                positions[concept] = ranked[0].position
                continue
            names = ", ".join(column.original_name for column in candidates)
            raise DiagnosticoPlanilha(
                mensagem=(
                    f"Mais de uma coluna na aba '{detection.sheet_name}' parece ser "
                    f"{rotular_conceito(concept)}: {names}."
                ),
                codigo="coluna_ambigua",
                titulo="Coluna ambígua",
                faltando=[concept],
                encontrado={concept: names},
                aba_selecionada=detection.sheet_name,
                dicas=[
                    f"Renomeie a coluna correta ou desambigue removendo a coluna duplicada ({names}).",
                ] + DICAS_PADRAO,
            )

    # ``Codigo_Cotacao`` é recorrente em exportações de ERP/portal de compras.
    # Ele não representa necessariamente o SKU, mas permite importar uma
    # linha de proposta quando não há outra chave de item disponível.
    if "ID" not in positions:
        quote_candidates = [
            column for column in detection.columns_detected
            if column.concept == "QUOTE_ID"
        ]
        if len(quote_candidates) == 1:
            positions["ID"] = quote_candidates[0].position

    missing = sorted(SOURCE_REQUIRED_CONCEPTS - set(positions))
    if missing:
        raise _diagnostico_colunas(
            detection,
            missing,
            motivo="as colunas obrigatórias",
        )
    return positions


def _motivos_descarte(row: Mapping[str, Any]) -> list[str]:
    """Descreve, campo a campo, por que um registro válido não pode ser usado.

    Distingue campo ausente de valor inválido (``<= 0``) para que a correção na
    planilha seja direta: preencher versus ajustar.
    """
    motivos: list[str] = []

    quantidade = row.get("QUANTITY")
    if _is_empty(quantidade):
        motivos.append("quantidade ausente")
    elif not _is_positive_number(quantidade):
        motivos.append(f"quantidade inválida ({quantidade})")

    preco = row.get("UNIT_PRICE")
    if _is_empty(preco):
        motivos.append("preço unitário ausente")
    elif not _is_positive_number(preco):
        motivos.append(f"preço unitário inválido ({preco})")

    for campo, rotulo in (
        ("DESCRIPTION", "descrição do item"),
        ("UNIT", "unidade"),
        ("SUPPLIER", "fornecedor"),
    ):
        if _is_empty(row.get(campo)):
            motivos.append(f"{rotulo} ausente")

    return motivos or ["registro incompleto"]


def _registro_descarte(
    linha: Any,
    header_row: int,
    motivos: list[str],
    row: Mapping[str, Any],
) -> dict:
    """Monta uma entrada do catálogo de linhas não aproveitadas."""
    return {
        "Linha (Excel)": int(linha) + 1,
        "Motivo": "; ".join(motivos),
        "Descrição encontrada": _text(row.get("DESCRIPTION")) or "",
        "Fornecedor encontrado": _text(row.get("SUPPLIER")) or "",
    }


def _first_text(values: pd.Series) -> str | None:
    for value in values:
        normalized = _text(value)
        if normalized is not None:
            return normalized
    return None


def _excel_rows(index: pd.Index, header_row: int, limit: int = 10) -> str:
    """Formata índices do DataFrame como números de linha visíveis no Excel."""
    # ``raw`` é lido com ``header=None``; portanto seu índice já corresponde
    # à linha zero-based original, independentemente da posição do cabeçalho.
    return ", ".join(str(int(row) + 1) for row in index[:limit])


def _is_quote_reference(detection: SheetDetection, id_position: int) -> bool:
    return any(
        column.position == id_position and column.concept == "QUOTE_ID"
        for column in detection.columns_detected
    )


def _stable_key(value: Any) -> str:
    text = _text(value) or ""
    return re.sub(r"\s+", " ", text).strip().casefold()


def _quote_reference_is_unreliable(normalized: pd.DataFrame) -> bool:
    references = normalized["ID"].dropna()
    if references.empty:
        return True
    unique_ratio = references.nunique() / len(references)
    return unique_ratio >= 0.75 and references.nunique() > normalized["DESCRIPTION"].nunique()


def _replace_unreliable_quote_ids(normalized: pd.DataFrame) -> None:
    normalized["ID"] = normalized.apply(
        lambda row: f"{_text(row['DESCRIPTION'])} [{_stable_key(row['UNIT']).upper()}]",
        axis=1,
    )


def _canonicalize_suppliers(normalized: pd.DataFrame) -> None:
    canonical: dict[str, str] = {}
    for value in normalized["SUPPLIER"]:
        key = _stable_key(value)
        if key and key not in canonical:
            canonical[key] = _text(value) or key
    normalized["SUPPLIER"] = normalized["SUPPLIER"].map(
        lambda value: canonical.get(_stable_key(value), _text(value))
    )


def _deduplicate_proposals(normalized: pd.DataFrame) -> tuple[list[str], list[dict]]:
    duplicate = normalized.duplicated(["ID", "SUPPLIER"], keep=False)
    if not duplicate.any():
        return [], []

    duplicate_rows = normalized.loc[duplicate].copy()
    duplicate_rows["_price_rank"] = duplicate_rows["UNIT_PRICE"].fillna(float("inf"))
    keep_indexes = duplicate_rows.groupby(["ID", "SUPPLIER"], sort=False)["_price_rank"].idxmin()
    drop_indexes = duplicate_rows.index.difference(keep_indexes.tolist())
    descartes = [
        {
            "Linha (Excel)": int(index) + 1,
            "Motivo": "proposta duplicada para o mesmo item e fornecedor; mantida a menor cotação",
            "Descrição encontrada": _text(normalized.at[index, "DESCRIPTION"]) or "",
            "Fornecedor encontrado": _text(normalized.at[index, "SUPPLIER"]) or "",
        }
        for index in drop_indexes
    ]
    normalized.drop(index=drop_indexes, inplace=True)
    return [
        f"{len(drop_indexes)} proposta(s) duplicada(s) para o mesmo produto e fornecedor "
        "foram descartadas; foi mantida a menor cotação válida."
    ], descartes


def _make_unique_quote_ids(normalized: pd.DataFrame, header_row: int) -> list[str]:
    """Evita colisões em exportações que reutilizam código de cotação.

    Não altera IDs de item genuínos: esta correção só é usada quando o ID foi
    obtido da coluna de referência de cotação. O sufixo aponta para a linha de
    origem e preserva a rastreabilidade do registro.
    """
    duplicated = normalized["ID"].duplicated(keep=False)
    if not duplicated.any():
        return []

    for index in normalized.index[duplicated]:
        normalized.at[index, "ID"] = f"{normalized.at[index, 'ID']}-L{index + 1}"
    return [
        "Códigos de cotação repetidos receberam o sufixo da linha de origem "
        f"para manter cada proposta distinta ({_excel_rows(normalized.index[duplicated], header_row)})."
    ]


def _total_warnings(normalized: pd.DataFrame, header_row: int) -> list[str]:
    """Reporta totais preenchidos que não fecham com quantidade x unitário."""
    if normalized["TOTAL_PRICE"].isna().all():
        return []

    comparable = normalized.dropna(subset=["QUANTITY", "UNIT_PRICE", "TOTAL_PRICE"])
    if comparable.empty:
        return []

    expected = comparable["QUANTITY"] * comparable["UNIT_PRICE"]
    tolerance = expected.abs().mul(0.01).clip(lower=0.01)
    mismatches = comparable[(comparable["TOTAL_PRICE"] - expected).abs() > tolerance]
    if mismatches.empty:
        return []

    rows = _excel_rows(mismatches.index, header_row)
    return [
        f"{len(mismatches)} total(is) informado(s) divergem de quantidade x preço unitário "
        f"acima da tolerância de 1% (linhas: {rows})."
    ]


def _normalizar_matriz_propostas(
    raw: pd.DataFrame, selected: SheetDetection
) -> tuple[pd.DataFrame, dict] | None:
    """Converte a matriz com um par Unitário/Total por fornecedor."""
    header_index = selected.header_row - 1
    group_index = header_index - 1
    if group_index < 0 or header_index >= len(raw):
        return None

    headers = [
        str(value).strip().casefold() if not _is_empty(value) else ""
        for value in raw.iloc[header_index]
    ]
    group_names = raw.iloc[group_index].tolist()
    unit_columns = [
        index for index, header in enumerate(headers)
        if index >= 5
        and (
            header in {"unitário", "unitario"}
            or (not header and index + 1 < len(headers) and headers[index + 1] in {"total"})
        )
    ]
    if len(unit_columns) < 3:
        return None

    def label(index: int) -> str | None:
        return _text(group_names[index])

    excluded = {
        "BASELINE (VIVex)", "BASELINE AJUSTADO (6,29%)",
        "ESTUDO DOS MÍNIMOS", "TARGET",
    }
    proposal_columns = []
    occurrences: dict[str, int] = {}
    final_columns: list[tuple[int, str]] = []
    for index in unit_columns:
        supplier = label(index)
        if not supplier or supplier in excluded:
            continue
        occurrences[supplier] = occurrences.get(supplier, 0) + 1
        is_final = occurrences[supplier] > 1
        if is_final:
            supplier = f"{supplier} (Final)"
            final_columns.append((index, supplier))
        proposal_columns.append((index, supplier))
    if len(proposal_columns) < 2:
        return None

    records = []
    matriz_descartes: list[dict] = []
    source_rows = raw.iloc[header_index + 1:]
    for position, (_, row) in enumerate(source_rows.iterrows()):
        item_id = _text(row.iloc[0])
        linha_excel = header_index + 1 + position + 1
        if not item_id:
            matriz_descartes.append({
                "Linha (Excel)": linha_excel,
                "Motivo": "linha sem identificador de item",
                "Descrição encontrada": _text(row.iloc[1]) or "",
                "Fornecedor encontrado": "",
            })
            continue
        if item_id.casefold() == "total":
            matriz_descartes.append({
                "Linha (Excel)": linha_excel,
                "Motivo": "linha de total (ignorada de propósito)",
                "Descrição encontrada": _text(row.iloc[1]) or "",
                "Fornecedor encontrado": "",
            })
            continue
        description = _text(row.iloc[1])
        speed = _text(row.iloc[2])
        unit = _text(row.iloc[3])
        quantity = converter_numero(row.iloc[4])
        if not description or quantity is None:
            faltas = []
            if not description:
                faltas.append("descrição do item ausente")
            if quantity is None:
                faltas.append("quantidade ausente")
            matriz_descartes.append({
                "Linha (Excel)": linha_excel,
                "Motivo": "; ".join(faltas) or "registro incompleto",
                "Descrição encontrada": description or "",
                "Fornecedor encontrado": "",
            })
            continue
        for column, supplier in proposal_columns:
            price = converter_numero(row.iloc[column])
            if price is None:
                continue
            records.append({
                "ID": item_id,
                "DESCRIPTION": description,
                "QUANTITY": quantity,
                "UNIT": unit or speed or "UN",
                "SUPPLIER": supplier,
                "UNIT_PRICE": price,
                "TOTAL_PRICE": converter_numero(row.iloc[column + 1]) if column + 1 < len(row) else None,
                "OBSERVATION": None,
            })

    normalized = pd.DataFrame(records)
    if normalized.empty:
        return None

    reference_columns = {
        "BASELINE": next((i for i in unit_columns if label(i) == "BASELINE (VIVex)"), None),
        "BASELINE AJUSTADO": next((i for i in unit_columns if label(i) == "BASELINE AJUSTADO (6,29%)"), None),
        "ESTUDO DOS MÍNIMOS": next((i for i in unit_columns if label(i) == "ESTUDO DOS MÍNIMOS"), None),
        "TARGET": next((i for i in unit_columns if label(i) == "TARGET"), None),
        "VIVO FINAL": final_columns[-1][0] if len(final_columns) == 1 else None,
    }
    reference_rows = []
    for _, row in source_rows.iterrows():
        item_id = _text(row.iloc[0])
        if not item_id or item_id.casefold() == "total" or _text(row.iloc[1]) is None:
            continue
        reference = {
            "ID": item_id,
            "Descrição": _text(row.iloc[1]),
            "Quantidade": converter_numero(row.iloc[4]),
        }
        for name, column in reference_columns.items():
            reference[name] = converter_numero(row.iloc[column]) if column is not None else None
        reference_rows.append(reference)

    return normalized, {
        "tipo": "Matriz de equalização com propostas iniciais e finais",
        "fornecedores": [supplier for _, supplier in proposal_columns],
        "fornecedor_final": final_columns[0][1] if len(final_columns) == 1 else None,
        "tabela": pd.DataFrame(reference_rows),
        "descartes": matriz_descartes,
    }


def normalizar_excel(
    arquivo: str | Path,
    *,
    detector: StructureDetector | None = None,
    aba: str | None = None,
    column_mapping: Mapping[str, int | str] | None = None,
    strict: bool = False,
) -> DadosNormalizados:
    """Lê e normaliza uma planilha tabular de propostas.

    ``column_mapping`` aceita o conceito semântico como chave (por exemplo,
    ``{"UNIT_PRICE": "Valor cotado"}``) e o nome ou índice zero-based da coluna.
    Por padrão, registros incompletos são descartados e reportados em
    ``avisos``; use ``strict=True`` para interromper a importação nesses casos.
    """
    path = Path(arquivo)
    structure = (detector or StructureDetector()).inspect(path)
    selected = next((sheet for sheet in structure.sheets if sheet.sheet_name == (aba or structure.selected_sheet)), None)
    if selected is None:
        disponiveis = [sheet.sheet_name for sheet in structure.sheets]
        raise DiagnosticoPlanilha(
            mensagem=(
                f"A aba '{aba}' não existe no arquivo. "
                f"Abas disponíveis: {', '.join(disponiveis) or 'nenhuma'}."
            ),
            codigo="aba_inexistente",
            titulo="Aba não encontrada",
            abas_analisadas=disponiveis,
            dicas=[
                f"Use uma das abas disponíveis: {', '.join(disponiveis)}.",
                "Deixe o campo \"Aba\" em branco para usar a detecção automática.",
            ],
        )

    try:
        raw = pd.read_excel(
            path,
            sheet_name=selected.sheet_name,
            header=None,
            engine="openpyxl",
            dtype=object,
        )
    except Exception as exc:
        raise DiagnosticoPlanilha(
            mensagem=(
                f"A aba '{selected.sheet_name}' não pôde ser aberta pelo leitor "
                f"de Excel: {exc}"
            ),
            codigo="aba_ilegivel",
            titulo="Aba ilegível",
            aba_selecionada=selected.sheet_name,
            dicas=[
                "Salve novamente o arquivo como .xlsx em um programa de planilhas.",
                "Verifique se a aba não está corrompida ou protegida por senha.",
            ],
        ) from exc

    matriz = _normalizar_matriz_propostas(raw, selected) if column_mapping is None else None
    if matriz is not None:
        normalized, referencia = matriz
        quote_reference = False
        positions = None
    else:
        positions = _column_positions(selected, column_mapping)
        # ``ID`` é opcional (a cotação pode ser agrupada por descrição), mas se
        # existir precisa ser a coluna de referência de item.
        quote_reference = (
            _is_quote_reference(selected, positions["ID"])
            if "ID" in positions
            else False
        )
    data = raw.iloc[selected.header_row:]
    linhas_fisicas = int(data.dropna(how="all").shape[0])
    linhas_vazias = int(data.shape[0]) - linhas_fisicas
    data = data.dropna(how="all").copy()

    if matriz is None:
        # Acesso posicional evita reatribuir ``DataFrame.columns`` (que tem uma
        # tipagem mais restritiva no pandas) e também funciona para cabeçalhos
        # duplicados ou ausentes.
        normalized = pd.DataFrame({
            concept: data.iloc[:, position] for concept, position in positions.items()
        })
    normalized = normalized.dropna(how="all")
    if "ID" not in normalized:
        normalized["ID"] = None
    normalized["ID"] = normalized["ID"].map(_text)
    normalized["DESCRIPTION"] = normalized["DESCRIPTION"].map(_text)
    normalized["UNIT"] = normalized["UNIT"].map(
        lambda value: (_text(value) or "").upper() or None
    )
    normalized["SUPPLIER"] = normalized["SUPPLIER"].map(_text)
    normalized["QUANTITY"] = normalized["QUANTITY"].map(converter_numero)
    normalized["UNIT_PRICE"] = normalized["UNIT_PRICE"].map(converter_numero)
    if "TOTAL_PRICE" in normalized:
        normalized["TOTAL_PRICE"] = normalized["TOTAL_PRICE"].map(converter_numero)
    else:
        normalized["TOTAL_PRICE"] = None
    if "OBSERVATION" not in normalized:
        normalized["OBSERVATION"] = None
    else:
        normalized["OBSERVATION"] = normalized["OBSERVATION"].map(_text)
    for concept in COMMERCIAL_CONCEPTS:
        if concept not in normalized:
            normalized[concept] = None
        else:
            normalized[concept] = normalized[concept].map(_text)
    for concept in SOURCE_ANALYSIS_CONCEPTS:
        if concept not in normalized:
            normalized[concept] = None
        else:
            normalized[concept] = normalized[concept].map(_text)

    linhas_importadas = len(normalized)
    # Uma linha é inválida quando falta algum campo obrigatório OU quando
    # quantidade/preço não são positivos. Os dois casos geram motivos distintos
    # para que a correção na planilha seja direta (preencher x ajustar valor).
    obrigatorios = ["ID", "DESCRIPTION", "UNIT", "SUPPLIER", "QUANTITY", "UNIT_PRICE"]
    invalid_mask = (
        normalized[obrigatorios].isna().any(axis=1)
        | ~normalized["QUANTITY"].map(_is_positive_number)
        | ~normalized["UNIT_PRICE"].map(_is_positive_number)
    )
    invalid = normalized[invalid_mask]
    avisos = [*selected.warnings, *structure.warnings]
    avisos.extend(_total_warnings(normalized, selected.header_row))

    descartes: list[dict] = []
    if matriz is not None:
        descartes.extend(referencia.get("descartes", []))
    elif linhas_vazias:
        descartes.append({
            "Linha (Excel)": None,
            "Motivo": f"{linhas_vazias} linha(s) totalmente vazia(s) após o cabeçalho (ignoradas automaticamente)",
            "Descrição encontrada": "",
            "Fornecedor encontrado": "",
        })

    if not invalid.empty:
        for index, row in invalid.iterrows():
            descartes.append(
                _registro_descarte(
                    index, selected.header_row, _motivos_descarte(row), row
                )
            )
        rows = _excel_rows(invalid.index, selected.header_row)
        message = (
            f"{len(invalid)} registro(s) com dados obrigatórios inválidos foram ignorados "
            f"(linhas: {rows})."
        )
        if strict:
            raise ValueError(message)
        avisos.append(message)
        normalized = normalized.drop(index=invalid.index).copy()

    if normalized.empty:
        raise DiagnosticoPlanilha(
            mensagem=(
                f"A aba '{selected.sheet_name}' não contém nenhuma proposta válida. "
                "Todos os registros encontrados estavam incompletos ou com valores inválidos."
            ),
            codigo="sem_propostas_validas",
            titulo="Nenhuma proposta válida",
            faltando=list(CONCEITOS_OBRIGATORIOS),
            aba_selecionada=selected.sheet_name,
            dicas=[
                "Confirme que a quantidade e o preço unitário estão preenchidos e são maiores que zero.",
            ] + DICAS_PADRAO,
        )

    if normalized["ID"].isna().all():
        _replace_unreliable_quote_ids(normalized)
        avisos.append(
            "Nenhum identificador de item foi encontrado; os itens foram agrupados "
            "por descrição e unidade."
        )

    if quote_reference:
        if _quote_reference_is_unreliable(normalized):
            _replace_unreliable_quote_ids(normalized)
            avisos.append(
                "Código de cotação não foi usado como ID de item porque é quase único "
                "por linha; os itens foram agrupados por descrição e unidade."
            )
        else:
            avisos.extend(_make_unique_quote_ids(normalized, selected.header_row))

    _canonicalize_suppliers(normalized)
    avisos_dedup, descartes_dedup = _deduplicate_proposals(normalized)
    avisos.extend(avisos_dedup)
    descartes.extend(descartes_dedup)

    linhas_total_fisicas = (
        linhas_importadas + linhas_vazias
        if matriz is None
        else linhas_importadas
        + len(referencia.get("descartes", []))
    )
    linhas_descartadas_total = len(descartes)
    contagem_linhas = {
        "Linhas físicas analisadas": int(linhas_total_fisicas),
        "Linhas aproveitadas": int(linhas_importadas - len(invalid)),
        "Linhas descartadas": int(linhas_descartadas_total),
    }

    analise_fonte = analisar_fonte(
        normalized,
        avisos,
        linhas_importadas=linhas_total_fisicas,
        linhas_descartadas=linhas_descartadas_total,
    )
    analise_fonte["perfil"].setdefault("qualidade", {}).update(contagem_linhas)
    if matriz is not None:
        analise_fonte["matriz_referencia"] = referencia

    item_columns = ["ID", "DESCRIPTION", "QUANTITY", "UNIT"]
    conflicting_items = normalized.groupby("ID")[['DESCRIPTION', 'UNIT']].nunique(dropna=False).gt(1).any(axis=1)
    if conflicting_items.any():
        ids = ", ".join(conflicting_items[conflicting_items].index.tolist())
        raise DiagnosticoPlanilha(
            mensagem=(
                f"O mesmo identificador de item aparece com descrição ou unidade "
                f"diferentes: {ids}. Cada ID deve representar um único item solicitado."
            ),
            codigo="ids_conflitantes",
            titulo="Identificadores de item conflitantes",
            aba_selecionada=selected.sheet_name,
            dicas=[
                "Garanta que cada ID tenha sempre a mesma descrição e unidade.",
                "Se os códigos se repetem por fornecedor, use uma coluna que identifique o item de forma única.",
            ],
        )
    itens = normalized[item_columns].drop_duplicates("ID").reset_index(drop=True)
    propostas = normalized[
        ["ID", "SUPPLIER", "DESCRIPTION", "QUANTITY", "UNIT", "UNIT_PRICE", "TOTAL_PRICE", "OBSERVATION"]
    ].reset_index(drop=True)
    commercial = normalized[["SUPPLIER", *COMMERCIAL_CONCEPTS]].copy()
    commercial = commercial.groupby("SUPPLIER", as_index=False).agg(_first_text)

    return DadosNormalizados(
        itens=itens,
        propostas=propostas,
        condicoes_comerciais=commercial,
        arquivo_origem=str(path),
        aba_origem=selected.sheet_name,
        avisos=avisos,
        analise_fonte=analise_fonte,
        descartes=descartes,
        contagem_linhas=contagem_linhas,
    )
