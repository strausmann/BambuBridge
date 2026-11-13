"""Masking of secrets in text that is stored for people to read (the communication log).

Three rules decide what becomes ``***``:

1. **By name.** The value of a header, JSON field, query or form parameter whose name is
   one of ``authorization``, ``cookie``, ``set-cookie``, ``x-bambubridge-key``, contains
   one of the words in ``SENSITIVE_WORDS`` (``token``, ``secret``, ``password``, ``key``,
   ``access_code`` and more) or has one of ``SENSITIVE_NAME_WORDS`` (``pass``, ``pin``,
   ``sid`` ...) as a word of its own (``user_pass``, ``userPW``), or a word that ends in
   ``pass`` or ``pw`` (``dbpass``, ``rootpw``). Names are compared without regard to case,
   after NFKC, without combining marks and with the dotless i as ``i`` - the same test for
   parsed JSON and for every text rule, which accept names of Unicode word characters.
2. **By path.** JSON fields a provider marked with ``"x-secret": true`` in its schema
   (:func:`secret_paths_from_schema`). The last segment of a path is what counts: every
   field of that name is masked, wherever it stands, in parsed JSON and in text alike, so
   that a body is never masked differently depending on what else is in it.
3. **By value.** Every occurrence of a known secret value of at least
   ``MIN_KNOWN_SECRET_LENGTH`` characters (surrounding white space removed), in any
   spelling an encoder writes: each character as itself or escaped (percent escape of its
   UTF-8 bytes in either case, ``\\uXXXX`` in either case and as a surrogate pair, ``\\xNN``,
   ``\\UXXXXXXXX``, the short escapes such as ``\\/`` and ``\\"``, ``+`` for a space, HTML and
   XML character references ``&#N;``, ``&#xH;`` and ``&amp; &lt; &gt; &quot; &apos;``), each
   backslash escape also as ``json.dumps`` or ``repr()`` write it a second time, the
   Python ``repr`` spellings, the UTF-8 bytes read as ISO 8859-1, and base64 or base64url of
   its UTF-8 bytes, also as part of a longer base64 value in any of the three alignments and
   wrapped over several lines.

Invisible format characters (Unicode category Cf: zero-width space, soft hyphen, byte order
mark, word joiner ...) are removed from a text before anything is searched.

In text that is not parsed JSON (an address, an error message, a body in another format,
broken JSON) the names are found by patterns: ``"name": value`` and ``'name': value`` (a
Python dict), ``name=value`` and ``name = value`` with a quoted or bare value (a bare value
ends at ``&`` or white space only), ``name: value`` (the rest of the line, as in a header
line ``Authorization: Token x`` or ``Cookie: a=1; sid=x``), ``--name value`` (a command
line), a multipart form field ``Content-Disposition: form-data; name="password"``, the user
information in ``scheme://user:password@host`` (up to the last ``@``; without a colon the
whole of it, a token given as the user name) and the credential after ``Bearer`` or
``Basic``. Each pattern and the known values are looked for in the same text and the union
of what they find is masked, so no pattern depends on what another one left. The same is
then done once more on the percent-decoded text (and on that decoded again, for an address
encoded into another one): if that finds anything, the decoded text is what is stored.

Masking prefers hiding too much over showing a secret: a field called ``monkey`` is masked
because its name contains ``key``. What it cannot do: find a secret nobody named or marked,
find a known secret that was transformed in a way not listed above (hashed, encrypted,
quoted-printable, ES6 ``\\u{..}`` or octal escapes, a look-alike letter), or keep the
structure below a masked field.

Nothing here logs, and no error message quotes a value.
"""

from __future__ import annotations

import base64
import bisect
import json
import re
import unicodedata
from collections.abc import Callable, Collection, Iterator, Mapping
from typing import Any, cast
from urllib.parse import quote, quote_plus, unquote, unquote_plus

MASK = "***"
MIN_KNOWN_SECRET_LENGTH = 8

SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "x-bambubridge-key"})
# Searched as substrings of the folded name. ``auth`` (``x-auth``, ``proxy-authorization``)
# but not the word ``author``.
SENSITIVE_WORDS = re.compile(
    r"token|secret|passw|pwd|key|auth(?!ors?(?![a-z]))|cookie|credential|session|sessid"
    r"|signature|access[_.\-\s]?code|passcode|passphrase|pin[_.\-\s]?code|totp|jwt|ticket"
    r"|assertion|psk|csrf|xsrf|samlresponse"
)
# Short words that count only as a whole word of the name: as substrings they would hide
# "compass", "spinner" or "inside".
SENSITIVE_NAME_WORDS = frozenset({"pass", "pw", "pin", "otp", "sig", "sid"})

NESTED_TOO_DEEPLY = "<not recorded: nested too deeply>"

# Words of a name: ``userPW`` -> user, PW; ``X-CSRF-Token`` -> X, CSRF, Token.
_NAME_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
_PERCENT_ESCAPE = re.compile(r"%[0-9A-F]{2}")
# How often the text is percent-decoded to look for names and known values once more.
_DECODE_ROUNDS = 3

# The text rules below each name the spans of a text that hold a secret; ``Masker.text``
# replaces the union of all spans. No rule works on the output of another one, so none can
# take away what another needs to see (a name, a quote, a scheme word).

# ``scheme://userinfo@host``: greedy up to the last ``@`` before the path.
_USERINFO = re.compile(r"(?<=://)([^/?#\s]*)@")
# ``Bearer <token>`` / ``Basic <credentials>``; a following all-lower-case word ("basic
# authentication failed") is prose, not a credential. Tried at every position (lookahead),
# so a scheme word inside the token of another one (``basic x=Bearer <token>``) counts too.
# An explicit header line (``Authorization: Bearer <token>``) is masked by name instead,
# whatever the token looks like.
_AUTH_SCHEME = re.compile(
    r"(?=\b(?i:bearer|basic)\s+((?![a-z]+(?![A-Za-z0-9._~+/=-]))[A-Za-z0-9._~+/=-]{8,}))"
)
# ``"name": value`` or ``'name': value`` in text that looks like JSON or a Python dict (also
# when it is cut off or broken), tried at every quote, because in broken text any quote may
# be the one that opens a name. The value is a string (possibly unterminated at the end of
# the text, possibly with a Python prefix such as ``b'...'``), the start of an object or
# array, or a bare literal. The bound on the name keeps the scan linear.
_QUOTED_FIELD = re.compile(
    r"""(?=
        (["'])((?:(?!\1)[^\\]|\\.){0,128})\1\s*:\s*
        (?: [bBrRuUfF]{0,2}(["'])((?:(?!\3)[^\\]|\\.)*)(\3)? | ([\[{]) | ([^\s,}\]"']+) )
    )""",
    re.VERBOSE,
)
# ``name=`` or ``name:`` (with optional blanks around the sign) as in a query string, a form
# body, a header line or a message for people. The lookbehind makes a name start only where
# a run of name characters starts, which keeps the scan linear.
_PAIR_NAME = re.compile(r"(?<![\w.%\-\[\]])([\w.%\-\[\]]+)[ \t]*([=:])[ \t]*")
# The value after ``name=``: quoted (possibly unterminated), a scheme word with what follows
# it (``Authorization=Bearer <token>``), or bare up to the next ``&`` or white space.
_PAIR_VALUE = re.compile(r""""(?:[^"\\]|\\.)*"?|'[^']*'?|(?i:bearer|basic)\s+[^&\s]*|[^&\s]*""")
# A value that is not a plain bare run: it starts with a quote or a scheme word.
_PAIR_VALUE_START = re.compile(r"""["']|(?i:bearer|basic)\s""")
# The value after ``name:``: the rest of the line.
_LINE_REST = re.compile(r"[^\r\n]*")
# ``--name value`` / ``-name value`` on a command line (``--name=value`` is a pair). Tried at
# every position (lookahead): a flag inside the bare value of another one counts too.
_FLAG = re.compile(
    r"""(?=(?<![\w-])--?((?:[^\W\d_]|%)[\w.%-]{0,127})[ \t]+("(?:[^"\\]|\\.)*"?|'[^']*'?|[^\s]+))"""
)
# A part of a multipart form body: its Content-Disposition line names the field; the value
# follows the blank line after the part's headers and ends before the next boundary line.
_MULTIPART_PART = re.compile(
    r"""(?im)^content-disposition:[^\r\n]*?\bname\*?=(?:"((?:[^"\\\r\n]|\\.)*)"|([^\s;"]+))
        [^\r\n]*(?:\r?\n[^\r\n]+){0,32}\r?\n\r?\n""",
    re.VERBOSE,
)
_BOUNDARY_LINE = re.compile(r"\r?\n--")
_SURROGATE = re.compile("[\ud800-\udfff]")


