"""Masking of secrets in text that is stored for people to read (the communication log).

Three rules decide what becomes ``***``:

1. **By name.** The value of a header, JSON field, query or form parameter whose name is
   one of ``authorization``, ``cookie``, ``set-cookie``, ``x-bambubridge-key`` or contains
   one of the words in ``SENSITIVE_WORDS`` (``token``, ``secret``, ``password``, ``key``
   and a few more). Names are compared without regard to case.
2. **By path.** JSON fields a provider marked with ``"x-secret": true`` in its schema
   (:func:`secret_paths_from_schema`). A path matches wherever a field path *ends* with it,
   so ``connection.access_code`` also covers the same object one level down in a message.
3. **By value.** Every occurrence of a known secret value of at least
   ``MIN_KNOWN_SECRET_LENGTH`` characters, as a substring, also in its percent-encoded,
   base64 (whole value, with and without padding) and JSON-escaped forms.

In text that is not parsed JSON (an address, an error message, a body in another format,
broken JSON) the names are found by patterns: ``"name": value``, ``name=value`` with a
quoted or bare value, the password in ``scheme://user:password@host`` and the credential
after ``Bearer`` or ``Basic``. Each pattern is tried at every position of the same text and
the union of what they find is masked, so no pattern depends on what another one left, and
a pair inside the quoted value of a plain name (``a="x password=y"``) is found as well.

Masking prefers hiding too much over showing a secret: a field called ``monkey`` is masked
because its name contains ``key``. What it cannot do: find a secret nobody named or marked,
find a known secret that was transformed in a way not listed above (hashed, base64 as part
of a longer value, encoded twice), or keep the structure below a masked field.

Nothing here logs, and no error message quotes a value.
"""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from collections.abc import Collection, Iterator, Mapping
from typing import Any, cast
from urllib.parse import quote, quote_plus, unquote, unquote_plus

MASK = "***"
MIN_KNOWN_SECRET_LENGTH = 8

SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "x-bambubridge-key"})
# ``auth`` (``x-auth``, ``proxy-authorization``) but not the word ``author``.
SENSITIVE_WORDS = re.compile(
    r"token|secret|passw|pwd|key|auth(?!ors?(?![a-z]))|cookie|credential|session|signature"
)

NESTED_TOO_DEEPLY = "<not recorded: nested too deeply>"

_PERCENT_ESCAPE = re.compile(r"%[0-9A-F]{2}")
# The text rules below each name the spans of a text that hold a secret; ``Masker.text``
# replaces the union of all spans. No rule works on the output of another one, so none can
# take away what another needs to see (a name, a quote, a scheme word).

# ``scheme://user:password@host``: the password.
_USERINFO = re.compile(r"(?<=://)[^/?#@\s:]*:([^/?#@\s]*)@")
# ``Bearer <token>`` / ``Basic <credentials>``; a following all-lower-case word ("basic
# authentication failed") is prose, not a credential. Tried at every position (lookahead),
# so a scheme word inside the token of another one (``basic x=Bearer <token>``) counts too.
_AUTH_SCHEME = re.compile(
    r"(?=\b(?i:bearer|basic)\s+((?![a-z]+(?![A-Za-z0-9._~+/=-]))[A-Za-z0-9._~+/=-]{8,}))"
)
# ``"name": value`` in text that looks like JSON (also when it is cut off or broken), tried
# at every quote, because in broken text any quote may be the one that opens a name. The
# value is a string (possibly unterminated at the end of the text), the start of an object
# or array, or a bare literal. The bound on the name keeps the scan linear.
_JSON_FIELD = re.compile(
    r"""(?=
        "((?:[^"\\]|\\.){0,128})"\s*:\s*
        (?: "((?:[^"\\]|\\.)*)("?) | ([\[{]) | ([^\s,}\]"]+) )
    )""",
    re.VERBOSE,
)
# ``name=`` as in a query string, a form body or a message for people. The lookbehind makes
# a name start only where a run of name characters starts, which keeps the scan linear.
_PAIR_NAME = re.compile(r"(?<![A-Za-z0-9_.%\-\[\]])([A-Za-z0-9_.%\-\[\]]+)=")
# The value after a secret name: quoted (possibly unterminated), a scheme word with what
# follows it (``Authorization=Bearer <token>``), or bare up to the next ``&``, space, quote
# or angle bracket.
_PAIR_VALUE = re.compile(
    r""""(?:[^"\\]|\\.)*"?|'[^']*'?|(?i:bearer|basic)\s+[^&\s"'<>]*|[^&\s"'<>]*"""
)
# A value that is not a plain bare run: it starts with a quote or a scheme word.
_PAIR_VALUE_START = re.compile(r"""["']|(?i:bearer|basic)\s""")
_SURROGATE = re.compile("[\ud800-\udfff]")


