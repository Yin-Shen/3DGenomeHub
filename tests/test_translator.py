from __future__ import annotations

import json
import urllib.request

import httpx
import pytest

from conftest import make_client
from genome_literature import config, pipeline, translator
from genome_literature.email_notifier import render_email_html
from genome_literature.readme_generator import write_outputs
from genome_literature.records import new_record
from genome_literature.storage import save_papers

TITLE = "Transformer model predicts Hi-C contact maps at 5-kb resolution"
ABSTRACT = (
    "We present C.Origami, a transformer that predicts CTCF-bound chromatin loops and topologically "
    "associating domains (TADs) from DNA sequence. It achieved a Pearson correlation of 0.91 across "
    "3 cell types and 1,200 loci."
)
GOOD = {
    "title_zh": "Transformer 模型以 5 kb 分辨率预测 Hi-C 接触图谱",
    "abstract_zh": "本文提出 C.Origami，这是一种基于 DNA 序列预测 CTCF 结合的染色质环和拓扑关联结构域（TAD）的 "
                   "Transformer 模型。该模型在 3 种细胞类型的 1200 个位点上的皮尔逊相关系数达到 0.91。",
}
BAD = {
    "title_zh": "Transformer 模型预测 Hi-C 接触图",
    "abstract_zh": "本文提出一种预测染色质回环和拓扑结构域的模型。",
}


class FakeLLM:
    def __init__(self, *answers, reject_format=False, status=200):
        self.answers = list(answers)
        self.requests = []
        self.reject_format = reject_format
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request, body))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "denied"})
        if self.reject_format and "response_format" in body:
            return httpx.Response(400, json={"error": "response_format is not supported"})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.fixture
