import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "telegram"))
import fmt  # noqa: E402
from tg import split_message  # noqa: E402


def test_german_numbers():
    assert fmt.num(1234.5, 2) == "1.234,50"
    assert fmt.money(10000) == "10.000" and fmt.money(12.345) == "12,35"
    assert fmt.pct(0.0123) == "+1,2 %" and fmt.pct(-0.5, 0) == "-50 %" and fmt.pct(None) == "–"
    assert fmt.price(84120.5) == "84.120,50" and fmt.price(0.51234) == "0,5123"


def test_duration():
    assert fmt.dur(1.5) == "1 T 12 h"
    assert fmt.dur(0.05) == "1 h 12 min"
    assert fmt.dur(0.001) == "1 min"


def test_table_aligns_and_escapes():
    t = fmt.table(["Wallet", "Wert"], [["a<b", "1"], ["long-name", "10.000"]])
    assert t.startswith("<pre>") and t.endswith("</pre>")
    assert "a&lt;b" in t
    lines = t[5:-6].split("\n")
    assert len({len(l) for l in lines[2:]}) == 1 or lines[3].endswith("10.000")  # rechtsbündige Zahlen


def test_split_keeps_pre_balanced():
    body = "<b>Titel</b>\n<pre>" + "\n".join(f"zeile {i:04d} " + "x" * 60 for i in range(200)) + "</pre>\nEnde"
    parts = split_message(body, 1000)
    assert len(parts) > 5 and all(len(p) <= 1000 for p in parts)
    for p in parts:
        assert p.count("<pre>") == p.count("</pre>"), p[:80]
    assert "".join(parts).replace("</pre><pre>", "").count("zeile") == 200


def test_split_short_message_untouched():
    assert split_message("kurz") == ["kurz"]
