"""
Domain knowledge retrieval for the agent.

Why this exists: the agent used to answer concept questions out of the model's own priors. That is
unacceptable here for a specific reason — the platform has documented simplifications (the fusion
layer receives the ground-truth target state except under ``KALMAN_FILTER``; one seed is one
sample; the Kalman process noise is an assumption). A model asked "what does the fusion layer
estimate?" will answer plausibly and *wrongly*, because it does not know the platform. Retrieval
grounds the answer in text that was written from the Java core, and the answer carries the source
titles so a reader can check it.

**There is deliberately no vector database.** The corpus is small (a few dozen sections) and the
queries are dominated by exact domain terms ("卡尔曼滤波", "trackingRate", "资源利用率"), which is
the regime where a lexical index is not just cheaper but *more* precise — an embedding search would
happily return the scheduling section for a question about fusion. BM25 over a domain-lexicon
tokenisation runs in microseconds, needs no service, no key, and no index file, and it is
deterministic, which matters because the agent's evidence has to be reproducible. The seam for a
different scorer is ``KnowledgeIndex.search``; if the corpus grows past a few hundred chunks or
questions start arriving as paraphrases, an embedding re-ranker can be dropped in behind it
without touching any caller. See ``docs/architecture/knowledge-retrieval.md``.

Two details carry most of the quality:

* **Tokenisation is dictionary-driven for CJK.** No ``jieba`` dependency: a curated multi-character
  lexicon (融合, 卡尔曼滤波, 资源利用率 …) is matched against each CJK run, *and* character bigrams
  are added as a fallback so an out-of-lexicon word still matches. Bigrams alone would make
  "什么是卡尔曼滤波" and "什么是轮询调度" share the low-information "什么/么是" pairs; the lexicon
  terms are what actually discriminate.
* **Synonyms map a question's vocabulary onto the corpus's.** A user asking about "定位精度" needs
  the ``averagePositionError`` section; "怎么算" plus a metric name should find the definition
  section rather than the reading-guide section. Both directions are encoded in ``SYNONYMS``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import KNOWLEDGE_DIR

DEFAULT_LIMIT = 3
# A hit must reach this fraction of the best score to be kept. Without it, a query that matches one
# section well drags marginal sections into the context and into the citation list. It is
# deliberately low: a strong match usually has supporting sections behind it (the Kalman section is
# followed by the note that its velocity is the only estimate on the platform), and those are worth
# carrying. The ``limit`` cap already bounds the noise.
RELATIVE_FLOOR = 0.25

BM25_K1 = 1.5
BM25_B = 0.75
# A term in the section heading is what the section is *about*; the same term buried in the body is
# often incidental. Without this split, a question about position error ranks the generic "how to
# read metrics together" section first, because that section mentions the word "metric" more often.
TITLE_BOOST = 2.4
# The document-level tags are hand-maintained, so a hit there is a deliberate signal.
TAG_BOOST = 1.6

ASCII_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.+-]*")
ASCII_PARTS = re.compile(r"[_.+-]+")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
# A heading like "卡尔曼滤波 KALMAN_FILTER kalman filter" is great for retrieval and noisy as a UI
# label, so the trailing latin aliases are stripped for display.
TRAILING_ASCII = re.compile(r"[\s·]*[A-Za-z_][A-Za-z0-9_ .+-]*$")


# Function words and low-information pairs. These appear in question after question, so keeping them
# would let two unrelated questions look similar. The discriminative terms are the entity names.
STOPWORDS = frozenset(
    {
        "的", "了", "是", "吗", "呢", "我", "你", "他", "它", "和", "与", "或", "在", "有", "会",
        "什么", "么是", "么意", "为什", "怎么", "么样", "如何", "哪些", "哪个", "一下", "可以",
        "不能", "这个", "那个", "这些", "那些", "我们", "你们", "它们", "帮我", "请问", "请帮",
        "告诉", "解释", "介绍", "说明", "区别", "差异", "不同", "哪个好", "怎么样", "是不是",
        "的是", "是一", "一下", "有什", "都", "就", "还", "也", "很", "让", "把", "被",
        "the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or", "in", "on",
        "for", "with", "what", "which", "how", "why", "does", "do", "it", "this", "that",
        "please", "tell", "explain", "about", "me", "you",
    }
)


# Multi-character domain terms, used both to segment CJK text and to recognise an entity in a
# question. Longest terms first so the specific name is preferred over its prefix.
LEXICON: tuple[str, ...] = tuple(
    sorted(
        {
            "卡尔曼滤波", "卡尔曼", "加权平均", "置信度加权", "简单平均", "最近邻", "距离门限",
            "门限", "融合方法", "融合算法", "数据融合", "观测融合", "融合位置", "融合速度",
            "轮询", "优先级", "调度策略", "调度切换", "资源调度", "资源分配", "资源利用率",
            "可用资源", "平均等待时间", "等待时间", "跟踪率", "位置误差", "平均位置误差",
            "目标数", "观测源", "观测模型", "观测时延", "时延", "缺失率", "噪声", "标准差",
            "置信度", "先验知识", "光电红外", "雷达", "随机种子", "种子", "仿真步数", "时步",
            "步长", "目标运动", "匀速直线", "机动", "杂波", "虚警", "漏检", "真值", "场景",
            "配置", "字段", "取值范围", "校验", "复现", "确定性", "可复现", "缓存", "基线",
            "对照", "单种子", "样本", "蒙特卡洛", "敏感性", "过程噪声", "简化假设", "局限性",
            "速度", "位置", "精度", "定位精度", "误差", "指标", "流程", "确认", "运行记录",
            "实验", "对比", "比较", "多步实验", "探索性",
        },
        key=len,
        reverse=True,
    )
)


# Query vocabulary -> corpus vocabulary. Keys and values are compared after tokenisation, so a key
# like "定位精度" matches only if the lexicon produced that token.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "定位精度": ("averagepositionerror", "位置误差", "误差"),
    "精度": ("averagepositionerror", "位置误差", "误差"),
    "误差": ("averagepositionerror", "位置误差"),
    "跟踪": ("trackingrate", "跟踪率"),
    "跟踪率": ("trackingrate",),
    "利用率": ("resourceutilization", "资源利用率"),
    "资源利用率": ("resourceutilization",),
    "等待": ("averagewaitingtime", "平均等待时间", "等待时间"),
    "平均等待时间": ("averagewaitingtime",),
    "切换": ("schedulingswitches", "调度切换"),
    "调度切换": ("schedulingswitches",),
    "卡尔曼": ("kalman_filter", "kalman", "卡尔曼滤波"),
    "卡尔曼滤波": ("kalman_filter", "kalman"),
    "加权平均": ("weighted_average",),
    "置信度加权": ("weighted_average", "加权平均"),
    "简单平均": ("simple_average",),
    "最近邻": ("nearest_neighbor", "nearest", "neighbor"),
    "距离门限": ("distance_gated", "门限"),
    "门限": ("distance_gated", "距离门限"),
    "轮询": ("round_robin",),
    "优先级": ("priority",),
    "种子": ("randomseed", "随机种子"),
    "随机种子": ("randomseed",),
    "缓存": ("determinism", "缓存", "确定性"),
    "复现": ("determinism", "reproducibility", "确定性"),
    "确定性": ("determinism", "确定性"),
    "机动": ("process", "noise", "机动"),
    "过程噪声": ("process", "noise"),
    "虚警": ("clutter", "虚警"),
    "杂波": ("clutter",),
    "融合": ("fusion", "fusionmethod", "融合方法"),
    "速度": ("velocity", "速度"),
    "流程": ("workflow", "流程"),
    "怎么做实验": ("workflow", "实验步骤"),
    "确认": ("confirmation", "确认"),
}


@dataclass(frozen=True)
class KnowledgeChunk:
    """One retrievable section of the corpus."""

    chunk_id: str
    doc: str
    title: str
    label: str
    tags: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class KnowledgeHit:
    chunk: KnowledgeChunk
    score: float

    def as_citation(self) -> dict[str, object]:
        """The UI-facing form: what was used and how strongly it matched."""
        return {
            "chunk_id": self.chunk.chunk_id,
            "doc": self.chunk.doc,
            "title": self.chunk.label,
            "score": round(self.score, 3),
        }


def cjk_tokens(run: str) -> list[str]:
    """Lexicon terms found in a CJK run, plus character bigrams as a fallback."""
    tokens = [term for term in LEXICON if term in run]
    if len(run) == 1:
        tokens.append(run)
    else:
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def tokenize(text: str) -> list[str]:
    """
    Split text into search tokens.

    ASCII keeps ``snake_case`` names whole (``weighted_average`` is the enum value and must match
    as one term) *and* contributes its parts, so a question asking about "the average error" still
    reaches a section whose only mention is ``WEIGHTED_AVERAGE``.
    """
    lowered = (text or "").lower()
    tokens: list[str] = []
    for word in ASCII_TOKEN.findall(lowered):
        tokens.append(word)
        if any(separator in word for separator in "_.+-"):
            tokens.extend(part for part in ASCII_PARTS.split(word) if len(part) >= 3)
    for run in CJK_RUN.findall(lowered):
        tokens.extend(cjk_tokens(run))
    return [token for token in tokens if token not in STOPWORDS]


def expand_query(query: str) -> list[str]:
    """Query tokens, widened by the synonym table."""
    tokens = tokenize(query)
    seen: dict[str, None] = {}
    for token in tokens:
        seen.setdefault(token, None)
        for alias in SYNONYMS.get(token, ()):
            seen.setdefault(alias, None)
    return list(seen)


def _slug(heading: str, index: int) -> str:
    """
    A stable, readable id for a section.

    It has to survive a mixed-case heading: ``trackingRate`` lowercased is one word, but matching
    the lowercase-only token pattern against the original text would split it into ``tracking`` and
    ``ate``. Part words are dropped once a longer word already contains them, so
    ``KALMAN_FILTER kalman filter`` gives ``kalman_filter`` rather than three near-duplicates.
    """
    words = [match.group(0) for match in ASCII_TOKEN.finditer(heading.lower()) if len(match.group(0)) >= 3]
    kept: list[str] = []
    for word in words:
        if any(word in existing for existing in kept):
            continue
        kept.append(word)
    if kept:
        return "-".join(kept[:4])
    terms = [term for term in LEXICON if term in heading]
    if terms:
        return terms[0]
    return f"section-{index}"


def _label(heading: str) -> str:
    stripped = TRAILING_ASCII.sub("", heading).strip(" ·-")
    return stripped or heading


def parse_document(text: str, fallback_doc: str) -> list[KnowledgeChunk]:
    """
    Split one markdown file into chunks, one per ``##`` heading.

    Granularity is the whole point: a section is the smallest unit that still answers something, so
    retrieval can hand the model the three sections it needs rather than a whole document.
    """
    doc = fallback_doc
    doc_tags: tuple[str, ...] = ()
    body_lines: list[str] = []
    lines = text.splitlines()
    index = 0
    if lines and lines[0].strip() == "---":
        index = 1
        while index < len(lines) and lines[index].strip() != "---":
            key, _, value = lines[index].partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "doc" and value:
                doc = value
            elif key == "tags" and value:
                doc_tags = tuple(part.strip() for part in value.split(",") if part.strip())
            index += 1
        index += 1
    body_lines = lines[index:]

    chunks: list[KnowledgeChunk] = []
    heading: str | None = None
    buffer: list[str] = []
    counter = 0

    def flush() -> None:
        nonlocal counter
        if heading is None:
            return
        text_block = "\n".join(buffer).strip()
        if not text_block:
            return
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{doc}#{_slug(heading, counter)}",
                doc=doc,
                title=heading,
                label=_label(heading),
                tags=doc_tags,
                text=text_block,
            )
        )
        counter += 1

    for line in body_lines:
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            buffer = []
        elif heading is not None:
            buffer.append(line)
    flush()
    return chunks


def load_corpus(directory: Path) -> list[KnowledgeChunk]:
    """Read every ``.md`` file in the knowledge directory. A missing corpus yields no chunks."""
    if not directory.is_dir():
        return []
    chunks: list[KnowledgeChunk] = []
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        chunks.extend(parse_document(text, fallback_doc=path.stem))
    return chunks


class KnowledgeIndex:
    """BM25 index over the corpus, plus the tag boost that rewards an explicit mention."""

    def __init__(self, chunks: Iterable[KnowledgeChunk]):
        self.chunks: list[KnowledgeChunk] = list(chunks)
        self._term_frequencies: list[dict[str, int]] = []
        self._lengths: list[int] = []
        self._title_tokens: list[frozenset[str]] = []
        self._tag_tokens: list[frozenset[str]] = []
        self._document_frequency: dict[str, int] = {}

        for chunk in self.chunks:
            searchable = f"{chunk.title} {chunk.text} {' '.join(chunk.tags)}"
            counts: dict[str, int] = {}
            for token in tokenize(searchable):
                counts[token] = counts.get(token, 0) + 1
            self._term_frequencies.append(counts)
            self._lengths.append(max(1, sum(counts.values())))
            self._title_tokens.append(frozenset(tokenize(chunk.title)))
            self._tag_tokens.append(frozenset(tokenize(" ".join(chunk.tags))))
            for token in counts:
                self._document_frequency[token] = self._document_frequency.get(token, 0) + 1

        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 1.0
        )

    def __len__(self) -> int:
        return len(self.chunks)

    def _idf(self, token: str) -> float:
        total = len(self.chunks)
        frequency = self._document_frequency.get(token, 0)
        # A term in no document still gets a small positive weight so it cannot be distinguished
        # from a total miss by accident; it simply contributes almost nothing.
        return math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> list[KnowledgeHit]:
        """
        Return the best-matching sections, best first.

        Only sections sharing at least one term with the query can match, so an unrelated question
        returns nothing rather than the least-bad section. The caller relies on that: an empty
        result is what tells the agent to say it has no material instead of improvising.
        """
        terms = expand_query(query)
        if not terms or not self.chunks:
            return []

        scored: list[KnowledgeHit] = []
        for position, chunk in enumerate(self.chunks):
            counts = self._term_frequencies[position]
            length = self._lengths[position]
            score = 0.0
            for term in terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                weight = (frequency * (BM25_K1 + 1)) / (
                    frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / self._average_length)
                )
                if term in self._title_tokens[position]:
                    weight *= TITLE_BOOST
                if term in self._tag_tokens[position]:
                    weight *= TAG_BOOST
                score += self._idf(term) * weight
            if score > 0:
                scored.append(KnowledgeHit(chunk=chunk, score=score))

        if not scored:
            return []
        scored.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        best = scored[0].score
        kept = [hit for hit in scored if hit.score >= best * RELATIVE_FLOOR]
        return kept[: max(1, limit)]


_CORPUS_CACHE: dict[str, KnowledgeIndex] = {}


def corpus_directory() -> Path:
    """The configured corpus directory, defaulting to ``agent-service/knowledge``."""
    if KNOWLEDGE_DIR:
        return Path(KNOWLEDGE_DIR).expanduser()
    return Path(__file__).resolve().parent.parent / "knowledge"


def get_index() -> KnowledgeIndex:
    """
    The process-wide index, built on first use.

    Keyed by directory so a test can point at its own corpus without disturbing the real one, and so
    the corpus is read from disk exactly once per process.
    """
    key = str(corpus_directory())
    index = _CORPUS_CACHE.get(key)
    if index is None:
        index = KnowledgeIndex(load_corpus(corpus_directory()))
        _CORPUS_CACHE[key] = index
    return index


def reset_cache() -> None:
    """Drop the cached index. Used by tests and after editing the corpus on a running service."""
    _CORPUS_CACHE.clear()


def retrieve(query: str, limit: int = DEFAULT_LIMIT) -> list[KnowledgeHit]:
    return get_index().search(query, limit=limit)


def render_context(hits: list[KnowledgeHit]) -> str:
    """
    The block handed to the model as grounding.

    Each entry is numbered and labelled with its section title so the model can cite it and so a
    reader of the transcript can tell which claim came from which section.
    """
    if not hits:
        return ""
    blocks = [
        f"[{position}] 《{hit.chunk.label}》（{hit.chunk.doc}）\n{hit.chunk.text}"
        for position, hit in enumerate(hits, start=1)
    ]
    return "\n\n".join(blocks)


def citations(hits: list[KnowledgeHit]) -> list[dict[str, object]]:
    return [hit.as_citation() for hit in hits]