# A format character written as an escape or reference: HTML/XML numeric reference, JSON or
# Python ``\\u``/``\\x`` escape (also escaped twice), or percent-encoded UTF-8.
_ENCODED_CHARACTER = re.compile(
    r"(?i:&\#x0{0,8}([0-9a-f]{1,6});|&\#0{0,8}([0-9]{1,7});|(?<!\\)\\{1,8}u([0-9a-f]{4})"
    r"|((?<!\\)(?:\\{1,8}x[0-9a-f]{2}){1,4})|((?:%[0-9a-f]{2}){1,4}))"
)


def _encoded_character(match: re.Match[str]) -> str:
    """The character an escape stands for, or ``""`` for a format character, else the
    escape as it was."""
    hex_ref, dec_ref, unicode_escape, hex_bytes, percent = match.groups()
    try:
        if hex_ref or dec_ref or unicode_escape:
            chars = chr(int(hex_ref or unicode_escape, 16) if not dec_ref else int(dec_ref))
        else:
            hexes = re.findall(r"[0-9a-fA-F]{2}", (hex_bytes or percent).replace("x", " "))
            data = bytes(int(h, 16) for h in hexes)
            try:
                chars = data.decode("utf-8")
            except UnicodeDecodeError:
                chars = data.decode("latin-1") if len(data) == 1 else ""
    except ValueError, OverflowError:
        return match.group()
    if chars and all(unicodedata.category(char) == "Cf" for char in chars):
        return ""
    return match.group()


def _drop_encoded_format(text: str) -> str:
    """``text`` without format characters written as escapes (``&#8203;``, ``%E2%80%8B``,
    ``\\u200b``): decoded, they would split a known secret just as the characters do."""
    return _ENCODED_CHARACTER.sub(_encoded_character, text)


def _format_characters() -> re.Pattern[str]:
    """All characters of Unicode category Cf (zero-width space, soft hyphen, byte order
    mark, word joiner ...). They are invisible, so they are taken out of a text before the
    search for known values: otherwise one of them inside a secret hides it."""
    chars = [
        chr(code)
        for start, end in ((0, 0x30000), (0xE0000, 0xE1000))
        for code in range(start, end)
        if unicodedata.category(chr(code)) == "Cf"
    ]
    return re.compile("[" + "".join(re.escape(char) for char in chars) + "]")


_FORMAT = _format_characters()
# Letters that NFKC keeps apart from their Latin twins in names (Turkish dotless i).
_NAME_LETTERS = str.maketrans({"\u0131": "i"})


def _normalize_name(name: str) -> str:
    """NFKC, without combining marks (``P\u0130N`` -> ``PIN``), the dotless i as ``i``."""
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", name))
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return unicodedata.normalize("NFC", bare).translate(_NAME_LETTERS)


def _fold(name: str) -> str:
    return _normalize_name(name).casefold()


def is_sensitive_name(name: str) -> bool:
    """Whether a header, field or parameter of this name holds a credential (rule 1).

    The same test serves parsed JSON and every text rule."""
    normalized = _normalize_name(name)
    folded = normalized.casefold()
    if folded in SENSITIVE_HEADERS or SENSITIVE_WORDS.search(folded) is not None:
        return True
    for word in _NAME_WORD.findall(normalized):
        word = word.casefold()
        # ``pass`` and ``pw`` also end a word: ``dbpass``, ``rootpw``, ``MQTTPASS``.
        if word in SENSITIVE_NAME_WORDS or word.endswith(("pass", "pw")):
            return True
    return False


# -- rule 3: the spellings of a known secret --------------------------------------------------

