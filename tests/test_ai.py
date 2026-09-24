from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import httpx
import pytest

from conftest import make_client
from genome_literature import assistant, config, fulltext, llm, notes, retrieval, web_app
from genome_literature.records import new_record
from genome_literature.storage import save_papers

JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><abstract><p>Abstract.</p></abstract></article-meta></front>
<body>
<sec><title>Introduction</title><p>Chromatin folds into TADs <xref ref-type="bibr">1</xref> formed by loop extrusion. %s</p></sec>
<sec><title>Results</title><p>Overview.</p>
  <sec><title>Model accuracy</title><p>Pearson R = 0.61 <inline-formula><tex-math>r^2</tex-math></inline-formula> on held-out data.</p>
  <fig><label>Fig. 1</label><caption><title>Model.</title><p>Architecture.</p></caption></fig></sec>
  <table-wrap><label>Table 1</label><caption><p>Benchmark</p></caption><table><tr><th>Model</th><th>R</th></tr><tr><td>Akita</td><td>0.61</td></tr></table></table-wrap>
</sec>
<sec><title>Methods</title><p>Trained with Adam. %s</p></sec>
<sec><title>Acknowledgements</title><p>Thanks to everyone.</p></sec>
</body><back><ref-list><ref>Reference text</ref></ref-list></back></article>""" % ("x " * 900, "y " * 400)

ARXIV = """<html><body><nav>menu</nav><article class="ltx_document"><h1 class="ltx_title">Paper</h1>
<div class="ltx_abstract"><p>abstract text</p></div>
<section class="ltx_section"><h2 class="ltx_title"><span class="ltx_tag">1 </span>Introduction</h2>
<div class="ltx_para"><p class="ltx_p">Hi-C maps <math alttext="\\alpha"><mi>a</mi></math> are sparse. %s</p></div>
<section class="ltx_subsection"><h3 class="ltx_title">1.1 Background</h3><p class="ltx_p">More context here for the model.</p></section></section>
<section class="ltx_section"><h2 class="ltx_title">2 Results</h2><p class="ltx_p">We obtain 0.9 accuracy on all held-out chromosomes. %s</p>
<figure class="ltx_figure"><figcaption>Figure 1: Overview.</figcaption></figure></section>
<section class="ltx_bibliography"><h2>References</h2><p>[1] ref</p></section></article></body></html>""" % ("z " * 500, "w " * 400)


def _papers():
    return [
        new_record("pubmed", title="Predicting 3D genome folding from DNA sequence with Akita", doi="10.1/akita",
                   pmcid="PMC123", abstract="A convolutional neural network predicts Hi-C contact maps from DNA sequence.",
                   authors=["Fudenberg G", "Kelley DR", "Pollard KS"], journal="Nature Methods", date="2020-10-12"),
        new_record("arxiv", title="Transformer model for single-cell Hi-C imputation", arxiv_id="2501.00001",
                   abstract="We impute sparse single-cell Hi-C contact matrices with a transformer.", authors=["Roe R"],
                   journal="arXiv (preprint)", date="2025-01-02"),
        new_record("pubmed", title="Cohesin loop extrusion forms TADs", doi="10.1/tad",
                   abstract="Loop extrusion by cohesin and CTCF boundaries forms topologically associating domains.",
                   authors=["Doe J"], journal="Cell", date="2019-05-01"),
    ]


def _sse(*chunks, reasoning=(), finish="stop"):
    lines = [json.dumps({"choices": [{"delta": {"reasoning_content": r}}]}) for r in reasoning]
    lines += [json.dumps({"choices": [{"delta": {"content": c}}]}, ensure_ascii=False) for c in chunks]
    lines.append(json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}))
    body = "".join(f"data: {line}\n\n" for line in lines) + ": keep-alive\n\ndata: [DONE]\n\n"
    return httpx.Response(200, content=body.encode("utf-8"), headers={"Content-Type": "text/event-stream"})


class FakeAPI:
    def __init__(self, answer="结论见 [1]，另见 [2] 与 [9]。", notes_text=None, fulltext_status=404):
        self.answer = answer
        self.notes_text = notes_text
        self.fulltext_status = fulltext_status
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "europepmc" in url:
            return httpx.Response(self.fulltext_status, text=JATS if self.fulltext_status == 200 else "")
        if "arxiv.org" in url:
            return httpx.Response(self.fulltext_status, text=ARXIV if self.fulltext_status == 200 else "")
        body = json.loads(request.content)
        self.calls.append(body)
        if body.get("stream"):
            return _sse(*[self.answer[i:i + 7] for i in range(0, len(self.answer), 7)],
                        reasoning=("先分析",) if "reasoner" in body["model"] else ())
        if body.get("response_format"):
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"keywords": ["loop extrusion", "cohesin", "TAD"]}'}}]})
        content = self.notes_text or "\n".join(f"[{n}] 研究问题：问题{n}；方法：方法{n}" for n in range(1, 60))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def ai(tmp_project, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-test-000000000000abcd")
    monkeypatch.setattr(config, "LLM_API_BASE", "https://llm.example.org")
    monkeypatch.setattr(config, "LLM_MODEL", "deepseek-chat")
    monkeypatch.setattr(config, "LLM_REASONING_MODEL", "deepseek-reasoner")
    monkeypatch.setattr(llm, "_json_mode_supported", {})
    return tmp_project


def test_stream_parsing_and_errors(ai, monkeypatch):
    api = FakeAPI(answer="你好，世界")
    out = list(llm.stream([{"role": "user", "content": "hi"}], model="deepseek-reasoner", client=make_client(api)))
    assert ("reasoning", "先分析") in out and out[-1] == ("finish", "stop")
    assert "".join(t for k, t in out if k == "content") == "你好，世界"
    body = api.calls[0]
    assert body["stream"] is True and body["max_tokens"] == config.LLM_REASONING_MAX_TOKENS and "temperature" not in body

    denied = make_client(lambda r: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(llm.LLMError, match="认证失败"):
        list(llm.stream([{"role": "user", "content": "hi"}], client=denied))
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    with pytest.raises(llm.LLMError, match="未配置"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_settings_saved_to_env_file_and_masked(ai, monkeypatch):
    for name in config.LLM_SETTING_KEYS + ("DEEPSEEK_API_KEY", "TRANSLATE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    result = llm.save_settings({"LLM_API_KEY": "sk-abcdefghijklmnop1234", "LLM_API_BASE": "https://api.deepseek.com",
                                "LLM_MODEL": "deepseek-chat"})
    text = config.ENV_FILE.read_text(encoding="utf-8")
    assert "LLM_API_KEY=sk-abcdefghijklmnop1234" in text and "LLM_MODEL=deepseek-chat" in text
    assert result["configured"] and result["key_hint"] == "sk-…1234" and "abcdefgh" not in json.dumps(result)
    assert config.LLM_API_KEY == "sk-abcdefghijklmnop1234"


def test_legacy_and_deepseek_key_aliases(monkeypatch):
    for name in config.LLM_SETTING_KEYS + ("DEEPSEEK_API_KEY", "TRANSLATE_API_KEY", "TRANSLATE_API_BASE", "TRANSLATE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    config.reload_llm_settings()
    try:
        assert config.LLM_API_KEY == "sk-deepseek" and config.LLM_API_BASE == config.DEFAULT_LLM_BASE
    finally:
        monkeypatch.delenv("DEEPSEEK_API_KEY")
        config.reload_llm_settings()


def test_jats_and_arxiv_parsing():
    sections = fulltext.parse_jats(JATS)
    titles = [s["title"] for s in sections]
    assert titles == ["Introduction", "Results", "Methods", "Figure legends", "Tables"]
    results = sections[1]["text"]
    assert "【Model accuracy】" in results and "$r^2$" in results and "0.61" in results
    assert "Fig. 1 Model. Architecture." in sections[3]["text"]
    assert "Akita | 0.61" in sections[4]["text"]
    assert not any("Thanks" in s["text"] or "Reference text" in s["text"] for s in sections)

    arxiv = fulltext.parse_arxiv_html(ARXIV)
    assert [s["title"] for s in arxiv] == ["Introduction", "Results", "Figure and table captions"]
    assert "$\\alpha$" in arxiv[0]["text"] and "【Background】" in arxiv[0]["text"]
    assert "abstract text" not in json.dumps(arxiv) and "[1] ref" not in json.dumps(arxiv)


def test_fulltext_budget_prefers_results_over_methods():
    sections = [{"title": "Results", "text": "r. " * 4000}, {"title": "Methods", "text": "m. " * 4000},
                {"title": "Introduction", "text": "i. " * 300}]
    trimmed = fulltext.budget_sections(sections, 9000)
    lengths = {s["title"]: len(s["text"]) for s in trimmed}
    assert sum(lengths.values()) <= 9200
    assert lengths["Results"] > lengths["Methods"] and lengths["Introduction"] == 900


def test_fulltext_fetch_and_cache(ai):
    paper = _papers()[0]
    api = FakeAPI(fulltext_status=200)
    doc = fulltext.get_fulltext(paper, client=make_client(api))
    assert doc["source"] == "Europe PMC" and doc["chars"] > 1500
    offline = make_client(lambda r: httpx.Response(500))
    assert fulltext.get_fulltext(paper, client=offline)["source"] == "Europe PMC"

    arxiv = _papers()[1]
    assert fulltext.get_fulltext(arxiv, client=make_client(FakeAPI(fulltext_status=200)))["source"] == "arXiv"
    missing = {**_papers()[2], "pmcid": "PMC999"}
    assert fulltext.get_fulltext(missing, client=make_client(FakeAPI(fulltext_status=404))) is None
    assert fulltext.get_fulltext(missing, client=make_client(FakeAPI(fulltext_status=200))) is None


def test_bm25_retrieval_ranks_relevant_papers_first():
    papers = _papers()
    assert retrieval.search(papers, "loop extrusion cohesin", k=3)[0]["doi"] == "10.1/tad"
    assert retrieval.search(papers, ["single-cell Hi-C imputation"], k=1)[0]["arxiv_id"] == "2501.00001"
    assert retrieval.search(papers, "the of and", k=3) == []
    assert "hic" in retrieval.tokenize("Hi-C maps") and "map" in retrieval.tokenize("Hi-C maps")
    allowed = {papers[0]["id"]}
    assert all(p["id"] in allowed for p in retrieval.search(papers, "Hi-C", k=3, allowed=allowed))


def test_citation_extraction_and_verification():
    assert assistant.extract_citations("见 [1]、[2, 3] 与 [4-6]，以及 [2]") == [1, 2, 3, 4, 5, 6]
    refs, invalid = assistant.verify_citations("A [1] B [3] C [7]", _papers())
    assert [r["n"] for r in refs] == [1, 3] and invalid == [7]
    assert refs[0]["title"].startswith("Predicting 3D genome") and refs[0]["doi"] == "10.1/akita"


def test_interpret_uses_fulltext_and_saves_note(ai):
    api = FakeAPI(answer="## 一句话总结\nAkita 从序列预测接触图 [1]。", fulltext_status=200)
    events = list(assistant.run_task("interpret", _papers()[:1], client=make_client(api)))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "delta" in kinds
    basis = next(e["basis"] for e in events if e["type"] == "meta" and "basis" in e)
    assert basis.startswith("全文 1 篇（Europe PMC）")
    prompt = api.calls[-1]["messages"][1]["content"]
    assert "请对文献 [1] 做深度解读" in prompt and "全文节选（来源：Europe PMC）" in prompt and "Pearson R = 0.61" in prompt
    assert api.calls[-1]["messages"][0]["content"].startswith("你是一位资深的三维基因组学")
    done = events[-1]
    assert [r["n"] for r in done["references"]] == [1] and done["warnings"] == []
    note = done["note"]
    saved = notes.get_note(note["id"])
    assert saved and "## 参考文献" in saved[1] and "https://doi.org/10.1/akita" in saved[1]
    assert notes.latest_interpretation(_papers()[0]["id"])["id"] == note["id"]
    assert notes.note_body(saved[1]).startswith("## 一句话总结")


def test_abstract_only_interpretation_is_declared(ai):
    api = FakeAPI(answer="本解读仅基于摘要。[1]")
    list(assistant.run_task("interpret", _papers()[2:3], client=make_client(api)))
    assert "本解读仅基于摘要" in api.calls[-1]["messages"][1]["content"]


def test_synthesis_flags_invalid_citations(ai):
    api = FakeAPI(answer="综述正文 [1][2] 与 [9]。")
    events = list(assistant.run_task("review", _papers(), question="环挤出", client=make_client(api)))
    done = events[-1]
    assert [r["n"] for r in done["references"]] == [1, 2]
    assert any("[9]" in w for w in done["warnings"])
    prompt = api.calls[-1]["messages"][1]["content"]
    assert "撰写一篇中文学术综述，重点围绕：环挤出" in prompt and "[3] Cohesin loop extrusion forms TADs" in prompt


def test_large_sets_are_condensed_before_synthesis(ai, monkeypatch):
    monkeypatch.setattr(config, "AI_CONTEXT_CHARS", 600)
    monkeypatch.setattr(config, "AI_BATCH_CHARS", 700)
    papers = [new_record("pubmed", title=f"Hi-C study number {i}", doi=f"10.9/{i}", abstract="Hi-C analysis. " * 20,
                         date="2024-01-01") for i in range(1, 9)]
    api = FakeAPI(answer="总结 [1][8]。")
    events = list(assistant.run_task("summary", papers, use_fulltext=False, client=make_client(api)))
    statuses = [e["message"] for e in events if e["type"] == "status"]
    assert any("分" in s and "批" in s for s in statuses)
    extract_calls = [c for c in api.calls if not c.get("stream")]
    assert len(extract_calls) >= 2
    final = api.calls[-1]["messages"][1]["content"]
    assert "要点：研究问题：问题8" in final and "先逐篇提炼要点再综合" in final


def test_task_errors_are_reported(ai, monkeypatch):
    events = list(assistant.run_task("summary", [], client=make_client(FakeAPI())))
    assert events[-1]["type"] == "error"
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    events = list(assistant.run_task("summary", _papers(), client=make_client(FakeAPI())))
    assert events == [{"type": "error", "message": events[0]["message"]}] and "未配置" in events[0]["message"]
    failing = make_client(lambda r: httpx.Response(402, json={}))
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-x")
    events = list(assistant.run_task("summary", _papers(), use_fulltext=False, client=failing))
    assert events[-1]["type"] == "error" and "余额不足" in events[-1]["message"]


def test_library_chat_retrieves_and_cites(ai):
    api = FakeAPI(answer="环挤出由黏连蛋白驱动 [1]。")
    library = _papers()
    events = list(assistant.chat([{"role": "user", "content": "环挤出如何形成拓扑关联结构域？"}], [], scope="library",
                                 library=library, client=make_client(api)))
    meta = next(e for e in events if e["type"] == "meta" and "context_ids" in e)
    assert meta["context_ids"][0] == library[2]["id"]
    system = api.calls[-1]["messages"][0]["content"]
    assert "[1] Cohesin loop extrusion forms TADs" in system and "本地文献库检索" in system
    assert events[-1]["type"] == "done" and events[-1]["references"][0]["id"] == library[2]["id"]
    assert "loop extrusion" in assistant.glossary_terms("环挤出与黏连蛋白")


def test_chat_keeps_context_numbering_and_history(ai):
    api = FakeAPI(answer="继续说明 [2]。")
    library = _papers()
    history = [{"role": "user", "content": "第一问"}, {"role": "assistant", "content": "回答 [1]"},
               {"role": "user", "content": "第二问"}]
    events = list(assistant.chat(history, library[:2], scope="selection", library=library, client=make_client(api)))
    sent = api.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert "[2] Transformer model for single-cell Hi-C imputation" in sent[0]["content"]
    assert events[-1]["references"][0]["n"] == 2
    note = assistant.save_conversation("AI 讨论", history + [{"role": "assistant", "content": "继续说明 [2]。"}], library[:2])
    assert note["kind"] == "chat" and [r["n"] for r in note["references"]] == [1, 2]


@pytest.fixture
def server(ai, monkeypatch):
    save_papers(_papers())
    web_app._cache.update(mtime=None, papers=[])
    api = FakeAPI(answer="解读内容 [1]。")
    monkeypatch.setattr(llm, "get_client", lambda: make_client(api))
    monkeypatch.setattr(fulltext, "get_client", lambda: make_client(api))
    srv = web_app.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", api
    srv.shutdown()
    srv.server_close()


def _post(url, payload, raw=False):
    req = urllib.request.Request(url, method="POST", data=json.dumps(payload).encode(),
                                 headers={"X-Requested-With": "3DGenomeHub", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read().decode("utf-8")
        return (r.headers.get("Content-Type"), data) if raw else json.loads(data)


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def test_web_ai_endpoints(server):
    base, api = server
    paper_id = _papers()[0]["id"]
    settings = _get(base + "/api/ai/settings")
    assert settings["configured"] and settings["key_hint"] == "sk-…abcd" and "0000abcd" not in json.dumps(settings)

    ctype, body = _post(base + "/api/ai/run", {"task": "interpret", "ids": [paper_id]}, raw=True)
    assert ctype.startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: ")]
    assert events[-1]["type"] == "done" and events[-1]["note"]["kind"] == "interpret"
    note_id = events[-1]["note"]["id"]

    saved = _get(base + "/api/ai/interpretation?id=" + urllib.request.quote(paper_id, safe=""))
    assert saved["note"]["id"] == note_id and saved["body"] == "解读内容 [1]。"
    assert [n["id"] for n in _get(base + "/api/ai/notes")["notes"]] == [note_id]
    with urllib.request.urlopen(base + "/api/ai/note-download?id=" + note_id, timeout=10) as r:
        assert "attachment" in r.headers["Content-Disposition"] and "## 参考文献" in r.read().decode("utf-8")

    _, body = _post(base + "/api/ai/chat", {"messages": [{"role": "user", "content": "cohesin loop extrusion?"}],
                                            "scope": "library", "context_ids": []}, raw=True)
    events = [json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: ")]
    assert any(e["type"] == "meta" and e.get("context_ids") for e in events) and events[-1]["type"] == "done"

    saved_chat = _post(base + "/api/ai/chat-save", {"title": "t", "messages": [{"role": "user", "content": "q"},
                       {"role": "assistant", "content": "a [1]"}], "context_ids": [paper_id]})
    assert saved_chat["ok"] and saved_chat["note"]["references"][0]["id"] == paper_id
    assert _post(base + "/api/ai/note-delete", {"id": note_id})["ok"] is True
    assert _get(base + "/api/ai/note?id=" + note_id)["note"] is None

    assert _post(base + "/api/ai/settings", {"base": "ftp://x"})["ok"] is False
    saved = _post(base + "/api/ai/settings", {"api_key": "sk-new-key-0000009999", "model": "deepseek-chat"})
    assert saved["ok"] and saved["settings"]["key_hint"] == "sk-…9999"
    assert "sk-new-key-0000009999" in config.ENV_FILE.read_text(encoding="utf-8")
    assert _post(base + "/api/ai/test", {})["ok"] is True


def test_ai_posts_require_custom_header(server):
    base, _ = server
    rebind = urllib.request.Request(base + "/api/ai/settings", headers={"Host": "evil.example.com"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(rebind, timeout=10)
    assert exc.value.code == 403
    with urllib.request.urlopen(urllib.request.Request(base + "/api/ai/settings", headers={"Host": "localhost:8686"}), timeout=10) as r:
        assert r.status == 200
    req = urllib.request.Request(base + "/api/ai/settings", method="POST", data=b'{"api_key": "x"}')
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 403
