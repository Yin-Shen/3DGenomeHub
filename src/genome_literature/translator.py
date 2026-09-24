"""Academic English -> Simplified Chinese translation of paper titles and abstracts.

The translation engine is the shared model client (``llm.py``): any
OpenAI-compatible chat-completions endpoint (DeepSeek by default, Qwen,
Moonshot, a local server, ...) configured with LLM_API_KEY / LLM_API_BASE /
LLM_MODEL or from the web app's AI settings.

Accuracy safeguards:

* a curated 3D-genome / epigenomics / machine-learning glossary; the terms that
  occur in a paper are sent with the request and their use is verified;
* deterministic decoding (temperature 0) and JSON-only output;
* automatic checks: every acronym, gene / tool name and number in the source
  must appear unchanged, the output must be Chinese, and its length must be
  plausible (catches omissions and additions);
* one corrective retry that lists the detected problems; anything still
  failing is stored with ``needs_review`` and the list of issues;
* results are cached in ``papers/translations.json`` keyed by paper id and a
  hash of the source text; entries marked ``"reviewed": true`` (manually
  corrected) are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import config, llm
from .matching import compile_term, normalize_text
from .net import HttpClient
from .storage import load_json, save_json

logger = logging.getLogger(__name__)

# (English term, accepted Chinese renderings - first one is preferred, verified in output?)
GLOSSARY: list[tuple[str, list[str], bool]] = [
    ("three-dimensional genome", ["三维基因组"], True),
    ("3D genome", ["三维基因组"], True),
    ("4D nucleome", ["4D核组", "四维核组"], True),
    ("genome organization", ["基因组组织"], False),
    ("genome architecture", ["基因组架构"], False),
    ("genome folding", ["基因组折叠"], True),
    ("chromatin folding", ["染色质折叠"], True),
    ("chromatin architecture", ["染色质架构"], False),
    ("chromatin organization", ["染色质组织"], False),
    ("chromatin structure", ["染色质结构"], False),
    ("higher-order chromatin structure", ["染色质高级结构", "高级染色质结构"], False),
    ("chromosome conformation capture", ["染色体构象捕获"], True),
    ("chromatin conformation", ["染色质构象"], True),
    ("topologically associating domain", ["拓扑关联结构域", "拓扑相关结构域"], True),
    ("topologically associated domain", ["拓扑关联结构域", "拓扑相关结构域"], True),
    ("topological domain", ["拓扑结构域"], True),
    ("A/B compartment", ["A/B区室"], True),
    ("compartmentalization", ["区室化"], True),
    ("subcompartment", ["亚区室"], True),
    ("compartment", ["区室"], True),
    ("chromatin loop", ["染色质环"], True),
    ("loop extrusion", ["环挤出", "环挤压"], True),
    ("loop anchor", ["环锚点", "锚点"], True),
    ("enhancer hijacking", ["增强子劫持"], True),
    ("enhancer", ["增强子"], True),
    ("promoter", ["启动子"], True),
    ("insulator", ["绝缘子"], True),
    ("silencer", ["沉默子"], True),
    ("cis-regulatory element", ["顺式调控元件"], True),
    ("chromatin interaction", ["染色质相互作用", "染色质互作"], True),
    ("long-range interaction", ["长程相互作用", "远程相互作用", "长距离相互作用", "长程互作"], True),
    ("contact map", ["接触图谱", "接触图"], True),
    ("contact matrix", ["接触矩阵"], True),
    ("contact frequency", ["接触频率"], True),
    ("insulation score", ["绝缘分数", "绝缘得分"], True),
    ("cohesin", ["黏连蛋白", "粘连蛋白"], True),
    ("condensin", ["凝缩蛋白"], True),
    ("nuclear lamina", ["核纤层"], True),
    ("lamina-associated domain", ["核纤层相关结构域", "核纤层关联结构域"], True),
    ("nuclear speckle", ["核斑点", "核小斑"], True),
    ("nucleolus", ["核仁"], True),
    ("chromosome territory", ["染色体疆域", "染色体领域"], True),
    ("chromosome territories", ["染色体疆域", "染色体领域"], True),
    ("heterochromatin", ["异染色质"], True),
    ("euchromatin", ["常染色质"], True),
    ("nucleosome", ["核小体"], True),
    ("liquid-liquid phase separation", ["液-液相分离", "液液相分离"], True),
    ("phase separation", ["相分离"], True),
    ("biomolecular condensate", ["生物分子凝聚体"], True),
    ("polymer model", ["聚合物模型", "高分子模型"], True),
    ("polymer simulation", ["聚合物模拟", "高分子模拟"], True),
    ("molecular dynamics", ["分子动力学"], True),
    ("coarse-grained", ["粗粒化", "粗粒度"], True),
    ("chromatin tracing", ["染色质示踪", "染色质追踪"], True),
    ("single-cell", ["单细胞"], True),
    ("single cell", ["单细胞"], True),
    ("sequencing depth", ["测序深度"], True),
    ("chromatin accessibility", ["染色质可及性", "染色质开放性"], True),
    ("histone modification", ["组蛋白修饰"], True),
    ("DNA methylation", ["DNA甲基化"], True),
    ("transcription factor", ["转录因子"], True),
    ("gene expression", ["基因表达"], True),
    ("gene regulation", ["基因调控"], False),
    ("epigenome", ["表观基因组"], True),
    ("epigenomic", ["表观基因组"], True),
    ("structural variant", ["结构变异"], True),
    ("structural variation", ["结构变异"], True),
    ("copy number variation", ["拷贝数变异"], True),
    ("genome-wide association", ["全基因组关联"], True),
    ("resolution enhancement", ["分辨率增强"], True),
    ("super-resolution", ["超分辨率", "超分辨"], True),
    ("imputation", ["插补", "填补", "补全"], True),
    ("denoising", ["去噪", "降噪"], True),
    ("in silico", ["计算机模拟", "计算机"], False),
    ("deep learning", ["深度学习"], True),
    ("machine learning", ["机器学习"], True),
    ("convolutional neural network", ["卷积神经网络"], True),
    ("graph neural network", ["图神经网络"], True),
    ("recurrent neural network", ["循环神经网络"], True),
    ("neural network", ["神经网络"], True),
    ("generative adversarial network", ["生成对抗网络", "生成式对抗网络"], True),
    ("variational autoencoder", ["变分自编码器"], True),
    ("autoencoder", ["自编码器", "自动编码器"], True),
    ("diffusion model", ["扩散模型"], True),
    ("attention mechanism", ["注意力机制"], True),
    ("self-attention", ["自注意力"], True),
    ("transformer", ["Transformer"], True),
    ("transfer learning", ["迁移学习"], True),
    ("contrastive learning", ["对比学习"], True),
    ("self-supervised", ["自监督"], True),
    ("representation learning", ["表示学习", "表征学习"], True),
    ("foundation model", ["基础模型", "基座模型"], True),
    ("large language model", ["大语言模型", "大型语言模型"], True),
    ("language model", ["语言模型"], True),
    ("random forest", ["随机森林"], True),
    ("support vector machine", ["支持向量机"], True),
    ("gradient boosting", ["梯度提升"], True),
    ("hypergraph", ["超图"], True),
    ("embedding", ["嵌入"], False),
    ("benchmark", ["基准"], True),
]

SYSTEM_PROMPT = """你是一名资深学术翻译，专长为三维基因组学、表观基因组学、分子生物学、生物信息学以及机器学习/深度学习。请将用户提供的英文论文标题和摘要翻译为规范、准确的简体中文学术语言，文风参照中文核心期刊的论文摘要。

