"""End-to-end test of the recipe bot against a real IMAP/SMTP server (GreenMail), with Claude scripted.

Needs Java and the GreenMail standalone jar:
  curl -o /tmp/greenmail.jar https://repo1.maven.org/maven2/com/icegreen/greenmail-standalone/2.1.3/greenmail-standalone-2.1.3.jar
  GREENMAIL_JAR=/tmp/greenmail.jar python -m pytest bot/tests -q
"""
import email
import email.policy
import imaplib
import io
import json
import os
import shutil
import smtplib
import socket
import ssl
import subprocess
import time
from email.message import EmailMessage
from pathlib import Path

import pytest
from PIL import Image

from bot import run as bot_run
from bot import store
from bot.ai import CLASSIFY_SCHEMA, FIX_SCHEMA, ModelError, ScriptedReader
from bot.config import Settings
from bot.mail import IGNORED_FOLDER, PROCESSED_FOLDER

REPO = Path(__file__).resolve().parents[2]
JAR = os.environ.get("GREENMAIL_JAR")
DOMAIN = "family.test"
BOT, ORLEE, DANA, STRANGER = (f"bot@{DOMAIN}", f"orlee@{DOMAIN}", f"dana@{DOMAIN}", "someone@elsewhere.test")
PASSWORD = "secret"

pytestmark = pytest.mark.skipif(not JAR or not shutil.which("java"), reason="needs GREENMAIL_JAR and java")


# ---------------------------------------------------------------- fixtures

def wait_for_port(port, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"port {port} never opened")


@pytest.fixture(scope="module")
def greenmail():
    users = ",".join(f"{a}:{PASSWORD}@{DOMAIN}".replace(f"@{DOMAIN}:", ":") for a in (BOT, ORLEE, DANA))
    proc = subprocess.Popen(
        ["java", "-Dgreenmail.setup.test.all", f"-Dgreenmail.users={users}", "-Dgreenmail.users.login=email",
         "-Dgreenmail.hostname=127.0.0.1", "-jar", JAR],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for port in (3025, 3993, 3465):
            wait_for_port(port)
        yield
    finally:
        proc.terminate()
        proc.wait(10)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """A throwaway git repo holding a copy of the real site data, with the bot pointed at it."""
    root = tmp_path_factory.mktemp("repo")
    (root / "site" / "data").mkdir(parents=True)
    shutil.copy(REPO / "site" / "data" / "recipes.json", root / "site" / "data" / "recipes.json")
    (root / "site" / "data" / "community.json").write_text('{"comments": [], "requests": []}\n')
    for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "bot"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "bot@test"], cwd=root, check=True)
    patches = {"RECIPES": root / "site/data/recipes.json", "COMMUNITY": root / "site/data/community.json",
               "STATE": root / "data/bot_state.json", "FAMILY_PHOTOS": root / "site/photos/family"}
    old = {k: getattr(store, k) for k in patches}
    for k, v in patches.items():
        setattr(store, k, v)
    old_root, bot_run.ROOT = bot_run.ROOT, root
    yield root
    for k, v in old.items():
        setattr(store, k, v)
    bot_run.ROOT = old_root


SETTINGS = Settings(bot_address=BOT, app_password=PASSWORD, imap_host="127.0.0.1", imap_port=3993,
                    smtp_host="127.0.0.1", smtp_port=3465, site_url="https://recipes.example",
                    admin_email=DANA, family={ORLEE: "Orlee", DANA: "Dana"})
INSECURE = ssl._create_unverified_context()  # GreenMail's self-signed certificate


def jpeg(color, size=(900, 1200), text_noise=True):
    image = Image.new("RGB", size, color)
    if text_noise:  # make the file big enough not to be mistaken for a logo
        image.putdata([(color[0] ^ (i % 37), color[1] ^ (i % 23), color[2] ^ (i % 11)) for i in range(size[0] * size[1])])
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def heic(color):
    import pillow_heif
    out = io.BytesIO()
    pillow_heif.from_pillow(Image.open(io.BytesIO(jpeg(color)))).save(out, quality=80)
    return out.getvalue()


def send(sender, subject, text=None, html=None, attachments=(), message_id=None, in_reply_to=None):
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"], msg["To"], msg["Subject"] = sender, BOT, subject
    msg["Message-ID"] = message_id or email.utils.make_msgid(domain=DOMAIN)
    if in_reply_to:
        msg["In-Reply-To"] = msg["References"] = in_reply_to
    if text:
        msg.set_content(text)
    if html:
        if text:
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(html, subtype="html")
    for name, ctype, data in attachments:
        maintype, subtype = ctype.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    with smtplib.SMTP("127.0.0.1", 3025) as smtp:
        smtp.send_message(msg)
    return msg["Message-ID"]


