# 0700 — The browser interface is a standard-library server with a token on every request

## Context
Item UI1 asks for `canary ui`: a local browser interface for a person who has never used a terminal. The toolchain is fixed (0002, 0090): no web framework, no front-end build step, no CDN, nothing that is not in the single executable. The page must work offline.

## Decision
- `http.server.ThreadingHTTPServer` from the standard library, bound to `127.0.0.1` only, on a free port chosen by the system (`--port 0`, the default). `jinja2` renders one page, `index.html.j2`; two static files (`app.css`, `app.js`) are written in the repository; no library, no font, no image, no external address.
- A random token (`secrets.token_urlsafe`) is made at every start and is in the address that is printed and opened. Every request, static files and the report included, must carry it in the query (`t`) or in the header `X-Canary-Token`; it is compared in constant time. A request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` is refused (a page of another site cannot talk to the server through a name that points here). Refusals are `403 Forbidden` with no detail.
- Routes: `GET /` (the page, `?lang=en|tr`), `GET /static/app.css|app.js` (only those two names), `GET /report?out=&run=` (the `report.html` of a finished run folder), and a JSON interface under `/api/` whose handlers are the methods `get_<name>` and `post_<name>` of the handler class. A run id is checked against `^[0-9a-f]{16}$` before it is joined to a path, so a request cannot leave the output folder.
- Replies carry `Cache-Control: no-store`, `Referrer-Policy: no-referrer` and `X-Content-Type-Options: nosniff`; the server logs nothing and sends nothing anywhere (no telemetry). The report is shown in an `iframe` with `sandbox="allow-scripts allow-popups allow-downloads"` (no `allow-same-origin`), or opened in a new tab with `rel="noopener"`.
- `canary ui` is registered from `ui/command.py` into the command line by two lines in `cli/__init__.py` (the import and `app.command("ui")(ui_command)`). Options: `--out`, `--profiles` (the defaults of the page), `--open/--no-open` (default open), `--port`, `--lang`. It prints the address; Ctrl+C or the Quit button of the page stops it (a run that is going needs a second confirmation).

## Consequences
- The page cannot be opened by someone who does not have the address of this start; the address is private to the person's computer, but anyone with access to the same account and process list can read it. Not a defence against a hostile local user.
- A second person on the same machine can reach the port but not the token. The port is open to connections from this machine only.
- Opening `canary ui` in two browsers at once works; they share the one run that may go at a time (0703).
- The page was opened in a real browser by hand during the item (Microsoft Edge, headless, driven through its debugging protocol from outside the repository); the repository tests do not open a browser (0705).
