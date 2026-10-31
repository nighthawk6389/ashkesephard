"""Recipe email bot: read new family emails, update the site's data, publish, and reply.

Run by .github/workflows/email-bot.yml every 15 minutes:
  python -m bot.run            process the inbox
  python -m bot.run --check    verify the mailbox, SMTP and Claude settings without changing anything

The Actions log of a public repository is public, so this script never prints email addresses or
email content, only counts and outcomes.
"""
import argparse
import subprocess
import sys
from dataclasses import dataclass, field

from .ai import ClaudeReader, ModelError
from .config import ROOT, Settings
from .mail import IGNORED_FOLDER, PROCESSED_FOLDER, Mailbox, build_reply, parse_message, send_all
from .store import SiteData, save_photo

MAX_FAILURES = 3


@dataclass
class Outcome:
    folder: str | None = None          # where to file the email; None leaves it in the inbox to retry
    reply: object = None
    summary: str = ""                  # one line for the commit message and the log
    log: str = ""


@dataclass
class RunReport:
    outcomes: list = field(default_factory=list)
    committed: bool = False


def photos_from(incoming, attachments, uses):
    """Save the attachments the model marked with one of `uses`, dish photos first."""
    chosen = sorted((a for a in attachments if a["use"] in uses), key=lambda a: (a["use"] != "dish_photo", a["number"]))
    photos = []
    for a in chosen:
        index = a["number"] - 1
        if 0 <= index < len(incoming.images):
            try:
                photos.append(save_photo(incoming.images[index].data, a.get("caption", "").strip()))
            except Exception:
                continue  # an image the model could see but Pillow can't decode is skipped, not fatal
    return photos


def link_lines(settings, slug):
    return f"\n\nSee it on the site: {settings.recipe_url(slug)}"


def reply_body(*parts):
    return "\n".join(p for p in parts if p is not None).strip() + "\n\n— The AshkeSephard recipe bot\n"


def process(settings, data, reader, incoming, number):
    if data.seen(incoming.message_id):
        return Outcome(folder=PROCESSED_FOLDER, log=f"email {number}: already handled, filing it")
    name = settings.family.get(incoming.sender)
    if not name:
        return Outcome(folder=IGNORED_FOLDER, log=f"email {number}: sender is not on the family list, ignored")
    thread_slug = data.thread_slug(incoming)

    try:
        result = reader.classify(incoming, name, thread_slug, data.recipes, data.community["requests"])
        intent = result["intent"]
        slug = result.get("recipe_slug") or thread_slug
        if intent in ("comment", "fix") and not data.recipe(slug or ""):
            intent = "unclear"
            result["reply_message"] = result.get("reply_message") or "Which recipe is this about? Reply with its name or the link from the site."

        if intent == "new_recipe":
            photos = photos_from(incoming, result["attachments"], {"dish_photo", "recipe_page"})
            recipe = data.add_recipe(result["recipe"], name, incoming.date, photos, result.get("request_ids") or [])
            counts = {s["kind"]: sum(1 for i in s["items"] if not i.get("sub")) for s in recipe["sections"]}
            read = f"I read {counts.get('ingredients', 0)} ingredients and {counts.get('directions', 0)} steps"
            unsure = result.get("uncertain") or []
            body = reply_body(
                result["reply_message"],
                f"\n“{recipe['title']}” is now on the site. {read}" + (f" and saved {len(photos)} photo{'s' if len(photos) != 1 else ''}." if photos else "."),
                ("\nI wasn't sure about:\n" + "\n".join(f"  • {u}" for u in unsure)) if unsure else None,
                "\nIf anything is wrong, just reply to this email with the correction.",
                link_lines(settings, recipe["slug"]))
            cc = [settings.admin_email] if settings.admin_email and settings.admin_email != incoming.sender else None
            reply = build_reply(settings, incoming, body, cc)
            data.remember_thread(reply["Message-ID"], recipe["slug"])
            data.mark_processed(incoming.message_id, "new_recipe", recipe["slug"])
            return Outcome(PROCESSED_FOLDER, reply, f"Add recipe “{recipe['title']}” from {name}", f"email {number}: new recipe added")

        if intent == "comment":
            recipe = data.recipe(slug)
            photos = photos_from(incoming, result["attachments"], {"dish_photo"})
            data.add_comment(slug, name, incoming.date, result["comment"], photos, incoming.message_id)
            body = reply_body(result["reply_message"], f"\nYour note is on “{recipe['title']}”"
                              + (f" with {len(photos)} photo{'s' if len(photos) != 1 else ''}." if photos else "."),
                              link_lines(settings, slug))
            data.mark_processed(incoming.message_id, "comment", slug)
            return Outcome(PROCESSED_FOLDER, build_reply(settings, incoming, body),
                           f"{name} on “{recipe['title']}”", f"email {number}: comment added")

        if intent == "request":
            request = data.add_request(name, incoming.date, result["request"], incoming.message_id)
            body = reply_body(result["reply_message"], f"\n“{request['title']}” is on the requested recipes list.",
                              f"\n\nSee the list: {settings.site_url}/#requests")
            data.mark_processed(incoming.message_id, "request")
            return Outcome(PROCESSED_FOLDER, build_reply(settings, incoming, body),
                           f"Request “{request['title']}” from {name}", f"email {number}: request added")

        if intent == "fix":
            recipe = data.recipe(slug)
            fix = reader.rewrite(incoming, name, data.for_model(recipe))
            photos = photos_from(incoming, fix["attachments"], {"dish_photo"})
            data.update_recipe(recipe, fix["recipe"], photos, incoming.date)
            body = reply_body(fix["reply_message"], f"\nWhat I changed: {fix['change_summary']}",
                              "\nReply again if it still isn't right.", link_lines(settings, slug))
            reply = build_reply(settings, incoming, body)
            data.remember_thread(reply["Message-ID"], slug)
            data.mark_processed(incoming.message_id, "fix", slug)
            return Outcome(PROCESSED_FOLDER, reply, f"Fix “{recipe['title']}” from {name}", f"email {number}: recipe corrected")

        body = reply_body(result.get("reply_message") or "I wasn't sure what to do with this email. Could you say a bit more?")
        reply = build_reply(settings, incoming, body)
        if thread_slug:
            data.remember_thread(reply["Message-ID"], thread_slug)
        data.mark_processed(incoming.message_id, "unclear")
        return Outcome(PROCESSED_FOLDER, reply, "", f"email {number}: unclear, asked a question")

    except ModelError as exc:
        failures = data.record_failure(incoming.message_id)
        if failures < MAX_FAILURES:
            return Outcome(None, None, "", f"email {number}: {exc} (attempt {failures}, will retry)")
        body = reply_body("Sorry, I couldn't read this email after a few tries, so a person will take a look.")
        cc = [settings.admin_email] if settings.admin_email and settings.admin_email != incoming.sender else None
        data.mark_processed(incoming.message_id, "failed")
        return Outcome(PROCESSED_FOLDER, build_reply(settings, incoming, body, cc), "",
                       f"email {number}: gave up after {failures} attempts: {exc}")


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check, capture_output=True, text=True)