def _fold(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold()


def is_sensitive_name(name: str) -> bool:
    """Whether a header, field or parameter of this name holds a credential (rule 1)."""
    folded = _fold(name)
    return folded in SENSITIVE_HEADERS or SENSITIVE_WORDS.search(folded) is not None


def _secret_variants(secret: str) -> set[str]:
    """The spellings of a known secret that are searched for."""
    raw = secret.encode("utf-8", "surrogatepass")
    percent = {quote(secret, safe=""), quote(secret, safe="/"), quote_plus(secret)}
    percent |= {_PERCENT_ESCAPE.sub(lambda m: m.group().lower(), p) for p in percent}
    b64 = {base64.b64encode(raw).decode("ascii"), base64.urlsafe_b64encode(raw).decode("ascii")}
    b64 |= {b.rstrip("=") for b in b64}
    escaped = {json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]}
    return {secret} | percent | b64 | escaped


class Masker:
    """The three rules for one set of secret paths and known secret values.

    Build it once per recorded exchange and use it for every part. ``secret_paths`` are
    dotted field paths (``connection.access_code``); ``known_secrets`` are plaintext values
    (bytes are read as UTF-8). A single string is taken as one entry. Other entries that are
    not strings, empty paths and values shorter than ``MIN_KNOWN_SECRET_LENGTH`` are ignored.
    """

    def __init__(
        self, *, secret_paths: Collection[str] = (), known_secrets: Collection[str] = ()
    ) -> None:
        paths: set[tuple[str, ...]] = set()
        for path in _entries(secret_paths):
            if isinstance(path, str):
                parts = tuple(_fold(part) for part in path.split(".") if part)
                if parts:
                    paths.add(parts)
        self._paths = frozenset(paths)
        self._leaf_names = frozenset(path[-1] for path in paths)
        variants: set[str] = set()
        for secret in _entries(known_secrets):
            if isinstance(secret, bytes):
                try:
                    secret = secret.decode("utf-8")
                except UnicodeDecodeError:
                    continue
            if isinstance(secret, str) and len(secret) >= MIN_KNOWN_SECRET_LENGTH:
                variants |= _secret_variants(secret)
        # Longest first: at one position the longest spelling is the one that is replaced.
        ordered = sorted(variants, key=lambda v: (-len(v), v))
        self.longest_secret = len(ordered[0]) if ordered else 0
        # A lookahead finds overlapping occurrences too.
        self._known = (
            re.compile("(?=(" + "|".join(re.escape(v) for v in ordered) + "))") if ordered else None
        )

    # -- rule 3: known values -----------------------------------------------

    def _known_spans(self, text: str) -> Iterator[tuple[int, int]]:
        """Merged spans of all occurrences of a known secret, in order."""
        if self._known is None:
            return
        start = end = -1
        for match in self._known.finditer(text):
            if match.start() < end:
                end = max(end, match.end(1))
                continue
            if end >= 0:
                yield start, end
            start, end = match.start(), match.end(1)
        if end >= 0:
            yield start, end

    def _replace_known(self, text: str) -> str:
        out: list[str] = []
        position = 0
        for start, end in self._known_spans(text):
            out += (text[position:start], MASK)
            position = end
        if not out:
            return text
        out.append(text[position:])
        return "".join(out)

    def _has_known(self, text: str) -> bool:
        return self._known is not None and self._known.search(text) is not None

    # -- rules 1 and 2 on names ---------------------------------------------

    def _is_secret_name(self, name: str) -> bool:
        return is_sensitive_name(name) or _fold(name) in self._leaf_names

    def _is_secret_written_name(self, name: str) -> bool:
        """For a name as written in text: judged as it stands and percent-decoded
        (``pass%77ord``; but ``%bAuthorization`` must not decode its way out)."""
        return self._is_secret_name(name) or self._is_secret_name(unquote_plus(name))

    def _at_secret_path(self, path: tuple[str, ...]) -> bool:
        return any(path[-len(secret) :] == secret for secret in self._paths)

    def _is_secret_json_name(self, raw: str) -> bool:
        """``raw`` is the name as written between the quotes, escapes included."""
        try:
            name = json.loads(f'"{raw}"')
        except ValueError:
            name = raw
        return self._is_secret_written_name(str(name))

    def _json_spans(self, text: str) -> Iterator[tuple[int, int]]:
        """Values of secret-named ``"name": value`` fields."""
        for match in _JSON_FIELD.finditer(text):
            if not self._is_secret_json_name(match.group(1)):
                continue
            if match.start(4) >= 0:
                # An object or array: a pattern cannot tell where it ends, the rest goes.
                yield match.start(4), len(text)
            elif match.start(5) >= 0:
                if match.group(5) != "null":
                    yield match.span(5)
            elif match.group(3):
                yield match.span(2)
            else:
                # A string that is never closed: it runs to the end of the text.
                yield match.start(2), len(text)

    def _pair_spans(self, text: str) -> Iterator[tuple[int, int]]:
        """Values of secret-named ``name=value`` pairs.

        Every name is looked at, also one inside the value of another: a pair inside the
        value of a plain name (``a="x password=y"``, ``a=1;password=y``) is found, and so is
        a pair inside a value that is masked already (quotes in broken text do not always
        pair up the way the first match took them).
        """
        # End of the bare run looked at last: no separator lies between its start and there.
        bare_end = -1
        for match in _PAIR_NAME.finditer(text):
            start = match.end()
            # A name that ends where a bare value ends was swallowed by that value; what
            # follows it (a quoted string) is part of the secret.
            swallowed = start == bare_end
            if not swallowed and not self._is_secret_written_name(match.group(1)):
                continue
            if start < bare_end and _PAIR_VALUE_START.match(text, start) is None:
                # Inside a bare run that was scanned before: the value ends where that
                # run ends. Not scanning again keeps a long chain of pairs linear.
                yield start, bare_end
                continue
            # Matches at every position, if only the empty string.
            value = cast("re.Match[str]", _PAIR_VALUE.match(text, start))
            if text[start : start + 1] not in ('"', "'"):
                bare_end = value.end()
            yield value.span()

    # -- public -------------------------------------------------------------

    def text(self, value: str) -> str:
        """Mask free text: a body that is not JSON, an address, an error message."""
        # Known values first: any other rule could cut one in two.
        value = self._replace_known(value)
        spans = sorted(
            {
                *(match.span(1) for match in _USERINFO.finditer(value)),
                *(match.span(1) for match in _AUTH_SCHEME.finditer(value)),
                *self._json_spans(value),
                *self._pair_spans(value),
            }
        )
        out: list[str] = []
        position = 0
        masked_to = -1
        for start, end in spans:
            if start <= masked_to:
                # Overlaps or touches the span before it: one mask stands for both.
                position = masked_to = max(masked_to, end)
                continue
            out += (value[position:start], MASK)
            position = masked_to = end
        out.append(value[position:])
        return "".join(out)

    def value(self, value: Any) -> Any:
        """A masked copy of a JSON-like value (dict, list, string, number ...).

        Dict keys become strings, tuples become lists and bytes become ``<binary N bytes>``.
        ``None`` under a secret name stays ``None``. Raises ``RecursionError`` for a value
        nested deeper than the interpreter allows.
        """
        return self._value(value, ())

    def _value(self, value: Any, path: tuple[str, ...]) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, item in value.items():
                name = key if isinstance(key, str) else str(key)
                here = (*path, _fold(name))
                if is_sensitive_name(name) or self._at_secret_path(here):
                    masked = None if item is None else MASK
                else:
                    masked = self._value(item, here)
                out[self.text(name)] = masked
            return out
        if isinstance(value, list | tuple):
            return [self._value(item, path) for item in value]
        if isinstance(value, bytes | bytearray | memoryview):
            return f"<binary {len(value)} bytes>"
        if isinstance(value, int | float) and not isinstance(value, bool):
            return MASK if self._has_known(str(value)) else value
        return value

    def target(self, target: str) -> str:
        """Mask a request address (URL, path with query string, topic).

        Besides :meth:`text`: a known secret that only shows after percent-decoding (any
        spelling, for example every character escaped) makes the decoded address the one
        that is masked and stored.
        """
        out = self.text(target)
        for decode in (unquote, unquote_plus):
            # Without the NUL an escape can bring in: taken out after masking, it could
            # join two halves of a secret.
            decoded = decode(out).replace("\x00", "")
            if decoded != out and self._has_known(decoded):
                out = self.text(decoded)
        return out

    def body(self, text: str) -> str:
        """Mask a message body given as text.

        A JSON object or array is masked field by field (rules 1 to 3 on the parsed
        values, so an escape sequence cannot hide a secret) and written back as compact
        JSON, but only if masking changed something: otherwise the text is kept as it
        came and the text rules of :meth:`text` run over it, as they do for any other
        body. A document nested too deeply to walk is replaced by a fixed note.
        """
        if text.lstrip()[:1] in ("{", "["):
            try:
                parsed = json.loads(text)
                masked = self.value(parsed)
                if masked != parsed:
                    # Every string in it went through the text rules already. A surrogate
                    # that came in as an escape sequence cannot be stored as a character.
                    written = json.dumps(masked, ensure_ascii=False, separators=(",", ":"))
                    return self._replace_known(_SURROGATE.sub("\ufffd", written))
            except RecursionError:
                return NESTED_TOO_DEEPLY
            except ValueError:
                pass  # not JSON after all: the text rules below still apply
        return self.text(text)

    def safe_prefix(self, text: str, *, complete: bool, limit: int) -> tuple[str, bool]:
        """Cut ``text`` to at most ``limit`` characters without cutting a known secret.

        Returns the prefix and whether anything was left out. ``complete`` says whether
        ``text`` is all there is; if the caller already holds only the beginning, the end of
        ``text`` may be the first part of a secret, so the last ``longest_secret`` characters
        are dropped as well. A known secret that would straddle the cut is left out whole:
        half a secret would no longer be recognised and masked.
        """
        if complete and len(text) <= limit:
            return text, False
        cut = min(limit, len(text) if complete else max(0, len(text) - self.longest_secret))
        for start, end in self._known_spans(text):
            if start >= cut:
                break
            if end > cut:
                cut = start
                break
        return text[:cut], True


