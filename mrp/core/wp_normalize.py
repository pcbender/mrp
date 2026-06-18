from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


FORBIDDEN_ARTIFACT_RE = re.compile(
    r"wp-block|<!--\s*/?\s*wp:|\bstk-|stackable|/wp-content/(?:plugins|themes)/",
    re.IGNORECASE,
)
WORDPRESS_COMMENT_RE = re.compile(r"<!--\s*/?\s*wp:[\s\S]*?-->", re.IGNORECASE)
SHORTCODE_RE = re.compile(r"\[([a-z_][a-z0-9_-]*)([^\]]*)\]", re.IGNORECASE)


SOCIAL_HOSTS = {
    "open.spotify.com": "spotify",
    "spotify.com": "spotify",
    "music.apple.com": "apple_music",
    "apple.com": "apple_music",
    "music.youtube.com": "youtube_music",
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "youtu.be": "youtube",
    "bandcamp.com": "bandcamp",
    "soundcloud.com": "soundcloud",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
}


@dataclass
class NormalizedWordPressContent:
    content_html: str
    content_markdown: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, str | None]] = field(default_factory=list)
    socials: dict[str, str] = field(default_factory=dict)
    unresolved_artifacts: list[dict[str, str]] = field(default_factory=list)


def normalize_wordpress_content(html: str, source_path: str) -> NormalizedWordPressContent:
    raw = unescape(html or "")
    sections = detect_sections(raw)
    cleaned_source = SHORTCODE_RE.sub("", WORDPRESS_COMMENT_RE.sub("", raw))
    parser = SemanticHtmlParser()
    parser.feed(cleaned_source)
    parser.close()
    content_html = collapse_blank_lines(parser.html()).strip()
    content_markdown = collapse_blank_lines(parser.markdown()).strip()
    unresolved = unresolved_artifacts(content_html, source_path)
    return NormalizedWordPressContent(
        content_html=content_html,
        content_markdown=content_markdown,
        sections=sections,
        images=parser.images,
        socials=parser.socials,
        unresolved_artifacts=unresolved,
    )


