"""Keep the project handbook navigable when documents move or headings change."""

from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def documentation_files() -> list[Path]:
    return [PROJECT_ROOT / "README.md", PROJECT_ROOT / "tests" / "README.md",
            *sorted((PROJECT_ROOT / "docs").rglob("*.md"))]


def prose_lines(text: str) -> list[str]:
    """Exclude fenced examples, whose links/headings need not describe the repo."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None:
            if marker:
                fence = marker.group(1)
            else:
                lines.append(line)
        elif marker and marker.group(1)[0] == fence[0]:
            if len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
                fence = None
    if fence is not None:
        raise ValueError("Unclosed Markdown code fence")
    return lines


def heading_anchors(text: str) -> set[str]:
    anchors = set()
    counts: dict[str, int] = {}
    for line in prose_lines(text):
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        slug = re.sub(r"[^\w\- ]", "", match.group(1).lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


class DocumentationTest(unittest.TestCase):
    def test_development_plan_preserves_public_milestone_anchors(self):
        """Keep inbound milestone links stable when completed tasks are condensed."""
        plan = PROJECT_ROOT / "docs" / "開發計畫.md"
        anchors = heading_anchors(plan.read_text(encoding="utf-8"))
        for anchor in (
            "p1-移除舊-ml",
            "p4-建立可調評分設定",
            "p5-建立設定比較流程",
            "p6-分批擴充評分與搜尋",
            "p7-評估自動調參",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, anchors)

    def test_code_fences_are_closed(self):
        for path in documentation_files():
            with self.subTest(document=path.relative_to(PROJECT_ROOT)):
                prose_lines(path.read_text(encoding="utf-8"))

    def test_local_links_and_heading_anchors_resolve(self):
        for path in documentation_files():
            prose = "\n".join(prose_lines(path.read_text(encoding="utf-8")))
            for href in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", prose):
                url = urlsplit(href.strip("<>"))
                if url.scheme or url.netloc:
                    continue
                target = (path.parent / unquote(url.path)).resolve() if url.path else path
                with self.subTest(document=path.relative_to(PROJECT_ROOT), link=href):
                    self.assertTrue(target.is_file(), f"Missing document: {target}")
                    if url.fragment and target.suffix == ".md":
                        anchors = heading_anchors(target.read_text(encoding="utf-8"))
                        self.assertIn(unquote(url.fragment), anchors)


if __name__ == "__main__":
    unittest.main()