def _entries(values: Collection[Any]) -> Collection[Any]:
    """A single string (or bytes) is one entry, not a collection of its characters."""
    return (values,) if isinstance(values, str | bytes) else values


def mask(
    value: Any, *, secret_paths: Collection[str] = (), known_secrets: Collection[str] = ()
) -> Any:
    """A masked copy of ``value``: headers, a JSON body, an address or any text.

    See the module text for the rules and :class:`Masker` for the parts.
    """
    return Masker(secret_paths=secret_paths, known_secrets=known_secrets).value(value)


def secret_paths_from_schema(schema: Mapping[str, Any]) -> frozenset[str]:
    """Dotted paths of the properties marked ``"x-secret": true`` in a JSON schema.

    Follows ``properties``, ``items``, ``allOf``/``anyOf``/``oneOf`` and local references
    (``#/$defs/Name``); array items do not add a path segment. Anything it does not
    understand is skipped.
    """
    found: set[str] = set()
    defs = schema.get("$defs") if isinstance(schema, Mapping) else None

    def walk(node: Any, path: tuple[str, ...], open_refs: frozenset[str]) -> None:
        if not isinstance(node, Mapping):
            return
        if node.get("x-secret") is True and path:
            found.add(".".join(path))
        ref = node.get("$ref")
        if (
            isinstance(ref, str)
            and ref.startswith("#/$defs/")
            and ref not in open_refs
            and isinstance(defs, Mapping)
        ):
            walk(defs.get(ref.removeprefix("#/$defs/")), path, open_refs | {ref})
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            for name, child in properties.items():
                walk(child, (*path, str(name)), open_refs)
        walk(node.get("items"), path, open_refs)
        for combinator in ("allOf", "anyOf", "oneOf"):
            branches = node.get(combinator)
            if isinstance(branches, list):
                for branch in branches:
                    walk(branch, path, open_refs)

    walk(schema, (), frozenset())
    return frozenset(found)
