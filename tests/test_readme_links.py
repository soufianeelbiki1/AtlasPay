import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_root_readme_local_links_resolve_inside_the_repository() -> None:
    readme = ROOT / "README.md"
    missing: list[str] = []

    for raw_target in MARKDOWN_LINK.findall(readme.read_text(encoding="utf-8")):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith("#"):
            continue

        relative = Path(unquote(parsed.path))
        resolved = (readme.parent / relative).resolve()
        if ROOT not in resolved.parents and resolved != ROOT:
            missing.append(f"{target} escapes the repository")
        elif not resolved.exists():
            missing.append(target)

    assert not missing, f"README contains unresolved local links: {missing}"
