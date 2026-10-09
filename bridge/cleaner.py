"""Markdown / text normalizer for the Free TTS Studio bridge.

Strips markdown formatting from text so it narrates cleanly through the
Kokoro engine. Pure stdlib (re only); no new dependencies.

Lives in the bridge so the engine stays untouched and existing callers see
no behavior change unless they opt in by sending `"clean_markdown": true`
in the /v1/synthesize body.

What it does:
  - drops code fences (``` ... ```) and front-matter (--- ... ---) entirely
  - drops images, keeps link labels (drops the URL)
  - strips header, list, blockquote, and HR markers (keeps the text inside)
  - drops inline-code backticks but keeps the inner text
  - drops bold / italic markers but keeps the inner text
  - strips HTML tags, decodes common HTML entities, decodes markdown escapes
  - preserves paragraph breaks (blank lines); collapses single newlines
    within a paragraph to spaces

What it intentionally does NOT do:
  - parse markdown correctly for every edge case (nested formatting,
    indented code blocks, esoteric flavors). This is a regex pass, not a
    full parser; it covers the common 80% of real-world input (READMEs,
    blog posts, doc pages).
"""


import re

# Pre-compiled patterns. Order of application matters and is documented
# in clean_markdown() below; do not reorder casually.

_FRONTMATTER = re.compile(
    r'\A---[ \t]*\r?\n.*?\r?\n---[ \t]*\r?\n', re.DOTALL,
)

# Fenced code blocks: ```...``` or ~~~...~~~
_FENCE = re.compile(r'(```|~~~).*?\1', re.DOTALL)

# Image syntax must be stripped before link syntax (different leading char).
_IMG_INLINE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_IMG_REF = re.compile(r'!\[[^\]]*\]\[[^\]]*\]')

# Reference-style link definitions (e.g. `[foo]: http://...`) on their own line.
_LINK_REF_DEF = re.compile(
    r'^[ \t]*\[[^\]]+\]:[ \t]*\S+.*$', re.MULTILINE,
)

# Links: keep the visible label, drop the URL.
_LINK_INLINE = re.compile(r'\[([^\]]+)\]\(([^)]*)\)')
_LINK_REF = re.compile(r'\[([^\]]+)\]\[[^\]]*\]')

# Phonetic hint: [word](/ipa-or-arpabet/) -- the URL is wrapped in slashes
# and contains phoneme characters rather than an http(s) target. This is
# Kokoro's official syntax for inline pronunciation overrides (see the
# model card example `[Kokoro](/kˈOkəɹO/)`). The cleaner preserves these
# wholesale; any other markdown link still has its URL stripped.
_PHONETIC_HINT = re.compile(r'\[([^\]]+)\]\((/[^()\s]+/)\)')

# HTML tags (open / close / self-closing).
_HTML_TAG = re.compile(r'<[^>]+>')

# Per-line markers.
_HEADER = re.compile(r'^[ \t]*(#{1,6})[ \t]+', re.MULTILINE)
_BLOCKQUOTE = re.compile(r'^[ \t]*>[ \t]?', re.MULTILINE)
# List markers: -, *, +, or 1. / 23. etc. We replace the marker AND a leading
# paragraph break, so list items narrate as separate "lines" instead of
# running together.
_LIST = re.compile(r'^[ \t]*(?:[-*+]|\d+\.)[ \t]+', re.MULTILINE)

# Horizontal rules: a line that is purely ---, ***, or ___ (3+ chars).
_HR = re.compile(r'^[ \t]*([-*_])[ \t]*\1{2,}[ \t]*$', re.MULTILINE)

# Inline code: keep inner text, drop backticks.
_INLINE_CODE = re.compile(r'`([^`]+)`')

# Bold then italic. Longest marker first so `**foo**` is consumed before `*foo*`.
# Negative lookbehind on BOTH opening and closing markers so escaped
# characters (\*foo\*) don't get treated as emphasis markers. The escape
# decoder below then turns \* into a literal *.
_BOLD_STAR = re.compile(r'(?<!\\)\*\*([^*\n]+)(?<!\\)\*\*')
_BOLD_UNDER = re.compile(r'(?<!\\)__([^_\n]+)(?<!\\)__')
_ITALIC_STAR = re.compile(r'(?<!\\)\*([^*\n]+)(?<!\\)\*')
# Italic with underscores: require word boundaries so snake_case_var isn't touched.
_ITALIC_UNDER = re.compile(r'(?<!\\)\b_([^_\n]+)(?<!\\)_\b')

