"""Unit tests for cleaner.clean_markdown. Stdlib only; no project deps."""
import unittest

from cleaner import clean_markdown, tts_normalize


class TestCleanMarkdown(unittest.TestCase):

    # --- safety / no-op behavior -----------------------------------------

    def test_empty_string_passes_through(self):
        self.assertEqual(clean_markdown(''), '')

    def test_none_passes_through(self):
        self.assertIsNone(clean_markdown(None))

    def test_non_string_passes_through(self):
        self.assertEqual(clean_markdown(123), 123)

    def test_plain_prose_unchanged(self):
        text = 'Hello world. This is plain prose with a comma, a period.'
        self.assertEqual(clean_markdown(text), text)

    # --- headers / structure ----------------------------------------------

    def test_h1_marker_stripped(self):
        self.assertEqual(
            clean_markdown('# Title\n\nBody paragraph.'),
            'Title\n\nBody paragraph.',
        )

    def test_h1_to_h6_markers_stripped(self):
        self.assertEqual(
            clean_markdown('# H1\n\n## H2\n\n### H3\n\n#### H4\n\n##### H5\n\n###### H6\n\nBody.'),
            'H1\n\nH2\n\nH3\n\nH4\n\nH5\n\nH6\n\nBody.',
        )

    def test_header_without_space_left_alone(self):
        # "#tag" isn't a header — no space after the #s.
        self.assertEqual(clean_markdown('#tag in prose.'), '#tag in prose.')

    # --- links / images ----------------------------------------------------

    def test_inline_link_keeps_label_drops_url(self):
        self.assertEqual(
            clean_markdown('See [our docs](https://example.com/path) for details.'),
            'See our docs for details.',
        )

    def test_reference_link_keeps_label(self):
        self.assertEqual(
            clean_markdown('See [the spec][1] for details.'),
            'See the spec for details.',
        )

    def test_link_reference_definition_dropped(self):
        self.assertEqual(
            clean_markdown('See [the spec][1].\n\n[1]: http://example.com "Title"'),
            'See the spec.',
        )

    # --- phonetic hints (Kokoro's [word](/ipa/) syntax) ---------------

    def test_phonetic_hint_preserved_verbatim(self):
        # The URL is wrapped in slashes and contains IPA characters;
        # the cleaner must NOT strip it like a real markdown link.
        self.assertEqual(
            clean_markdown('[Kokoro](/kˈOkəɹO/) is open-weight.'),
            '[Kokoro](/kˈOkəɹO/) is open-weight.',
        )

    def test_phonetic_hint_with_arpabet_preserved(self):
        self.assertEqual(
            clean_markdown('Use [SQL](/ˌɛskjuːˈɛl/) for queries.'),
            'Use [SQL](/ˌɛskjuːˈɛl/) for queries.',
        )

    def test_real_link_still_stripped_alongside_phonetic_hint(self):
        # A real https link and a phonetic hint in the same line -- only
        # the real URL should be dropped.
        self.assertEqual(
            clean_markdown('Visit [docs](https://example.com) and [Nguyen](/wɪn/).'),
            'Visit docs and [Nguyen](/wɪn/).',
        )

    def test_phonetic_hint_inside_list(self):
        # The list-marker regex replaces '-' + spaces with '\n\n', but the
        # hint stash runs first so it survives.
        self.assertEqual(
            clean_markdown('- [Python](/ˈpaɪθən/) is great\n- [Kokoro](/kˈOkəɹO/) too'),
            '[Python](/ˈpaɪθən/) is great\n\n[Kokoro](/kˈOkəɹO/) too',
        )