必须严格遵守：
1. 忠实完整：逐句翻译，不得增译、漏译、概括、评论或解释；保留原文的逻辑关系、限定语、比较级与不确定性表述（如 may、suggest、potentially、likely）。
2. 术语：使用“术语表”中给出的译法；术语表未列出的专业术语使用中国大陆学界通行的规范译名（参照全国科学技术名词审定委员会公布的名词）。
3. 保持原样、不翻译不改写：基因和蛋白名称、实验技术与测序方法名称（如 Hi-C、Micro-C、ChIP-seq、ATAC-seq）、软件/工具/模型/算法名称、缩写、物种拉丁学名、数据库名称、数值（一律使用阿拉伯数字）、单位、统计量（如 p < 0.05、AUROC）、公式和化学式。
4. 缩写：原文给出全称时译为“中文全称（英文缩写）”；原文仅出现缩写时直接保留缩写。
5. 结构化摘要的小标题（Background、Methods、Results、Conclusions 等）译为“背景：”“方法：”“结果：”“结论：”等，并保持原有顺序。
6. 标题译文简洁规范，句末不加句号。
7. 只输出一个 JSON 对象：{"title_zh": "标题译文", "abstract_zh": "摘要译文"}，不要输出任何其他内容；摘要为空时 abstract_zh 为空字符串。"""

_CJK = re.compile(r"[一-鿿]")
_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9+/'.-]*[A-Za-z0-9+]|(?<![A-Za-z0-9])[A-Z](?![A-Za-z0-9])")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![A-Za-z])")
_DIMENSION = re.compile(r"^([2-4])D$")
_UNIT_SUFFIX = re.compile(r"^\d+(?:\.\d+)?-?(?:fold|times|th|st|nd|rd|mer|mers)$", re.I)
_DIMENSION_ZH = {"2": "二维", "3": "三维", "4": "四维"}
_GLOSSARY_PATTERNS = [(en, zh, check, compile_term(en)) for en, zh, check in GLOSSARY]


TranslationError = llm.LLMError
_FATAL_ERRORS = ("认证失败", "未配置", "无法连接", "余额不足")


def is_configured() -> bool:
    return llm.is_configured()


def source_hash(title: str, abstract: str) -> str:
    return hashlib.sha1(f"{title}\n{abstract}".encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Glossary and verification
# ---------------------------------------------------------------------------

def glossary_for(text: str) -> list[tuple[str, list[str], bool]]:
    """Glossary entries whose English term occurs in ``text`` (longest terms first)."""
    norm = normalize_text(text)
    found = [(en, zh, check) for en, zh, check, pattern in _GLOSSARY_PATTERNS if pattern.search(norm)]
    return sorted(found, key=lambda item: -len(item[0]))


def _is_protected(token: str) -> bool:
    upper = sum(1 for c in token if c.isupper())
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    if len(token) < 2 or not has_alpha or _UNIT_SUFFIX.match(token):
        return False
    return upper >= 2 or (upper == 1 and not token[0].isupper()) or has_digit


def protected_tokens(text: str) -> list[str]:
    """Acronyms, gene/tool names and mixed alphanumerics that must survive translation verbatim.

    Hyphenated compounds with ordinary English words (``CTCF-bound``) contribute only
    their protected parts (``CTCF``), since the English word itself is translated.
    """
    tokens: list[str] = []
    for raw in _TOKEN.findall(normalize_text(text)):
        token = raw.strip(".-'/")
        parts = token.split("-")
        if len(parts) > 1 and any(part.isalpha() and part.islower() and len(part) >= 3 for part in parts):
            candidates = [part for part in parts if _is_protected(part)]
        else:
            candidates = [token] if _is_protected(token) else []
        for cand in candidates:
            if re.search(r"[A-Z]s$", cand) and len(cand) > 2:
                cand = cand[:-1]
            if cand not in tokens:
                tokens.append(cand)
    return tokens


def numbers_in(text: str) -> list[str]:
    values = []
    for n in _NUMBER.findall(normalize_text(text)):
        value = _plain_number(n)
        if value not in values:
            values.append(value)
    return values


def _plain_number(n: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", n)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text))


def _key(text: str) -> str:
    """Comparison key tolerant to spacing, hyphenation and case (Hi-C / HiC, 5-kb / 5 kb)."""
    return re.sub(r"[\s\-]+", "", normalize_text(text)).lower()


def check_translation(title: str, abstract: str, title_zh: str, abstract_zh: str) -> list[str]:
    """Return human-readable problems (empty list = passed all checks)."""
    issues: list[str] = []
    source = f"{title}\n{abstract}"
    target = f"{title_zh}\n{abstract_zh}"
    target_compact = _compact(target)
    target_key = _key(target)

    if title and not title_zh.strip():
        issues.append("标题译文为空")
    if abstract and not abstract_zh.strip():
        issues.append("摘要译文为空")

    missing_tokens = []
    for token in protected_tokens(source):
        dim = _DIMENSION.match(token)
        if dim and _DIMENSION_ZH[dim.group(1)] in target_compact:
            continue
        if _key(token) not in target_key:
            missing_tokens.append(token)
    if missing_tokens:
        issues.append("译文缺少原文中应保持原样的名称/缩写：" + ", ".join(missing_tokens[:15]))

    target_numbers = _plain_number(normalize_text(target))
    missing_numbers = [n for n in numbers_in(source) if not re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", target_numbers)]
    if missing_numbers:
        issues.append("译文缺少原文中的数值：" + ", ".join(missing_numbers[:15]))

    wrong_terms = []
    for en, zh, check in glossary_for(source):
        if check and not any(_key(z) in target_key for z in zh):
            wrong_terms.append(f"{en} → {zh[0]}")
    if wrong_terms:
        issues.append("以下术语未按术语表翻译：" + "；".join(wrong_terms[:15]))

    for label, en, zh in (("标题", title, title_zh), ("摘要", abstract, abstract_zh)):
        words = len(re.findall(r"[A-Za-z]+", en))
        if words >= 4 and zh.strip() and not _CJK.search(zh):
            issues.append(f"{label}译文不是中文")
    if abstract and abstract_zh.strip():
        ratio = len(_compact(abstract_zh)) / max(len(_compact(abstract)), 1)
        if ratio < config.TRANSLATE_MIN_LENGTH_RATIO:
            issues.append(f"摘要译文明显偏短（长度比 {ratio:.2f}），可能存在漏译")
        elif ratio > config.TRANSLATE_MAX_LENGTH_RATIO:
            issues.append(f"摘要译文明显偏长（长度比 {ratio:.2f}），可能存在增译")
    return issues


# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------

def build_user_message(title: str, abstract: str) -> str:
    source = f"{title}\n{abstract}"
    terms = glossary_for(source)
    tokens = protected_tokens(source)
    lines = []
    if terms:
        lines.append("术语表（英文 → 中文）：")
        lines += [f"- {en} → {zh[0]}" for en, zh, _ in terms]
        lines.append("")
    if tokens:
        lines.append("以下名称/缩写须在译文中保持原样：" + ", ".join(tokens))
        lines.append("")
    lines.append("待翻译内容：")
    lines.append(f"TITLE: {title}")
    lines.append(f"ABSTRACT: {abstract or '(无摘要)'}")
    return "\n".join(lines)


def _chat(messages: list[dict[str, str]], client: HttpClient | None) -> str:
    return llm.chat(messages, temperature=0, json_mode=True, client=client)


def parse_output(content: str) -> tuple[str, str]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise TranslationError("模型未返回 JSON 译文")
    try:
        data = json.loads(text[start:end + 1], strict=False)
    except ValueError as exc:
        raise TranslationError("模型返回的 JSON 无法解析") from exc
    return str(data.get("title_zh") or "").strip(), str(data.get("abstract_zh") or "").strip()


def translate_text(title: str, abstract: str, client: HttpClient | None = None) -> dict[str, Any]:
    """Translate one title/abstract pair, verify it and retry once with the detected problems."""
    llm._require_config()
    title = normalize_text(title)
    abstract = normalize_text(abstract)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(title, abstract)},
    ]
    content = _chat(messages, client)
    title_zh, abstract_zh = parse_output(content)
    issues = check_translation(title, abstract, title_zh, abstract_zh)
    attempts = 1
    if issues:
        messages += [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "上一版译文存在以下问题，请逐条修正后重新输出完整的 JSON（仍须忠实完整，不得增删内容）：\n"
                                        + "\n".join(f"{i + 1}. {msg}" for i, msg in enumerate(issues))},
        ]
        content = _chat(messages, client)
        attempts = 2
        retry_title, retry_abstract = parse_output(content)
        retry_issues = check_translation(title, abstract, retry_title, retry_abstract)
        if len(retry_issues) <= len(issues):
            title_zh, abstract_zh, issues = retry_title, retry_abstract, retry_issues
    return {
        "title_zh": title_zh,
        "abstract_zh": abstract_zh if abstract else "",
        "needs_review": bool(issues),
        "issues": issues,
        "attempts": attempts,
        "model": config.LLM_MODEL,
        "source_hash": source_hash(title, abstract),
        "translated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reviewed": False,
    }


# ---------------------------------------------------------------------------
# Cache and batch translation
# ---------------------------------------------------------------------------

def load_cache() -> dict[str, dict[str, Any]]:
    data = load_json(config.TRANSLATIONS_JSON, {})
    return data if isinstance(data, dict) else {}


_cache_lock = threading.Lock()


def save_cache(cache: dict[str, dict[str, Any]]) -> None:
    save_json(config.TRANSLATIONS_JSON, dict(sorted(cache.items())))


def update_cache(entries: dict[str, dict[str, Any]]) -> None:
    """Merge ``entries`` into the file (re-reading it first so concurrent writers do not clobber each other)."""
    with _cache_lock:
        cache = load_cache()
        cache.update(entries)
        save_cache(cache)


def cached_translation(paper: dict[str, Any], cache: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Cached entry if it still matches the paper's text (reviewed entries always count)."""
    entry = cache.get(paper.get("id", ""))
    if not entry:
        return None
    if entry.get("reviewed"):
        return entry
    if entry.get("source_hash") == source_hash(normalize_text(paper.get("title", "")), normalize_text(paper.get("abstract", ""))):
        return entry
    return None


