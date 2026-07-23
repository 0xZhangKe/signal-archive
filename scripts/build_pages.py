#!/usr/bin/env python3
"""Build the static GitHub Pages reader from an archive catalog and feeds."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlparse


CONTENT_TAGS = {"encoded", "content"}
SUMMARY_TAGS = {"description", "summary"}
SAFE_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "div", "em",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "i", "img", "kbd", "li", "mark", "ol", "p", "pre", "q", "s",
    "small", "span", "strong", "sub", "sup", "table", "tbody", "td",
    "th", "thead", "tr", "u", "ul",
}
VOID_TAGS = {"br", "hr", "img"}
DROP_CONTENT_TAGS = {"button", "canvas", "embed", "form", "iframe", "input", "object", "script", "style", "svg", "textarea"}
SAFE_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
PAGE_SIZE = 60


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def short_hash(value: str, length: int = 20) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def source_id(feed_path: str) -> str:
    identifier = PurePosixPath(feed_path).stem
    if not identifier:
        raise ValueError(f"cannot derive source ID from feedPath: {feed_path!r}")
    return identifier


def folder_id(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title.strip())
    if not normalized:
        raise ValueError("cannot derive folder ID from an empty title")
    return f"folder-{short_hash(normalized, 16)}"


def safe_archive_path(archive_root: Path, feed_path: str) -> Path:
    path = PurePosixPath(feed_path)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] not in {("rss",), ("ai",)}:
        raise ValueError(f"unsafe feedPath in catalog: {feed_path!r}")
    return archive_root.joinpath(*path.parts)


def node_title(node: dict[str, Any]) -> str:
    title = node.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else "未命名来源"


def flatten_sources(nodes: Iterable[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "category":
            for child in node.get("children", []):
                visit(child)
            return
        feed_path = node.get("feedPath")
        if not isinstance(feed_path, str) or not feed_path or feed_path in seen:
            return
        seen.add(feed_path)
        flattened.append(node)

    for item in nodes:
        visit(item)
    return flattened


def build_rendered(
    catalog: dict[str, Any],
    source_pages: dict[str, list[str]] | None = None,
    folder_pages: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[str]]]:
    children = catalog.get("children")
    if not isinstance(children, list):
        raise ValueError("catalog must contain a children array")

    source_pages = source_pages or {}
    folder_pages = folder_pages or {}
    items: list[dict[str, Any]] = []
    unique_sources: dict[str, dict[str, Any]] = {}
    folders: dict[str, list[str]] = {}
    category_titles: set[str] = set()

    def validate_category_titles(nodes: Iterable[Any]) -> None:
        for node in nodes:
            if not isinstance(node, dict) or node.get("type") != "category":
                continue
            title = node_title(node)
            normalized = unicodedata.normalize("NFC", title)
            if normalized in category_titles:
                raise ValueError(f"category titles must be globally unique: {title!r}")
            category_titles.add(normalized)
            validate_category_titles(node.get("children", []))

    validate_category_titles(children)

    def source_view(source: dict[str, Any]) -> dict[str, Any]:
        feed_path = source.get("feedPath")
        if not isinstance(feed_path, str) or not feed_path:
            raise ValueError(f"source {node_title(source)!r} is missing feedPath")
        unique_sources.setdefault(feed_path, source)
        identifier = source_id(feed_path)
        view = {
            "pages": source_pages.get(identifier, []),
            "lastContentChangedAt": source.get("lastContentChangedAt"),
            "lastSuccessfulFetchAt": source.get("lastSuccessfulFetchAt"),
            "originalUrl": source.get("originalUrl"),
            "title": node_title(source),
            "type": source.get("type", "rss"),
        }
        return view

    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "category":
            flattened = flatten_sources(child.get("children", []))
            identifier = folder_id(node_title(child))
            feed_paths = [source["feedPath"] for source in flattened]
            folders[identifier] = feed_paths
            items.append({
                "pages": folder_pages.get(identifier, []),
                "children": [source_view(source) for source in flattened],
                "type": "category",
                "title": node_title(child),
            })
        else:
            items.append(source_view(child))

    return {"children": items}, unique_sources, folders


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    if len(element):
        return (element.text or "") + "".join(ET.tostring(child, encoding="unicode") for child in element)
    return element.text or ""


def first_child(element: ET.Element, names: set[str]) -> ET.Element | None:
    return next((child for child in element if local_name(child.tag) in names), None)


def first_text(element: ET.Element, names: set[str]) -> str:
    return element_text(first_child(element, names)).strip()


def normalize_date(value: str) -> tuple[str | None, float]:
    if not value:
        return None, 0
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value, 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z"), parsed.timestamp()


def valid_web_url(value: str) -> str | None:
    value = html.unescape(value.strip())
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    return value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else None


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class FirstImageExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.src: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.src is not None or tag.lower() != "img":
            return
        value = dict(attrs).get("src")
        if value:
            self.src = valid_web_url(value)


class HtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth or tag not in SAFE_TAGS:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            name = name.lower()
            if value is None or name not in SAFE_ATTRS.get(tag, set()):
                continue
            if name in {"href", "src"}:
                value = valid_web_url(value)
                if value is None:
                    continue
            safe_attrs.append(f'{name}="{html.escape(value, quote=True)}"')
        if tag == "a":
            safe_attrs.extend(['target="_blank"', 'rel="noopener noreferrer"'])
        suffix = " " + " ".join(safe_attrs) if safe_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in DROP_CONTENT_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if not self.drop_depth and tag in SAFE_TAGS and tag not in VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.drop_depth:
            self.parts.append(html.escape(data))


def plain_text(value: str, limit: int | None = None) -> str:
    parser = TextExtractor()
    parser.feed(value)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    if limit is not None and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def sanitize_html(value: str) -> str:
    parser = HtmlSanitizer()
    parser.feed(value)
    return "".join(parser.parts).strip()


def first_image(value: str) -> str | None:
    parser = FirstImageExtractor()
    parser.feed(value)
    return parser.src


def item_image(item: ET.Element, content: str) -> str | None:
    for element in item.iter():
        name = local_name(element.tag)
        if name in {"enclosure", "content", "thumbnail"}:
            url = valid_web_url(element.get("url", ""))
            media_type = (element.get("type") or "").lower()
            medium = (element.get("medium") or "").lower()
            if url and (name == "thumbnail" or medium == "image" or media_type.startswith("image/")):
                return url
    return first_image(content)


def atom_link(entry: ET.Element) -> str:
    fallback = ""
    for child in entry:
        if local_name(child.tag) != "link":
            continue
        href = child.get("href") or element_text(child).strip()
        if not href:
            continue
        if child.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


def parse_feed(path: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"cannot parse feed {path}: {error}") from error

    root_name = local_name(root.tag)
    if root_name == "feed":
        elements = [child for child in root if local_name(child.tag) == "entry"]
        is_atom = True
    elif root_name in {"rss", "rdf"}:
        elements = [element for element in root.iter() if local_name(element.tag) == "item"]
        is_atom = False
    else:
        raise ValueError(f"unsupported feed root <{root.tag}> in {path}")

    feed_path = source["feedPath"]
    identifier = source_id(feed_path)
    source_title = node_title(source)
    articles: list[dict[str, Any]] = []
    for position, item in enumerate(elements):
        title = plain_text(first_text(item, {"title"})) or "无标题文章"
        link = atom_link(item) if is_atom else first_text(item, {"link"})
        link = valid_web_url(link) or ""
        guid = first_text(item, {"id", "guid"})
        date_value = first_text(item, {"published", "updated", "pubdate", "date"})
        published_at, sort_time = normalize_date(date_value)

        content = first_text(item, CONTENT_TAGS)
        summary_html = first_text(item, SUMMARY_TAGS)
        if not content:
            content = summary_html
        if not summary_html:
            summary_html = content
        safe_content = sanitize_html(content)
        summary = plain_text(summary_html, 360)
        identity = guid or link or f"{title}\0{date_value}\0{position}"
        article_id = short_hash(feed_path + "\0" + identity, 24)
        detail_path = f"articles/{article_id}.json"
        articles.append({
            "id": article_id,
            "title": title,
            "summary": summary,
            "image": item_image(item, content or summary_html),
            "publishedAt": published_at,
            "sortTime": sort_time,
            "sourceId": identifier,
            "sourceTitle": source_title,
            "link": link or None,
            "feedPath": feed_path,
            "detailPath": detail_path,
            "content": safe_content or f"<p>{html.escape(summary)}</p>",
        })
    return articles


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_item(article: dict[str, Any]) -> dict[str, Any]:
    return {
        key: article.get(key)
        for key in (
            "id",
            "title",
            "summary",
            "image",
            "publishedAt",
            "sourceId",
            "sourceTitle",
            "link",
            "detailPath",
        )
    }


def article_detail(article: dict[str, Any]) -> dict[str, Any]:
    return {
        key: article.get(key)
        for key in (
            "id",
            "title",
            "summary",
            "content",
            "image",
            "publishedAt",
            "sourceId",
            "sourceTitle",
            "link",
        )
    }


def write_article_pages(
    data_root: Path,
    identifier: str,
    articles: list[dict[str, Any]],
) -> list[str]:
    paths: list[str] = []
    for offset in range(0, len(articles), PAGE_SIZE):
        page_number = offset // PAGE_SIZE + 1
        relative_path = f"categories/{identifier}/page-{page_number:03d}.json"
        write_json(data_root / relative_path, {
            "items": [list_item(article) for article in articles[offset:offset + PAGE_SIZE]],
        })
        paths.append(relative_path)
    return paths


def build_pages(catalog_path: Path, archive_root: Path, site_root: Path, output: Path) -> dict[str, int]:
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read catalog {catalog_path}: {error}") from error
    if not isinstance(catalog, dict):
        raise ValueError("catalog must contain a JSON object")

    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(site_root, output)
    data_root = output / "data"
    source_state_path = archive_root / "source_state.json"
    if source_state_path.exists():
        try:
            source_state = json.loads(source_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read source state {source_state_path}: {error}") from error
        if not isinstance(source_state, list):
            raise ValueError("source_state.json must contain a JSON array")
    else:
        source_state = []
    write_json(data_root / "source_state.json", source_state)

    _, sources, folders = build_rendered(catalog)
    articles_by_source: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, str]] = []
    article_details: dict[str, dict[str, Any]] = {}

    for feed_path, source in sources.items():
        source["feedPath"] = feed_path
        feed_file = safe_archive_path(archive_root, feed_path)
        try:
            articles = parse_feed(feed_file, source) if feed_file.exists() else []
        except ValueError as error:
            failures.append({"feedPath": feed_path, "error": str(error)})
            articles = []
        articles.sort(key=lambda article: article["sortTime"], reverse=True)
        articles_by_source[feed_path] = articles
        for article in articles:
            article_details.setdefault(article["id"], article)

    for article in article_details.values():
        write_json(
            data_root / "articles" / f"{article['id']}.json",
            article_detail(article),
        )

    source_pages: dict[str, list[str]] = {}
    for feed_path, articles in articles_by_source.items():
        identifier = source_id(feed_path)
        source_pages[identifier] = write_article_pages(data_root, identifier, articles)

    folder_pages: dict[str, list[str]] = {}
    for identifier, feed_paths in folders.items():
        merged: dict[str, dict[str, Any]] = {}
        for feed_path in feed_paths:
            for article in articles_by_source.get(feed_path, []):
                merged.setdefault(article["id"], article)
        category_articles = sorted(merged.values(), key=lambda article: article["sortTime"], reverse=True)
        folder_pages[identifier] = write_article_pages(data_root, identifier, category_articles)

    rendered, _, _ = build_rendered(catalog, source_pages, folder_pages)
    write_json(data_root / "rendered.json", rendered)
    return {
        "sources": len(sources),
        "articles": len(article_details),
        "failures": len(failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        summary = build_pages(args.catalog, args.archive_root, args.site_root, args.output)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "Pages build complete: "
        f"sources={summary['sources']} articles={summary['articles']} failures={summary['failures']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