# Markdown backslash escapes: \* -> *, \# -> #, etc.
_ESCAPE = re.compile(r'\\(.)')

# Tiny HTML-entity table for the common ones. Numeric refs (&#123;) skipped.
_ENTITIES = {
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&apos;': "'",
    '&#39;': "'",
    '&nbsp;': ' ',
    '&mdash;': '\u2014',
    '&ndash;': '\u2013',
    '&hellip;': '\u2026',
    '&rsquo;': '\u2019',
    '&lsquo;': '\u2018',
    '&rdquo;': '\u201d',
    '&ldquo;': '\u201c',
}

# Paragraph break: one or more blank lines (whitespace-only lines).
_PARAGRAPH_BREAK = re.compile(r'[ \t]*\r?\n[ \t]*(?:\r?\n[ \t]*)+')
# Single newline within a paragraph.
_INNER_NEWLINE = re.compile(r'[ \t]*\r?\n[ \t]*')
# Runs of spaces / tabs (within a paragraph).
_MULTI_WS = re.compile(r'[ \t]+')

# Acronyms that should be all-caps for TTS reading (the model reads "GPU"
# as "G P U" but "gpu" as a single syllable -- capitalizing fixes that).
# Lower-case keys; matching is case-insensitive and word-boundary.
_KNOWN_ACRONYMS = frozenset({
    # tech / dev
    'api', 'cli', 'css', 'cdn', 'csv', 'dns', 'dom', 'gcp', 'gpu', 'gui',
    'http', 'https', 'ide', 'id', 'io', 'ip', 'json', 'js', 'jwt', 'llm',
    'ml', 'mvp', 'nlp', 'npm', 'ocr', 'os', 'pdf', 'png', 'rag', 'ram',
    'rest', 'rpc', 'rss', 'sdk', 'sql', 'ssh', 'ssl', 'svg', 'tcp', 'tls',
    'tts', 'udp', 'ui', 'uri', 'url', 'usb', 'utf', 'uuid', 'ux', 'vm',
    'vpn', 'wlan', 'xml', 'yaml',
    # company / product
    'aws', 'ibm', 'ms', 'nasa',
    # geo / org
    'dc', 'eu', 'la', 'nyc', 'sf', 'uk', 'usa', 'ussr',
    # role / title
    'ceo', 'cfo', 'cto', 'vp',
    # misc
    'asap', 'aka', 'fyi', 'imo', 'irl', 'tbh', 'tba', 'tbd', 'tl', 'dr',
    'mr', 'mrs', 'ms', 'st',
})

# Word-boundary aware word match (letters / digits / underscore).
_ACRONYM_MATCH = re.compile(r'\b[A-Za-z][A-Za-z0-9]*\b')

# Long sentence splitter (>= LONG_SENTENCE_WORDS words ends with '.', '!', '?').
# The trailing (?=\s|\Z) lets us match the last sentence in a text even if it
# has no trailing whitespace.
_LONG_SENTENCE = re.compile(
    r'(.{1,300}?[\.!?])(?=\s|\Z)',
    re.DOTALL,
)
LONG_SENTENCE_WORDS = 30
LONG_SENTENCE_INSERT = ', '


def _decode_entities(text):
    for k, v in _ENTITIES.items():
        text = text.replace(k, v)
    return text


# A unique placeholder format used to stash phonetic-hint links during
# markdown processing so the link/emphasis regexes don't eat them. NUL bytes
# don't appear in prose input, so the format string is unambiguous.
_PHONETIC_PLACEHOLDER = '\x00PHONETIC{idx}\x00'


def _stash_phonetic_hints(text):
    """Replace [word](/ipa/) links with placeholders; returns (text, list)."""
    stash = []

    def _repl(m):
        idx = len(stash)
        stash.append(m.group(0))
        return _PHONETIC_PLACEHOLDER.format(idx=idx)

    return _PHONETIC_HINT.sub(_repl, text), stash


def _restore_phonetic_hints(text, stash):
    for i, original in enumerate(stash):
        text = text.replace(_PHONETIC_PLACEHOLDER.format(idx=i), original)
    return text