class TestTtsNormalize(unittest.TestCase):

    def test_empty_passes_through(self):
        self.assertEqual(tts_normalize(''), '')
        self.assertIsNone(tts_normalize(None))
        self.assertEqual(tts_normalize(123), 123)

    def test_known_acronym_uppercased(self):
        self.assertEqual(
            tts_normalize('The api and the gpu are fast.'),
            'The API and the GPU are fast.',
        )

    def test_unknown_word_unchanged(self):
        # "idea" contains "id" as a substring; the word-boundary check
        # must not promote it.
        self.assertEqual(
            tts_normalize('That idea was solid.'),
            'That idea was solid.',
        )

    def test_mixed_case_acronym_normalized(self):
        self.assertEqual(
            tts_normalize('Use http or Https for the API.'),
            'Use HTTP or HTTPS for the API.',
        )

    def test_short_sentence_not_split(self):
        # < 30 words, no change.
        text = 'This is a short sentence about the API and the GPU.'
        self.assertEqual(tts_normalize(text), text)

    def test_long_sentence_gets_a_breathing_pause(self):
        # 33+ words so it crosses the LONG_SENTENCE_WORDS threshold.
        long = (
            'The team spent the entire quarter planning, '
            'building, testing, documenting, reviewing, refining, and '
            'finally shipping the new feature to production after much '
            'deliberation about scope and timing for the rollout plan.'
        )
        word_count = len(long.split())
        self.assertGreaterEqual(word_count, 30, 'test fixture must be long enough')
        out = tts_normalize(long)
        # We injected ", " right after the first ", " in the sentence, so
        # the output now contains the ", , " pattern (comma-space-comma-space).
        self.assertIn(', , ', out, f'expected injected pause in: {out!r}')
        self.assertGreater(len(out), len(long))

    def test_image_dropped(self):
        # Whitespace around the dropped image collapses to a single space.
        self.assertEqual(
            clean_markdown('Before ![alt text](http://x.com/y.png) after.'),
            'Before after.',
        )

    # --- code --------------------------------------------------------------

    def test_fenced_code_block_dropped(self):
        self.assertEqual(
            clean_markdown('Intro.\n\n```python\nprint("hi")\n```\n\nOutro.'),
            'Intro.\n\nOutro.',
        )

    def test_tilde_fenced_code_block_dropped(self):
        self.assertEqual(
            clean_markdown('Intro.\n\n~~~ruby\nputs "hi"\n~~~\n\nOutro.'),
            'Intro.\n\nOutro.',
        )

    def test_inline_code_keeps_inner_text(self):
        self.assertEqual(
            clean_markdown('Run `print(x)` to test.'),
            'Run print(x) to test.',
        )

    def test_html_tags_dropped(self):
        # Whitespace runs are collapsed at the end, so single spaces remain
        # where the tags used to be.
        self.assertEqual(
            clean_markdown('A <b>bold</b> word and <em>em</em>.'),
            'A bold word and em .',
        )

    # --- emphasis ----------------------------------------------------------

    def test_bold_with_stars_stripped(self):
        self.assertEqual(clean_markdown('**bold** word.'), 'bold word.')

    def test_bold_with_underscores_stripped(self):
        self.assertEqual(clean_markdown('__bold__ word.'), 'bold word.')

    def test_italic_with_stars_stripped(self):
        self.assertEqual(clean_markdown('*italic* word.'), 'italic word.')

    def test_italic_with_underscores_stripped(self):
        self.assertEqual(clean_markdown('word _italic_ here.'), 'word italic here.')

    def test_snake_case_left_alone(self):
        # Underscores in identifiers must not be eaten as italic markers.
        self.assertEqual(
            clean_markdown('Use snake_case_var in your code.'),
            'Use snake_case_var in your code.',
        )

    # --- lists -------------------------------------------------------------

    def test_unordered_list_separated_into_paragraphs(self):
        self.assertEqual(
            clean_markdown('- one\n- two\n- three'),
            'one\n\ntwo\n\nthree',
        )

    def test_ordered_list_separated_into_paragraphs(self):
        self.assertEqual(
            clean_markdown('1. first\n2. second\n3. third'),
            'first\n\nsecond\n\nthird',
        )

    def test_nested_list_keeps_indented_marker(self):
        # Indented markers still stripped, but they don't get their own paragraph.
        text = '- outer one\n- outer two'
        self.assertEqual(clean_markdown(text), 'outer one\n\nouter two')

    # --- blockquote / horizontal rule -------------------------------------

    def test_blockquote_marker_stripped(self):
        self.assertEqual(clean_markdown('> quoted line.'), 'quoted line.')

    def test_horizontal_rule_dropped(self):
        self.assertEqual(
            clean_markdown('Before.\n\n---\n\nAfter.'),
            'Before.\n\nAfter.',
        )

    # --- entities / escapes -----------------------------------------------

    def test_html_entities_decoded(self):
        self.assertEqual(
            clean_markdown('Tom &amp; Jerry said &quot;hi&quot;.'),
            'Tom & Jerry said "hi".',
        )

    def test_markdown_escape_decoded(self):
        self.assertEqual(
            clean_markdown(r'This is \*not italic\*.'),
            'This is *not italic*.',
        )

    # --- paragraph preservation -------------------------------------------

    def test_paragraph_breaks_preserved(self):
        self.assertEqual(
            clean_markdown('Para 1 line 1.\nPara 1 line 2.\n\nPara 2.'),
            'Para 1 line 1. Para 1 line 2.\n\nPara 2.',
        )

    def test_multiple_paragraph_breaks_collapse_to_one(self):
        self.assertEqual(
            clean_markdown('A.\n\n\n\n\nB.'),
            'A.\n\nB.',
        )

    # --- front matter -----------------------------------------------------

    def test_front_matter_dropped(self):
        self.assertEqual(
            clean_markdown('---\ntitle: Foo\nauthor: Bar\n---\n\n# Heading\n\nBody.'),
            'Heading\n\nBody.',
        )

    # --- full integration ------------------------------------------------

    def test_full_readme_snippet(self):
        src = (
            '# Project Title\n\n'
            'A short description.\n\n'
            '## Installation\n\n'
            'Run `pip install foo` then:\n\n'
            '```bash\n'
            'pip install foo\n'
            '```\n\n'
            'See [the docs](https://example.com/docs) for more.\n'
        )
        expected = (
            'Project Title\n\n'
            'A short description.\n\n'
            'Installation\n\n'
            'Run pip install foo then:\n\n'
            'See the docs for more.'
        )
        self.assertEqual(clean_markdown(src), expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