def configured(tmp_project, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATE_API_KEY", "sk-test")
    monkeypatch.setattr(config, "TRANSLATE_API_BASE", "https://llm.example.org/v1")
    monkeypatch.setattr(config, "TRANSLATE_MODEL", "test-model")
    monkeypatch.setattr(translator, "_response_format_supported", {})
    return tmp_project


def _paper(**overrides):
    fields = dict(title=TITLE, abstract=ABSTRACT, doi="10.1/zh", authors=["Doe J"], journal="Cell",
                  date="2025-01-02")
    fields.update(overrides)
    return new_record("pubmed", **fields)


def test_glossary_tokens_and_numbers():
    source = f"{TITLE}\n{ABSTRACT}"
    terms = [en for en, _, _ in translator.glossary_for(source)]
    assert terms[:3] == ["topologically associating domain", "chromatin loop", "contact map"]
    assert "transformer" in terms
    assert translator.protected_tokens(source) == ["Hi-C", "5-kb", "C.Origami", "CTCF", "TAD", "DNA"]
    assert translator.numbers_in(source) == ["5", "0.91", "3", "1200"]
    assert translator.protected_tokens("3D genome folding by 10-fold enrichment") == ["3D"]


def test_check_translation_accepts_faithful_and_flags_defects():
    assert translator.check_translation(TITLE, ABSTRACT, GOOD["title_zh"], GOOD["abstract_zh"]) == []
    issues = translator.check_translation(TITLE, ABSTRACT, BAD["title_zh"], BAD["abstract_zh"])
    joined = "\n".join(issues)
    assert "C.Origami" in joined and "CTCF" in joined and "TAD" in joined
    assert "0.91" in joined and "1200" in joined
    assert "chromatin loop → 染色质环" in joined
    assert "偏短" in joined
    english = translator.check_translation(TITLE, ABSTRACT, TITLE, ABSTRACT)
    assert any("不是中文" in i for i in english)


def test_dimension_terms_may_be_translated():
    issues = translator.check_translation("3D genome organization", "", "三维基因组组织", "")
    assert issues == []


def test_translate_text_request_and_result(configured):
    llm = FakeLLM(GOOD)
    entry = translator.translate_text(TITLE, ABSTRACT, client=make_client(llm))
    assert entry["title_zh"] == GOOD["title_zh"] and entry["needs_review"] is False
    assert entry["attempts"] == 1 and entry["model"] == "test-model" and entry["reviewed"] is False
    request, body = llm.requests[0]
    assert str(request.url) == "https://llm.example.org/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == "test-model" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert "拓扑关联结构域" in body["messages"][1]["content"]
    assert "C.Origami" in body["messages"][1]["content"]


def test_corrective_retry_fixes_defects(configured):
    llm = FakeLLM(BAD, GOOD)
    entry = translator.translate_text(TITLE, ABSTRACT, client=make_client(llm))
    assert len(llm.requests) == 2 and entry["attempts"] == 2
    assert entry["abstract_zh"] == GOOD["abstract_zh"] and not entry["needs_review"]
    retry_messages = llm.requests[1][1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "染色质环" in retry_messages[-1]["content"]


def test_persistent_defects_are_flagged_for_review(configured):
    llm = FakeLLM(BAD)
    entry = translator.translate_text(TITLE, ABSTRACT, client=make_client(llm))
    assert entry["needs_review"] is True and entry["issues"]
    assert entry["attempts"] == 2


def test_fenced_json_and_response_format_fallback(configured):
    fenced = "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"
    llm = FakeLLM(fenced, reject_format=True)
    client = make_client(llm)
    entry = translator.translate_text(TITLE, ABSTRACT, client=client)
    assert entry["title_zh"] == GOOD["title_zh"]
    assert "response_format" not in llm.requests[-1][1]
    translator.translate_text(TITLE, ABSTRACT, client=client)
    assert "response_format" not in llm.requests[-1][1]


def test_errors_are_reported_clearly(configured, monkeypatch):
    with pytest.raises(translator.TranslationError, match="认证失败"):
        translator.translate_text(TITLE, ABSTRACT, client=make_client(FakeLLM(GOOD, status=401)))
    with pytest.raises(translator.TranslationError, match="JSON"):
        translator.translate_text(TITLE, ABSTRACT, client=make_client(FakeLLM("抱歉，无法翻译。")))
    monkeypatch.setattr(config, "TRANSLATE_API_KEY", "")
    with pytest.raises(translator.TranslationError, match="未配置"):
        translator.translate_text(TITLE, ABSTRACT, client=make_client(FakeLLM(GOOD)))


def test_missing_abstract_translates_title_only(configured):
    llm = FakeLLM({"title_zh": "Transformer 模型以 5 kb 分辨率预测 Hi-C 接触图谱", "abstract_zh": "（无摘要）"})
    entry = translator.translate_text(TITLE, "", client=make_client(llm))
    assert entry["abstract_zh"] == "" and not entry["needs_review"]


def test_cache_reuse_invalidation_and_reviewed_entries(configured):
    paper = _paper()
    llm = FakeLLM(GOOD)
    client = make_client(llm)
    stats = translator.translate_papers([paper], client=client)
    assert stats["translated"] == 1 and stats["needs_review"] == 0
    cache = translator.load_cache()
    assert cache[paper["id"]]["title_zh"] == GOOD["title_zh"]

    assert translator.translate_papers([paper], client=client)["requested"] == 0
    assert len(llm.requests) == 1

    changed = {**paper, "abstract": ABSTRACT + " Code is available."}
    assert translator.attach_translations([changed])[0].get("title_zh") is None
    translator.translate_papers([changed], client=client)
    assert len(llm.requests) == 2

    cache = translator.load_cache()
    cache[paper["id"]].update(title_zh="人工校对后的标题", reviewed=True)
    translator.save_cache(cache)
    stats = translator.translate_papers([paper], force=True, client=client)
    assert stats["requested"] == 0 and len(llm.requests) == 2
    shown = translator.attach_translations([paper])[0]
    assert shown["title_zh"] == "人工校对后的标题" and shown["zh_needs_review"] is False


def test_batch_stops_on_authentication_failure(configured):
    papers = [_paper(doi=f"10.1/zh{i}") for i in range(3)]
    llm = FakeLLM(GOOD, status=403)
    stats = translator.translate_papers(papers, client=make_client(llm))
    assert stats["failed"] == 1 and stats["translated"] == 0 and len(llm.requests) == 1


def test_limit_counts_skipped_papers(configured):
    papers = [_paper(doi=f"10.1/zh{i}") for i in range(3)]
    stats = translator.translate_papers(papers, limit=2, client=make_client(FakeLLM(GOOD)))
    assert stats["translated"] == 2 and stats["skipped_over_limit"] == 1


def test_outputs_show_chinese_titles(configured):
    paper = _paper()
    paper.update(track="ml", relevance=20, categories=["Hi-C Contact Map Prediction"])
    translator.translate_papers([paper], client=make_client(FakeLLM(GOOD)))
    write_outputs([paper], [paper])
    readme = (configured / "README.md").read_text(encoding="utf-8")
    assert GOOD["title_zh"] in readme
    html = render_email_html([paper], {"generated_at": "2025-01-02T00:00:00", "statistics": {}, "new_statistics": {}})
    assert GOOD["title_zh"] in html


def test_pipeline_translates_new_papers(configured, monkeypatch):
    calls = []

    def fake_translate(papers, limit=None, progress=None, **kwargs):
        calls.append([p["id"] for p in papers])
        return {"translated": len(papers), "needs_review": 0, "failed": 0, "errors": []}

    def fake_fetch_all(**kwargs):
        return [_paper(doi=f"10.1/run{len(runs)}", title=f"{TITLE} in {'mouse' if runs else 'human'} cells")]

    runs = []

    monkeypatch.setattr(translator, "translate_papers", fake_translate)
    monkeypatch.setattr(pipeline, "fetch_all_papers", fake_fetch_all)
    monkeypatch.setattr(config, "SEARCH_TOPICS", config.SEARCH_TOPICS[:1])
    result = pipeline.run_pipeline(skip_email=True, skip_readme=True)
    assert result["new_count"] == 1 and len(calls) == 1 and result["translation"]["translated"] == 1

    runs.append(1)
    monkeypatch.setattr(config, "TRANSLATE_NEW_PAPERS", False)
    result = pipeline.run_pipeline(skip_email=True, skip_readme=True)
    assert result["new_count"] == 1 and len(calls) == 1 and "translation" not in result


def _post(url, payload):
    req = urllib.request.Request(url, method="POST", data=json.dumps(payload).encode(),
                                 headers={"X-Requested-With": "3DGenomeHub", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_web_translate_endpoint(configured, monkeypatch):
    import threading

    from genome_literature import web_app

    paper = _paper()
    save_papers([paper])
    web_app._cache.update(mtime=None, papers=[])
    web_app._tr_cache.update(mtime=None, data={})
    llm = FakeLLM(GOOD)
    monkeypatch.setattr(translator, "get_client", lambda: make_client(llm))
    srv = web_app.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/papers", timeout=10) as r:
            assert "title_zh" not in json.loads(r.read())[0]
        reply = _post(base + "/api/translate", {"id": paper["id"]})
        assert reply["ok"] is True and reply["translation"]["title_zh"] == GOOD["title_zh"]
        with urllib.request.urlopen(base + "/api/papers", timeout=10) as r:
            shown = json.loads(r.read())[0]
        assert shown["title_zh"] == GOOD["title_zh"] and shown["abstract_zh"] == GOOD["abstract_zh"]
        with urllib.request.urlopen(base + "/api/stats", timeout=10) as r:
            assert json.loads(r.read())["translation"] == {"configured": True, "model": "test-model", "translated": 1}
        assert _post(base + "/api/translate", {"id": "missing"})["ok"] is False
        monkeypatch.setattr(config, "TRANSLATE_API_KEY", "")
        assert _post(base + "/api/translate-batch", {"ids": [paper["id"]]})["ok"] is False
    finally:
        srv.shutdown()
        srv.server_close()
