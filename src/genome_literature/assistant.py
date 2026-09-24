"""AI reading assistant: interpretation, multi-paper synthesis, review writing and discussion.

Every task is a generator of events consumed by the web app (as server-sent
events) and the CLI:

* ``{"type": "meta", ...}``      context description (papers, basis, model)
* ``{"type": "status", ...}``    progress message
* ``{"type": "reasoning", ...}`` thinking trace of reasoning models
* ``{"type": "delta", ...}``     answer text
* ``{"type": "done", ...}``      verified references, warnings and the saved note
* ``{"type": "error", ...}``

Faithfulness safeguards: the model only sees numbered source material and
must cite it as ``[n]``; citations are checked against the material and the
reference list is generated from the database, never by the model.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

from . import config, fulltext, llm, notes, retrieval
from .net import HttpClient
from .relevance import track_label
from .translator import GLOSSARY

logger = logging.getLogger(__name__)

Event = dict[str, Any]

TASKS = {
    "interpret": "AI 解读",
    "summary": "多篇总结",
    "compare": "对比分析",
    "review": "撰写综述",
    "gaps": "研究空白与选题",
    "ask": "文献问答",
}

SYSTEM_PROMPT = """你是一位资深的三维基因组学（Hi-C 等染色质构象捕获技术、染色质环、拓扑关联结构域、A/B 区室、单细胞三维基因组、成像）与深度学习交叉领域的研究者和审稿人，负责帮助中文读者准确、深入地理解英文科研文献。

必须遵守的原则：
1. 只依据提供的文献材料作答。材料中没有的信息，写明“文中未提及”或“摘要未提供”，不得猜测或编造数据、结论、数据集、代码、作者观点。
2. 每个具体论断后用方括号标注来源编号，如 [1] 或 [2][5]；只能使用材料中出现的编号，不得虚构文献，也不要自行编写参考文献列表（系统会自动生成）。
3. 需要补充材料之外的领域背景知识时，明确标注“（背景知识）”，且不要给它加文献编号。
4. 数值、模型名、数据集、基因/蛋白名、工具名保持原文；专业术语首次出现时写作“中文（English）”，如 拓扑关联结构域（TAD）。
5. 使用规范、简洁的中文学术表达，结构清晰，使用 Markdown（标题、列表、表格）；不要空话套话。"""

TASK_PROMPTS = {
    "interpret": """请对文献 [1] 做深度解读，面向希望快速而准确地理解该文的研究生和科研人员。{basis_note}