def detect_sections(raw: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    lowered = raw.lower()
    for match in SHORTCODE_RE.finditer(raw):
        if match.group(1).lower() == "child_pages" and "thumbs" in match.group(2).lower():
            add_section(sections, {"type": "artist_releases"})
    if "stk-block-posts" in lowered or "stackable/posts" in lowered:
        if "/artists/" in lowered and not re.search(r"/artists/[^\"' <]+/[^\"' <]+", lowered):
            add_section(sections, {"type": "artist_carousel"})
        else:
            add_section(sections, {"type": "latest_releases"})
    if "stk-block-carousel" in lowered:
        if "/artists/" in lowered:
            add_section(sections, {"type": "artist_carousel"})
        if "/releases/" in lowered or re.search(r"/artists/[^\"' <]+/[^\"' <]+", lowered):
            add_section(sections, {"type": "latest_releases"})
    return sections


def add_section(sections: list[dict[str, Any]], section: dict[str, Any]) -> None:
    if section not in sections:
        sections.append(section)


def unresolved_artifacts(value: str, source_path: str) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for match in FORBIDDEN_ARTIFACT_RE.finditer(value):
        start = max(match.start() - 40, 0)
        end = min(match.end() + 40, len(value))
        artifacts.append(
            {
                "path": source_path,
                "artifact": match.group(0),
                "snippet": value[start:end].replace("\n", " "),
                "reason": "WordPress-specific artifact remains after semantic normalization.",
            }
        )
    return artifacts


def collapse_blank_lines(value: str) -> str:
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value


class SemanticHtmlParser(HTMLParser):
    block_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
    passthrough_tags = {"strong", "em", "br"}
    skip_tags = {"script", "style", "svg", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._html: list[str] = []
        self._markdown: list[str] = []
        self._tag_stack: list[str] = []
        self._skip_depth = 0
        self._link_stack: list[dict[str, str]] = []
        self.images: list[dict[str, str | None]] = []
        self.socials: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        if tag in self.skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self.block_tags:
            self._open_block(tag)
        elif tag in {"ul", "ol"}:
            self._append_html(f"<{tag}>")
            self._append_markdown("\n")
            self._tag_stack.append(tag)
        elif tag in self.passthrough_tags:
            self._append_html("<br>" if tag == "br" else f"<{tag}>")
            self._append_markdown("\n" if tag == "br" else markdown_marker(tag))
            if tag != "br":
                self._tag_stack.append(tag)
        elif tag == "a":
            href = clean_url(attr_map.get("href", ""))
            if href and not is_plugin_or_theme_asset(href):
                self._append_html(f'<a href="{escape(href, quote=True)}">')
                self._append_markdown("[")
                self._link_stack.append({"href": href, "text": ""})
                self._tag_stack.append(tag)
                social = social_key(href)
                if social and social not in self.socials:
                    self.socials[social] = href
        elif tag == "img":
            src = clean_url(attr_map.get("src", ""))
            alt = unescape(attr_map.get("alt", "")).strip() or None
            if src and not is_plugin_or_theme_asset(src):
                self.images.append({"src": src, "alt": alt})
                alt_attr = f' alt="{escape(alt, quote=True)}"' if alt else ""
                self._append_html(f'<img src="{escape(src, quote=True)}"{alt_attr}>')
                self._append_markdown(f"![{alt or ''}]({src})")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.skip_tags:
            self._skip_depth = max(self._skip_depth - 1, 0)
            return
        if self._skip_depth:
            return
        if tag in self.block_tags:
            self._close_block(tag)
        elif tag in {"ul", "ol"}:
            self._append_html(f"</{tag}>")
            self._append_markdown("\n")
            self._pop_tag(tag)
        elif tag in {"strong", "em"}:
            self._append_html(f"</{tag}>")
            self._append_markdown(markdown_marker(tag))
            self._pop_tag(tag)
        elif tag == "a":
            if self._tag_stack and self._tag_stack[-1] == "a":
                self._append_html("</a>")
                link = self._link_stack.pop() if self._link_stack else {"href": "", "text": ""}
                if link["href"]:
                    self._append_markdown(f"]({link['href']})")
                self._pop_tag(tag)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = re.sub(r"\s+", " ", data)
        if not text.strip():
            return
        if text.startswith(" ") and (not self._html or self._html[-1].endswith((">", "\n", " "))):
            text = text.lstrip()
        self._append_html(escape(text))
        self._append_markdown(text)
        if self._link_stack:
            self._link_stack[-1]["text"] += text

    def html(self) -> str:
        while self._tag_stack:
            tag = self._tag_stack.pop()
            if tag == "a":
                self._html.append("</a>")
            elif tag in {"strong", "em"}:
                self._html.append(f"</{tag}>")
            elif tag in {"ul", "ol"}:
                self._html.append(f"</{tag}>")
            elif tag in self.block_tags:
                self._html.append(f"</{tag}>")
        return "".join(self._html)

    def markdown(self) -> str:
        return "".join(self._markdown)

    def _open_block(self, tag: str) -> None:
        self._append_html(f"<{tag}>")
        if tag.startswith("h") and len(tag) == 2:
            level = int(tag[1])
            self._append_markdown("\n" + "#" * level + " ")
        elif tag == "li":
            self._append_markdown("\n- ")
        else:
            self._append_markdown("\n")
        self._tag_stack.append(tag)

    def _close_block(self, tag: str) -> None:
        if tag == "li":
            self._append_html("</li>")
            self._append_markdown("\n")
        else:
            self._append_html(f"</{tag}>")
            self._append_markdown("\n\n")
        self._pop_tag(tag)

    def _append_html(self, value: str) -> None:
        self._html.append(value)

    def _append_markdown(self, value: str) -> None:
        self._markdown.append(value)

    def _pop_tag(self, tag: str) -> None:
        if tag in self._tag_stack:
            self._tag_stack.remove(tag)


def markdown_marker(tag: str) -> str:
    return "**" if tag == "strong" else "_"


def normalize_spacing(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_url(value: str) -> str:
    return unescape(value or "").strip()


def social_key(href: str) -> str | None:
    parsed = urlparse(href)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in SOCIAL_HOSTS:
        return SOCIAL_HOSTS[host]
    for suffix, key in SOCIAL_HOSTS.items():
        if host.endswith(f".{suffix}"):
            return key
    return None


def is_plugin_or_theme_asset(value: str) -> bool:
    return bool(re.search(r"/wp-content/(?:plugins|themes)/", value, re.IGNORECASE))
