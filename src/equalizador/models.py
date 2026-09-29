from dataclasses import dataclass, field


@dataclass(frozen=True)
class ItemSolicitado:
    id_item: str
    descricao: str
    quantidade: float
    unidade: str


@dataclass(frozen=True)
class ItemProposta:
    id_item: str
    descricao: str
    quantidade: float
    unidade: str
    valor_unitario: float | None = None
    valor_total: float | None = None
    observacao: str | None = None


@dataclass(frozen=True)
class CondicoesComerciais:
    pagamento: str | None = None
    prazo_entrega: str | None = None
    pedido_minimo: str | None = None
    frete: str | None = None
    validade_proposta: str | None = None
    observacao: str | None = None


@dataclass
class Fornecedor:
    nome: str
    itens: list[ItemProposta] = field(default_factory=list)
    condicoes: CondicoesComerciais = field(default_factory=CondicoesComerciais)


@dataclass
class Cotacao:
    id_cotacao: str
    titulo: str
    itens: list[ItemSolicitado] = field(default_factory=list)
    fornecedores: list[Fornecedor] = field(default_factory=list)
