"""Testes de marcação da página inicial (web/index.html).

Garantem que os IDs de elementos e as referências de script/estilo dos quais
o app.js depende continuam presentes, evitando quebras silenciosas na UI.
"""

from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"

REQUIRED_IDS = [
    "upload-form",
    "file-input",
    "file-label",
    "sheet-input",
    "process-button",
    "error-message",
    "loading-message",
    "progress-bar",
    "results",
    "result-title",
    "download-link",
    "metrics",
    "charts-panel",
    "charts-grid",
    "chart-card-template",
    "source-analysis",
    "alerts-panel",
    "alerts-toggle",
    "alerts-list",
    "descartes-panel",
    "descartes-head",
    "descartes-body",
    "descartes-count",
    "recommendations-body",
    "insights-list",
    "error-diagnostic",
    "diagnostic-title",
    "diagnostic-message",
    "diagnostic-missing-list",
    "diagnostic-found-list",
    "diagnostic-tips-list",
]


def _read_index() -> str:
    assert INDEX.exists(), f"index.html não encontrado em {INDEX}"
    return INDEX.read_text(encoding="utf-8")


def test_index_existe():
    assert INDEX.exists()


def test_ids_obrigatorios_presentes():
    html = _read_index()
    faltando = [i for i in REQUIRED_IDS if f'id="{i}"' not in html]
    assert not faltando, f"IDs ausentes no index.html: {faltando}"


def test_referencias_de_assets():
    html = _read_index()
    assert '<script src="/app.js' in html, "script app.js não referenciado"
    assert 'href="/styles.css' in html, "stylesheet styles.css não referenciado"


def test_assets_tem_versao_para_cache_busting():
    html = _read_index()
    assert "/app.js?v=" in html, "app.js deve ter query de versão para invalidar cache"
    assert "/styles.css?v=" in html, "styles.css deve ter query de versão para invalidar cache"


def test_estados_iniciais_ocultos():
    html = _read_index()
    assert 'id="results" hidden' in html, "#results deve iniciar oculto"
    assert 'id="alerts-list" class="alerts-list" hidden' in html, "#alerts-list deve iniciar oculto"
    assert 'id="download-link"' in html and 'hidden' in html.split('id="download-link"')[1].split('>')[0], "#download-link deve iniciar oculto"


def test_ids_dos_graficos_no_app_js():
    app = INDEX.parent / "app.js"
    assert app.exists(), f"app.js não encontrado em {app}"
    js = app.read_text(encoding="utf-8")
    for chart_id in ["supplier-value-chart", "supplier-wins-chart", "spread-chart", "delivery-chart", "scenario-chart"]:
        assert f"id: '{chart_id}'" in js, f"gráfico {chart_id} não configurado em app.js"


def test_toggle_de_alertas_controla_atributo_hidden():
    """O botão do olho deve revelar o painel removendo ``hidden``.

    O bloco #alerts-list inicia oculto pelo atributo ``hidden`` e o CSS
    ``[hidden] { display: none !important; }`` vence qualquer classe. Alternar
    apenas a classe ``collapsed`` deixava o painel invisível para sempre; por
    isso o contrato exige que o handler escreva em ``alertsList.hidden``.
    """
    app = INDEX.parent / "app.js"
    js = app.read_text(encoding="utf-8")
    assert "function setAlertsOpen(" in js, "app.js deve ter a função setAlertsOpen"
    assert "alertsList.hidden = !abrir" in js, (
        "o toggle deve controlar alertsList.hidden, não apenas a classe collapsed"
    )
    assert "setAlertsOpen(false)" in js, (
        "showResult deve deixar os alertas fechados via setAlertsOpen(false)"
    )


def test_download_link_revelado_ao_mostrar_resultado():
    app = INDEX.parent / "app.js"
    js = app.read_text(encoding="utf-8")
    assert "downloadLink.hidden = false" in js, "app.js deve revelar o link de download ao exibir o resultado"
def test_diagnostico_estruturado_renderizado_no_app_js():
    app = INDEX.parent / "app.js"
    js = app.read_text(encoding="utf-8")

    # A UI precisa saber ler o payload estruturado que a API devolve em erro.
    assert "function renderDiagnostic(" in js, "app.js deve ter renderDiagnostic"
    assert "detail.message" in js or "detail.mensagem" in js, (
        "app.js deve ler a mensagem do diagnóstico estruturado"
    )
    assert "renderDiagnostic(detail)" in js, (
        "o fluxo de erro deve passar o diagnóstico para a renderização"
    )
    assert "function resetDiagnostic(" in js, "app.js deve limpar o diagnóstico a cada envio"


def test_layout_tem_breakpoints_de_responsividade():
    css = (INDEX.parent / "styles.css").read_text(encoding="utf-8")

    # Camadas distintas para tablet e celular, sem largura mínima fixa nos gráficos.
    assert "@media (max-width: 1024px)" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 520px)" in css
    assert ".chart-svg { min-width: 540px; }" not in css, (
        "os gráficos não devem forçar largura mínima em telas pequenas"
    )


def test_estilos_do_diagnostico_presentes():
    css = (INDEX.parent / "styles.css").read_text(encoding="utf-8")
    for classe in [".diagnostic {", ".diagnostic-head", ".diagnostic-chips", ".diagnostic-tips"]:
        assert classe in css, f"estilo {classe} ausente em styles.css"