_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "/": "\\/",
    "'": "\\'",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _char_forms(char: str) -> set[str]:
    """Every spelling of one character that an encoder or ``repr`` writes."""
    forms = {char}
    data = char.encode("utf-8", "surrogatepass")
    forms.add("".join(f"%{byte:02x}" for byte in data))
    forms.add("".join(f"\\x{byte:02x}" for byte in data))
    code = ord(char)
    if code < 0x100:
        forms.add(f"\\x{code:02x}")
    if code > 0xFFFF:
        forms.add(f"\\U{code:08x}")
    units = char.encode("utf-16-be", "surrogatepass")
    forms.add("".join(f"\\u{units[i]:02x}{units[i + 1]:02x}" for i in range(0, len(units), 2)))
    if char == " ":
        forms.add("+")
    if char in _SHORT_ESCAPES:
        forms.add(_SHORT_ESCAPES[char])
    return forms


# HTML/XML named references, and the numeric reference as a pattern: ``&#N;`` and
# ``&#xH;`` in either case, with up to eight leading zeros.
_NAMED_REFERENCES = {
    "&": ("&amp;",),
    "<": ("&lt;",),
    ">": ("&gt;",),
    '"': ("&quot;",),
    "'": ("&apos;",),
}
_MAX_REFERENCE_ZEROS = 8


def _escape_twice(form: str) -> list[str]:
    """A spelling as written once, and as ``json.dumps`` or ``repr()`` write it again when a
    caller puts the text into a string a second (and third) time: longest first."""
    if not any(char in form for char in "\\\"'"):
        return [form]
    variants = {form}
    for _ in range(2):
        variants |= {
            again
            for value in variants
            for again in (
                json.dumps(value)[1:-1],
                json.dumps(value, ensure_ascii=False)[1:-1],
                repr(value)[1:-1],
            )
        }
    return sorted(variants, key=lambda v: (-len(v), v))


def _form_pattern(form: str) -> str:
    # Only escapes and references are matched without regard to case, never the character.
    if len(form) > 1 and form[0] in "%&\\":
        return "(?i:" + "|".join(re.escape(f) for f in _escape_twice(form)) + ")"
    return re.escape(form)


def _reference_patterns(char: str) -> tuple[list[str], int]:
    code = ord(char)
    zeros = f"0{{0,{_MAX_REFERENCE_ZEROS}}}"
    patterns = [f"(?i:&\\#x{zeros}{code:x};)", f"&\\#{zeros}{code};"]
    return patterns, len(f"&#x{code:x};") + _MAX_REFERENCE_ZEROS


def _char_pattern(char: str) -> tuple[str, int]:
    """The atomic group for one character, and the longest text it matches."""
    # Atomic, longest form first: no backtracking between overlapping forms (``\\`` and
    # ``\\\\``, ``%`` and ``%25``, ``&amp;`` and ``&``), which keeps the search linear.
    forms = sorted(
        _char_forms(char) | set(_NAMED_REFERENCES.get(char, ())), key=lambda f: (-len(f), f)
    )
    references, reference_length = _reference_patterns(char)
    longest = max(reference_length, *(len(_escape_twice(f)[0]) for f in forms))
    return "(?>" + "|".join([*references, *(_form_pattern(f) for f in forms)]) + ")", longest


def _runs(secret: str) -> list[str]:
    """``secret`` in runs: a run of backslashes is one unit, every other character one."""
    return [match.group() for match in re.finditer(r"\\+|.", secret, re.DOTALL)]


def _run_pattern(run: str) -> tuple[str, int]:
    """The atomic group for one unit of :func:`_runs`.

    A backslash run is spelled the same way throughout (``k`` backslashes, ``2k`` when
    escaped, ``4k`` when escaped twice ...): matched one by one, the escaped form of the
    first backslash would take the second one and starve the next group.
    """
    if len(run) == 1:
        return _char_pattern(run)
    forms = sorted(
        {variant for form in _char_forms("\\") for variant in _escape_twice(form)},
        key=lambda f: (-len(f), f),
    )
    longest = max(len(form) for form in forms) * len(run)
    return "(?>" + "|".join(f"(?i:{re.escape(form * len(run))})" for form in forms) + ")", longest


_LINE_BREAK = r"(?:\r?\n)?"


def _wrapped(encoded: str) -> str:
    """``encoded`` with an optional line break between any two characters."""
    return _LINE_BREAK.join(re.escape(char) for char in encoded)


