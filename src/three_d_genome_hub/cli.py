"""Command line interface for 3DGenomeHub."""

from __future__ import annotations

from pathlib import Path
import typer

from .config import DEFAULT_DATA_FILE, DEFAULT_DB_PATH, DEFAULT_INDEX_PATH
from .ingestion.loader import KnowledgeBaseRepository
from .ingestion.schema import flatten_resources
from .knowledge_base import KnowledgeBase
from .utils.logging import configure_logging

app = typer.Typer(help="3DGenomeHub 管理工具")
LOGGER = configure_logging(name="three_d_genome_hub.cli")


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


@app.command()
def ingest(
    data_file: Path = typer.Argument(
        ..., exists=True, readable=True, help="YAML/JSON 数据文件"
    ),
    database: Path = typer.Option(DEFAULT_DB_PATH, help="SQLite 数据库路径"),
) -> None:
    """导入知识库资源。"""

    data_file = _resolve_path(data_file)
    database = _resolve_path(database)
    repo = KnowledgeBaseRepository(database)
    bundle = flatten_resources([data_file])
    count = repo.upsert_resources(bundle.resources)
    typer.echo(f"已导入 {count} 条资源到 {database}")


@app.command("build-index")
def build_index(
    database: Path = typer.Option(DEFAULT_DB_PATH, help="SQLite 数据库路径"),
    output: Path = typer.Option(DEFAULT_INDEX_PATH, help="向量索引输出路径"),
) -> None:
    """构建 TF-IDF 索引。"""

    database = _resolve_path(database)
    output = _resolve_path(output)
    kb = KnowledgeBase(KnowledgeBaseRepository(database), index_path=output)
    kb.build_index(output)
    typer.echo(f"索引已生成：{output}")


@app.command()
def query(
    text: str = typer.Argument(..., help="查询内容"),
    database: Path = typer.Option(DEFAULT_DB_PATH, help="SQLite 数据库路径"),
    index_path: Path = typer.Option(DEFAULT_INDEX_PATH, help="向量索引路径"),
    top_k: int = typer.Option(5, help="返回结果数量"),
) -> None:
    """执行语义检索。"""

    database = _resolve_path(database)
    index_path = _resolve_path(index_path)
    kb = KnowledgeBase(KnowledgeBaseRepository(database), index_path=index_path)
    kb.load_index(index_path)
    results = kb.search(text, top_k=top_k)
    if not results:
        typer.echo("未找到匹配结果")
        raise typer.Exit(code=0)
    for item in results:
        typer.echo(f"[{item.score:.3f}] {item.resource.title} ({item.resource.category}) -> {item.resource.url}")


@app.command()
def bootstrap(
    data_file: Path = typer.Option(DEFAULT_DATA_FILE, help="默认 YAML 文件"),
    database: Path = typer.Option(DEFAULT_DB_PATH, help="SQLite 数据库路径"),
    index_path: Path = typer.Option(DEFAULT_INDEX_PATH, help="索引路径"),
) -> None:
    """快速构建示例知识库。"""

    data_file = _resolve_path(data_file)
    database = _resolve_path(database)
    index_path = _resolve_path(index_path)
    repo = KnowledgeBaseRepository(database)
    bundle = flatten_resources([data_file])
    repo.upsert_resources(bundle.resources)
    kb = KnowledgeBase(repo, index_path=index_path)
    kb.build_index(index_path)
    typer.echo("示例知识库构建完成。")


if __name__ == "__main__":
    app()
