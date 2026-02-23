"""Tree-sitter based syntax highlighter for diff views.

Replaces the previous Pygments-based approach. Instead of tokenising one line
at a time (which was the primary performance bottleneck), this module parses
the entire source content once and returns pre-computed per-line highlight
spans that the diff renderer can look up in O(1).

Grammar discovery relies on the ``$buildInputs`` environment variable that
``nix-shell`` exports.  All grammars are loaded lazily and cached for the
lifetime of the process.
"""

import ctypes
import os
import warnings
from dataclasses import dataclass, field

from rich.style import Style
from rich.text import Text

# ---------------------------------------------------------------------------
# Gruvbox-dark colour palette mapped to standard tree-sitter capture names.
# Capture names follow the convention used by highlights.scm files shipped
# with each grammar: @keyword, @function, @string, etc.
# ---------------------------------------------------------------------------

_TOKEN_STYLES: dict[str, Style] = {
    "keyword":               Style(color="#fb4934", bold=True),   # red
    "keyword.import":        Style(color="#fb4934", bold=True),
    "keyword.return":        Style(color="#fb4934", bold=True),
    "keyword.operator":      Style(color="#fb4934"),
    "keyword.type":          Style(color="#fabd2f", bold=True),   # yellow
    "function":              Style(color="#b8bb26"),              # green
    "function.def":          Style(color="#b8bb26", bold=True),
    "function.method":       Style(color="#b8bb26"),
    "function.method.call":  Style(color="#b8bb26"),
    "function.call":         Style(color="#b8bb26"),
    "function.builtin":      Style(color="#8ec07c"),              # aqua
    "method":                Style(color="#b8bb26"),
    "method.call":           Style(color="#b8bb26"),
    "variable":              Style(color="#ebdbb2"),              # fg
    "variable.parameter":    Style(color="#d3869b"),              # purple
    "variable.builtin":      Style(color="#fe8019"),              # orange
    "type":                  Style(color="#fabd2f"),              # yellow
    "type.builtin":          Style(color="#fabd2f", bold=True),
    "constructor":           Style(color="#fabd2f"),
    "constant":              Style(color="#d3869b", bold=True),   # purple
    "constant.builtin":      Style(color="#d3869b", bold=True),
    "string":                Style(color="#b8bb26"),              # green
    "string.special":        Style(color="#8ec07c"),              # aqua
    "string.escape":         Style(color="#8ec07c"),
    "number":                Style(color="#d3869b"),              # purple
    "float":                 Style(color="#d3869b"),
    "comment":               Style(color="#928374", italic=True), # grey
    "operator":              Style(color="#ebdbb2"),              # fg
    "punctuation":           Style(color="#ebdbb2"),
    "punctuation.bracket":   Style(color="#ebdbb2"),
    "punctuation.delimiter": Style(color="#ebdbb2"),
    "attribute":             Style(color="#8ec07c"),              # aqua
    "tag":                   Style(color="#83a598"),              # blue
    "namespace":             Style(color="#fabd2f"),
    "label":                 Style(color="#fb4934"),
    "property":              Style(color="#8ec07c"),
}


def _resolve_style(capture_name: str) -> Style | None:
    """Resolve a capture name to a Rich Style using exact then prefix fallback.

    Args:
        capture_name: Capture name from highlights.scm, e.g. ``"function.def"``.

    Returns:
        A Style, or None if no mapping is found (caller should use default).
    """
    if capture_name in _TOKEN_STYLES:
        return _TOKEN_STYLES[capture_name]
    # Try progressively shorter prefixes:
    # "function.method.call" → "function.method" → "function"
    parts = capture_name.split(".")
    for n in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:n])
        if prefix in _TOKEN_STYLES:
            return _TOKEN_STYLES[prefix]
    return None


# ---------------------------------------------------------------------------
# Extension → tree-sitter language name mapping.
# ---------------------------------------------------------------------------

_EXT_TO_LANG: dict[str, str] = {
    # C / C++
    ".c":    "cpp",
    ".cc":   "cpp",
    ".cpp":  "cpp",
    ".cxx":  "cpp",
    ".h":    "cpp",
    ".hpp":  "cpp",
    ".hxx":  "cpp",
    # Python
    ".py":   "python",
    # SQL
    ".sql":  "sql",
    # JSON
    ".json": "json",
    # Markdown
    ".md":   "markdown",
    ".mdx":  "markdown",
    # Shell
    ".sh":   "bash",
    ".bash": "bash",
    ".zsh":  "bash",
    ".fish": "bash",
    # Dockerfile  (filename match handled separately below)
    # TOML
    ".toml": "toml",
    # YAML
    ".yaml": "yaml",
    ".yml":  "yaml",
}