def mailbox(user, folder="INBOX"):
    imap = imaplib.IMAP4_SSL("127.0.0.1", 3993, ssl_context=INSECURE)
    imap.login(user, PASSWORD)
    status, _ = imap.select(folder)
    if status != "OK":
        imap.logout()
        return []
    _, data = imap.search(None, "ALL")
    messages = [email.message_from_bytes(imap.fetch(n, "(RFC822)")[1][0][1], policy=email.policy.default)
                for n in data[0].split()]
    imap.logout()
    return messages


def blank_recipe(**over):
    recipe = {"title": "", "cooks": [], "courses": [], "kashrut": "pareve", "shabbat": False, "holiday": False,
              "pesach": False, "gluten_free": False, "summary": "", "intro": [], "notes": [], "tools": [],
              "ingredients": [], "directions": [], "facts": [], "adapted_from": ""}
    recipe.update(over)
    return recipe


def answer(intent, **over):
    base = {"intent": intent, "recipe_slug": "", "request_ids": [], "reply_message": "", "uncertain": [],
            "comment": {"made_it": False, "verdict": "none", "text": "", "changes": ""},
            "request": {"title": "", "details": ""}, "recipe": blank_recipe(), "attachments": []}
    base.update(over)
    return base


def validate(instance, schema):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance, schema)


# ---------------------------------------------------------------- the test

