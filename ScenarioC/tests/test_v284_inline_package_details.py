from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'DemoWeb/wwwroot/unified.js').read_text(encoding='utf-8')
HTML = (ROOT / 'DemoWeb/wwwroot/index.html').read_text(encoding='utf-8')


def test_details_use_expanded_inline_table_row():
    assert 'detailRow.className=\'package-detail-row\'' in JS
    assert 'cell.colSpan=5' in JS
    assert 'expandedPackage===p.name?null:p.name' in JS
    assert 'createPackageDetails(p)' in JS
    assert "$('detail')" not in JS


def test_analyze_skipped_message_is_displayed():
    assert 'No new analysis was run.' in JS
    assert 'already-analyzed or completed packages are skipped' in JS


def test_no_duplicate_details_area_below_table():
    assert 'id="detail"' not in HTML
