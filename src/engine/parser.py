"""AST-based code parser — language detection, file discovery, chunk extraction.

Uses tree-sitter grammars to parse source files into ASTs, then extracts
meaningful chunks (function/class/interface definitions, variable declarations,
imports, comments, etc.) for indexing.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

from src.engine.config import LanguageConfig, Settings

logger = logging.getLogger(__name__)

_warned_keys: set[str] = set()

# Chunk node types that act as definition anchors: each stays its own
# chunk (FQN / call-graph attribution intact) and may absorb leaf boilerplate.
# Leaf node types are merged into the nearest enclosing anchor.
_ANCHOR_NODE_TYPES: frozenset[str] = frozenset(
    {
        "function_definition",
        "method_definition",
        "class_definition",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "method_declaration",
        "constructor_declaration",
        "record_declaration",
        "annotation_type_declaration",
        "module_definition",
        "arrow_function",
    }
)
_LEAF_NODE_TYPES: frozenset[str] = frozenset(
    {
        "field_declaration",
        "import_statement",
        "comment",
        "type_alias",
        "module_expression",
        "expression_statement",
        "variable_declaration",
    }
)


def _reset_warned_keys() -> None:
    """Clear the deduplicated grammar-load warnings (used by tests)."""
    _warned_keys.clear()


# Maps file extensions to internal language identifiers.
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cs": "c_sharp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

# Directories automatically excluded during file discovery. Includes common
# build-output directories so generated artifacts never pollute the index.
EXCLUSION_PATTERNS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".context",
    "dist",
    "build",
    "target",
    "out",
    "bin",
    ".gradle",
    ".next",
    ".output",
    ".egg-info",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".benchmarks",
    "htmlcov",
    ".tox",
}

# Prose / transient file extensions that are never indexed unless
# ``index_prose`` (or an explicit resource-extension allowlist) opts them in.
# ``.markdown``/``.adoc`` join the set so discovery agrees with the existing
# ``DOCS`` content classification.
PROSE_EXTENSIONS: set[str] = {".md", ".markdown", ".txt", ".rst", ".adoc", ".lock", ".log"}

# Well-known lockfile names that must not outrank source files in results.
LOCKFILE_NAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-lock.yml",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "npm-shrinkwrap.json",
    "bun.lock",
    "bun.lockb",
    "flake.lock",
}


def _is_lockfile(file_path: Path) -> bool:
    """Return True when *file_path* is a well-known package lockfile."""
    return file_path.name in LOCKFILE_NAMES or file_path.suffix.lower() == ".lock"


# Extension-less infra filenames that are indexed as resource chunks when
# ``include_resources`` opts them in. They have no suffix, so the
# extension-based resource allowlist never reaches them; the name maps to the
# language token stored on their chunks.
EXTENSIONLESS_INFRA_FILES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
}


# Languages for which tree-sitter grammars are bundled.
SUPPORTED_LANGUAGES: set[str] = {
    "python",
    "java",
    "javascript",
    "typescript",
    "c_sharp",
    "cpp",
    "go",
    "rust",
    "ruby",
    "swift",
    "kotlin",
    "php",
    "shell",
    "yaml",
    "toml",
}

# Maps language -> tree-sitter grammar Python package name.
LANGUAGE_GRAMMAR_MAP: dict[str, str] = {
    "python": "tree_sitter_python",
    "java": "tree_sitter_java",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "c_sharp": "tree_sitter_c_sharp",
    "cpp": "tree_sitter_cpp",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "ruby": "tree_sitter_ruby",
    "swift": "tree_sitter_swift",
    "kotlin": "tree_sitter_kotlin",
    "php": "tree_sitter_php",
    "shell": "tree_sitter_bash",
    "yaml": "tree_sitter_yaml",
    "toml": "tree_sitter_toml",
}

_TREE_SITTER_AVAILABLE = False
_LANGUAGE_GRAMMARS: dict[str, Any] = {}

try:
    import tree_sitter as ts

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    ts = None  # type: ignore[assignment]
    logger.warning("tree-sitter not available. AST parsing disabled.")


def _init_grammar(lang: str, grammar_module_name: str | None = None) -> Any:
    """Import and cache a tree-sitter Language object for *lang*."""
    if not _TREE_SITTER_AVAILABLE:
        return None
    if lang in _LANGUAGE_GRAMMARS:
        return _LANGUAGE_GRAMMARS[lang]
    if grammar_module_name is None:
        grammar_module_name = LANGUAGE_GRAMMAR_MAP.get(lang)
    if not grammar_module_name:
        return None
    try:
        import importlib

        mod = importlib.import_module(grammar_module_name)
        lang_func = getattr(mod, "language", None)
        if lang_func is None:
            # tree-sitter-typescript exposes per-dialect languages instead of a
            # plain ``language()`` helper.
            lang_func = getattr(mod, f"language_{lang}", None)
        if lang_func is None:
            logger.warning("No language() found in %s for %s", grammar_module_name, lang)
            _LANGUAGE_GRAMMARS[lang] = None
            return None
        raw = lang_func() if callable(lang_func) else lang_func
        language = ts.Language(raw)
        _LANGUAGE_GRAMMARS[lang] = language
        return language
    except Exception as exc:
        key = f"grammar:{lang}"
        if key not in _warned_keys:
            logger.warning("Failed to load grammar for %s: %s", lang, exc)
            _warned_keys.add(key)
        else:
            logger.debug("Grammar %s already failed: %s", lang, exc)
        _LANGUAGE_GRAMMARS[lang] = None
        return None


_initialized_grammars = False


def _init_grammars() -> None:
    """Eagerly initialise all bundled language grammars into the module-level cache."""
    global _initialized_grammars
    if _initialized_grammars or not _TREE_SITTER_AVAILABLE:
        return
    for lang in LANGUAGE_GRAMMAR_MAP:
        _init_grammar(lang)
    _initialized_grammars = True


def _get_language(lang: str, grammar_map: dict[str, str] | None = None) -> Any:
    """Get or create a tree-sitter Language for *lang*, using optional custom grammar map."""
    if not _TREE_SITTER_AVAILABLE:
        return None
    if lang in _LANGUAGE_GRAMMARS:
        return _LANGUAGE_GRAMMARS[lang]
    gram_module = None
    if grammar_map:
        gram_module = grammar_map.get(lang)
    gram = _init_grammar(lang, gram_module)
    return gram


ParsedNode = dict[str, Any]


class ASTParser:
    """Parses source files using tree-sitter and extracts indexable chunks.

    Supports custom language definitions via ``LanguageConfig``, allowing
    users to add new languages or override built-in extension/grammar mappings.
    """

    def __init__(
        self,
        exclusion_patterns: set[str] | None = None,
        language_config: LanguageConfig | None = None,
        index_prose: bool = False,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the parser with optional exclusions and language overrides.

        When *language_config* is given, the built-in language map is merged
        with the operator config and drives extension detection, supported
        languages, and grammar-module resolution for this instance.

        Args:
            exclusion_patterns: Directory names to skip during discovery;
                defaults to the module-level :data:`EXCLUSION_PATTERNS`.
            language_config: Optional operator overrides for language
                definitions (extensions / grammar modules / chunk node types).
            index_prose: Whether prose/transient files (Markdown, lockfiles,
                shell scripts) are indexed by default for this instance.
            settings: Engine settings used for the chunk-merge bounds;
                defaults to ``Settings.from_env()`` when omitted.
        """
        self._exclusion_patterns = exclusion_patterns or EXCLUSION_PATTERNS
        self._index_prose = index_prose
        self._settings = settings
        self._parsers: dict[str, Any] = {}
        self._language_config = language_config
        self._custom_ext_map: dict[str, str] = {}
        self._custom_grammar_map: dict[str, str] = {}
        self._custom_supported: set[str] = set()
        if language_config is not None:
            default_languages: dict[str, dict[str, Any]] = {}
            for lang in LANGUAGE_GRAMMAR_MAP:
                exts = [ext for ext, lang_name in LANGUAGE_MAP.items() if lang_name == lang]
                default_languages[lang] = {
                    "name": lang,
                    "extensions": exts,
                    "grammar_module": LANGUAGE_GRAMMAR_MAP[lang],
                }
            merged = language_config.merge_with_defaults(default_languages)
            for name, cfg in merged.items():
                self._custom_supported.add(name)
                self._custom_grammar_map[name] = cfg.get("grammar_module", "")
                for ext in cfg.get("extensions", []):
                    self._custom_ext_map[ext] = name

    def _get_ext_map(self) -> dict[str, str]:
        """Return the active extension->language map for this instance."""
        return self._custom_ext_map if self._language_config else LANGUAGE_MAP

    def _get_supported(self) -> set[str]:
        """Return the active set of supported language names."""
        return self._custom_supported if self._language_config else SUPPORTED_LANGUAGES

    def _get_grammar_map(self) -> dict[str, str]:
        """Return the active language->grammar-module map."""
        return self._custom_grammar_map if self._language_config else LANGUAGE_GRAMMAR_MAP

    def _get_parser(self, lang: str) -> Any:
        """Return a cached tree-sitter ``Parser`` for *lang*, or ``None``.

        Creates and caches the parser on first use. ``None`` is returned when
        tree-sitter is unavailable, no grammar loads, or the language is
        unsupported.
        """
        if not _TREE_SITTER_AVAILABLE:
            return None
        if lang in self._parsers:
            return self._parsers[lang]
        grammar_map = self._get_grammar_map()
        language = _get_language(lang, grammar_map)
        if language is None:
            return None
        parser = ts.Parser(language)
        self._parsers[lang] = parser
        return parser

    def parse_file(self, file_path: Path, source_bytes: bytes | None = None) -> Any:
        """Parse a single file into a tree-sitter tree, or ``None`` on failure.

        When *source_bytes* is provided, uses it directly instead of reading
        from disk (allows relative *file_path* for FQN construction).
        """
        lang = self.detect_language(file_path)
        if lang is None:
            return None
        parser = self._get_parser(lang)
        if parser is None:
            return None
        try:
            source = source_bytes if source_bytes is not None else file_path.read_bytes()
            tree = parser.parse(source)
            return tree
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", file_path, exc)
            return None

    def detect_language(
        self, file_path: Path, resource_extensions: tuple[str, ...] | None = None
    ) -> str | None:
        """Return the language identifier for *file_path*, or ``None`` if unsupported.

        When *resource_extensions* is provided and the file extension matches,
        returns the extension without the dot (e.g., ``"xml"``, ``"sql"``).
        Extension-less infra filenames (``Dockerfile``/``Makefile``) resolve
        through the same allowlist gate so they carry a resource language
        token when resources are being indexed.
        """
        suffix = file_path.suffix.lower()
        ext_map = self._get_ext_map()
        supported = self._get_supported()
        lang = ext_map.get(suffix)
        if lang and lang in supported:
            return lang
        if resource_extensions:
            if suffix in resource_extensions:
                return suffix.lstrip(".")
            if file_path.name.lower() in EXTENSIONLESS_INFRA_FILES:
                return EXTENSIONLESS_INFRA_FILES[file_path.name.lower()]
        return None

    def discover_files(
        self,
        root_path: Path,
        exclusion_patterns: set[str] | None = None,
        include_resources: bool = False,
        resource_extensions: tuple[str, ...] | None = None,
        index_prose: bool | None = None,
    ) -> list[Path]:
        """Walk *root_path* and return all supported source files, skipping excluded dirs.

        When *include_resources* is True, also include resource files matching
        *resource_extensions* (e.g., .xml, .sql, .properties, .gradle).

        Prose/transient files (``.md``/``.txt``/lockfiles) and shell scripts
        are skipped by default. Passing *index_prose*=True (or explicitly
        listing a prose extension in *resource_extensions*) opts them in.
        """
        patterns = exclusion_patterns or self._exclusion_patterns
        res_exts = set(resource_extensions or [])
        opt_in_prose = bool(index_prose if index_prose is not None else self._index_prose)
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root_path):
            rel = Path(dirpath).relative_to(root_path)
            parts = set(rel.parts)
            if parts & patterns:
                dirnames.clear()
                continue
            for fname in filenames:
                fpath = Path(dirpath) / fname
                suffix = fpath.suffix.lower()
                is_prose = suffix in PROSE_EXTENSIONS or _is_lockfile(fpath)
                lang = self.detect_language(fpath)
                if lang == "shell" and not opt_in_prose:
                    continue
                if is_prose and not opt_in_prose and not res_exts.intersection(PROSE_EXTENSIONS):
                    continue
                is_infra = include_resources and fpath.name.lower() in EXTENSIONLESS_INFRA_FILES
                if (
                    lang is not None
                    or (include_resources and res_exts and suffix in res_exts)
                    or (opt_in_prose and is_prose)
                    or is_infra
                ):
                    files.append(fpath)
        return sorted(files)

    @staticmethod
    def get_node_text(node: object, source_bytes: bytes) -> str:
        """Return the source text covered by an AST node.

        Decodes the node's byte span from *source_bytes* as UTF-8 with
        replacement on invalid bytes. Returns an empty string when the node
        lacks ``start_byte``/``end_byte`` or decoding fails.

        Args:
            node: A tree-sitter node (duck-typed for type-safety).
            source_bytes: The raw file bytes the node was parsed from.

        Returns:
            The node's text, or ``""`` on any failure.
        """
        try:
            start_byte = node.start_byte  # type: ignore[attr-defined]
            end_byte = node.end_byte  # type: ignore[attr-defined]
            return source_bytes[start_byte:end_byte].decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def get_node_range(node: object) -> tuple[int, int, int, int]:
        """Return ``(row_start, col_start, row_end, col_end)`` for an AST node."""
        try:
            return (
                node.start_point[0],  # type: ignore[attr-defined]
                node.start_point[1],  # type: ignore[attr-defined]
                node.end_point[0],  # type: ignore[attr-defined]
                node.end_point[1],  # type: ignore[attr-defined]
            )
        except Exception:
            return (0, 0, 0, 0)

    @staticmethod
    def _annotation_rules(node: object, source_bytes: bytes) -> str:
        """Return joined Java annotation text declared on *node*.

        Java annotations live under the node's ``modifiers`` child, so both
        the direct ``annotation``/``marker_annotation`` children and the
        annotations nested under a ``modifiers`` child are collected. A
        marker annotation (``@Deprecated`` with no arguments) parses as
        ``marker_annotation`` rather than ``annotation``, so both node types
        are read. Returns ``""`` when none are found.

        Args:
            node: A tree-sitter definition node (method/class/constructor/...).
            source_bytes: The raw file bytes the node was parsed from.

        Returns:
            The space-joined annotation texts, or ``""``.
        """
        annotation_types = {"annotation", "marker_annotation"}
        texts: list[str] = []
        try:
            for child in node.children:  # type: ignore[attr-defined]
                if child.type in annotation_types:
                    texts.append(ASTParser.get_node_text(child, source_bytes))
                elif child.type == "modifiers":
                    for m in child.children:
                        if m.type in annotation_types:
                            texts.append(ASTParser.get_node_text(m, source_bytes))
        except Exception:
            pass
        return " ".join(t for t in texts if t.strip())

    @staticmethod
    def _decorator_rules(node: object, source_bytes: bytes) -> str:
        """Return joined Python decorator text attached to a decorated definition.

        Args:
            node: A tree-sitter ``decorated_definition`` node.
            source_bytes: The raw file bytes the node was parsed from.

        Returns:
            The space-joined decorator texts, or ``""``.
        """
        texts: list[str] = []
        try:
            for child in node.children:  # type: ignore[attr-defined]
                if child.type == "decorator":
                    texts.append(ASTParser.get_node_text(child, source_bytes))
        except Exception:
            pass
        return " ".join(t for t in texts if t.strip())

    def is_excluded_file(self, file_path: Path, root_path: Path) -> bool:
        """Check whether *file_path* falls under one of the exclusion patterns."""
        try:
            rel = file_path.relative_to(root_path)
            parts = set(rel.parts)
            return bool(parts & self._exclusion_patterns)
        except ValueError:
            return False

    def get_chunks_for_file(self, file_path: Path, source_bytes: bytes) -> list[ParsedNode]:
        """Extract indexable AST chunks (definitions, declarations, imports, comments, etc.)."""
        tree = self.parse_file(file_path, source_bytes=source_bytes)
        if tree is None:
            return []
        root_node = tree.root_node
        chunks: list[ParsedNode] = []
        self._extract_chunks(root_node, source_bytes, file_path, chunks)
        return self._merge_leaf_boilerplate(chunks)

    def _merge_leaf_boilerplate(self, chunks: list[ParsedNode]) -> list[ParsedNode]:
        """Merge leaf boilerplate into the nearest enclosing definition anchor.

         hybrid chunk merging: definition anchors stay their
        own chunks with exact spans (never merged into / split), while leaf
        boilerplate (``field_declaration``, ``import_statement``, ``comment``,
        ``type_alias``, bare ``expression_statement``) is appended into the
        smallest enclosing anchor chunk, bounded by ``chunk_target_chars``.
        Top-level leaves with no enclosing anchor coalesce with their adjacent
        siblings into a single module-boilerplate region chunk.

        Args:
            chunks: The per-file chunk list produced by :meth:`_extract_chunks`.

        Returns:
            The merged chunk list with standalone leaf chunks removed.
        """
        if not chunks:
            return chunks
        settings = self._settings or Settings.from_env()
        target = max(1, settings.chunk_target_chars)
        min_region = max(1, settings.chunk_min_chars)

        anchors = [c for c in chunks if c.get("chunk_node_type") in _ANCHOR_NODE_TYPES]
        leaves = [c for c in chunks if c.get("chunk_node_type") in _LEAF_NODE_TYPES]
        if not leaves:
            return chunks
        if not anchors:
            # 100%-boilerplate file: coalesce all leaves into region chunks.
            kept = [c for c in chunks if c.get("chunk_node_type") not in _LEAF_NODE_TYPES]
            return kept + self._coalesce_top_level_leaves(leaves, min_region)

        anchor_full: set[int] = set()
        unmerged_leaves: list[ParsedNode] = []
        for leaf in leaves:
            owner = self._nearest_enclosing_anchor(leaf, anchors)
            if owner is None:
                unmerged_leaves.append(leaf)
                continue
            owner_key = id(owner)
            if owner_key in anchor_full:
                unmerged_leaves.append(leaf)
                continue
            if len(owner["content"]) + len(leaf["content"]) > target:
                anchor_full.add(owner_key)
                unmerged_leaves.append(leaf)
                continue
            separator = "" if owner["content"].endswith("\n") else "\n"
            owner["content"] = owner["content"] + separator + leaf["content"]
            owner["line_end"] = max(owner["line_end"], leaf["line_end"])

        merged: list[ParsedNode] = [
            chunk for chunk in chunks if chunk.get("chunk_node_type") not in _LEAF_NODE_TYPES
        ]
        if unmerged_leaves:
            merged.extend(self._coalesce_top_level_leaves(unmerged_leaves, min_region))
        return merged

    @staticmethod
    def _nearest_enclosing_anchor(leaf: ParsedNode, anchors: list[ParsedNode]) -> ParsedNode | None:
        """Return the smallest anchor whose span fully contains *leaf*.

        Args:
            leaf: A leaf boilerplate chunk.
            anchors: The candidate definition anchor chunks.

        Returns:
            The enclosing anchor with the narrowest line span, or ``None``.
        """
        best: ParsedNode | None = None
        best_span = 0
        for anchor in anchors:
            if (
                anchor["line_start"] <= leaf["line_start"]
                and anchor["line_end"] >= leaf["line_end"]
            ):
                span = anchor["line_end"] - anchor["line_start"]
                if best is None or span < best_span:
                    best = anchor
                    best_span = span
        return best

    @staticmethod
    def _coalesce_top_level_leaves(chunks: list[ParsedNode], min_region: int) -> list[ParsedNode]:
        """Coalesce adjacent top-level leaf chunks into module-boilerplate regions.

        Leaves are grouped by contiguous line runs (a leaf starts on the line
        after the previous group ended). Each group becomes a single
        ``is_definition = 0`` region chunk spanning its leaves; tiny groups
        below *min_region* characters merge into the following group when
        possible.

        Args:
            chunks: Leaf chunks with no enclosing anchor, sorted by line.
            min_region: Minimum merged-region size (``chunk_min_chars``).

        Returns:
            The coalesced region chunks (and any leaves left standalone).
        """
        ordered = sorted(chunks, key=lambda c: (c["line_start"], c["line_end"]))
        groups: list[list[ParsedNode]] = []
        for chunk in ordered:
            if groups and chunk["line_start"] <= groups[-1][-1]["line_end"] + 1:
                groups[-1].append(chunk)
            else:
                groups.append([chunk])
        regions: list[ParsedNode] = []
        for group in groups:
            total = sum(len(c["content"]) for c in group)
            if total < min_region and len(group) == 1:
                regions.append(group[0])
                continue
            first = group[0]
            text = "\n".join(c["content"] for c in group)
            regions.append(
                {
                    "file_path": first["file_path"],
                    "line_start": min(c["line_start"] for c in group),
                    "line_end": max(c["line_end"] for c in group),
                    "content": text,
                    "language": first["language"],
                    "is_definition": False,
                    "chunk_type": "ast",
                    "chunk_node_type": "module",
                }
            )
        return regions

    def _extract_chunks(
        self,
        node: object,
        source_bytes: bytes,
        file_path: Path,
        chunks: list[ParsedNode],
        parent_is_root: bool = False,
        declared_rules: str = "",
    ) -> None:
        """Recursively walk the AST and collect chunks of interest.

        Chunk types include definitions (functions, classes, interfaces, enums),
        declarations (variables, imports, type aliases), decorators, comments,
        and top-level expressions.

        *declared_rules* carries rule text (Java annotations, Python
        decorators) from an enclosing decorated definition into the wrapped
        definition chunk, so guarded behavior is indexed alongside the code
        that declares it.
        """
        try:
            node_type = node.type  # type: ignore[attr-defined]
        except Exception:
            return

        lang_suffix = file_path.suffix.lower()
        lang = LANGUAGE_MAP.get(lang_suffix, "unknown")

        chunk_types: set[str] = {
            "function_definition",
            "method_definition",
            "class_definition",
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "method_declaration",
            "constructor_declaration",
            "field_declaration",
            "module_definition",
            "arrow_function",
            "annotation_type_declaration",
            "record_declaration",
            "annotation_declaration",
            "type_alias_declaration",
        }

        new_chunk_types: dict[str, str] = {
            "variable_declaration": "variable_declaration",
            "import_statement": "import_statement",
            "import_from_statement": "import_statement",
            "require_statement": "import_statement",
            "decorator": "decorator",
            "comment": "comment",
            "type_alias": "type_alias",
            "type_alias_statement": "type_alias",
            "type_definition": "type_alias",
            "alias_declaration": "type_alias",
        }

        is_definition_types: set[str] = {
            "function_definition",
            "method_definition",
            "class_definition",
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "method_declaration",
            "constructor_declaration",
            "field_declaration",
        }

        # Container definitions (classes/interfaces/enums/records/modules) hold
        # nested member definitions. We keep the enclosing chunk AND descend
        # into its body so every member becomes its own per-definition chunk.
        container_definition_types: set[str] = {
            "class_definition",
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "module_definition",
            "annotation_type_declaration",
        }

        # Non-container definitions with executable bodies (functions/methods/
        # constructors) also descend so bare expressions inside them surface as
        # leaves and merge into the enclosing definition instead of being
        # silently dropped.
        body_definition_types: set[str] = {
            "function_definition",
            "method_definition",
            "method_declaration",
            "constructor_declaration",
            "arrow_function",
            "annotation_declaration",
        }

        if node_type in chunk_types or node_type in new_chunk_types:
            line_start, _col_start, line_end, _col_end = self.get_node_range(node)
            text = self.get_node_text(node, source_bytes)
            if node_type == "comment" and len(text.strip()) < 5:
                return
            if text.strip():
                resolved_type = new_chunk_types.get(node_type, node_type)
                is_def = node_type in is_definition_types
                rules = declared_rules or self._annotation_rules(node, source_bytes)
                chunk: ParsedNode = {
                    "file_path": str(file_path),
                    "line_start": line_start,
                    "line_end": line_end,
                    "content": text,
                    "language": lang or "unknown",
                    "is_definition": is_def,
                    "chunk_type": "ast",
                    "chunk_node_type": resolved_type,
                }
                if rules:
                    chunk["declared_rules"] = rules
                chunks.append(chunk)
            if node_type in container_definition_types or node_type in body_definition_types:
                try:
                    for child in node.children:  # type: ignore[attr-defined]
                        self._extract_chunks(child, source_bytes, file_path, chunks)
                except Exception:
                    pass
            return

        if node_type == "decorated_definition":
            rules = self._decorator_rules(node, source_bytes)
            try:
                for child in node.children:  # type: ignore[attr-defined]
                    self._extract_chunks(
                        child, source_bytes, file_path, chunks, declared_rules=rules
                    )
            except Exception:
                pass
            return

        if node_type == "expression_statement":
            sub_types = set()
            try:
                for child in node.children:  # type: ignore[attr-defined]
                    with contextlib.suppress(Exception):
                        sub_types.add(child.type)
            except Exception:
                pass
            if "assignment" in sub_types:
                line_start, _col_start, line_end, _col_end = self.get_node_range(node)
                text = self.get_node_text(node, source_bytes)
                if text.strip():
                    chunks.append(
                        {
                            "file_path": str(file_path),
                            "line_start": line_start,
                            "line_end": line_end,
                            "content": text,
                            "language": lang or "unknown",
                            "is_definition": False,
                            "chunk_type": "ast",
                            "chunk_node_type": "variable_declaration",
                        }
                    )
                return
            if parent_is_root:
                line_start, _col_start, line_end, _col_end = self.get_node_range(node)
                text = self.get_node_text(node, source_bytes)
                if text.strip():
                    chunks.append(
                        {
                            "file_path": str(file_path),
                            "line_start": line_start,
                            "line_end": line_end,
                            "content": text,
                            "language": lang or "unknown",
                            "is_definition": False,
                            "chunk_type": "ast",
                            "chunk_node_type": "module_expression",
                        }
                    )
                return
            # Bare non-root expression (e.g. ``trigger();`` inside a method
            # body): emit it as a leaf so the merge pass absorbs it into the
            # nearest enclosing definition instead of dropping it.
            line_start, _col_start, line_end, _col_end = self.get_node_range(node)
            text = self.get_node_text(node, source_bytes)
            if text.strip():
                chunks.append(
                    {
                        "file_path": str(file_path),
                        "line_start": line_start,
                        "line_end": line_end,
                        "content": text,
                        "language": lang or "unknown",
                        "is_definition": False,
                        "chunk_type": "ast",
                        "chunk_node_type": "expression_statement",
                    }
                )
            return

        try:
            for child in node.children:  # type: ignore[attr-defined]
                self._extract_chunks(
                    child,
                    source_bytes,
                    file_path,
                    chunks,
                    parent_is_root=(node_type in ("module", "program")),
                )
        except Exception:
            pass
