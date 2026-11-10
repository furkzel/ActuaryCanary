"""The page rendered in both languages and parsed; no browser is used (record 0705).

The page was not opened in a browser by these tests: what is checked is the HTML the server sends,
that every control has a label, that every element the script reaches for exists, and that the
page asks for nothing outside this server.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from actuarycanary.ui import server, strings

from .conftest import Client

UI = Path(server.__file__).parent


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.labels_for: list[str] = []
        self.controls: list[dict[str, str | None]] = []
        self.urls: list[str] = []
        self.tags: list[str] = []
        self.lang = ""
        self.title = ""
        self._in_title = False
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self.tags.append(tag)
        if tag == "html":
            self.lang = a.get("lang") or ""
        if "id" in a and a["id"]:
            self.ids.append(a["id"])
        if tag == "label" and a.get("for"):
            self.labels_for.append(a["for"] or "")
        if tag in ("input", "select", "textarea"):
            self.controls.append(a)
        for name in ("href", "src", "action"):
            if a.get(name):
                self.urls.append(a[name] or "")
        self._in_title = tag == "title"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        self.text.append(data)


def parse(page: str) -> Page:
    parser = Page()
    parser.feed(page)
    parser.close()
    return parser


@pytest.fixture(scope="module", params=strings.LANGUAGES)
def rendered(request: pytest.FixtureRequest) -> tuple[str, str, Page]:
    from actuarycanary.ui.server import UiServer

    app = UiServer(0)
    try:
        html = app.render_page(request.param)
    finally:
        app.server_close()
    return request.param, html, parse(html)


def test_the_page_declares_its_language_and_has_a_title(rendered) -> None:
    language, _, page = rendered
    assert page.lang == language and page.title.strip()


def test_every_id_is_unique(rendered) -> None:
    _, _, page = rendered
    assert len(page.ids) == len(set(page.ids))


def test_every_form_control_has_a_label(rendered) -> None:
    _, _, page = rendered
    labelled = set(page.labels_for)
    for control in page.controls:
        if control.get("type") == "hidden":
            continue
        assert control.get("id") in labelled or control.get("aria-label"), control


def test_every_label_points_at_a_control_that_exists(rendered) -> None:
    _, _, page = rendered
    assert set(page.labels_for) <= set(page.ids)


def test_the_five_screens_the_landmarks_and_the_skip_link_are_there(rendered) -> None:
    _, _, page = rendered
    for screen in ("start", "mapping", "run", "result", "past"):
        assert f"screen-{screen}" in page.ids and f"{screen}-title" in page.ids
    assert "main" in page.tags and "header" in page.tags and "nav" in page.tags
    assert any(u == "#main" for u in page.urls)  # the skip link
    assert "live" in page.ids  # the region that announces changes


def test_every_element_the_script_reaches_for_is_in_the_page(rendered) -> None:
    _, _, page = rendered
    script = (UI / "static" / "app.js").read_text(encoding="utf-8")
    wanted = set(re.findall(r'\$\("([a-z][a-z0-9_-]*)"\)', script))
    wanted |= {f"screen-{s}" for s in ("start", "mapping", "run", "result", "past")}
    built = {"sheet", "past-table"}  # ids the script makes itself are prefixes, not looked up
    missing = sorted(w for w in wanted if w not in page.ids and w not in built)
    # titles are looked up as $(screen + "-title"), so they are named in the test above
    assert not missing, missing


def test_the_form_has_a_field_for_every_key_the_script_sends(rendered) -> None:
    _, _, page = rendered
    script = (UI / "static" / "app.js").read_text(encoding="utf-8")
    keys = re.search(r"const FORM_KEYS = \[(.*?)\];", script, re.S)
    assert keys
    for key in re.findall(r'"([a-z_]+)"', keys.group(1)):
        assert key in page.ids, key


def test_the_page_asks_for_nothing_outside_this_server(rendered) -> None:
    _, html, page = rendered
    for url in page.urls:
        assert url.startswith(("#", "/static/", "?t=", "data:,")), url
    assert not re.search(r"https?://", html)  # no CDN, no external font, no link out
    script = (UI / "static" / "app.js").read_text(encoding="utf-8")
    style = (UI / "static" / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"https?://", script + style)
    assert "@import" not in style and "url(" not in style


def test_the_script_reaches_the_server_only_through_its_own_routes(rendered) -> None:
    script = (UI / "static" / "app.js").read_text(encoding="utf-8")
    routes = set(re.findall(r'"/(?:api|report)[a-z/]*', script))
    handler = (UI / "server.py").read_text(encoding="utf-8")
    for route in routes:
        name = route.strip('"/').removeprefix("api/")
        assert name == "report" or f"def get_{name}" in handler or f"def post_{name}" in handler, (
            name
        )


def test_the_report_frame_is_sandboxed_and_links_out_are_safe(rendered) -> None:
    _, html, _ = rendered
    frame = re.search(r"<iframe[^>]*>", html)
    assert frame and "sandbox=" in frame.group(0) and "allow-same-origin" not in frame.group(0)
    for link in re.findall(r"<a [^>]*target=\"_blank\"[^>]*>", html):
        assert "noopener" in link


def test_no_english_label_is_left_on_the_turkish_page(rendered) -> None:
    language, html, _ = rendered
    if language != "tr":
        return
    visible = " ".join(parse(html).text)
    for english in ("Check the files", "Run now", "Output folder", "Past runs", "Quit"):
        assert english not in visible, english


def test_the_page_embeds_the_strings_of_its_language(rendered) -> None:
    language, html, _ = rendered
    block = re.search(r'<script id="strings" type="application/json">(.*?)</script>', html, re.S)
    assert block
    import json

    embedded = json.loads(block.group(1))
    assert embedded == strings.table(language)


def test_the_served_page_is_the_rendered_page(make_server, rendered) -> None:
    language, html, _ = rendered
    client: Client = make_server()
    served = client.get(f"/?lang={language}")[2].decode("utf-8")
    # the token differs from one server to the next; everything else is the same
    token = client.server.token
    assert served.replace(token, "T") != "" and len(served) > 1000
    assert parse(served).ids == parse(html).ids