按以下结构输出：
## 一句话总结
## 研究背景与要解决的问题
## 核心方法
- 数据与实验体系（物种、细胞类型、测序/成像技术、数据集）
- 模型或算法设计（输入、输出、架构、关键设计、训练与评估方式）；若非计算类论文，写实验设计与关键技术
## 主要结果（给出原文中的关键数值及对比对象）
## 创新点与贡献
## 局限性与值得推敲之处（区分作者自述的局限与你的审稿式分析）
## 在三维基因组研究中的位置（可结合背景知识，须标注）
## 关键术语速览（表格：术语 | 中文 | 含义）
## 阅读建议（最值得精读的部分或图表、复现时需注意的问题）""",
    "summary": """请综合以下 {n} 篇文献，撰写一份多篇文献综合总结{focus}。

结构：
## 总体概览（这些文献共同关注的问题与整体脉络）
## 主题归类（按研究问题或方法路线分组；每组说明代表性工作、核心思路与主要结论）
## 关键发现与共识
## 分歧、矛盾或尚无定论之处
## 推荐优先阅读（3-5 篇，说明理由）

要求：{coverage}不要逐篇机械罗列，要归纳与比较。""",
    "compare": """请对以下 {n} 篇文献做系统的对比分析{focus}。

## 对比总表
Markdown 表格，每篇一行，列为：文献 | 研究任务 | 数据/实验体系 | 方法或模型 | 评估指标与主要结果 | 优势 | 局限。
“文献”列写编号与简称（如 [3] Akita），每个单元格不超过 40 字，文中未提及的写“未提及”。{table_note}
## 横向比较（任务设定、数据、方法设计、性能与适用场景的异同）
## 选型建议（针对不同研究需求推荐方法并说明理由）""",
    "review": """请基于以下 {n} 篇文献，撰写一篇中文学术综述{focus}。

要求：
- 结构：# 综述标题；**摘要**（200-300 字）；**关键词**；1 引言（研究背景、意义与综述范围）；2 至 4 按研究主题或方法路线组织的主体章节（可设小节，比较不同工作的思路、数据、结果与局限）；5 挑战与展望；6 结论。
- 行文为综述体：归纳、比较、评述，而不是逐篇摘要堆砌；每个具体论断都标注引用编号，{coverage}
- 不要编写参考文献列表（系统会根据引用编号自动生成）。
- 篇幅约 3000-5000 字。""",
    "gaps": """请基于以下 {n} 篇文献，分析该方向的研究空白与未来方向{focus}。

## 当前研究格局（简述）
## 尚未解决的关键问题（逐条说明：为何重要、现有工作做到哪一步、差距在哪里）
## 方法学上的不足（数据、评估基准、可解释性、泛化性、实验验证等）
## 可行的研究选题（5-8 个；每个给出研究问题、可能的数据与方法、预期贡献与风险）

区分“有文献支持的判断”（标注编号）与“你的推测”（标注“推测”）。""",
    "ask": """请基于以下 {n} 篇文献回答问题：

{question}

先给出直接回答，再展开论证；引用具体文献编号；材料不足以回答的部分请明确说明。""",
}

CHAT_PROMPT = """你正在与用户讨论下列文献（编号即引用编号）。{scope_note}
回答要直接、准确、有条理；引用具体文献编号；材料不足以回答时说明缺什么，可补充标注为“（背景知识）”的一般性说明。"""

EXTRACT_PROMPT = """下面是若干篇文献（编号为全局编号）。请为每一篇提取要点，严格依据材料，不要编造。
每篇单独一行，格式：
[编号] 研究问题：…；数据/体系：…；方法：…；主要结果（含关键数值）：…；局限：…
每篇不超过 150 字，按编号顺序输出，不要遗漏任何一篇，不要输出其他内容。"""

EXPAND_PROMPT = """把用户关于三维基因组、表观基因组或深度学习文献的问题，转换为用于检索英文论文标题和摘要的关键词。
输出 JSON：{"keywords": ["...", "..."]}，包含 5-15 个英文关键词或短语，涵盖同义词、缩写与全称（如 TAD 与 topologically associating domain、Hi-C 与 chromatin conformation capture）。只输出 JSON。"""

_CITE = re.compile(r"\[(\d{1,3}(?:\s*(?:[-–—~,，、]|and)\s*\d{1,3})*)\]")


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------

def _authors(p: dict[str, Any]) -> str:
    authors = p.get("authors") or []
    return ", ".join(authors[:3]) + (" 等" if len(authors) > 3 else "") if authors else "未知作者"


def paper_header(n: int, p: dict[str, Any]) -> str:
    facts = [f"作者：{_authors(p)}", f"期刊：{p.get('journal') or '未知'}", f"年份：{p.get('year') or '未知'}",
             f"类型：{track_label(p.get('track', ''))}"]
    if p.get("dl_methods"):
        facts.append("方法：" + ", ".join(p["dl_methods"][:4]))
    if p.get("is_preprint"):
        facts.append("预印本")
    lines = [f"[{n}] {p.get('title', '').strip()}", " | ".join(facts)]
    if p.get("doi"):
        lines.append(f"DOI：{p['doi']}")
    return "\n".join(lines)


def paper_block(n: int, p: dict[str, Any], body: str | None = None, abstract_limit: int | None = None) -> str:
    abstract = (p.get("abstract") or "").strip()
    if abstract_limit and len(abstract) > abstract_limit:
        abstract = abstract[:abstract_limit].rsplit(" ", 1)[0] + " …"
    block = [paper_header(n, p), f"摘要：{abstract or '（无摘要）'}"]
    if body:
        block.append(body)
    return "\n".join(block)