def test_family_emails_end_to_end(greenmail, site):
    request_mid = "<request-1@family.test>"
    request_id = "q-" + store.digest(request_mid)[:8]
    lemon = blank_recipe(
        title="Orlee's Lemon Chicken", cooks=["Orlee"], courses=["mains"], kashrut="meat", shabbat=True,
        summary="Bright, garlicky chicken for Friday night.", notes=[{"text": "Orlee uses Meyer lemons when she can.", "heading": False}],
        ingredients=[{"text": "Chicken", "heading": True}, {"text": "8 chicken thighs", "heading": False},
                     {"text": "3 lemons", "heading": False}, {"text": "Sauce:", "heading": True},
                     {"text": "1/4 cup honey (?)", "heading": False}],
        directions=[{"text": "Preheat the oven to 400°F.", "heading": False},
                    {"text": "Roast 45 minutes, basting once.", "heading": False}],
        facts=["Serves 6"])
    answers = {
        "Request: Savta's chocolate mandelbroit": {"classify": answer(
            "request", reply_message="I'll ask around!",
            request={"title": "Savta's chocolate mandelbroit", "details": "The one with the chips"})},
        "New recipe: Orlee's Lemon Chicken": {"classify": answer(
            "new_recipe", reply_message="Thanks Orlee, this looks delicious!", uncertain=["the honey amount"],
            request_ids=[request_id], recipe=lemon,
            attachments=[{"number": 1, "use": "recipe_page", "caption": "Orlee's card"},
                         {"number": 2, "use": "dish_photo", "caption": "Fresh out of the oven"}])},
        "Made the couscous!": {"classify": answer(
            "comment", recipe_slug="ema-s-couscous", reply_message="Looks amazing!",
            comment={"made_it": True, "verdict": "changes", "text": "Came out great.", "changes": "Half the salt."},
            attachments=[{"number": 1, "use": "dish_photo", "caption": ""}])},
        "Spam!": {"classify": answer("unclear")},
        "Blurry card": ModelError("Claude API error 529; will retry next run"),
        "Re: New recipe: Orlee's Lemon Chicken": {
            "classify": answer("fix", reply_message=""),
            "rewrite": {"recipe": {**lemon, "ingredients": [{"text": "8 chicken thighs", "heading": False},
                                                            {"text": "2 lemons", "heading": False}]},
                        "change_summary": "Changed 3 lemons to 2 lemons.", "reply_message": "Fixed!", "attachments": []}},
    }
    for value in answers.values():
        if isinstance(value, dict):
            validate(value["classify"], CLASSIFY_SCHEMA)
            if "rewrite" in value:
                validate(value["rewrite"], FIX_SCHEMA)
    reader = ScriptedReader(answers)

    logo = Image.new("RGB", (40, 40), (200, 0, 0))
    logo_bytes = io.BytesIO()
    logo.save(logo_bytes, "PNG")

    send(DANA, "Request: Savta's chocolate mandelbroit", "Does anyone have it?", message_id=request_mid)
    send(ORLEE, "New recipe: Orlee's Lemon Chicken", "Here's my card and how it came out.\n\nSent from my iPhone",
         attachments=[("card.jpg", "image/jpeg", jpeg((240, 230, 200))), ("dish.heic", "image/heic", heic((200, 120, 40))),
                      ("logo.png", "image/png", logo_bytes.getvalue())])
    send(DANA, "Made the couscous!", html="<p>Made <b>Ema's couscous</b> tonight, came out great. Used half the salt.</p>"
         "<div class='gmail_quote'>On Mon someone wrote: old stuff</div>",
         attachments=[("couscous.png", "image/png", jpeg((100, 160, 90)))])
    send(STRANGER, "Spam!", "Buy now")
    send(ORLEE, "Blurry card", "Can you read this?", attachments=[("blurry.jpg", "image/jpeg", jpeg((10, 10, 10)))])

    # ---- run 1
    report = bot_run.run(SETTINGS, reader, ssl_context=INSECURE, push=False)
    assert report.committed
    assert [c for c in reader.calls if c[0] == "classify"][-1][1] == "Blurry card"
    assert ("classify", "Spam!", None) not in reader.calls, "strangers must never reach the model"

    data = json.loads(store.RECIPES.read_text())
    community = json.loads(store.COMMUNITY.read_text())
    added = data["recipes"][-1]
    assert added["title"] == "Orlee's Lemon Chicken" and added["slug"] == "orlee-s-lemon-chicken"
    assert added["number"] == 189 and data["total"] == 189 and added["added_by"] == "Orlee"
    assert added["complete"] and not added["in_progress"] and added["shabbat"]
    ing = next(s for s in added["sections"] if s["kind"] == "ingredients")["items"]
    assert ing[0] == {"text": "Chicken", "sub": True} and ing[3] == {"text": "Sauce", "sub": True}
    assert [p.get("caption") for p in added["photos"]] == ["Fresh out of the oven", "Orlee's card"], "dish photo leads"
    for photo in added["photos"]:
        assert (site / "site" / photo["src"]).exists() and (site / "site" / photo["thumb"]).exists()
    assert community["requests"][0]["id"] == request_id
    assert community["requests"][0]["status"] == "found" and community["requests"][0]["recipe"] == "orlee-s-lemon-chicken"
    comment = community["comments"][0]
    assert comment["recipe"] == "ema-s-couscous" and comment["name"] == "Dana" and comment["verdict"] == "changes"
    assert len(comment["photos"]) == 1

    log = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=site, capture_output=True, text=True).stdout
    assert "Add recipe “Orlee's Lemon Chicken” from Orlee" in log and "Dana on “Ema's Couscous”" in log
    assert "@" not in log, "commit messages must not contain email addresses"

    inbox = mailbox(BOT)
    assert [m["Subject"] for m in inbox] == ["Blurry card"], "failed email stays in the inbox for a retry"
    assert {m["Subject"] for m in mailbox(BOT, PROCESSED_FOLDER)} == {
        "Request: Savta's chocolate mandelbroit", "New recipe: Orlee's Lemon Chicken", "Made the couscous!"}
    assert [m["Subject"] for m in mailbox(BOT, IGNORED_FOLDER)] == ["Spam!"]

    orlee_mail = mailbox(ORLEE)
    assert len(orlee_mail) == 1
    confirmation = orlee_mail[0]
    body = confirmation.get_content()
    assert confirmation["Subject"] == "Re: New recipe: Orlee's Lemon Chicken"
    assert "https://recipes.example/?recipe=orlee-s-lemon-chicken" in body
    assert "3 ingredients and 2 steps" in body and "the honey amount" in body and "saved 2 photos" in body
    dana_mail = sorted(m["Subject"] for m in mailbox(DANA))
    assert dana_mail == ["Re: Made the couscous!", "Re: New recipe: Orlee's Lemon Chicken",
                         "Re: Request: Savta's chocolate mandelbroit"], "Dana gets her replies plus the admin copy"

    # ---- run 2: Orlee replies to the confirmation with a correction; the model doesn't name the recipe,
    # so the bot must find it from the email thread.
    send(ORLEE, "Re: New recipe: Orlee's Lemon Chicken", "Oops, it's 2 lemons not 3.\n\n> quoted confirmation",
         in_reply_to=confirmation["Message-ID"])
    bot_run.run(SETTINGS, reader, ssl_context=INSECURE, push=False)
    assert ("classify", "Re: New recipe: Orlee's Lemon Chicken", "orlee-s-lemon-chicken") in reader.calls
    fixed = json.loads(store.RECIPES.read_text())["recipes"][-1]
    assert [i["text"] for i in fixed["sections"][-2]["items"]] == ["8 chicken thighs", "2 lemons"]
    assert len(fixed["photos"]) == 2, "fix keeps existing photos"
    assert any("Changed 3 lemons to 2 lemons." in m.get_content() for m in mailbox(ORLEE))

    # ---- run 3: the email that keeps failing gets an apology and is filed for a person
    bot_run.run(SETTINGS, reader, ssl_context=INSECURE, push=False)
    assert mailbox(BOT) == []
    apology = [m for m in mailbox(ORLEE) if m["Subject"] == "Re: Blurry card"]
    assert len(apology) == 1 and "a person will take a look" in apology[0].get_content()
    state = json.loads(store.STATE.read_text())
    assert state["failures"] == {} and len(state["processed"]) == 5

    # ---- run 4: nothing new, nothing happens
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=site, capture_output=True, text=True).stdout
    report = bot_run.run(SETTINGS, reader, ssl_context=INSECURE, push=False)
    assert not report.outcomes
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=site, capture_output=True, text=True).stdout == before
