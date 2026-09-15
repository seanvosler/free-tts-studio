"""SpaCy-free English G2P for Kokoro/misaki.

misaki's English frontend normally relies on spaCy for tokenization,
POS tagging and whitespace attribution. On machines where Windows Smart App
Control blocks spaCy's unsigned native DLLs, we substitute a pure-Python
tokenizer/POS tagger built on NLTK. It produces the same Penn/OntoNotes-style
tags misaki's lexicon expects, so pronunciation quality is preserved.

Import order matters: `patch()` MUST run before `misaki.en` is imported.
"""

import sys
import types

import nltk
from nltk.tag import PerceptronTagger
from nltk.tokenize import word_tokenize

_TAGGER = PerceptronTagger()


def _install_spacy_stub():
    """Pretend spaCy exists so `misaki.en` can be imported."""
    def _noop(*args, **kwargs):
        return None

    stub = types.ModuleType('spacy')
    stub.is_package = _noop
    stub.cli = types.ModuleType('spacy.cli')
    stub.cli.download = _noop
    stub.util = types.ModuleType('spacy.util')
    stub.util.is_package = _noop
    stub.training = types.ModuleType('spacy.training')
    stub.training.Alignment = _noop
    sys.modules['spacy'] = stub
    sys.modules['spacy.cli'] = stub.cli
    sys.modules['spacy.util'] = stub.util
    sys.modules['spacy.training'] = stub.training


class _Token:
    __slots__ = ('text', 'tag_', 'whitespace_')

    def __init__(self, text, tag_, whitespace_=''):
        self.text = text
        self.tag_ = tag_
        self.whitespace_ = whitespace_

    def __repr__(self):
        return f'{self.text!r}/{self.tag_!r}'


def _normalize_tag(text, tag):
    """Bring NLTK output in line with the tags misaki expects."""
    punct = {
        '.': '.', ',': ',', '!': '.', '?': '.', ';': '.', '…': '.',
        ':': ':', ';': '.',
        '-': ':', '–': ':', '—': '.',
        '(': '-LRB-', ')': '-RRB-', '[': '-LRB-', ']': '-RRB-',
    }
    if text in ('``', '"', '"'):
        return '``'
    if text in ("''", "'"):
        return "''"
    if text in punct:
        return punct[text]
    if not tag:
        return 'NN'
    return tag


def _whitespace(text, tokens):
    """Attach spaCy-style whitespace_ by matching tokens back to the source."""
    out = []
    spans = []
    pos = 0
    for tok in tokens:
        start = text.find(tok, pos)
        if start == -1:
            n = text.count(tok[:1]) if tok else -1
            start = pos
            if len(tok) == 1:
                cand = text.find(tok, pos)
                if cand != -1:
                    start = cand
        spans.append((start, start + len(tok)))
        pos = start + len(tok) if start >= pos else pos + len(tok)
    for i, (start, end) in enumerate(spans):
        if i + 1 < len(spans):
            ws = text[end:spans[i + 1][0]]
        else:
            ws = text[end:]
        out.append((start, end, ws))
    return out


class LightTokenizer:
    """Pure-Python spaCy-flavoured tokenizer + tagger."""

    def __init__(self):
        self.tagger = _TAGGER

    def __call__(self, text):
        raw = word_tokenize(text)
        tagged = self.tagger.tag(raw)
        spans = _whitespace(text, raw)
        tokens = []
        for (tok, tag), (start, end, ws) in zip(tagged, spans):
            tokens.append(_Token(tok, _normalize_tag(tok, tag), ws))
        return tokens


def make_en_g2p():
    """Return a misaki `en.G2P` subclass that never touches spaCy."""
    from misaki import en as en_misaki

    _tokenizer = LightTokenizer()

    class NoSpacyG2P(en_misaki.G2P):
        def __init__(self, version=None, trf=False, british=False, fallback=None, unk=''):
            self.version = version
            self.british = british
            self.lexicon = en_misaki.Lexicon(british)
            self.fallback = fallback if fallback else None
            self.unk = unk

        def tokenize(self, text, tokens, features):
            return [
                en_misaki.MToken(
                    text=_t.text,
                    tag=_t.tag_,
                    whitespace=_t.whitespace_,
                    _=en_misaki.MToken.Underscore(is_head=True, num_flags='', prespace=False),
                )
                for _t in _tokenizer(text)
            ]

    return NoSpacyG2P


def apply():
    """Install the spaCy stub and swap misaki's English G2P."""
    _install_spacy_stub()
    from misaki import en as en_misaki
    en_misaki.G2P = make_en_g2p()