def clean_markdown(text):
    """Return narration-friendly prose derived from markdown `text`.

    Empty / non-string input is returned unchanged. The function never raises.
    """
    if not isinstance(text, str) or not text:
        return text

    out = text

    # 0. Stash Kokoro phonetic-hint links ([word](/ipa/)) so the rest of the
    #    markdown processing doesn't strip them. We restore them at the very
    #    end so the engine still sees [word](/pronunciation/) verbatim.
    out, _phonetic_stash = _stash_phonetic_hints(out)

    # 1. Front matter (YAML between --- fences at top of doc).
    out = _FRONTMATTER.sub('', out, count=1)

    # 2. Fenced code blocks.
    out = _FENCE.sub('', out)

    # 3. Images (must come before links).
    out = _IMG_INLINE.sub(' ', out)
    out = _IMG_REF.sub(' ', out)

    # 4. Link reference definitions (own line).
    out = _LINK_REF_DEF.sub('', out)

    # 5. Links: keep label, drop URL.
    out = _LINK_INLINE.sub(r'\1', out)
    out = _LINK_REF.sub(r'\1', out)

    # 6. HTML tags.
    out = _HTML_TAG.sub(' ', out)

    # 7. Per-line markers: headers, blockquotes, lists, HR.
    out = _HEADER.sub('', out)
    out = _BLOCKQUOTE.sub('', out)
    # Lists: replace the marker + following whitespace with a paragraph break
    # so each item becomes its own "paragraph" for narration. The extra
    # newlines get collapsed by the paragraph pass below.
    out = _LIST.sub('\n\n', out)
    out = _HR.sub('', out)

    # 8. Inline code (keeps inner text).
    out = _INLINE_CODE.sub(r'\1', out)

    # 9. Bold then italic. Bold first so ** isn't partially consumed by italic.
    #    The regexes use negative lookbehind for \ so escaped markers survive.
    out = _BOLD_STAR.sub(r'\1', out)
    out = _BOLD_UNDER.sub(r'\1', out)
    out = _ITALIC_STAR.sub(r'\1', out)
    out = _ITALIC_UNDER.sub(r'\1', out)

    # 10. Markdown backslash escapes. Runs AFTER emphasis so a literal
    #     "\*foo\*" survives the italic pass, then becomes "*foo*".
    out = _ESCAPE.sub(r'\1', out)

    # 11. HTML entities.
    out = _decode_entities(out)

    # 12. Paragraph pass.
    #     - Blank lines separate paragraphs (kept as \n\n in the output).
    #     - Single newlines within a paragraph become single spaces.
    #     - Runs of spaces/tabs collapse to one.
    paragraphs = _PARAGRAPH_BREAK.split(out)
    cleaned = []
    for para in paragraphs:
        para = _INNER_NEWLINE.sub(' ', para)
        para = _MULTI_WS.sub(' ', para).strip()
        if para:
            cleaned.append(para)
    out = '\n\n'.join(cleaned)

    # 13. Restore the phonetic-hint links that we stashed at the start.
    out = _restore_phonetic_hints(out, _phonetic_stash)

    return out


def tts_normalize(text):
    """Apply TTS-specific normalizations to prose `text`.

    - Capitalize known acronyms so the model reads them letter-by-letter
      ("GPU" not "gpu", "API" not "api", "USA" not "usa").
    - Insert a short pause (", ") in very long sentences (>= 30 words) to
      give Kokoro room for natural prosody.

    Empty / non-string input is returned unchanged. The function never raises.
    """
    if not isinstance(text, str) or not text:
        return text

    # Capitalize known acronyms. Word-boundary regex keeps us from touching
    # "id" inside "idea" or "ssn" inside "lesson".
    def _cap(m):
        word = m.group(0)
        if word.lower() in _KNOWN_ACRONYMS:
            return word.upper()
        return word
    text = _ACRONYM_MATCH.sub(_cap, text)

    # Break long sentences at the earliest clause boundary. We look for a
    # comma + space within the sentence body and, if found, insert a
    # breathing pause right after it (so we get ", , " instead of ",, ").
    def _break_long(m):
        sentence = m.group(1)
        if len(sentence.split()) < LONG_SENTENCE_WORDS:
            return sentence
        for i in range(8, len(sentence) - 1):
            if sentence[i] == ',' and sentence[i + 1] == ' ':
                # Insert ", " right after the existing ", "
                return sentence[:i + 2] + LONG_SENTENCE_INSERT + sentence[i + 2:]
        # No comma+space found: fall back to a hard split at position 8.
        if len(sentence) > 8:
            return sentence[:8] + LONG_SENTENCE_INSERT + sentence[8:].lstrip()
        return sentence

    text = _LONG_SENTENCE.sub(_break_long, text)
    return text