def _base64_patterns(raw: bytes) -> tuple[list[str], int]:
    """Patterns for base64 and base64url of ``raw``: the whole value, and the part that
    only ``raw`` decides when it is in a longer value at each of the three alignments."""
    patterns: list[str] = []
    longest = 0
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        whole = encode(raw).decode("ascii").rstrip("=")
        patterns.append(_wrapped(whole) + f"(?:{_LINE_BREAK}=){{0,2}}")
        longest = max(longest, 3 * len(whole) + 6)
        cores = set()
        for offset in (0, 1, 2):
            # Characters whose six bits all come from ``raw``, behind ``offset`` other bytes.
            text = encode(b"\0" * offset + raw).decode("ascii")
            first = -(-8 * offset // 6)
            last = 8 * (offset + len(raw)) // 6
            cores.add(text[first:last])
        patterns += [_wrapped(core) for core in sorted(cores, key=lambda c: (-len(c), c))]
    return patterns, longest


def _literal_spellings(secret: str) -> set[str]:
    """Whole-value spellings, for what the per-character pattern cannot take apart (a run
    of backslashes in the secret itself, where the atomic groups take the wrong pair)."""
    raw = secret.encode("utf-8", "surrogatepass")
    percent = {quote(secret, safe=""), quote(secret, safe="/"), quote_plus(secret)}
    percent |= {_PERCENT_ESCAPE.sub(lambda m: m.group().lower(), p) for p in percent}
    escaped = {json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]}
    escaped.add(json.dumps(secret)[1:-1].replace("/", "\\/"))
    reprs = {repr(secret)[1:-1], repr(raw)[2:-1]}
    latin_1 = {raw.decode("latin-1")}
    once = {secret} | percent | escaped | reprs | latin_1
    # Escaped a second (and third) time by ``repr()`` or ``json.dumps``.
    return once | {twice for value in once for twice in _escape_twice(value)}


def _secret_pattern(secret: str) -> tuple[str, int]:
    """One alternation for all spellings of ``secret``, and the longest it can match."""
    groups = [_run_pattern(run) for run in _runs(secret)]
    per_char = "".join(group for group, _ in groups)
    longest = sum(length for _, length in groups)
    b64, b64_longest = _base64_patterns(secret.encode("utf-8", "surrogatepass"))
    literals = sorted(_literal_spellings(secret), key=lambda v: (-len(v), v))
    longest = max(longest, b64_longest, len(literals[0]))
    return "|".join([*b64, per_char, *(re.escape(v) for v in literals)]), longest


def _known_secret(entry: object) -> str:
    if isinstance(entry, bytes):
        try:
            return entry.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise ValueError("known_secrets must hold strings or UTF-8 bytes") from None
    if isinstance(entry, str):
        return entry.strip()
    raise ValueError("known_secrets must hold strings or UTF-8 bytes")


class _Pairs(list[tuple[str, Any]]):
    """A JSON object as its (name, value) pairs, because a name occurs more than once."""


