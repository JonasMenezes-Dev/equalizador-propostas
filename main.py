import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Garante a exibição correta de acentos no terminal integrado do Windows.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

from equalizador.config import EngineConfig
from equalizador.demo import criar_cotacao_demo
from equalizador.pipeline import executar_pipeline, executar_pipeline_de_excel


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Equaliza propostas de fornecedores a partir de uma planilha Excel."
    )
    parser.add_argument(
        "arquivo",
        nargs="?",
        type=Path,
        help="Planilha .xlsx tabular com as propostas. Sem arquivo, executa a demonstração.",
    )
    parser.add_argument(
        "--aba",
        help="Nome da aba a importar. Por padrão, a aba é detectada automaticamente.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        help="Caminho do relatório final. O padrão usa a pasta output/.",
    )
    args = parser.parse_args()

    if args.arquivo is not None:
        output = args.saida or Path("output") / f"{args.arquivo.stem}_relatorio.xlsx"
        resultado = executar_pipeline_de_excel(
            args.arquivo,
            aba=args.aba,
            output_path=output,
        )
    else:
        output = args.saida or Path("output") / "COT-ESCALA-001_relatorio.xlsx"
        resultado = executar_pipeline(
            criar_cotacao_demo(),
            EngineConfig(),
            output_path=output,
        )

    base = resultado["base_recomendacao"]
    recomendacoes = resultado["recomendacoes"]

    print("=" * 70)
    print("EQUALIZADOR DE PROPOSTAS — GEP")
    print("=" * 70)
    print(f"Itens: {resultado['indicadores']['Total de Itens']}")
    print(f"Fornecedores: {resultado['indicadores']['Total de Fornecedores']}")
    print(f"Candidatos: {len(base)}")
    print(f"Elegíveis: {int(base['Elegível para Recomendação'].sum())}")
    print(f"Recomendações: {len(recomendacoes)}")
    print(f"Relatório: {resultado['arquivo_relatorio']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
