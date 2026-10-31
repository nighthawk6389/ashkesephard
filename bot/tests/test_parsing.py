"""Fast checks for email parsing and recipe conversion (no mail server needed)."""
import json
from pathlib import Path

from bot.config import parse_family
from bot.mail import parse_message, split_quoted
from bot.store import SiteData

REPO = Path(__file__).resolve().parents[2]


def test_split_quoted_gmail_wrapped_header():
    own, quoted = split_quoted("It's 2 lemons not 3.\n\nOn Fri, Oct 30, 2026 at 3:12 PM AshkeSephard Recipe Bot <\nbot@x.com> wrote:\n> “Orlee's Lemon Chicken” is now on the site.")
    assert own == "It's 2 lemons not 3."
    assert "is now on the site" in quoted


def test_split_quoted_apple_mail_and_signoff():
    own, _ = split_quoted("Made it, perfect as is!\n\nSent from my iPhone\n\nOn Oct 30, 2026, at 15:12, Bot <b@x.com> wrote:\n\n> hi")
    assert own == "Made it, perfect as is!"


def test_split_quoted_outlook():
    own, quoted = split_quoted("Fix the salt please\n\n-----Original Message-----\nFrom: Bot\nSent: today")
    assert own == "Fix the salt please" and quoted.startswith("-----Original")


def test_parse_family_formats():
    assert parse_family('{"Orlee@Example.com": "Orlee"}') == {"orlee@example.com": "Orlee"}
    assert parse_family("Orlee <orlee@example.com>\nDoda Pnena <PNENA@example.com>\n") == {
        "orlee@example.com": "Orlee", "pnena@example.com": "Doda Pnena"}


def test_parse_html_only_message_drops_gmail_quote():
    raw = (b"From: Dana <dana@x.com>\r\nTo: bot@x.com\r\nSubject: hi\r\nMessage-ID: <1@x>\r\n"
           b"Content-Type: text/html; charset=utf-8\r\n\r\n"
           b"<div>Made it!<br>Loved it.</div><div class=\"gmail_quote\">On Mon wrote:<br>old</div>")
    msg = parse_message("1", raw)
    assert msg.sender == "dana@x.com" and msg.sender_display == "Dana"
    assert msg.text == "Made it!\nLoved it." and "old" in msg.quoted


def test_blog_recipe_round_trips_through_model_format():
    catalog = json.loads((REPO / "site/data/recipes.json").read_text())
    for recipe in catalog["recipes"]:
        model = SiteData.for_model(recipe)
        sections = SiteData.to_sections(model)
        flat = lambda secs: [(i["text"], bool(i.get("sub"))) for s in secs for i in s["items"]]
        assert sorted(flat(sections)) == sorted(flat(recipe["sections"])), recipe["slug"]