class Masker:
    """The three rules for one set of secret paths and known secret values.

    Build it once per recorded exchange and use it for every part. ``secret_paths`` are
    dotted field paths (``connection.access_code``); ``known_secrets`` are plaintext values,
    strings or UTF-8 bytes; anything else raises ``ValueError``. A single string is taken as
    one entry. Values shorter than ``MIN_KNOWN_SECRET_LENGTH`` (after removing surrounding
    white space) and secret paths that are not strings or empty are ignored.
    """

    def __init__(
        self, *, secret_paths: Collection[str] = (), known_secrets: Collection[str] = ()
    ) -> None:
        leaves: set[str] = set()
        for path in _entries(secret_paths):
            if isinstance(path, str):
                parts = [part for part in path.split(".") if part]
                if parts:
                    leaves.add(_fold(parts[-1]))
        self._leaf_names = frozenset(leaves)
        secrets = {_known_secret(entry) for entry in _entries(known_secrets)}
        # Longest first: at one position the longest secret is the one that is replaced.
        ordered = sorted(
            (s for s in secrets if len(s) >= MIN_KNOWN_SECRET_LENGTH), key=lambda s: (-len(s), s)
        )
        patterns = [_secret_pattern(secret) for secret in ordered]
        self.longest_secret = max((longest for _, longest in patterns), default=0)
        # A lookahead finds overlapping occurrences too.
        self._known = (
            re.compile("(?=(" + "|".join(pattern for pattern, _ in patterns) + "))")
            if patterns
            else None
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
        return next(self._known_spans(text), None) is not None

    # -- rules 1 and 2 on names ---------------------------------------------

    def _is_secret_name(self, name: str) -> bool:
        return is_sensitive_name(name) or _fold(name) in self._leaf_names

    def _is_secret_written_name(self, name: str) -> bool:
        """For a name as written: judged as it stands and percent-decoded (``pass%77ord``;
        but ``%bAuthorization`` must not decode its way out)."""
        return self._is_secret_name(name) or self._is_secret_name(unquote_plus(name))

    def _is_secret_quoted_name(self, raw: str, quote_char: str) -> bool:
        """``raw`` is the name as written between the quotes, escapes included."""
        name: object = raw
        if quote_char == '"':
            try:
                name = json.loads(f'"{raw}"')
            except ValueError:
                name = raw
        return self._is_secret_written_name(str(name)) or self._is_secret_written_name(raw)

    def _quoted_field_spans(self, text: str) -> Iterator[tuple[int, int]]:
        """Values of secret-named ``"name": value`` / ``'name': value`` fields."""
        for match in _QUOTED_FIELD.finditer(text):
            if not self._is_secret_quoted_name(match.group(2), match.group(1)):
                continue
            if match.start(6) >= 0:
                # An object or array: a pattern cannot tell where it ends, the rest goes.
                yield match.start(6), len(text)
            elif match.start(7) >= 0:
                if match.group(7) not in ("null", "None"):
                    yield match.span(7)
            elif match.group(5) is not None:
                yield match.span(4)
            else:
                # A string that is never closed: it runs to the end of the text.
                yield match.start(4), len(text)

    def _pair_spans(self, text: str) -> Iterator[tuple[int, int]]:
        """Values of secret-named ``name=value`` and ``name: value`` pairs.

        Every name is looked at, also one inside the value of another: a pair inside the
        value of a plain name (``a="x password=y"``, ``a=1;password=y``) is found, and so is
        a pair inside a value that is masked already (quotes in broken text do not always
        pair up the way the first match took them).
        """
        # End of the bare run looked at last: no separator lies between its start and there.
        bare_end = -1
        for match in _PAIR_NAME.finditer(text):
            start = match.end()
            if match.group(2) == ":" and text.startswith("//", match.end(2)):
                continue  # ``scheme://``
            # A name inside the bare value of a secret name was swallowed by that value;
            # what follows it (a quoted string) is part of the secret.
            swallowed = start <= bare_end
            if not swallowed and not self._is_secret_written_name(match.group(1)):
                continue
            if start < bare_end and _PAIR_VALUE_START.match(text, start) is None:
                # Inside a bare run that was scanned before: the value ends where that
                # run ends. Not scanning again keeps a long chain of pairs linear.
                yield start, bare_end
                continue
            pattern = _LINE_REST if match.group(2) == ":" else _PAIR_VALUE
            # Matches at every position, if only the empty string.
            value = cast("re.Match[str]", pattern.match(text, start))
            if text[start : start + 1] not in ('"', "'") or pattern is _LINE_REST:
                bare_end = max(bare_end, value.end())
            yield value.span()

    def _flag_spans(self, text: str) -> Iterator[tuple[int, int]]:
        for match in _FLAG.finditer(text):
            if self._is_secret_written_name(match.group(1)):
                yield match.span(2)

    def _multipart_spans(self, text: str) -> Iterator[tuple[int, int]]:
        boundaries: list[int] | None = None
        for match in _MULTIPART_PART.finditer(text):
            name = match.group(1) if match.group(1) is not None else match.group(2)
            if not self._is_secret_written_name(name):
                continue
            if boundaries is None:
                boundaries = [b.start() for b in _BOUNDARY_LINE.finditer(text)]
            index = bisect.bisect_left(boundaries, match.end())
            yield match.end(), boundaries[index] if index < len(boundaries) else len(text)

    def _userinfo_spans(self, text: str) -> Iterator[tuple[int, int]]:
        for match in _USERINFO.finditer(text):
            userinfo = match.group(1)
            if not userinfo:
                continue
            colon = userinfo.find(":")
            # Without a colon the user name may be the token itself.
            yield (match.start(1) + colon + 1 if colon >= 0 else match.start(1)), match.end(1)

    def _mask_once(self, value: str) -> str:
        spans = sorted(
            {
                *self._known_spans(value),
                *self._userinfo_spans(value),
                *(match.span(1) for match in _AUTH_SCHEME.finditer(value)),
                *self._quoted_field_spans(value),
                *self._pair_spans(value),
                *self._flag_spans(value),
                *self._multipart_spans(value),
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
        if not out:
            return value
        out.append(value[position:])
        return "".join(out)

    # -- public -------------------------------------------------------------

    def text(self, value: str) -> str:
        """Mask free text: a body that is not JSON, an address, an error message.

        Invisible format characters (Unicode category Cf) are taken out first: they would
        otherwise split a known secret so that its search no longer finds it.
        """
        out = self._mask_once(_FORMAT.sub("", value))
        decoders: tuple[Callable[[str], str], ...] = (unquote, unquote_plus, _drop_encoded_format)
        for decode in decoders:
            probe = out
            for _ in range(_DECODE_ROUNDS):
                # Without the NUL an escape can bring in: taken out later, it could join two
                # halves of a secret.
                decoded = _FORMAT.sub("", decode(probe).replace("\x00", ""))
                if decoded == probe:
                    break
                masked = self._mask_once(decoded)
                if masked != decoded:
                    out = probe = masked
                else:
                    probe = decoded
        return out

    def value(self, value: Any) -> Any:
        """A masked copy of a JSON-like value (dict, list, string, number ...).

        Dict keys become strings, tuples become lists and bytes become ``<binary N bytes>``.
        ``None`` under a secret name stays ``None``. A value of any other type is masked as
        its ``str()``. Raises ``RecursionError`` for a value nested deeper than the
        interpreter allows.
        """
        return self._value(value)

    def _items(self, items: Iterator[tuple[Any, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, item in items:
            name = key if isinstance(key, str) else str(key)
            if self._is_secret_written_name(name):
                masked = None if item is None else MASK
            else:
                masked = self._value(item)
            written = self.text(name)
            if written in out:
                # A repeated name (or two that mask the same): numbered, so no value is lost.
                number = 2
                while f"{written}#{number}" in out:
                    number += 1
                written = f"{written}#{number}"
            out[written] = masked
        return out

    def _value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, _Pairs):
            return self._items(iter(value))
        if isinstance(value, Mapping):
            return self._items(iter(value.items()))
        if isinstance(value, list | tuple):
            return [self._value(item) for item in value]
        if isinstance(value, bytes | bytearray | memoryview):
            return f"<binary {len(value)} bytes>"
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return MASK if self._has_known(str(value)) else value
        # Fail closed: an unknown type is stored as its masked text, never as it is.
        return self.text(str(value))

    def target(self, target: str) -> str:
        """Mask a request address (URL, path with query string, topic).

        The same as :meth:`text`, which also looks at the percent-decoded address: a known
        secret or a secret-named parameter that only shows after decoding (any spelling,
        for example every character escaped) makes the decoded address the one stored.
        """
        return self.text(target)

    def body(self, text: str) -> str:
        """Mask a message body given as text.

        A JSON object or array (after a byte order mark and white space) is masked field by
        field (rules 1 to 3 on the parsed values, so an escape sequence cannot hide a
        secret) and written back as compact JSON if masking changed something or a name
        occurs more than once in an object (the repeats are numbered, ``name#2``, so that
        no value is lost and no parser can pick a different one). Otherwise the text is
        kept as it came and the text rules of :meth:`text` run over it, as they do for any
        other body. A document nested too deeply to walk is replaced by a fixed note.
        """
        stripped = text.lstrip("\ufeff \t\r\n")
        if stripped[:1] in ("{", "["):

            def pairs(items: list[tuple[str, Any]]) -> dict[str, Any] | _Pairs:
                found = dict(items)
                return found if len(found) == len(items) else _Pairs(items)

            try:
                parsed = json.loads(stripped, object_pairs_hook=pairs)
                masked = self.value(parsed)
                # A ``_Pairs`` (a repeated name) is a list and never equals its masked dict:
                # such a document always counts as changed.
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
        # The same text that masking will see: without invisible format characters, so that
        # a secret they split is found here as well and never cut in two.
        text = _FORMAT.sub("", text)
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

    See the module text for the rules and :class:`Masker` for the parts. A value of a type
    that is not JSON-like is masked as its ``str()``.
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