def reference(n: int, p: dict[str, Any]) -> dict[str, Any]:
    return {"n": n, "id": p.get("id"), "title": p.get("title", ""), "year": p.get("year"),
            "journal": p.get("journal", ""), "doi": p.get("doi", ""), "url": p.get("url", ""),
            "authors": (p.get("authors") or [])[:4]}


def extract_citations(text: str) -> list[int]:
    found: list[int] = []
    for group in _CITE.findall(text):
        for part in re.split(r"\s*(?:[,，、]|and)\s*", group):
            bounds = re.split(r"\s*[-–—~]\s*", part)
            try:
                nums = [int(b) for b in bounds if b]
            except ValueError:
                continue
            if len(nums) == 2 and 0 < nums[1] - nums[0] <= 50:
                nums = list(range(nums[0], nums[1] + 1))
            for num in nums:
                if num not in found:
                    found.append(num)
    return found


def verify_citations(text: str, papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    cited = extract_citations(text)
    refs = [reference(n, papers[n - 1]) for n in sorted(cited) if 1 <= n <= len(papers)]
    invalid = sorted(n for n in cited if not 1 <= n <= len(papers))
    return refs, invalid


def _fulltext_bodies(papers: list[dict[str, Any]], client: HttpClient | None) -> Iterator[Event | tuple[int, str, str]]:
    budget = max(8000, config.AI_FULLTEXT_CHARS // max(1, len(papers)))
    for i, p in enumerate(papers):
        yield {"type": "status", "message": f"正在获取全文（{i + 1}/{len(papers)}）：{p.get('title', '')[:60]}"}
        try:
            doc = fulltext.get_fulltext(p, client=client)
        except Exception as exc:
            logger.warning("Full text failed for %s: %s", p.get("id"), exc)
            doc = None
        if doc:
            yield i, doc["source"], f"全文节选（来源：{doc['source']}）：\n" + fulltext.as_prompt_text(doc, budget)


def build_context(papers: list[dict[str, Any]], use_fulltext: bool, client: HttpClient | None) -> Iterator[Event | tuple[str, str]]:
    """Yield status events, then finally ``(context_text, basis_description)``."""
    bodies: dict[int, str] = {}
    sources: dict[int, str] = {}
    if use_fulltext and papers and len(papers) <= config.AI_FULLTEXT_MAX_PAPERS:
        for item in _fulltext_bodies(papers, client):
            if isinstance(item, dict):
                yield item
            else:
                i, source, body = item
                bodies[i], sources[i] = body, source
    blocks = [paper_block(i + 1, p, bodies.get(i)) for i, p in enumerate(papers)]
    if sources:
        basis = f"全文 {len(sources)} 篇（{'、'.join(sorted(set(sources.values())))}）" + (
            f"，其余 {len(papers) - len(sources)} 篇仅摘要" if len(sources) < len(papers) else "")
    else:
        basis = "标题与摘要"
    yield "\n\n".join(blocks), basis


def _batches(papers: list[dict[str, Any]], limit: int) -> list[list[int]]:
    groups: list[list[int]] = [[]]
    size = 0
    for i, p in enumerate(papers):
        length = len(paper_block(i + 1, p)) + 2
        if groups[-1] and size + length > limit:
            groups.append([])
            size = 0
        groups[-1].append(i)
        size += length
    return groups


def condense(papers: list[dict[str, Any]], client: HttpClient | None) -> Iterator[Event | str]:
    """Map step for large sets: extract per-paper key points in batches; finally yields the notes text."""
    groups = _batches(papers, config.AI_BATCH_CHARS)
    yield {"type": "status", "message": f"文献较多（{len(papers)} 篇），先分 {len(groups)} 批提炼每篇要点…"}

    def run(group: list[int]) -> str:
        material = "\n\n".join(paper_block(i + 1, papers[i]) for i in group)
        return llm.chat([{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": EXTRACT_PROMPT + "\n\n" + material}],
                        temperature=0.2, client=client)

    notes_by_n: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run, g) for g in groups]
        for k, fut in enumerate(futures):
            text = fut.result()
            yield {"type": "status", "message": f"已完成第 {k + 1}/{len(groups)} 批要点提炼"}
            for line in text.splitlines():
                m = re.match(r"\s*\[(\d+)\]\s*(.+)", line)
                if m and 1 <= int(m.group(1)) <= len(papers):
                    notes_by_n[int(m.group(1))] = m.group(2).strip()
    lines = []
    for i, p in enumerate(papers):
        n = i + 1
        point = notes_by_n.get(n) or "摘要节选：" + (p.get("abstract") or "（无摘要）")[:500]
        lines.append(f"{paper_header(n, p)}\n要点：{point}")
    yield "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def _stream_answer(messages: list[dict[str, str]], deep: bool, temperature: float,
                   client: HttpClient | None) -> Iterator[Event | tuple[str, str]]:
    parts: list[str] = []
    finish = "stop"
    for kind, text in llm.stream(messages, model=llm.model_for(deep), temperature=temperature, client=client):
        if kind == "content":
            parts.append(text)
            yield {"type": "delta", "text": text}
        elif kind == "reasoning":
            yield {"type": "reasoning", "text": text}
        elif kind == "finish":
            finish = text
    yield "".join(parts), finish


def _done(answer: str, finish: str, papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    refs, invalid = verify_citations(answer, papers)
    warnings = []
    if invalid:
        warnings.append(f"回答中出现了材料之外的引用编号 {invalid}，已忽略，请谨慎对待相关论断。")
    if finish == "length":
        warnings.append("输出达到长度上限，内容可能不完整。可在对话中让 AI 继续。")
    if papers and not refs and answer.strip():
        warnings.append("回答没有标注任何文献编号，请核对其依据。")
    return refs, warnings


def _title_for(task: str, papers: list[dict[str, Any]], question: str, answer: str) -> str:
    heading = re.search(r"^#\s+(.+)$", answer, re.M)
    if task == "review" and heading:
        return heading.group(1).strip()
    if task == "interpret" and papers:
        return papers[0].get("title", "")
    if question:
        return f"{TASKS[task]}：{question[:60]}"
    first = papers[0].get("title", "") if papers else ""
    return f"{TASKS[task]}：{first[:50]}{' 等 %d 篇' % len(papers) if len(papers) > 1 else ''}"


def run_task(task: str, papers: list[dict[str, Any]], *, question: str = "", deep: bool = False,
             use_fulltext: bool = True, save: bool = True, client: HttpClient | None = None) -> Iterator[Event]:
    """Interpretation (one paper) or synthesis (many papers) as a stream of events."""
    try:
        yield from _run_task(task, papers, question, deep, use_fulltext, save, client)
    except llm.LLMError as exc:
        yield {"type": "error", "message": str(exc)}
    except Exception as exc:
        logger.exception("AI task %s failed", task)
        yield {"type": "error", "message": f"处理失败：{exc}"}


def _run_task(task: str, papers: list[dict[str, Any]], question: str, deep: bool, use_fulltext: bool,
              save: bool, client: HttpClient | None) -> Iterator[Event]:
    if task not in TASKS:
        raise ValueError(f"未知任务：{task}")
    llm._require_config()
    if not papers:
        yield {"type": "error", "message": "请先选择文献（加入研读清单）"}
        return
    if task == "interpret":
        papers = papers[:1]
    if task == "ask" and not question.strip():
        yield {"type": "error", "message": "请输入要提问的问题"}
        return
    papers = papers[: config.AI_MAX_PAPERS]
    n = len(papers)
    model = llm.model_for(deep)
    yield {"type": "meta", "task": task, "label": TASKS[task], "model": model,
           "papers": [{"n": i + 1, "id": p.get("id"), "title": p.get("title", ""), "year": p.get("year")}
                      for i, p in enumerate(papers)]}

    context = basis = ""
    for item in build_context(papers, use_fulltext, client):
        if isinstance(item, dict):
            yield item
        else:
            context, basis = item
    if task != "interpret" and len(context) > config.AI_CONTEXT_CHARS:
        for item in condense(papers, client):
            if isinstance(item, dict):
                yield item
            else:
                context = item
        basis = f"{basis}（先逐篇提炼要点再综合）"
    yield {"type": "meta", "basis": basis}

    if task == "interpret":
        if "全文" in basis:
            basis_note = "材料包含全文节选，请充分利用正文、图注与表格中的信息。"
        elif papers[0].get("abstract"):
            basis_note = "注意：未获取到全文，只有标题与摘要。请在开头用一行说明“本解读仅基于摘要”，不要推测方法细节与未报告的数值。"
        else:
            basis_note = "注意：该文献只有标题，没有摘要与全文。请说明信息不足，仅就标题做谨慎、简短的解读。"
        prompt = TASK_PROMPTS["interpret"].format(basis_note=basis_note)
    else:
        focus = f"，重点围绕：{question.strip()}" if question.strip() and task != "ask" else ""
        coverage = "所有文献都应至少被引用一次；" if n <= 30 else "尽量覆盖全部文献，优先讨论代表性工作；"
        table_note = "" if n <= 25 else "文献较多时，可按方法路线分成多个表格。"
        prompt = TASK_PROMPTS[task].format(n=n, focus=focus, coverage=coverage, table_note=table_note,
                                           question=question.strip())
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{prompt}\n\n=== 文献材料（依据：{basis}）===\n\n{context}"},
    ]
    yield {"type": "status", "message": "AI 正在思考…" if deep else "AI 正在撰写…"}
    answer, finish = "", "stop"
    for item in _stream_answer(messages, deep, 0.3, client):
        if isinstance(item, dict):
            yield item
        else:
            answer, finish = item
    refs, warnings = _done(answer, finish, papers)
    note = None
    if save and answer.strip():
        note = notes.save_note(task, _title_for(task, papers, question, answer), answer,
                               paper_ids=[p.get("id") for p in papers], references=refs, model=model, basis=basis,
                               extra={"question": question.strip()} if question.strip() else None)
    yield {"type": "done", "references": refs, "warnings": warnings, "note": note, "finish": finish}


# ---------------------------------------------------------------------------
# Discussion
# ---------------------------------------------------------------------------

def glossary_terms(question: str) -> list[str]:
    """English glossary terms whose Chinese renderings occur in ``question`` (offline query expansion)."""
    found = []
    for en, zh_list, _ in GLOSSARY:
        if any(z and z in question for z in zh_list if not z.isascii()):
            found.append(en)
    return found


def expand_query(question: str, client: HttpClient | None = None) -> list[str]:
    terms: list[str] = []
    try:
        raw = llm.chat([{"role": "system", "content": EXPAND_PROMPT}, {"role": "user", "content": question}],
                       temperature=0, max_tokens=400, json_mode=True, client=client)
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1]) if start != -1 else {}
        terms = [str(t) for t in data.get("keywords", []) if str(t).strip()][:20]
    except (llm.LLMError, ValueError) as exc:
        logger.info("Query expansion failed, using the question itself: %s", exc)
    return terms + glossary_terms(question) + [question]


