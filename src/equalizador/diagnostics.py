"""Diagnóstico legível de falhas de leitura de planilhas.

O motor já sabe *por que* uma planilha não pôde ser lida, mas essa informação
se perdia ao virar uma mensagem genérica na API. Este módulo carrega o motivo
real, os conceitos que faltaram e o que foi encontrado, para que a interface
possa explicar ao usuário exatamente o que não foi reconhecido.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Rótulos em português dos conceitos semânticos reconhecidos pelo motor.
CONCEITOS = {
    "ID": "identificador do item",
    "DESCRIPTION": "descrição do item",
    "QUANTITY": "quantidade",
    "UNIT": "unidade",
    "UNIT_PRICE": "preço unitário",
    "TOTAL_PRICE": "preço total",
    "SUPPLIER": "fornecedor",
    "SUPPLIER_ID": "código do fornecedor",
    "QUOTE_ID": "código da cotação",
    "CURRENCY": "moeda",
    "CATEGORY": "categoria",
    "QUOTE_DATE": "data da cotação",
    "PAYMENT_DAYS": "prazo de pagamento",
    "DELIVERY_DAYS": "prazo de entrega",
    "FREIGHT": "frete",
    "MIN_ORDER": "pedido mínimo",
    "PROPOSAL_VALIDITY": "validade da proposta",
    "STATUS": "status",
    "OBSERVATION": "observação",
}

# Conceitos sem os quais uma linha de proposta não pode ser montada. Esta é a
# única fonte de verdade do "obrigatório": ``normalization`` e os testes importam
# daqui para que as definições nunca divirjam.
CONCEITOS_OBRIGATORIOS: tuple[str, ...] = (
    "DESCRIPTION", "QUANTITY", "UNIT", "SUPPLIER", "UNIT_PRICE",
)
# Conceitos que identificam um item; ausentes, o motor agrupa por descrição.
CONCEITOS_IDENTIFICADOR: tuple[str, ...] = ("ID",)
# União usada ao montar a cotação completa (item + proposta).
CONCEITOS_OBRIGATORIOS_ITEM: tuple[str, ...] = (
    CONCEITOS_IDENTIFICADOR + CONCEITOS_OBRIGATORIOS
)


def rotular_conceito(conceito: str) -> str:
    return CONCEITOS.get(conceito, conceito)


@dataclass
class DiagnosticoPlanilha(ValueError):
    """Erro de leitura com contexto suficiente para orientar o usuário.

    É uma exceção para continuar interrompendo o fluxo, mas carrega um payload
    estruturado que a API devolve e a interface renderiza como checklist.
    Herda de ``ValueError`` porque representa dados de entrada inválidos.
    """

    mensagem: str
    codigo: str = "leitura_invalida"
    titulo: str = "Não foi possível ler a planilha"
    faltando: list[str] = field(default_factory=list)
    encontrado: dict[str, str] = field(default_factory=dict)
    abas_analisadas: list[str] = field(default_factory=list)
    aba_selecionada: str | None = None
    dicas: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.mensagem)

    def para_payload(self) -> dict:
        return {
            "codigo": self.codigo,
            "titulo": self.titulo,
            "mensagem": self.mensagem,
            "faltando": [rotular_conceito(c) for c in self.faltando],
            "faltando_tecnico": list(self.faltando),
            "encontrado": {
                rotular_conceito(conceito): coluna
                for conceito, coluna in self.encontrado.items()
            },
            "abas_analisadas": list(self.abas_analisadas),
            "aba_selecionada": self.aba_selecionada,
            "dicas": list(self.dicas),
        }


DICAS_PADRAO = [
    "Cada linha deve representar um item cotado por um fornecedor.",
    "Inclua uma linha de cabeçalho com nomes como Descrição, Quantidade, Unidade, Fornecedor e Preço Unitário.",
    "Se a planilha tiver várias abas, informe o nome da aba correta no campo \"Aba\".",
]