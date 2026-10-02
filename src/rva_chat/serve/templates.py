"""Server-rendered HTML. One page, two ways to reach it:

- `GET /` — empty shell. JS takes over the form and talks to `/chat` (SSE).
- `POST /chat-plain` — the SAME shell, pre-filled with the submitted question
  and the rendered result, for the no-JS case (docs/PLAN.md §8: "a no-JS
  fallback (plain POST → rendered page) from the start"). One `<form>` with
  `method="POST" action="/chat-plain"` serves both paths — JS intercepts the
  submit when present; the browser's native form POST handles it when absent.

Hand-rolled instead of Jinja2: the page is small and this avoids a templating
dependency for ~80 lines of HTML. Every piece of user- or model-provided text
is run through `html.escape()` before being embedded — the query string and
the LLM's answer are both untrusted input.
"""

from __future__ import annotations

from html import escape

from rva_chat.retrieve.corpus import Chunk

PAGE_CSS = """
:root {
  color-scheme: light dark;
  --bg: #faf9f6; --fg: #1a1a1a; --muted: #5a5a5a;
  --card-bg: #ffffff; --border: #ddd6cc; --accent: #2f6e4f; --accent-fg: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #16181a; --fg: #eceae6; --muted: #a7a39c; --card-bg: #1f2123; --border: #35383a; --accent: #4fae7d; --accent-fg: #0c0f0d; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; padding-bottom: 48px; background: var(--bg); color: var(--fg);
       font: 16px/1.5 system-ui, -apple-system, sans-serif; max-width: 640px; margin-inline: auto; }
h1 { font-size: 1.3rem; margin: 0 0 4px; }
p.sub { color: var(--muted); margin: 0 0 20px; font-size: 0.95rem; }
form { display: flex; flex-direction: column; gap: 10px; margin-bottom: 24px; }
input[type=text] { font-size: 1.05rem; padding: 12px; border: 1px solid var(--border);
       border-radius: 8px; background: var(--card-bg); color: var(--fg); min-height: 44px; }
button { font-size: 1.05rem; padding: 12px; border: none; border-radius: 8px;
       background: var(--accent); color: var(--accent-fg); min-height: 44px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: default; }
label.checkbox { font-size: 0.85rem; color: var(--muted); display: flex; gap: 6px; align-items: center; }
#status { color: var(--muted); font-size: 0.9rem; min-height: 1.2em; }
.answer { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
       padding: 14px; margin-bottom: 16px; }
.answer.dropped { border-color: #b35; }
.card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
       padding: 12px; margin-bottom: 10px; }
.card .name { font-weight: 600; }
.card .meta { color: var(--muted); font-size: 0.85rem; margin-top: 4px; }
.card a { color: var(--accent); word-break: break-all; }
noscript p { color: var(--muted); font-size: 0.85rem; }
"""

PAGE_JS = """
const form = document.getElementById('chat-form');
const input = document.getElementById('q-input');
const noLog = document.getElementById('no-log');
const status = document.getElementById('status');
const cardsEl = document.getElementById('cards');
const answerEl = document.getElementById('answer');
const button = document.getElementById('ask-btn');

let activeStream = null;

function clearResults() {
  cardsEl.innerHTML = '';
  answerEl.innerHTML = '';
  answerEl.className = 'answer';
}

function renderCard(c) {
  const div = document.createElement('div');
  div.className = 'card';
  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = c.name;
  div.appendChild(name);
  if (c.url) {
    const a = document.createElement('a');
    a.href = c.url; a.textContent = c.url; a.rel = 'noopener';
    div.appendChild(a);
  }
  const meta = document.createElement('div');
  meta.className = 'meta';
  const bits = [];
  if (c.topics && c.topics.length) bits.push('topics: ' + c.topics.join(', '));
  if (c.volunteer) bits.push('takes volunteers');
  bits.push('verified ' + c.last_verified);
  meta.textContent = bits.join(' | ');
  div.appendChild(meta);
  if (c.notes_public) {
    const note = document.createElement('div');
    note.textContent = c.notes_public;
    div.appendChild(note);
  }
  cardsEl.appendChild(div);
}

form.addEventListener('submit', (e) => {
  if (typeof EventSource === 'undefined') return; // let the no-JS POST fallback run
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;

  if (activeStream) activeStream.close();
  clearResults();
  button.disabled = true;
  status.textContent = 'Searching...';

  const params = new URLSearchParams({ q });
  if (noLog.checked) params.set('no_log', '1');
  const es = new EventSource('/chat?' + params.toString());
  activeStream = es;

  es.addEventListener('cards', (ev) => {
    const data = JSON.parse(ev.data);
    status.textContent = data.cards.length ? 'Found ' + data.cards.length + ' source(s). Thinking...' : '';
    data.cards.forEach(renderCard);
  });

  es.addEventListener('answer', (ev) => {
    const data = JSON.parse(ev.data);
    if (data.text) {
      answerEl.textContent = data.text;
      if (data.grounded === false) answerEl.className = 'answer dropped';
    } else if (data.reason) {
      answerEl.textContent = data.reason;
      answerEl.className = 'answer dropped';
    }
  });

  es.addEventListener('done', () => {
    status.textContent = '';
    button.disabled = false;
    es.close();
    activeStream = null;
  });

  es.onerror = () => {
    status.textContent = 'Connection lost.';
    button.disabled = false;
    es.close();
    activeStream = null;
  };
});
"""


def render_card_html(chunk: Chunk) -> str:
    bits = []
    if chunk.topics:
        bits.append("topics: " + escape(", ".join(chunk.topics)))
    if chunk.volunteer:
        bits.append("takes volunteers")
    bits.append(f"verified {escape(chunk.last_verified)}")
    note_html = f"<div>{escape(chunk.notes_public)}</div>" if chunk.notes_public else ""
    url_html = (
        f'<a href="{escape(chunk.url)}" rel="noopener">{escape(chunk.url)}</a>' if chunk.url else ""
    )
    return (
        '<div class="card">'
        f'<div class="name">{escape(chunk.name)}</div>'
        f"{url_html}"
        f'<div class="meta">{" | ".join(bits)}</div>'
        f"{note_html}"
        "</div>"
    )


def render_page(
    *,
    initial_query: str = "",
    cards: list[Chunk] | None = None,
    answer_text: str | None = None,
    answer_dropped: bool = False,
) -> str:
    cards_html = "".join(render_card_html(c) for c in (cards or []))
    answer_html = ""
    if answer_text is not None:
        cls = "answer dropped" if answer_dropped else "answer"
        answer_html = f'<div class="{cls}">{escape(answer_text)}</div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RVA Sustainability Chat</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<h1>RVA Sustainability Chat</h1>
<p class="sub">Ask about recycling, disposal, or getting involved in the Richmond, VA area.</p>

<form id="chat-form" method="POST" action="/chat-plain">
  <input type="text" id="q-input" name="q" placeholder="Where do I take old batteries?"
         value="{escape(initial_query)}" required autocomplete="off">
  <label class="checkbox"><input type="checkbox" id="no-log" name="no_log" value="1"> Don't log this question</label>
  <button type="submit" id="ask-btn">Ask</button>
</form>
<div id="status"></div>
<div id="answer">{answer_html}</div>
<div id="cards">{cards_html}</div>

<noscript><p>JavaScript is off — each question reloads the page with its answer below.</p></noscript>
<script>{PAGE_JS}</script>
</body>
</html>"""