def library_search(question: str, library: list[dict[str, Any]], k: int, allowed: set[str] | None,
                   client: HttpClient | None) -> list[dict[str, Any]]:
    return retrieval.search(library, expand_query(question, client), k=k, allowed=allowed)


def _trim_history(messages: list[dict[str, str]], limit_chars: int = 30000) -> list[dict[str, str]]:
    clean = [{"role": m["role"], "content": str(m.get("content") or "")} for m in messages
             if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()]
    out: list[dict[str, str]] = []
    total = 0
    for m in reversed(clean[-16:]):
        total += len(m["content"])
        if out and total > limit_chars:
            break
        out.append(m)
    return list(reversed(out))


def chat(messages: list[dict[str, str]], context: list[dict[str, Any]], *, scope: str = "selection",
         library: list[dict[str, Any]] | None = None, allowed: set[str] | None = None, deep: bool = False,
         use_fulltext: bool = False, client: HttpClient | None = None) -> Iterator[Event]:
    """One assistant turn of a discussion about ``context`` papers (library scope retrieves more)."""
    try:
        yield from _chat(messages, context, scope, library or [], allowed, deep, use_fulltext, client)
    except llm.LLMError as exc:
        yield {"type": "error", "message": str(exc)}
    except Exception as exc:
        logger.exception("AI chat failed")
        yield {"type": "error", "message": f"处理失败：{exc}"}


