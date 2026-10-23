"""Local browser review for VLM and other unlocated transcriptions."""

from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pymupdf

from datacompiler.model.document import (
    Divergence, OcrCandidate, PageReview, ReviewDecision, ReviewProposal,
)
from datacompiler.review.divergence import decide, refresh_state

logger = logging.getLogger(__name__)


def _source_identity(path):
    source = Path(path).resolve()
    stat = source.stat()
    return {"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _review_to_dict(page):
    return {
        "candidates": [dataclasses.asdict(item) for item in page.ocr.candidates],
        "review": dataclasses.asdict(page.review),
    }


def _restore_review(page, data):
    page.ocr.candidates = [
        OcrCandidate(**item) for item in data.get("candidates", [])
    ]
    raw = data.get("review") or {}
    divergences = []
    for item in raw.get("divergences", []):
        proposals = [ReviewProposal(**p) for p in item.get("proposals", [])]
        raw_decision = item.get("decision")
        decision = ReviewDecision(**raw_decision) if raw_decision else None
        divergences.append(Divergence(
            id=item["id"], kind=item.get("kind", "substitution"),
            ref_start=item.get("ref_start", 0), ref_end=item.get("ref_end", 0),
            context_before=item.get("context_before", ""),
            context_after=item.get("context_after", ""),
            proposals=proposals, decision=decision,
        ))
    page.review = PageReview(
        state=raw.get("state", "in_review"),
        reference_candidate_id=raw.get("reference_candidate_id"),
        divergences=divergences,
        validated_text=raw.get("validated_text"),
        draft_text=raw.get("draft_text"),
    )


def load_review_session(document, path):
    """Restore stored VLM candidates and review decisions, if a session exists."""
    path = Path(path)
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"Unsupported review session version in {path}")
    source = _source_identity(document.metadata.source_pdf)
    stored = data.get("source", {"path": data.get("source_pdf")})
    if stored != source:
        raise ValueError(f"Review session {path} belongs to a different source PDF")
    restored = set()
    from datacompiler.frontend.ocr.vlm import fill_provisional_ocr
    for page in document.pages:
        entry = data.get("pages", {}).get(str(page.number))
        if entry:
            _restore_review(page, entry)
            if page.ocr.candidates or page.review.state == "in_review":
                if page.ocr.candidates:
                    text = page.review.validated_text or page.review.draft_text or page.ocr.candidates[0].text
                    engine = page.ocr.candidates[0].model
                else:
                    text = page.review.draft_text or "\n".join(block.content for block in page.ocr.blocks)
                    engine = page.ocr.engine or "manual-review"
                fill_provisional_ocr(
                    page, text, engine=engine,
                    extra_metadata={"review_state": page.review.state, "provisional": page.review.state == "in_review"},
                )
                restored.add(page.number)
    return restored