def _lang_name_for_path(file_path: str) -> str | None:
    """Return the tree-sitter language name for a file path, or None.

    Args:
        file_path: Path to the source file.

    Returns:
        Language name string (e.g. ``"python"``), or None if unknown.
    """
    if not file_path:
        return None
    basename = os.path.basename(file_path)
    # Dockerfile has no extension — match by filename prefix.
    if basename == "Dockerfile" or basename.startswith("Dockerfile."):
        return "dockerfile"
    _, ext = os.path.splitext(basename.lower())
    return _EXT_TO_LANG.get(ext)


# ---------------------------------------------------------------------------
# Grammar loading — lazy, cached, discovered via $buildInputs.
# ---------------------------------------------------------------------------

# Cache: language name → (Language | None, highlights_scm_content | None)
_LANG_CACHE: dict[str, tuple] = {}


def _find_grammar_paths(lang_name: str) -> tuple[str | None, str | None]:
    """Search $buildInputs for a grammar .so and its highlights.scm.

    Args:
        lang_name: Language name, e.g. ``"python"``.

    Returns:
        Tuple of (so_path, highlights_path), either element may be None.
    """
    build_inputs = os.environ.get("buildInputs", "")
    so_path: str | None = None
    hl_path: str | None = None
    needle = f"tree-sitter-{lang_name}-grammar"
    for entry in build_inputs.split():
        if needle in entry:
            candidate_so = os.path.join(entry, "parser")
            if os.path.exists(candidate_so):
                so_path = candidate_so
            candidate_hl = os.path.join(entry, "queries", "highlights.scm")
            if os.path.exists(candidate_hl):
                hl_path = candidate_hl
            break
    return so_path, hl_path


def _load_language(lang_name: str):
    """Load a tree-sitter Language from its Nix grammar package.

    Uses ctypes to call the exported ``tree_sitter_<lang>()`` function from
    the grammar shared object, then wraps the returned pointer in a
    ``tree_sitter.Language``.  The ``DeprecationWarning`` emitted by the
    int-pointer constructor is suppressed locally.

    Args:
        lang_name: Language name, e.g. ``"python"``.

    Returns:
        A ``tree_sitter.Language`` object, or None on failure.
    """
    try:
        from tree_sitter import Language  # noqa: PLC0415
    except ImportError:
        return None

    so_path, _ = _find_grammar_paths(lang_name)
    if so_path is None:
        return None

    try:
        lib = ctypes.cdll.LoadLibrary(so_path)
        fn_name = f"tree_sitter_{lang_name.replace('-', '_')}"
        fn = getattr(lib, fn_name, None)
        if fn is None:
            return None
        fn.restype = ctypes.c_void_p
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return Language(fn())
    except Exception:  # noqa: BLE001
        return None


def _get_language_and_highlights(lang_name: str) -> tuple:
    """Return a cached (Language | None, highlights_scm | None) pair.

    Args:
        lang_name: Language name, e.g. ``"python"``.

    Returns:
        Tuple of (Language | None, highlights_scm_str | None).
    """
    if lang_name not in _LANG_CACHE:
        language = _load_language(lang_name)
        _, hl_path = _find_grammar_paths(lang_name)
        highlights_scm: str | None = None
        if hl_path:
            try:
                with open(hl_path) as fh:
                    highlights_scm = fh.read()
            except OSError:
                highlights_scm = None
        _LANG_CACHE[lang_name] = (language, highlights_scm)
    return _LANG_CACHE[lang_name]


# ---------------------------------------------------------------------------
# Public data type
# ---------------------------------------------------------------------------