def _chat(messages: list[dict[str, str]], context: list[dict[str, Any]], scope: str,
          library: list[dict[str, Any]], allowed: set[str] | None, deep: bool, use_fulltext: bool,
          client: HttpClient | None) -> Iterator[Event]:
    llm._require_config()
    history = _trim_history(messages)
    if not history or history[-1]["role"] != "user":
        yield {"type": "error", "message": "请输入问题"}
        return
    question = history[-1]["content"]
    context = list(context)
    if scope in ("library", "filtered"):
        where = "当前筛选结果" if scope == "filtered" else "整个文献库"
        yield {"type": "status", "message": f"正在从{where}中检索相关文献…"}
        known = {p.get("id") for p in context}
        found = library_search(question, library, config.AI_LIBRARY_TOP_K,
                               allowed if scope == "filtered" else None, client)
        for p in found:
            if p.get("id") not in known and len(context) < config.AI_CHAT_CONTEXT_MAX:
                context.append(p)
                known.add(p.get("id"))
    yield {"type": "meta", "model": llm.model_for(deep), "context_ids": [p.get("id") for p in context],
           "papers": [{"n": i + 1, "id": p.get("id"), "title": p.get("title", ""), "year": p.get("year")}
                      for i, p in enumerate(context)]}
    if not context:
        scope_note = "当前没有提供任何文献材料；请据实说明，并仅给出标注为“（背景知识）”的一般性回答。"
        material, basis = "", "无"
    else:
        material, basis = "", ""
        for item in build_context(context, use_fulltext, client):
            if isinstance(item, dict):
                yield item
            else:
                material, basis = item
        if len(material) > config.AI_CONTEXT_CHARS:
            material = "\n\n".join(paper_block(i + 1, p, abstract_limit=900) for i, p in enumerate(context))
        scope_note = ("以下文献是根据用户问题从本地文献库检索到的最相关结果；若它们不足以回答，请说明。"
                      if scope in ("library", "filtered") else "以下是用户选定的文献。")
    system = f"{SYSTEM_PROMPT}\n\n{CHAT_PROMPT.format(scope_note=scope_note)}"
    if material:
        system += f"\n\n=== 文献材料（依据：{basis}）===\n\n{material}"
    yield {"type": "meta", "basis": basis}
    answer, finish = "", "stop"
    for item in _stream_answer([{"role": "system", "content": system}] + history, deep, 0.5, client):
        if isinstance(item, dict):
            yield item
        else:
            answer, finish = item
    refs, warnings = _done(answer, finish, context)
    yield {"type": "done", "references": refs, "warnings": warnings, "finish": finish}


def save_conversation(title: str, messages: list[dict[str, str]], context: list[dict[str, Any]],
                      model: str = "") -> dict[str, Any]:
    parts = []
    for m in messages:
        who = "**我：**" if m.get("role") == "user" else "**AI：**"
        parts.append(f"{who}\n\n{str(m.get('content') or '').strip()}")
    text = "\n\n---\n\n".join(parts)
    refs, _ = verify_citations(text, context)
    return notes.save_note("chat", title or "AI 讨论", text, paper_ids=[p.get("id") for p in context],
                           references=refs, model=model)
