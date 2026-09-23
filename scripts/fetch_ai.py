"""Merge validated research items into stable RSS feeds in archive/ai/."""

from __future__ import annotations

import hashlib
import html
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scripts.ai_agent import ResearchAgent, web_url
from scripts.ai_sources import AiSource
from scripts.fetch_rss import FetchFailure, Source, atomic_write, utc_now


CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ARCHIVE_NS = "https://0xzhangke.github.io/signal-archive/ns"
ET.register_namespace("content", CONTENT_NS)
ET.register_namespace("archive", ARCHIVE_NS)
RETAIN_ITEMS = 200


def canonical_article_url(url: str) -> str:
    parts = urlsplit(web_url(url))
    # Only discard known tracking parameters; retain parameters that identify content.
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def article_guid(source_id: str, url: str) -> str:
    digest = hashlib.sha256((source_id + "\0" + canonical_article_url(url)).encode("utf-8")).hexdigest()
    return f"urn:signal-archive:ai:{digest[:32]}"


def existing_channel(content: bytes | None) -> ET.Element | None:
    if content is None:
        return None
    root = ET.fromstring(content)
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("existing AI archive is not an RSS feed")
    return channel


def recent_articles(content: bytes | None) -> list[dict]:
    channel = existing_channel(content)
    if channel is None:
        return []
    return [{"title": item.findtext("title", "")[:300], "url": item.findtext("link", ""),
             "publishedAt": item.findtext("pubDate")}
            for item in channel.findall("item")[:50]]


def item_sort_key(item: ET.Element) -> tuple[str, str]:
    published = item.findtext("pubDate")
    timestamp = parsedate_to_datetime(published).isoformat() if published else item.findtext(f"{{{ARCHIVE_NS}}}collectedAt", "")
    return timestamp, item.findtext("guid", "")


def merge_feed(source: AiSource, old_content: bytes | None, items: list[dict], now: str) -> bytes:
    old_channel = existing_channel(old_content)
    old_items = old_channel.findall("item") if old_channel is not None else []
    by_guid = {item.findtext("guid"): item for item in old_items}
    added = False
    for entry in items:
        guid = article_guid(source.id, entry["url"])
        if guid in by_guid:
            continue  # Keep the first curated version; no changes from model paraphrasing.
        item = ET.Element("item")
        ET.SubElement(item, "title").text = entry["title"]
        ET.SubElement(item, "link").text = canonical_article_url(entry["url"])
        ET.SubElement(item, "guid", isPermaLink="false").text = guid
        if entry["publishedAt"]:
            date = datetime.fromisoformat(entry["publishedAt"].replace("Z", "+00:00"))
            ET.SubElement(item, "pubDate").text = format_datetime(date)
        ET.SubElement(item, f"{{{ARCHIVE_NS}}}collectedAt").text = now
        ET.SubElement(item, "description").text = html.escape(entry["summary"])
        paragraphs = f"<p>{html.escape(entry['summary'])}</p>"
        if entry["keyPoints"]:
            paragraphs += "<ul>" + "".join(f"<li>{html.escape(point)}</li>" for point in entry["keyPoints"]) + "</ul>"
        paragraphs += "<h3>来源 / Sources</h3><ul>" + "".join(
            f'<li><a href="{html.escape(reference["url"], quote=True)}">{html.escape(reference["title"])}</a></li>'
            for reference in entry["references"]) + "</ul>"
        ET.SubElement(item, f"{{{CONTENT_NS}}}encoded").text = paragraphs
        by_guid[guid] = item
        added = True
    if old_content is not None and not added and old_channel.findtext("title") == source.title:
        return old_content
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = source.title
    ET.SubElement(channel, "link").text = "https://0xzhangke.github.io/signal-archive/"
    ET.SubElement(channel, "description").text = "AI 整理的公开网络内容，附原始来源。"
    for item in sorted(by_guid.values(), key=item_sort_key, reverse=True)[:RETAIN_ITEMS]:
        channel.append(item)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def collect_ai_nodes(catalog: dict) -> dict[str, list[dict]]:
    nodes: dict[str, list[dict]] = {}

    def visit(children: list) -> None:
        for node in children:
            if node.get("type") == "category":
                visit(node["children"])
            elif node.get("type") == "ai":
                nodes.setdefault(node["feedPath"], []).append(node)

    visit(catalog["children"])
    return nodes


def fetch_ai_catalog(catalog: dict, archive_root: Path, sources: list[AiSource],
                     agent_factory: Callable[[], ResearchAgent], *,
                     now: Callable[[], str] = utc_now) -> tuple[int, int, int, list[FetchFailure]]:
    nodes = collect_ai_nodes(catalog)
    configured = {source.feed_path: source for source in sources}
    if set(nodes) != set(configured):
        raise ValueError("AI configuration and catalog differ; regenerate the catalog before fetching")
    successful = changed = 0
    errors = []
    for path, source in configured.items():
        try:
            destination = archive_root / source.feed_path
            if not destination.resolve().is_relative_to(archive_root.resolve()):
                raise ValueError("AI feed path escapes the archive")
            old_content = destination.read_bytes() if destination.exists() else None
            agent = agent_factory()
            items = agent.run(source.read_prompt(), now=now(),
                              last_success=nodes[path][0].get("lastSuccessfulFetchAt"),
                              recent=recent_articles(old_content))
            fetched_at = now()
            content = merge_feed(source, old_content, items, fetched_at)
            ET.fromstring(content)
            content_changed = content != old_content
            if content_changed:
                atomic_write(destination, content)
                changed += 1
            for node in nodes[path]:
                node["lastSuccessfulFetchAt"] = fetched_at
                if content_changed:
                    node["lastContentChangedAt"] = fetched_at
            successful += 1
            print(f"AI {source.id}: items={len(items)} changed={content_changed} usage={agent.usage}")
        except Exception as error:  # A failed AI source must not discard other sources.
            errors.append(FetchFailure(Source(path, f"ai:{source.id}", tuple(nodes[path])), str(error)))
    return len(sources), successful, changed, errors
