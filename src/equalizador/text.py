import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz


SUBSTITUICOES = {
    r"\bunid\b": "unidade",
    r"\bun\b": "unidade",
    r"\bpcs\b": "peca",
    r"\bpc\b": "peca",
    r"\bcaixas\b": "caixa",
    r"\bcaix\b": "caixa",
    r"\bpcts\b": "pacote",
    r"\bpct\b": "pacote",
}


def normalizar_texto(texto: Any) -> str:
    if texto is None:
        return ""

    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))

    for padrao, substituto in SUBSTITUICOES.items():
        texto = re.sub(padrao, substituto, texto)

    # "." é preservado para não fundir "1.5" em "15" durante a comparação.
    texto = re.sub(r"[^a-z0-9.\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def calcular_similaridade(descricao_solicitada: Any, descricao_cotada: Any) -> float:
    solicitada = normalizar_texto(descricao_solicitada)
    cotada = normalizar_texto(descricao_cotada)

    if not solicitada or not cotada:
        return 0.0

    return float(fuzz.token_set_ratio(solicitada, cotada))


def classificar_similaridade(score: float, limite_alto: float, limite_alerta: float) -> str:
    if score >= limite_alto:
        return "ALTA"
    if score >= limite_alerta:
        return "REVISAR"
    return "BAIXA"


def extrair_atributos(descricao: Any) -> dict[str, str | None]:
    texto = normalizar_texto(descricao)

    atributos: dict[str, str | None] = {
        "cor": None,
        "ponta": None,
        "tamanho": None,
        "gramatura": None,
    }

    for cor in ("azul", "preto", "branco", "vermelho", "verde", "amarelo", "rosa", "cinza"):
        if re.search(rf"\b{cor}\b", texto):
            atributos["cor"] = cor
            break

    for ponta in ("fina", "media", "grossa"):
        if re.search(rf"\b{ponta}\b", texto):
            atributos["ponta"] = ponta
            break

    match_tamanho = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(cm|mm|m)\b", texto)
    if match_tamanho:
        valor = match_tamanho.group(1).replace(",", ".")
        atributos["tamanho"] = f"{valor} {match_tamanho.group(2)}"

    match_gramatura = re.search(r"\b(\d+(?:[.,]\d+)?)\s*g\b", texto)
    if match_gramatura:
        valor = match_gramatura.group(1).replace(",", ".")
        atributos["gramatura"] = f"{valor} g"

    return atributos
