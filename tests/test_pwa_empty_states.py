"""T32 — D4 friendly empty states: hand-drawn receipt doodle + history loading shimmer."""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "ocr.db")
    return TestClient(app, raise_server_exceptions=False)


def doodle(html: str) -> str:
    return html.split('id="gecmis-bos"', 1)[1].split("</div>", 1)[0]


# --- empty state ---


def test_empty_state_is_hidden_by_default_with_turkish_copy(client):
    html = client.get("/app/").text
    assert 'id="gecmis-bos" hidden' in html
    assert "Henüz fiş yok" in html
    assert "ilk fişini çek" in html


def test_doodle_is_a_hand_drawn_inline_svg(client):
    html = client.get("/app/").text
    block = doodle(html)
    assert "<svg" in block and "<img" not in block  # inline, no binary asset
    assert "stroke-dasharray" in block  # sketchy dashed strokes read as hand-drawn
    assert "rotate(" in block  # slight tilt, not a sterile straight receipt


def test_doodle_gently_sways_and_respects_reduced_motion(client):
    html = client.get("/app/").text
    assert re.search(r"\.bos-fis svg \{[^}]*animation: salinim", html)
    assert "@keyframes salinim" in html
    reduced = html.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".bos-fis svg" in reduced.split("}", 1)[0]


# --- loading shimmer ---


def test_shimmer_rows_exist_and_start_hidden(client):
    html = client.get("/app/").text
    assert 'id="gecmis-yukleniyor" hidden' in html
    assert html.count('class="iskele-satir"') == 3


def test_shimmer_animates_a_sweeping_highlight(client):
    html = client.get("/app/").text
    assert "@keyframes parilti" in html
    assert re.search(r"\.iskele-mini, \.iskele-cizgi \{[^}]*animation: parilti", html)
    reduced = html.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".iskele-mini" in reduced.split("}", 1)[0]


def test_history_module_drives_the_shimmer(client):
    src = client.get("/app/history.js").text
    assert 'getElementById("gecmis-yukleniyor")' in src
    # shown the moment a first-page load starts, hidden by every redraw
    assert "yukleniyor.hidden = false" in src
    assert "yukleniyor.hidden = !(loading && items.length === 0)" in src


def test_page_defines_every_hook_history_reaches_for(client):
    html = client.get("/app/").text
    src = client.get("/app/history.js").text
    for hook in set(re.findall(r'getElementById\("([^"]+)"\)', src)):
        assert f'id="{hook}"' in html, f"index.html is missing #{hook}"