def translate_paper(
    paper: dict[str, Any],
    cache: dict[str, dict[str, Any]] | None = None,
    force: bool = False,
    client: HttpClient | None = None,
) -> dict[str, Any]:
    """Translate a paper (using and updating the cache) and return its entry."""
    own_cache = cache is None
    cache = load_cache() if own_cache else cache
    existing = cache.get(paper["id"])
    if existing and existing.get("reviewed"):
        return existing
    if not force:
        hit = cached_translation(paper, cache)
        if hit:
            return hit
    entry = translate_text(paper.get("title", ""), paper.get("abstract", ""), client=client)
    cache[paper["id"]] = entry
    if own_cache:
        update_cache({paper["id"]: entry})
    return entry


def translate_papers(
    papers: Iterable[dict[str, Any]],
    force: bool = False,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    client: HttpClient | None = None,
) -> dict[str, Any]:
    """Translate papers lacking a current translation; saves after every paper."""
    cache = load_cache()
    todo = [p for p in papers if force or cached_translation(p, cache) is None]
    todo = [p for p in todo if not (cache.get(p["id"]) or {}).get("reviewed")]
    skipped_limit = max(0, len(todo) - limit) if limit else 0
    if limit:
        todo = todo[:limit]
    stats = {"requested": len(todo), "translated": 0, "needs_review": 0, "failed": 0,
             "skipped_over_limit": skipped_limit, "errors": []}
    for i, paper in enumerate(todo, 1):
        msg = f"[{i}/{len(todo)}] 翻译: {paper.get('title', '')[:70]}"
        logger.info(msg)
        if progress:
            progress(msg)
        try:
            entry = translate_paper(paper, cache, force=force, client=client)
        except TranslationError as exc:
            stats["failed"] += 1
            stats["errors"].append(f"{paper.get('id')}: {exc}")
            logger.warning("Translation failed for %s: %s", paper.get("id"), exc)
            if any(marker in str(exc) for marker in _FATAL_ERRORS):
                break
            continue
        stats["translated"] += 1
        stats["needs_review"] += 1 if entry.get("needs_review") else 0
        update_cache({paper["id"]: entry})
    return stats


def attach_translations(papers: list[dict[str, Any]], cache: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Shallow copies of ``papers`` carrying title_zh / abstract_zh / zh_needs_review when available."""
    cache = load_cache() if cache is None else cache
    out = []
    for p in papers:
        entry = cached_translation(p, cache)
        if entry:
            p = {**p, "title_zh": entry.get("title_zh", ""), "abstract_zh": entry.get("abstract_zh", ""),
                 "zh_needs_review": bool(entry.get("needs_review")) and not entry.get("reviewed"),
                 "zh_issues": entry.get("issues", [])}
        out.append(p)
    return out