def commit_and_push(message, push=True):
    git("add", "site/data", "site/photos/family", "data/bot_state.json")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    git("commit", "-m", message)
    if not push:
        return True
    for attempt in range(4):
        if git("push", "origin", "HEAD:main", check=False).returncode == 0:
            return True
        git("pull", "--rebase", "origin", "main", check=False)  # someone else pushed meanwhile
    raise RuntimeError("Could not push the bot's changes; nothing was replied to, the emails will be retried")


def run(settings, reader, ssl_context=None, push=True, send=True):
    report = RunReport()
    data = SiteData()
    with Mailbox(settings, ssl_context) as box:
        pending = []
        for number, (uid, raw) in enumerate(box.fetch(settings.max_per_run), 1):
            incoming = parse_message(uid, raw)
            outcome = process(settings, data, reader, incoming, number)
            print(outcome.log)
            report.outcomes.append(outcome)
            pending.append((uid, outcome))
        if not pending:
            print("Inbox is empty")
            return report

        data.save()
        lines = [o.summary for o in report.outcomes if o.summary]
        title = lines[0] if len(lines) == 1 else f"Recipe bot: {len(lines)} updates from family emails" if lines else "Recipe bot: bookkeeping"
        report.committed = commit_and_push(title + ("\n\n" + "\n".join(f"- {l}" for l in lines) if len(lines) > 1 else ""), push)

        # Only now that the site update is pushed do we tell people it's live and file their emails.
        if send:
            send_all(settings, [o.reply for o in report.outcomes if o.reply], ssl_context)
        for uid, outcome in pending:
            if outcome.folder:
                box.move(uid, outcome.folder)
    return report


def check(settings, ssl_context=None):
    """Connectivity check for the workflow's "self test" button. Changes nothing."""
    import smtplib
    import ssl as ssl_lib

    import anthropic

    ok = True
    missing = settings.missing()
    print("Settings:", "all present" if not missing else "MISSING " + ", ".join(missing))
    if missing:
        print("Add the missing secrets/variables (see README: Setting up the recipe bot), then run the self test again.")
        return False
    print(f"Family list: {len(settings.family)} address(es)")
    try:
        with Mailbox(settings, ssl_context) as box:
            print(f"Mailbox: logged in, {box.count()} email(s) waiting in the inbox")
    except Exception as exc:
        ok = False
        print(f"Mailbox: FAILED ({type(exc).__name__}: {exc})")
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                              context=ssl_context or ssl_lib.create_default_context()) as smtp:
            smtp.login(settings.bot_address, settings.app_password)
        print("Sending mail: logged in")
    except Exception as exc:
        ok = False
        print(f"Sending mail: FAILED ({type(exc).__name__}: {exc})")
    # A real (tiny) reading with the same schema and settings as live emails, so a green check means
    # the whole pipeline works, not just the API key.
    from datetime import datetime, timezone

    from .mail import IncomingEmail
    sample = IncomingEmail(uid="0", message_id="<self-test@local>", sender="test@example.com", sender_display="Test",
                           subject="New recipe: Self-test toast", date=datetime.now(timezone.utc),
                           text="Self-test toast. 2 slices bread, butter. Toast the bread, then butter it.", quoted="")
    try:
        result = ClaudeReader(settings.model).classify(sample, "Test", None, [], [])
        good = result["intent"] == "new_recipe" and result["recipe"]["ingredients"]
        print(f"Claude ({settings.model}): {'read the sample recipe correctly' if good else 'answered, but misread the sample: ' + result['intent']}")
        ok &= bool(good)
    except (ModelError, anthropic.APIError) as exc:
        ok = False
        print(f"Claude ({settings.model}): FAILED ({type(exc).__name__}: {exc})")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="test the mailbox, SMTP and Claude settings")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.check:
        sys.exit(0 if check(settings) else 1)
    missing = settings.missing()
    if missing:
        print("The recipe bot is not set up yet; missing secrets: " + ", ".join(missing))
        sys.exit(0)  # not an error until the family sets it up; the scheduled run stays green
    run(settings, ClaudeReader(settings.model))


if __name__ == "__main__":
    main()