def save_review_session(document, path):
    path = Path(path)
    payload = {
        "schema_version": 1,
        "source": _source_identity(document.metadata.source_pdf),
        "pages": {
            str(page.number): _review_to_dict(page)
            for page in document.pages if page.ocr.candidates or page.review.state == "in_review"
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


_HTML = r'''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revue de transcription</title><style>
*{box-sizing:border-box}body{margin:0;font:15px system-ui,sans-serif;color:#20242a;background:#f3f4f6}header{padding:12px 20px;background:#182331;color:white;display:flex;gap:18px;align-items:center}header h1{font-size:17px;margin:0}select,button{font:inherit;padding:7px 10px;border:1px solid #c4cbd3;border-radius:6px;background:white;cursor:pointer}main{height:calc(100vh - 105px);display:grid;grid-template-columns:minmax(320px,1fr) minmax(400px,1fr);gap:14px;padding:14px}.scan,.work{background:white;border:1px solid #d9dee5;border-radius:8px;overflow:auto}.scan{display:flex;align-items:flex-start;justify-content:center;background:#dfe3e8}.scan img{max-width:100%;height:auto}.work{padding:16px;display:flex;flex-direction:column;gap:12px}.work textarea{width:100%;flex:1;min-height:200px;resize:none;border:1px solid #b9c2cc;border-radius:6px;padding:12px;font:16px/1.55 ui-monospace,monospace}.candidates,.diffs{border-top:1px solid #e3e7eb;padding-top:10px}.candidates button{margin:4px}.diff{padding:9px;background:#f6f7f8;margin:6px 0;border-radius:6px}.diff button{margin:4px}.footer{height:48px;padding:5px 18px;display:flex;align-items:center;justify-content:space-between}.status{color:#576271}.primary{background:#1769aa;color:white;border-color:#1769aa}@media(max-width:850px){main{height:auto;grid-template-columns:1fr}.scan{max-height:50vh}.work{height:65vh}}
</style><header><h1>Revue de transcription</h1><label>Page <select id="pages"></select></label><span id="models"></span></header><main><section class="scan"><img id="scan" alt="Scan original"></section><section class="work"><div id="title"></div><div class="candidates" id="candidates"></div><div class="diffs" id="diffs"></div><textarea id="text" aria-label="Transcription à valider"></textarea></section></main><footer class="footer"><span class="status" id="status"></span><span><button id="save">Enregistrer</button> <button id="quit">Enregistrer et quitter</button> <button class="primary" id="finish">Valider la transcription</button></span></footer>
<script>
const token=location.pathname.split('/').filter(Boolean).pop();let data,pageno,decisions={};const $=id=>document.getElementById(id);
async function init(){data=await(await fetch('/'+token+'/api')).json();const pages=Object.keys(data.pages);$('pages').innerHTML=pages.map(n=>`<option value="${n}"> ${n}</option>`).join('');$('pages').onchange=()=>show($('pages').value);show(pages[0]);}
function show(n){pageno=n;const p=data.pages[n];decisions={};$('scan').src='/'+token+'/scan/'+n+'.png';$('title').textContent=`Page ${n} · ${p.review.state==='validated'?'validée':'à vérifier'}`;$('models').textContent=p.candidates.map(c=>c.model).join(' · ');$('text').value=p.review.draft_text??p.review.validated_text??p.candidates[0]?.text??'';$('candidates').innerHTML='<b>Lectures des modèles :</b> '+p.candidates.map((c,i)=>`<button data-cand="${i}">${String.fromCharCode(65+i)} · ${esc(c.model)}</button>`).join('');document.querySelectorAll('[data-cand]').forEach(b=>b.onclick=()=>{$('text').value=p.candidates[+b.dataset.cand].text});$('diffs').innerHTML=p.review.divergences.length?'<b>Passages en désaccord</b>'+p.review.divergences.map((d,i)=>`<div class="diff"><small>${esc(d.context_before)} <b>→</b> ${esc(d.context_after)}</small><br>${d.proposals.map((q,j)=>`<button data-d="${i}" data-p="${j}">${String.fromCharCode(65+j)} : ${esc(q.text||'∅')}</button>`).join('')}<input data-custom="${i}" placeholder="Correction personnelle"><button data-own="${i}">Saisir</button><button data-pending="${i}">En suspens</button></div>`).join(''):'';document.querySelectorAll('[data-p]').forEach(b=>b.onclick=()=>{decisions[p.review.divergences[b.dataset.d].id]={choice:p.review.divergences[b.dataset.d].proposals[b.dataset.p].candidate_ids[0]};save(false)});document.querySelectorAll('[data-own]').forEach(b=>b.onclick=()=>{decisions[p.review.divergences[b.dataset.own].id]={choice:'custom',text:document.querySelector(`[data-custom="${b.dataset.own}"]`).value};save(false)});document.querySelectorAll('[data-pending]').forEach(b=>b.onclick=()=>{decisions[p.review.divergences[b.dataset.pending].id]={choice:'pending'};save(false)});$('status').textContent=`${p.candidates.length} candidat(s) · ${p.review.divergences.length} désaccord(s)`;}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function save(finalize){const r=await fetch('/'+token+'/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page:pageno,text:$('text').value,decisions,finalize})});const result=await r.json();$('status').textContent=result.message;if(result.pages){data.pages=result.pages;show(pageno)}if(result.complete){$('status').textContent='Toutes les pages sont validées.';await fetch('/'+token+'/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quit:true})})}}
$('save').onclick=()=>save(false);$('finish').onclick=()=>save(true);$('quit').onclick=async()=>{await save(false);await fetch('/'+token+'/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quit:true})});};init();
</script></html>'''


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def open_review(document, pdf_path, session_path):
    """Open a localhost transcription review; return True only when all pages validate."""
    review_pages = [p for p in document.pages if p.ocr.candidates or p.review.state == "in_review"]
    if not review_pages:
        return False
    token = secrets.token_urlsafe(20)
    token_path = "/" + token

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logger.debug("review server: " + fmt, *args)

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, bytes):
                payload = body
            elif isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == token_path:
                return self._send(200, _HTML, "text/html; charset=utf-8")
            if path == token_path + "/api":
                return self._send(200, json.dumps({
                    "pages": {str(p.number): {
                        **_review_to_dict(p),
                        "review": dataclasses.asdict(p.review),
                    } for p in review_pages}
                }, ensure_ascii=False))
            if path.startswith(token_path + "/scan/") and path.endswith(".png"):
                try:
                    page_number = int(path.rsplit("/", 1)[1][:-4])
                    with pymupdf.open(pdf_path) as source:
                        pix = source[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                        return self._send(200, pix.tobytes("png"), "image/png")
                except (ValueError, IndexError, RuntimeError):
                    return self._send(404, {"error": "page not found"})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != token_path + "/api":
                return self._send(404, {"error": "not found"})
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if payload.get("quit"):
                    self._send(200, {"message": "Session enregistrée."})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                page = next(p for p in review_pages if p.number == int(payload["page"]))
                for divergence in page.review.divergences:
                    action = payload.get("decisions", {}).get(divergence.id)
                    if action:
                        decide(divergence, action["choice"], action.get("text"))
                text = str(payload.get("text", ""))
                previous_draft = page.review.draft_text
                if payload.get("finalize"):
                    if len(page.ocr.candidates) > 1 and text == previous_draft:
                        refresh_state(page.review, page.ocr.candidates)
                        if page.review.validated_text is not None:
                            text = page.review.validated_text
                    page.review.divergences = []
                    page.review.validated_text = text
                    page.review.draft_text = text
                    page.review.state = "validated"
                else:
                    page.review.draft_text = text
                    if len(page.ocr.candidates) > 1:
                        refresh_state(page.review, page.ocr.candidates)
                        if page.review.validated_text is not None and text == previous_draft:
                            page.review.draft_text = page.review.validated_text
                save_review_session(document, session_path)
                complete = all(p.review.state == "validated" for p in review_pages)
                return self._send(200, json.dumps({
                    "message": "Page validée." if payload.get("finalize") else "Session enregistrée.",
                    "complete": complete,
                    "pages": {str(p.number): _review_to_dict(p) for p in review_pages},
                }, ensure_ascii=False))
            except Exception as exc:
                return self._send(400, {"error": str(exc)})

    server = _Server(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}{token_path}"
    thread = threading.Thread(target=server.serve_forever, name="datacompiler-review", daemon=True)
    thread.start()
    webbrowser.open(url)
    logger.info("Review interface opened at %s", url)
    try:
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return all(p.review.state == "validated" for p in review_pages)
