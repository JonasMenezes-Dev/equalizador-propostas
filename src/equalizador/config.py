from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineConfig:
    """Regras centrais do motor. Política fica separada da implementação."""

    limite_similaridade: float = 85.0
    limite_similaridade_alerta: float = 65.0
    limite_empate_tecnico: float = 0.50

    # Fórmula oficial do score.
    pesos_score: dict[str, float] = field(default_factory=lambda: {
        "Score Preço": 0.30,
        "Score Similaridade": 0.20,
        "Score Atributos": 0.20,
        "Score Comercial": 0.30,
    })

    def validar(self) -> None:
        if not 0 <= self.limite_similaridade_alerta <= self.limite_similaridade <= 100:
            raise ValueError("Limites de similaridade inválidos.")

        if self.limite_empate_tecnico < 0:
            raise ValueError("Limite de empate técnico não pode ser negativo.")

        if set(self.pesos_score) != {
            "Score Preço",
            "Score Similaridade",
            "Score Atributos",
            "Score Comercial",
        }:
            raise ValueError("Pesos do score não possuem os quatro componentes esperados.")

        if any(p < 0 for p in self.pesos_score.values()):
            raise ValueError("Pesos não podem ser negativos.")

        if abs(sum(self.pesos_score.values()) - 1.0) > 1e-9:
            raise ValueError("Os pesos do score devem somar exatamente 1.0.")
