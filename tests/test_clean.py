from voicechat.clean import clean


def speak(md, **kw):
    return clean(md, **kw).text


def test_drops_fenced_code_and_counts_it():
    out = clean("Run this:\n```bash\nnpm install\n```\nThen restart.")
    assert out.text == "Run this. Then restart."
    assert out.dropped_code_blocks == 1


def test_keeps_short_inline_code_drops_long():
    assert speak("Call `fetchUser()` next.") == "Call fetchUser() next."
    long = "`" + "x" * 60 + "`"
    assert speak(f"Paste {long} there.") == "Paste there."


def test_links_and_urls():
    assert speak("See [the docs](https://example.com/a/b) and https://x.y/z now.") == "See the docs and link now."


def test_headings_bullets_bold_and_quotes():
    md = "## Summary\n\n- **First** item\n- Second _item_\n> quoted\n1. numbered"
    assert speak(md) == "Summary. First item. Second item. quoted. numbered."


def test_tables_are_dropped():
    md = "Results:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nDone."
    assert speak(md) == "Results. Done."


def test_paths_become_basenames():
    assert speak("Edited src/voicechat/clean.py and /Users/me/dev/app/main.go today.") == (
        "Edited clean.py and main.go today."
    )
    assert speak("Look at clean.py:42 for the bug.") == "Look at clean.py line 42 for the bug."
    assert speak("See src/voicechat/clean.py:42:7 too.") == "See clean.py line 42 too."


def test_secrets_are_redacted():
    assert "sk-abc" not in speak("Key is sk-abcdefghijklmnopqrstuvwxyz1234 ok.")
    assert speak("Token ghp_abcdefghijklmnopqrstuvwxyz123456 set.") == "Token redacted set."
    assert "deadbeef" not in speak("Hash deadbeefdeadbeefdeadbeefdeadbeefdeadbeef done.")
    assert speak("password: hunter2 was weak.") == "redacted was weak."


def test_symbols_are_spoken():
    assert speak("Rename a -> b && go.") == "Rename a to b and go."


def test_truncates_at_sentence_boundary():
    md = "One sentence here. Two sentence here. Three sentence here. Four sentence here."
    out = clean(md, max_chars=45, truncation_suffix="More on screen.")
    assert out.truncated
    assert out.text == "One sentence here. Two sentence here. More on screen."


def test_no_truncation_when_short():
    out = clean("Short reply.", max_chars=700)
    assert not out.truncated and out.text == "Short reply."


def test_only_code_means_silence():
    assert speak("```py\nprint(1)\n```") == ""
    assert speak("---\n\n| a |\n") == ""


def test_unterminated_fence_dropped():
    assert speak("Here you go:\n```python\nprint('x')") == "Here you go."
