from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from rapidfuzz import fuzz


@dataclass(frozen=True)
class SemanticConcept:
    key: str
    label: str
    aliases: tuple[str, ...]
    priority: int = 0


@dataclass(frozen=True)
class SemanticMatch:
    concept: str | None
    score: float
    confidence: str
    matched_alias: str | None


class SemanticEngine:
    """
    Motor semântico bilíngue PT/EN para identificar o significado de colunas.

    O motor:
    - normaliza acentos, caixa e separadores;
    - usa aliases exatos e fuzzy matching;
    - resolve colisões por regras de prioridade;
    - devolve confiança HIGH/MEDIUM/LOW/NONE;
    - pode receber contexto de outras colunas.
    """

    CONCEPTS = (
        SemanticConcept("ID", "Identificador", (
            "id", "codigo", "código", "cod", "codigo item", "código item",
            "item id", "item code", "item codigo", "item código",
            "sku", "part number", "pn", "material code", "material codigo",
            "material código", "reference", "referencia", "referência",
            "numero item", "número item", "numero do item", "número do item",
            "linha", "item number", "line number", "product code", "codigo produto",
            "código produto", "codigo material", "código material",
        ), 90),
        SemanticConcept("DESCRIPTION", "Descrição", (
            "descricao", "descrição", "descricao item", "descrição item",
            "descricao do item", "descrição do item", "item description",
            "description", "desc", "produto", "material description",
            "nome do item", "nome produto", "item", "material",
            "nome do produto", "produto descricao", "produto descrição",
            "descricao produto", "descrição produto", "especificacao",
            "especificação", "produto servico", "produto serviço", "item name",
            "product name", "product description", "material name",
        ), 60),
        SemanticConcept("QUANTITY", "Quantidade", (
            "quantidade", "qtd", "qtde", "qte", "quant", "qty",
            "quantity", "requested quantity", "volume", "vol",
            "qtd solicitada", "quantidade solicitada", "quantidade requisitada",
            "quantidade pedida", "demand", "order quantity", "requested qty",
        ), 80),
        SemanticConcept("UNIT", "Unidade", (
            "unidade", "un", "und", "unid", "u.m.", "um",
            "unit", "unit of measure", "uom", "measurement unit",
            "unidade de medida", "und medida", "unidade comercial", "embalagem",
            "packaging", "measure", "medida",
        ), 80),
        SemanticConcept("UNIT_PRICE", "Preço unitário", (
            "preco unitario", "preço unitário", "valor unitario",
            "valor unitário", "preco por unidade", "preço por unidade",
            "unit price", "unit cost", "price per unit", "rate",
            "unit rate", "quoted price", "preco", "preço", "valor",
            "preco cotado", "preço cotado", "valor cotado", "cotacao unitario",
            "cotação unitário", "valor por unidade", "valor unit", "custo unitario",
            "custo unitário", "preco de compra", "preço de compra", "purchase price",
        ), 100),
        SemanticConcept("TOTAL_PRICE", "Preço total", (
            "preco total", "preço total", "valor total", "total price",
            "total cost", "extended price", "extended cost", "amount",
            "total amount", "net amount", "gross amount",
            "valor da proposta", "valor cotado total", "subtotal", "total geral",
        ), 95),
        SemanticConcept("SUPPLIER", "Fornecedor", (
            "fornecedor", "forn", "vendor", "supplier", "provider",
            "seller", "empresa fornecedora", "nome fornecedor",
            "nome do fornecedor", "razao social", "razão social", "empresa",
            "supplier name", "vendor name", "company name",
        ), 100),
        # Metadados comuns que não devem ser confundidos com os campos usados
        # para montar a cotação. Eles são reconhecidos para evitar falsos
        # positivos em cabeçalhos como ``ID_Fornecedor`` e ``Moeda``.
        SemanticConcept("SUPPLIER_ID", "Código do fornecedor", (
            "id fornecedor", "id do fornecedor", "codigo fornecedor",
            "código fornecedor", "cod fornecedor", "supplier id", "vendor id",
            "supplier code", "vendor code",
        ), 100),
        SemanticConcept("QUOTE_ID", "Código da cotação", (
            "codigo cotacao", "código cotação", "cod cotacao", "cod cotação",
            "codigo da cotacao", "código da cotação", "numero cotacao",
            "número cotação", "id cotacao", "id cotação", "quote id",
            "quote code", "quotation code", "quote number", "quotation number",
            "rfq", "rfq number",
        ), 100),
        SemanticConcept("CURRENCY", "Moeda", (
            "moeda", "currency", "currency code", "codigo moeda", "código moeda",
            "curr", "fx currency",
        ), 100),
        SemanticConcept("QUOTE_DATE", "Data da cotação", (
            "data cotacao", "data cotação", "data da cotacao", "data da cotação",
            "quote date", "quotation date", "proposal date", "date quoted",
        ), 100),
        SemanticConcept("CATEGORY", "Categoria", (
            "categoria", "categoria produto", "categoria do produto", "category",
            "product category", "grupo", "familia", "família",
        ), 80),
        SemanticConcept("PAYMENT_DAYS", "Prazo de pagamento", (
            "dias pagamento", "dias para pagamento", "prazo pagamento",
            "condicao pagamento", "condição pagamento", "payment days",
            "payment term", "payment terms", "terms of payment",
            "days to pay", "net days", "payment period",
        ), 90),
        SemanticConcept("DELIVERY_DAYS", "Prazo de entrega", (
            "dias entrega", "prazo entrega", "lead time", "delivery days",
            "delivery time", "delivery term", "days to delivery",
            "days for delivery", "prazo de fornecimento",
            "condicoes entrega", "condições entrega", "condicao de entrega",
            "condição de entrega", "condicoes de entrega", "condições de entrega",
            "delivery conditions", "shipping conditions", "entrega prevista",
        ), 90),
        SemanticConcept("FREIGHT", "Frete", (
            "frete", "frete incluso", "frete incluso no preco",
            "frete incluso no preço", "freight", "freight included",
            "shipping", "shipping included", "delivery freight",
            "cif", "fob",
        ), 90),
        SemanticConcept("MIN_ORDER", "Pedido mínimo", (
            "pedido minimo", "pedido mínimo", "quantidade minima",
            "quantidade mínima", "minimum order", "minimum order quantity",
            "moq", "minimum quantity", "minimum purchase",
            "ordem minima", "ordem mínima",
        ), 90),
        SemanticConcept("PROPOSAL_VALIDITY", "Validade da proposta", (
            "validade proposta", "validade da proposta", "validade",
            "prazo validade", "proposal validity", "quote validity",
            "quotation validity", "offer validity", "valid until",
            "validity period",
            "validade da cotacao", "validade da cotação", "validade da oferta",
        ), 85),
        SemanticConcept("BENCHMARK", "Benchmark", (
            "benchmark", "referencia de preco", "referência de preço",
            "preco benchmark", "preço benchmark", "benchmark price",
            "reference price", "target price", "baseline price",
            "preco base", "preço base", "valor de referencia",
            "valor de referência",
        ), 95),
        SemanticConcept("NEW_RATE", "Nova tarifa/preço", (
            "nova tarifa", "novo rate", "new rate", "new price",
            "novo preco", "novo preço", "preco novo", "preço novo",
            "proposed rate", "proposed price", "recommended rate",
            "recommended price",
        ), 95),
        SemanticConcept("DIFFERENCE", "Diferença", (
            "diferenca", "diferença", "delta", "difference", "variance",
            "price difference", "rate difference", "variacao",
            "variação", "gap", "desvio",
        ), 70),
        SemanticConcept("REDUCTION", "Redução", (
            "reducao", "redução", "reduction", "saving", "savings",
            "economia", "economia valor", "discount", "desconto",
            "reduction value", "saving value",
        ), 75),
        SemanticConcept("INCREASE", "Aumento", (
            "aumento", "increase", "increase value", "acrescimo",
            "acréscimo", "price increase", "rate increase",
            "variacao positiva", "variação positiva",
        ), 75),
        SemanticConcept("STATUS", "Status", (
            "status", "situacao", "situação", "estado", "state",
            "condition", "status cotacao", "status cotação",
            "quote status", "proposal status",
        ), 80),
        SemanticConcept("OBSERVATION", "Observação", (
            "observacao", "observação", "obs", "observacoes",
            "observações", "comentario", "comentário", "comments",
            "comment", "notes", "note", "observation", "remarks",
        ), 70),
    )

    _NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
    # These are result columns produced by this application, not fields from a
    # supplier's proposal.  Treating them as input fields makes a generated
    # report look like a valid source spreadsheet when it is inspected again.
    _DERIVED_HEADER_TOKENS = {
        "score", "similaridade", "elegivel", "recomendacao",
        "classificacao", "ranking", "validacao", "divergencias",
    }

    def __init__(
        self,
        high_threshold: float = 92.0,
        medium_threshold: float = 78.0,
        low_threshold: float = 62.0,
    ):
        if not (0 <= low_threshold <= medium_threshold <= high_threshold <= 100):
            raise ValueError("Thresholds devem respeitar 0 <= LOW <= MEDIUM <= HIGH <= 100.")
        self.high_threshold = float(high_threshold)
        self.medium_threshold = float(medium_threshold)
        self.low_threshold = float(low_threshold)

        self._concept_by_key = {c.key: c for c in self.CONCEPTS}
        self._alias_index = {}
        for concept in self.CONCEPTS:
            for alias in concept.aliases:
                self._alias_index[self.normalize(alias)] = concept.key

    @staticmethod
    def normalize(text: object) -> str:
        if text is None:
            return ""
        text = str(text).strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.replace("&", " e ")
        text = re.sub(r"[_\-/\\|:;]+", " ", text)
        text = re.sub(r"[^\w\s.%]", " ", text, flags=re.UNICODE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _confidence(self, score: float) -> str:
        if score >= self.high_threshold:
            return "HIGH"
        if score >= self.medium_threshold:
            return "MEDIUM"
        if score >= self.low_threshold:
            return "LOW"
        return "NONE"

    def _context_bonus(self, header: str, concept: SemanticConcept,
                       context: list[str] | None) -> float:
        if not context:
            return 0.0
        ctx = " ".join(self.normalize(x) for x in context)
        bonus = 0.0

        # Desempates semânticos comuns.
        if concept.key == "UNIT_PRICE" and any(
            x in ctx for x in ("fornecedor", "supplier", "vendor", "preco", "preco unitario")
        ):
            bonus += 2
        if concept.key == "TOTAL_PRICE" and any(
            x in ctx for x in ("quantidade", "quantity", "qtd")
        ):
            bonus += 3
        if concept.key == "PAYMENT_DAYS" and any(
            x in ctx for x in ("pagamento", "payment")
        ):
            bonus += 4
        if concept.key == "DELIVERY_DAYS" and any(
            x in ctx for x in ("entrega", "delivery", "lead time")
        ):
            bonus += 4
        if concept.key == "DESCRIPTION" and any(
            x in ctx for x in ("quantidade", "quantity", "unit", "unidade")
        ):
            bonus += 1
        return bonus

    def _score_alias(self, header: str, alias: str) -> float:
        if header == alias:
            return 100.0

        # A substring is not necessarily a header term: for example, ``id``
        # occurs inside "similaridade" and ``obs`` occurs inside
        # "atributos".  Only reward an alias when it is a complete token (or
        # token sequence) in the header.
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", header):
            # Evita que "preco" ganhe de "preco unitario".
            coverage = len(alias) / max(len(header), 1)
            return min(97.0, 88.0 + coverage * 9.0)

        scores = [
            fuzz.ratio(header, alias),
            fuzz.token_set_ratio(header, alias),
        ]
        # Partial matching is useful for meaningful aliases, but produces
        # false positives for short abbreviations such as ID, UN and OBS.
        if len(alias) >= 4:
            scores.append(fuzz.partial_ratio(header, alias) * 0.96)
        return float(max(scores))

    def candidates(self, header: object,
                   context: list[str] | None = None,
                   limit: int = 5) -> list[SemanticMatch]:
        normalized = self.normalize(header)
        if not normalized:
            return []

        scored = []
        for concept in self.CONCEPTS:
            best_score = 0.0
            best_alias = None
            for alias in concept.aliases:
                a = self.normalize(alias)
                score = self._score_alias(normalized, a)
                score += self._context_bonus(normalized, concept, context)
                score = min(score, 100.0)
                if score > best_score:
                    best_score, best_alias = score, alias

            # Prioridade só desempata; não fabrica confiança.
            scored.append(SemanticMatch(
                concept.key,
                round(best_score, 2),
                self._confidence(best_score),
                best_alias,
            ))

        scored.sort(
            key=lambda m: (
                m.score,
                self._concept_by_key[m.concept].priority if m.concept else 0,
            ),
            reverse=True,
        )
        return scored[:max(1, limit)]

    def classify(self, header: object,
                 context: list[str] | None = None) -> SemanticMatch:
        normalized = self.normalize(header)
        if not normalized:
            return SemanticMatch(None, 0.0, "NONE", None)

        tokens = set(normalized.split())
        if tokens & self._DERIVED_HEADER_TOKENS:
            return SemanticMatch(None, 0.0, "NONE", None)

        # Alias exato é determinístico.
        exact = self._alias_index.get(normalized)
        if exact:
            concept = self._concept_by_key[exact]
            return SemanticMatch(exact, 100.0, "HIGH", concept.aliases[0])

        matches = self.candidates(header, context=context, limit=3)
        if not matches:
            return SemanticMatch(None, 0.0, "NONE", None)

        best = matches[0]
        # Se os dois primeiros conceitos estão muito próximos, não forçamos
        # uma falsa certeza. A estrutura pode pedir confirmação ao usuário.
        if len(matches) > 1 and best.score < self.high_threshold:
            gap = best.score - matches[1].score
            if gap < 3.0 and best.score < self.medium_threshold:
                return SemanticMatch(None, best.score, "NONE", best.matched_alias)

        if best.score < self.low_threshold:
            return SemanticMatch(None, best.score, "NONE", best.matched_alias)

        return best

    def classify_many(self, headers: list[object],
                      context: list[str] | None = None) -> list[SemanticMatch]:
        return [self.classify(h, context=context) for h in headers]

    def explain(self, header: object,
                context: list[str] | None = None) -> dict:
        matches = self.candidates(header, context=context, limit=5)
        best = self.classify(header, context=context)
        return {
            "header": str(header),
            "normalized": self.normalize(header),
            "best_concept": best.concept,
            "score": best.score,
            "confidence": best.confidence,
            "matched_alias": best.matched_alias,
            "alternatives": [
                {
                    "concept": m.concept,
                    "score": m.score,
                    "confidence": m.confidence,
                    "matched_alias": m.matched_alias,
                }
                for m in matches
            ],
        }

    def concepts(self) -> list[dict]:
        return [
            {
                "key": c.key,
                "label": c.label,
                "aliases": list(c.aliases),
                "priority": c.priority,
            }
            for c in self.CONCEPTS
        ]