@dataclass
class LineSpans:
    """Pre-computed highlight spans for a single source line.

    Attributes:
        spans: Ordered list of (text_fragment, Style | None) pairs covering
            the entire line.  Style is None for unstyled text.
    """

    spans: list[tuple[str, Style | None]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def highlight_lines(source_lines: list[str], file_path: str) -> list[LineSpans]:
    """Parse *source_lines* with tree-sitter and return per-line highlight spans.

    The entire content is parsed in a single tree-sitter pass for performance.
    If no grammar is available for the file's extension, each line is returned
    as a single unstyled span (plain-text fallback).

    Args:
        source_lines: List of source lines **without** a leading diff prefix
            character (``" "``, ``"+"`` or ``"-"`` have already been stripped).
        file_path: Path to the file being diffed; used to select the grammar.

    Returns:
        A list of ``LineSpans``, one per entry in *source_lines*, each
        containing an ordered list of ``(text_fragment, Style | None)`` pairs.
    """
    def _plain(lines: list[str]) -> list[LineSpans]:
        return [LineSpans(spans=[(line, None)]) for line in lines]

    lang_name = _lang_name_for_path(file_path)
    if lang_name is None:
        return _plain(source_lines)

    language, highlights_scm = _get_language_and_highlights(lang_name)
    if language is None or not highlights_scm:
        return _plain(source_lines)

    try:
        from tree_sitter import Parser, Query, QueryCursor  # noqa: PLC0415
    except ImportError:
        return _plain(source_lines)

    # Reconstruct the full source so tree-sitter has context for accurate
    # parsing (e.g. multi-line strings, nested structures).
    full_source = "\n".join(source_lines).encode("utf-8", errors="replace")

    try:
        parser = Parser(language)
        tree = parser.parse(full_source)
        query = Query(language, highlights_scm)
        qc = QueryCursor(query)
        captures: dict[str, list] = qc.captures(tree.root_node)
    except Exception:  # noqa: BLE001
        return _plain(source_lines)

    # Build a flat list of (start_byte, end_byte, Style) sorted by start byte.
    # When spans overlap, the first (highest-priority) match wins.
    raw_spans: list[tuple[int, int, Style]] = []
    for capture_name, nodes in captures.items():
        style = _resolve_style(capture_name)
        if style is None:
            continue
        for node in nodes:
            raw_spans.append((node.start_byte, node.end_byte, style))

    raw_spans.sort(key=lambda s: s[0])

    # Pre-compute absolute byte offset of the start of each line.
    line_start_bytes: list[int] = []
    byte_pos = 0
    for line in source_lines:
        line_start_bytes.append(byte_pos)
        byte_pos += len(line.encode("utf-8", errors="replace")) + 1  # +1 for '\n'

    result: list[LineSpans] = []
    span_cursor = 0  # index into raw_spans; advances as we move through lines

    for line_idx, line in enumerate(source_lines):
        line_start = line_start_bytes[line_idx]
        line_end = line_start + len(line.encode("utf-8", errors="replace"))

        line_spans = LineSpans()
        pos = line_start  # current absolute byte position

        # Skip spans that end before this line starts
        while span_cursor < len(raw_spans) and raw_spans[span_cursor][1] <= line_start:
            span_cursor += 1

        # Walk spans that overlap this line
        i = span_cursor
        while i < len(raw_spans):
            span_start, span_end, style = raw_spans[i]
            if span_start >= line_end:
                break

            effective_start = max(span_start, line_start)
            effective_end = min(span_end, line_end)

            # Gap of unstyled text before this span
            if pos < effective_start:
                gap = full_source[pos:effective_start].decode("utf-8", errors="replace")
                if gap:
                    line_spans.spans.append((gap, None))

            if effective_start >= pos:
                chunk = full_source[effective_start:effective_end].decode(
                    "utf-8", errors="replace"
                )
                if chunk:
                    line_spans.spans.append((chunk, style))
                pos = effective_end

            i += 1

        # Remaining unstyled text at end of line
        if pos < line_end:
            tail = full_source[pos:line_end].decode("utf-8", errors="replace")
            if tail:
                line_spans.spans.append((tail, None))

        # Ensure every line has at least one span
        if not line_spans.spans:
            line_spans.spans.append((line, None))

        result.append(line_spans)

    return result


def build_rich_text(
    line_number: int, line_spans: LineSpans, indicator: str = "  "
) -> Text:
    """Assemble a Rich ``Text`` object from pre-computed highlight spans.

    Args:
        line_number: The line number to prepend (left-aligned in 4 chars).
        line_spans: Pre-computed spans for this line from ``highlight_lines()``.
        indicator: Optional 2-character string inserted after the line number
            (used for the comment indicator ``"C "``).

    Returns:
        A Rich ``Text`` ready to pass to ``Static()``.
    """
    text = Text(f"{line_number:<4}{indicator}", overflow="fold")
    for fragment, style in line_spans.spans:
        fragment = fragment.replace("\n", "")
        if fragment:
            text.append(fragment, style=style if style is not None else Style())
    return text
