#!/usr/bin/env python3
"""Import every public post from the AshkeSephard Blogger site into site/data/recipes.json.

The Blogger posts are free-form, so this script converts each post into a structured
recipe (ingredients, directions, notes, tools and photos) without inventing anything:
every line of the original post lands in some section, and each recipe links back to
its source post. Manual corrections live in data/overrides.json.

Photos are downloaded into site/photos/ (a full-size and a thumbnail WebP per photo), so the
site does not depend on Blogger's image servers. Already-downloaded photos are reused.

Usage:
  python3 scripts/import_blogger.py              # fetch the live feed
  python3 scripts/import_blogger.py --feed-dir D # reuse saved feed pages (D/*.json)
"""
import argparse
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image, ImageOps

BLOG = "https://ashkesephardfamilyrecipes.blogspot.com"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "recipes.json"
PHOTO_DIR = ROOT / "site" / "photos"
FULL_SIZE, THUMB_SIZE = 1400, 640
OVERRIDES = ROOT / "data" / "overrides.json"
PAGE_SIZE = 150

# ---------------------------------------------------------------- fetching

def fetch_feed():
    entries, seen = [], set()
    for page in range(40):
        url = f"{BLOG}/feeds/posts/default?alt=json&max-results={PAGE_SIZE}&start-index={page * PAGE_SIZE + 1}"
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AshkeSephardRecipeImporter/2.0"})
                with urllib.request.urlopen(req, timeout=40) as resp:
                    payload = json.load(resp)
                break
            except Exception as exc:  # network hiccups: retry with backoff
                if attempt == 3:
                    raise RuntimeError(f"Cannot fetch feed page {page + 1}: {exc}") from exc
                time.sleep(2 ** (attempt + 1))
        batch = payload.get("feed", {}).get("entry", [])
        for entry in batch:
            ident = entry.get("id", {}).get("$t")
            if ident and ident not in seen:
                seen.add(ident)
                entries.append(entry)
        print(f"Feed page {page + 1}: {len(batch)} posts (total {len(entries)})")
        if len(batch) < PAGE_SIZE:
            return entries
    raise RuntimeError("Feed had more pages than expected; refusing to write a partial archive")


def load_feed_dir(path):
    entries, seen = [], set()
    for file in sorted(Path(path).glob("*.json")):
        for entry in json.loads(file.read_text()).get("feed", {}).get("entry", []):
            ident = entry["id"]["$t"]
            if ident not in seen:
                seen.add(ident)
                entries.append(entry)
    return entries

# ---------------------------------------------------------------- html -> lines

BLOCK = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "tbody",
         "thead", "blockquote", "center", "figure", "figcaption", "section", "article", "pre", "hr"}
DROP = {"script", "style", "iframe", "object", "embed", "form", "button", "input", "video",
        "audio", "noscript", "svg", "select", "textarea"}
EMAIL_JUNK = {"reply", "forward", "add reaction", "reply all", "show quoted text"}


class Stream:
    """Flattens HTML into ordered text lines and images."""

    def __init__(self):
        self.items, self.buf, self.flags = [], [], set()

    def text(self, value, flags):
        self.buf.append(value)
        self.flags |= flags

    def flush(self):
        line = clean_text("".join(self.buf))
        glued = re.match(r"^(.+[.)])\s*(Directions|Instructions|Ingredients)\s*:?$", line)
        for part in ([glued.group(1), glued.group(2)] if glued else [line]):
            if part:
                self.items.append({"type": "line", "text": part, **{f: True for f in self.flags}})
        self.buf, self.flags = [], set()

    def image(self, src):
        self.flush()
        self.items.append({"type": "image", "src": src})


def clean_text(value):
    value = unicodedata.normalize("NFC", value).replace("\u200b", "").replace("\ufeff", "").replace("\u2044", "/")
    return re.sub(r"\s+", " ", value).strip()


def is_centered(tag):
    for node in [tag, *tag.parents]:
        if isinstance(node, Tag):
            style = (node.get("style") or "").replace(" ", "").lower()
            if "text-align:center" in style or node.name == "center":
                return True
    return False


def walk(node, stream, flags=frozenset()):
    for child in node.children:
        if isinstance(child, NavigableString):
            if child.__class__.__name__ in ("Comment", "Doctype", "CData", "ProcessingInstruction"):
                continue
            stream.text(str(child), flags | ({"centered"} if is_centered(child.parent) else set()))
            continue
        if not isinstance(child, Tag) or child.name in DROP:
            continue
        name = child.name
        if name == "br":
            stream.flush()
        elif name == "img":
            src = image_url(child.get("src") or child.get("data-src") or "")
            if src:
                stream.image(src)
        elif name == "td" and "tr-caption" in (child.get("class") or []):
            stream.flush()
            walk(child, stream, flags | {"caption"})
            stream.flush()
        elif name in BLOCK:
            stream.flush()
            extra = set()
            if name == "li":
                extra.add("li")
            if name in ("h1", "h2", "h3", "h4", "h5", "h6") or (name in ("b", "strong")):
                extra.add("heading")
            walk(child, stream, flags | extra)
            stream.flush()
        else:
            if name in ("td", "th"):
                stream.text(" ", set())
            walk(child, stream, flags | ({"bold"} if name in ("b", "strong") else set()))


def image_url(src):
    src = src.strip()
    if src.startswith("//"):
        src = "https:" + src
    if "blogger.googleusercontent.com/img/" in src or "bp.blogspot.com" in src:
        return src
    if src.startswith("https://s3.amazonaws.com/"):
        return src
    return None  # avatars, tracking pixels, data: URIs, email icons


def sized(src, size):
    """Blogger image URLs encode their size; ask for the size we want."""
    if "googleusercontent.com/img/a/" in src:
        return re.sub(r"=[swh]\d+[^/]*$", "", src) + f"=s{size}"
    if "googleusercontent.com/img/b/" in src or "bp.blogspot.com" in src:
        m = re.match(r"(.*?/img/b/[^/]+/[^/]+/)(?:([swh]\d+[^/]*)/)?(.*)$", src)
        if m:
            return f"{m.group(1)}s{size}/{m.group(3)}"
    return src

# ---------------------------------------------------------------- sectioning

HEADINGS = [
    ("ingredients", r"ingredients?(?: list)?|what you(?:'|’)?ll need|you will need"),
    ("directions", r"directions?|instructions?|method|preparation|steps|how to make it"),
    ("notes", r"notes?|tips?|serving suggestions?|variations?"),
    ("tools", r"(?:cooking |kitchen )?(?:tools|utensils|equipment|vessels?)|cooking vessels?"),
]
HEADING_RE = [(kind, re.compile(rf"^(?:{pat})\s*[:.\-–]?\s*$", re.I)) for kind, pat in HEADINGS]
HEADING_PREFIX_RE = [(kind, re.compile(rf"^(?:{pat})\s*[:\-–]\s*(.+)$", re.I)) for kind, pat in HEADINGS]
# Named headings such as "Meat Patty Ingredients", "Ingredients for Dough", "Directions for burekas",
# "Note from Savta". The name becomes a sub-heading inside the section.
NAMED_RE = [
    ("ingredients", re.compile(r"^(?P<pre>[\w'’/&,\- ]{1,30}?\s)?ingredients?(?:\s+(?:for|of)(?: the)?\s+(?P<post>[\w'’/&\- ]{1,30}))?(?P<paren>\s*\(.*\))?\s*:?$", re.I)),
    ("directions", re.compile(r"^(?P<pre>[\w'’/&\- ]{1,25}?\s)?(?:directions?|instructions?)(?:\s+for(?: the)?\s+(?P<post>[\w'’/&\- ]{1,40}))?(?P<paren>\s*\(.*\))?\s*:?$", re.I)),
    ("notes", re.compile(r"^(?P<pre>[\w'’ ]{1,18}?\s)?notes?(?:\s+from\s+(?P<post>[\w'’ ]{1,20}))?\s*:?$", re.I)),
]
GLUED_NOTES_RE = re.compile(r"^(Notes)(?=[A-Z][a-z])(.+)$")
FACT_RE = re.compile(r"^(?:serves|servings|yield|yields|makes|prep(?:aration)? time|cook(?:ing)? time|total time|serving size|bake time)\b\s*:?\s*(.*)$", re.I)
STEP_NUM_RE = re.compile(r"^(?:step\s*)?(\d{1,2})\s*[.)]\s*(?=\S)", re.I)
BULLET_RE = re.compile(r"^(?:[•▢▪◦●○■□✓✔·]|-(?=\s)|–(?=\s)|\*(?=\s)|-(?=[A-Za-z0-9½¼¾⅓⅔]))\s*")
SOURCE_RE = re.compile(r"^(?:original\s+)?(?:recipe|adapted|inspired)?\s*(?:from|by|source|via)?\s*:?\s*(https?://\S+)\s*$", re.I)
QTY_RE = re.compile(r"^(?:\d|[½¼¾⅓⅔⅛]|a |an |one |two |three |four |five |six |eight |ten |twelve |half |a few |a couple |about |approx|1/|pinch|dash|handful|juice|zest|\d+\s*(?:x|-))", re.I)
VERB_RE = re.compile(r"^(?:preheat|heat|mix|combine|bake|place|put|add|in a|in the|cook|boil|bring|stir|pour|whisk|beat|cut|slice|chop|spread|roast|fry|saute|sauté|melt|remove|serve|let|cover|grease|line|transfer|blend|season|sprinkle|top|fold|wash|peel|drain|soak|rinse|form|roll|shape|simmer|refrigerate|chill|marinate|take|using|when|once|after|while|then|repeat|set|turn|lower|flip|spray|brush|dip|coat|fill|arrange|layer|scoop|drop|start|first|make)\b", re.I)


def classify_heading(text):
    """Return (kind, sub_heading, inline_text) when the line is a section heading."""
    for kind, rx in HEADING_RE:
        if rx.match(text):
            return kind, None, None
    lead = re.split(r"ingredient|direction|instruction|note", text.lower())[0]
    if len(text) <= 60 and not QTY_RE.match(text) and not VERB_RE.match(text) and \
            not re.search(r"\b(?:to|all|with|together|bowl|spoon|as in|see)\b", lead):
        for kind, rx in NAMED_RE:
            m = rx.match(text)
            if m:
                if kind != "ingredients" and m.group("pre"):
                    name = text.rstrip(": ")  # "Overnight instructions", "Note from Savta"
                else:
                    name = " ".join(x.strip() for x in (m.group("pre"), m.group("post"), m.groupdict().get("paren")) if x and x.strip())
                if kind == "notes" and m.group("post") and not m.group("pre"):
                    name = text.rstrip(": ")
                return kind, (name[:1].upper() + name[1:]) if name else None, None
    if len(text) < 200:
        for kind, rx in HEADING_PREFIX_RE:
            m = rx.match(text)
            if m and not text.lower().startswith(("method of", "directions to")):
                return kind, None, m.group(1).strip()
    m = GLUED_NOTES_RE.match(text)
    if m:
        return "notes", None, m.group(2).strip()
    return None, None, None


def strip_bullet(text):
    return BULLET_RE.sub("", text, count=1).strip()


def is_subhead(text):
    t = text.strip()
    return 2 < len(t) <= 48 and t.endswith(":") and not QTY_RE.match(t) and "http" not in t


def looks_like_step(text):
    return bool(STEP_NUM_RE.match(text)) or (len(text) > 85 and bool(VERB_RE.match(text))) or (
        len(text) > 140 and text.count(". ") >= 1)


def looks_like_ingredient(text):
    if VERB_RE.match(text) or re.match(r"^(?:boil|baked?|smash)", text, re.I):
        return False
    return len(text) <= 90 and not text.endswith((".", "!")) or bool(QTY_RE.match(text)) and len(text) <= 110


def is_junk(text, title):
    low = text.lower().strip(" .:-–")
    if not low or low in EMAIL_JUNK or re.fullmatch(r"[.\-–•*_~=]+", text.strip()):
        return True
    if low == clean_title(title)[0].lower().strip(" .:-–"):
        return True
    return False


def parse_post(html, title):
    soup = BeautifulSoup(html, "html.parser")
    stream = Stream()
    walk(soup, stream)
    stream.flush()
    items = stream.items

    # Attach captions to photos: Blogger caption cells, or a centered line touching an image.
    photos, lines = [], []
    for i, item in enumerate(items):
        if item["type"] == "image":
            if any(p["src"] == item["src"] for p in photos):
                continue
            photo = {"src": item["src"], "caption": None}
            nxt = items[i + 1] if i + 1 < len(items) else None
            prv = items[i - 1] if i else None
            if nxt and nxt["type"] == "line" and nxt.get("caption"):
                photo["caption"], nxt["used"] = nxt["text"], True
            elif prv and prv["type"] == "line" and prv.get("centered") and len(prv["text"]) < 160 \
                    and not prv.get("used") and not classify_heading(prv["text"])[0]:
                photo["caption"], prv["used"] = prv["text"], True
            photos.append(photo)
    for item in items:
        if item["type"] == "line" and not item.get("used"):
            lines.append(item)

    sections = []          # [{kind, title?, items:[{text, sub?}]}]
    current = None
    source = None
    saw_heading = False
    implicit_steps = False
    facts = []

    def open_section(kind):
        nonlocal current
        for sec in sections:  # merge repeated headings (e.g. two "Directions" blocks)
            if sec["kind"] == kind and sec is sections[-1]:
                current = sec
                return sec
        current = {"kind": kind, "items": []}
        sections.append(current)
        return current

    for item in lines:
        text = item["text"]
        if is_junk(text, title):
            continue
        m = SOURCE_RE.match(text)
        if m and not source:
            source = m.group(1).rstrip(").,")
            continue
        fact = FACT_RE.match(strip_bullet(text))
        if fact and len(text) <= 60 and fact.group(1):
            facts.append(strip_bullet(text).rstrip("."))
            continue
        kind, sub, rest = classify_heading(strip_bullet(text))
        if kind:
            saw_heading = True
            implicit_steps = False
            open_section(kind)
            if sub:
                current["items"].append({"text": sub, "sub": True})
            if rest:
                if kind == "tools" or not FACT_RE.match(rest):
                    current["items"].append({"text": strip_bullet(rest)})
                else:
                    facts.append(rest)
            continue
        if current is None:
            open_section("intro")
        body = strip_bullet(text)
        if not body or is_junk(body, title):
            continue
        if is_subhead(body):
            if implicit_steps:  # e.g. "Sauce:" after a block of steps -> back to ingredients
                implicit_steps = False
                open_section("ingredients")
            current["items"].append({"text": body.rstrip(":").strip(), "sub": True})
            continue
        if current["kind"] == "ingredients" and not item.get("li") and looks_like_step(body) and \
                len(current["items"]) >= 2:
            implicit_steps = True
            open_section("directions")
        current["items"].append({"text": body, "li": bool(item.get("li"))})

    # Posts without headings: split a leading run of ingredient-like lines from the method.
    if not saw_heading and sections and sections[0]["kind"] == "intro":
        rows = sections[0]["items"]
        cut = 0
        for row in rows:
            if row.get("sub") or looks_like_ingredient(row["text"]):
                cut += 1
            else:
                break
        if cut >= 3:
            ing = {"kind": "ingredients", "items": rows[:cut]}
            rest = rows[cut:]
            sections = [ing] + ([{"kind": "directions", "items": rest}] if rest else [])
        elif sections[0]["items"] and all(looks_like_step(r["text"]) or len(r["text"]) > 60 for r in rows):
            sections[0]["kind"] = "method"

    return finalize(sections), photos, source, facts


def finalize(sections):
    out = []
    for sec in sections:
        rows = [r for r in sec["items"] if r["text"] and r["text"] not in ("-", ".")]
        if sec["kind"] == "directions":
            rows = merge_steps(rows)
        for r in rows:
            r.pop("li", None)
        if rows:
            same = next((o for o in out if o["kind"] == sec["kind"]), None)
            if same:
                same["items"].extend(rows)
            else:
                out.append({"kind": sec["kind"], "items": rows})
    for sec in out:  # drop a sub-heading left with nothing under it
        sec["items"] = [r for i, r in enumerate(sec["items"])
                        if not r.get("sub") or (i + 1 < len(sec["items"]) and not sec["items"][i + 1].get("sub"))]
    return [sec for sec in out if sec["items"]]


def merge_steps(rows):
    numbered = sum(1 for r in rows if STEP_NUM_RE.match(r["text"]))
    merged = []
    for r in rows:
        text = r["text"]
        if numbered >= 2 and not r.get("sub"):
            m = STEP_NUM_RE.match(text)
            if m:
                merged.append({"text": text[m.end():].strip()})
                continue
            if merged and not merged[-1].get("sub"):
                # wrapped continuation of a numbered step (common when pasting from PDFs)
                merged[-1]["text"] = (merged[-1]["text"] + " " + text).strip()
                continue
        elif not r.get("sub"):
            m = STEP_NUM_RE.match(text)
            if m:
                text = text[m.end():].strip()
        merged.append({**r, "text": text})
    return merged

# ---------------------------------------------------------------- metadata

TITLE_TODO = [
    r"^\s*fix\s*(?:recipe)?\s*(?:\([^)]*\))?\s*[-=:–]+\s*",
    r"^\s*fix\s*-\s*",
    r"\s*[-–]\s*needs? editing(?: and pics)?\s*$",
    r"\s*[-–]\s*needs? exact measurements\s*$",
    r"\s*\((?:just photos|cant read picture of recipe|can't read picture of recipe)\)\s*",
    r"\s*[-–]\s*update\s*$",
]


def clean_title(raw):
    title = clean_text(raw)
    todo = False
    for pat in TITLE_TODO:
        new = re.sub(pat, " ", title, flags=re.I).strip()
        if new != title:
            todo = True
            title = new
    title = re.sub(r"\s+", " ", title).strip(" -–=")
    return title, todo


COOKS = {
    "Ema": "Ema", "Savta": "Savta", "Saba": "Saba", "Abba": "Abba", "Orlee": "Orlee",
    "Alex": "Alex", "TanTan": "TanTan", "Danish": "Danish", "Yatti": "Yatti",
    "Doda Pnena": "Doda Pnena", "Doda": "Doda Pnena", "Amanda": "Amanda", "Sue Zeitlin": "Sue Zeitlin",
}
TITLE_COOKS = {"Elior": "Elior", "Ema": "Ema", "Savta": "Savta", "Saba": "Saba", "Abba": "Abba", "Orlee": "Orlee",
               "Alex": "Alex", "TanTan": "TanTan", "Danish": "Danish", "Yatti": "Yatti", "Doda Pnena": "Doda Pnena"}
COURSE_LABELS = [  # label -> course key, in priority order for the "primary" course
    ("Entree", "mains"), ("Soup", "soups"), ("Salad", "salads"), ("Side", "sides"),
    ("Appetizer", "starters"), ("Breakfast", "breakfast"), ("Dessert", "desserts"),
    ("Snack", "snacks"), ("Dressing", "sauces"), ("Sauce", "sauces"), ("Dip", "sauces"),
    ("Guides", "guides"),
]
COURSE_NAMES = {"mains": "Main", "soups": "Soup", "salads": "Salad", "sides": "Side",
                "starters": "Starter", "breakfast": "Breakfast", "desserts": "Dessert",
                "snacks": "Snack", "sauces": "Sauce & dressing", "guides": "Kitchen guide"}
HOLIDAY_LABELS = {"Chagim", "Pesach", "Thanksgiving"}
HOLIDAY_WORDS = r"pesach|passover|purim|chanukah|hanukkah|rosh hashana|sukkot|shavuot|seder|charoset|marror|hamantaschen|hamatashen|thanksgiving"
MEAT_WORDS = r"\b(?:chicken|beef|meat|veal|lamb|brisket|turkey|duck|flanken|corn(?:ed)? beef|pastrami|kishke|kishka|schnitzel|meatballs?|franks|hot dogs?|steak|roast|ribs|tongue|sweetbreads|marrow bones)\b"
DAIRY_WORDS = r"\b(?:cheese|cheddar|mozzarella|parmesan|ricotta|milk|butter(?! beans)|sour cream|cream cheese|yogurt|lactaid|heavy cream|whipped cream)\b"
FISH_WORDS = r"\b(?:fish|salmon|cod|flounder|tuna|tilapia|whitefish|haddock|dagim)\b"


def kashrut(labels, text):
    s = set(labels)
    if s & {"Fleischig", "Meat", "Chicken"}:
        return "meat"
    if "Dairy" in s:
        return "dairy"
    if "Fish" in s:
        return "fish"
    if "Parve" in s:
        return "pareve"
    low = text.lower()
    if "Vegetarian" not in s and re.search(MEAT_WORDS, low) and not re.search(r'"(?:chicken|shrimp)"', low):
        return "meat"
    if re.search(DAIRY_WORDS, low):
        return "dairy"
    if re.search(FISH_WORDS, low):
        return "fish"
    return "pareve"


def courses_for(labels, title):
    keys = []
    for label, key in COURSE_LABELS:
        if label in labels and key not in keys:
            keys.append(key)
    low = title.lower()
    guesses = [(r"chicken|meat|roast|brisket|steak|fish|salmon|casserole|chili|veal|beef|lamb|duck|turkey", "mains"), (r"soup", "soups"),
               (r"salad|slaw", "salads"),
               (r"kugel|pashtida|potato|rice|stuffing|spinach|zucchini|broccoli|vegetable|charoset|marror|horseradish", "sides"),
               (r"noodle|pasta|spaghetti|ziti|macaroni|gnocchi", "mains"),
               (r"cake|cookie|\bpie\b|muffin|bars|tiramisu|pudding|doughnut|cream puff|mandelbroit|pears", "desserts"),
               (r"pancake|french toast|\beggs?\b|toast", "breakfast"), (r"dressing|sauce|rub|spice|mayonnaise", "sauces")]
    if not keys and "Pasta" in labels:
        keys.append("mains")
    if not keys:
        for pat, key in guesses:
            if re.search(pat, low):
                keys.append(key)
                break
    return keys or ["mains"]


def slugify(value):
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:80] or "recipe"


QTY_STRIP = re.compile(
    r"^(?:(?:about|approx|approximately|a few|a couple(?: of)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"twelve|half(?: a)?|several|some|to|or|x|plus)\b\.?|\d+(?:[./]\d+)?|[½¼¾⅓⅔⅛]|-|–|\+|\(.*?\))\s*",
    re.I)
UNIT_STRIP = re.compile(
    r"^(?:cups?|c\.|tablespoons?|tbsps?\.?|tbs\.?|t\.|teaspoons?|tsps?\.?|lbs?\.?|pounds?|oz\.?|ounces?|grams?|g\b|kg|"
    r"cans?|boxes|box|bags?|packages?|pkgs?\.?|cloves?|sticks?|containers?|jars?|bunch(?:es)?|large|medium|small|"
    r"heaping|level|squares?|cubes?|pinch(?:es)?|dash(?:es)?|handful|liters?|ml|quarts?|pints?|slices?|pieces?|"
    r"inch|whole|bottles?|sprigs?|heads?|T|tspns?|lg|sm|med)\b\.?\s*(?:of\s+)?", re.I)


def ingredient_name(text):
    t = re.sub(r"\(.*?\)", "", text)
    for _ in range(6):
        nt = QTY_STRIP.sub("", t, count=1)
        nt = UNIT_STRIP.sub("", nt, count=1)
        if nt == t:
            break
        t = nt
    t = re.split(r"[,;(]| - | – |\bor\b|\bfor\b|\bto taste\b", t)[0].strip(" .:*")
    if not t or len(t) > 28 or len(t.split()) > 4 or re.search(r"[?+/]|\band a half\b|\bdivided\b", t) or not re.search(r"[a-z]", t, re.I) or \
            t.lower().startswith(("optional", "salt", "pepper", "oil", "water", "cooking spray", "spray")):
        return None
    return t[0].lower() + t[1:] if not t[:2].isupper() else t


def summary_for(recipe):
    for sec in recipe["sections"]:
        if sec["kind"] in ("intro", "notes", "method"):
            for row in sec["items"]:
                t = row["text"]
                t = re.sub(r"^(?:note|notes|ema says|savta says)\s*[:\-–]\s*", "", t, flags=re.I)
                if row.get("sub") or "http" in t or len(t) < 25:
                    continue
                first = re.split(r"(?<=[.!?])\s", t)[0]
                if 30 <= len(first) <= 170 and first[0].isupper() and not first.endswith(("?", ":")) \
                        and not re.search(r"\d/\d{2,4}|\brecipes?\d", first):
                    return first
            break
    names = []
    for sec in recipe["sections"]:
        if sec["kind"] == "ingredients":
            for row in sec["items"]:
                if row.get("sub"):
                    continue
                n = ingredient_name(row["text"])
                if n and n.lower() not in (x.lower() for x in names):
                    names.append(n)
                if len(names) == 4:
                    break
    if len(names) >= 2:
        return "With " + ", ".join(names[:-1]) + " & " + names[-1] + "."
    cook = recipe["cooks"][0] if recipe["cooks"] else None
    course = COURSE_NAMES.get(recipe["courses"][0], "dish").lower()
    if recipe["photos"] and not any(s["kind"] in ("ingredients", "directions") for s in recipe["sections"]):
        return f"A {course} from {cook + '’s' if cook else 'the family'} kitchen, shared in photos."
    return f"A {course} from {cook + '’s' if cook else 'the family'} kitchen."


def build(entries, overrides):
    recipes = []
    for entry in entries:
        raw_title = entry.get("title", {}).get("$t", "")
        link = next((l["href"] for l in entry.get("link", []) if l.get("rel") == "alternate"), "")
        ov = overrides.get(link.rsplit("/", 1)[-1].removesuffix(".html"), {})
        if ov.get("skip"):
            continue
        title, todo = clean_title(ov.get("title") or raw_title)
        labels = sorted({c["term"].strip() for c in entry.get("category", []) if c.get("term")})
        html = entry.get("content", {}).get("$t") or entry.get("summary", {}).get("$t") or ""
        sections, photos, source, facts = parse_post(html, raw_title)
        if not title:
            title = ov.get("title") or "Untitled family recipe"
        text_all = " ".join([title] + [r["text"] for s in sections for r in s["items"]])
        cooks = []
        for lab in labels:
            name = COOKS.get(lab)
            if name and name not in cooks:
                cooks.append(name)
        for word, name in TITLE_COOKS.items():
            if re.search(rf"\b{word}\b", title) and name not in cooks:
                cooks.append(name)
        cooks = ov.get("cooks", cooks)
        # Lead with the cook named in the title ("Savta's ...") when there are several.
        named = [c for c in cooks if re.search(rf"\b{re.escape(c)}\b", title)]
        cooks = named + [c for c in cooks if c not in named]
        courses = ov.get("courses") or courses_for(labels, title)
        holiday = bool(set(labels) & HOLIDAY_LABELS) or bool(re.search(HOLIDAY_WORDS, title, re.I))
        has_ing = any(s["kind"] == "ingredients" for s in sections)
        has_dir = any(s["kind"] in ("directions", "method") for s in sections)
        recipe = {
            "title": title,
            "slug": None,
            "cooks": cooks,
            "kashrut": ov.get("kashrut") or kashrut(labels, text_all),
            "courses": courses,
            "shabbat": "Shabbat" in labels or bool(re.search(r"shabb?b?at|chulent|chollent|chamin", title, re.I)),
            "holiday": holiday,
            "pesach": "Pesach" in labels or bool(re.search(r"pesach|passover|seder|charoset|marror", title, re.I)),
            "gluten_free": "Gluten Free" in labels or bool(re.search(r"gluten[- ]free|\bGF\b", title, re.I)),
            "vegetarian": "Vegetarian" in labels,
            "complete": has_ing and has_dir,
            "in_progress": todo or ov.get("in_progress", False),
            "labels": labels,
            "sections": sections,
            "photos": [{"original": sized(p["src"], 1600), **({"caption": p["caption"]} if p["caption"] else {})} for p in photos],
            "facts": facts,
            "adapted_from": source,
            "source_url": link,
            "published": entry.get("published", {}).get("$t", "")[:10],
            "updated": entry.get("updated", {}).get("$t", "")[:10],
        }
        recipe["summary"] = ov.get("summary") or summary_for(recipe)
        recipes.append(recipe)

    recipes.sort(key=lambda r: (r["published"], r["source_url"]))
    used = set()
    for n, r in enumerate(recipes, 1):
        r["number"] = n
        base = slugify(r["title"])
        slug, i = base, 2
        while slug in used:
            slug, i = f"{base}-{i}", i + 1
        used.add(slug)
        r["slug"] = slug
    # stable key order: number first for readability
    return [{"number": r.pop("number"), **r} for r in recipes]


# ---------------------------------------------------------------- photos

def photo_key(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def download_photo(url):
    """Save a full-size and thumbnail WebP for one Blogger photo.

    Returns (width, height), "gone" when the image no longer exists, or None on other failures."""
    key = photo_key(url)
    full, thumb = PHOTO_DIR / f"{key}.webp", PHOTO_DIR / f"{key}-sm.webp"
    if full.exists() and thumb.exists():
        with Image.open(full) as im:
            return im.size
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AshkeSephardRecipeImporter/2.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
            break
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (404, 410):
                print(f"  ! photo no longer exists, skipping: {url}", file=sys.stderr)
                return "gone"
            if attempt == 3:
                print(f"  ! could not download {url[:90]}…: {exc}", file=sys.stderr)
                return None
            time.sleep(2 ** (attempt + 1))
    big = image.copy()
    big.thumbnail((FULL_SIZE, FULL_SIZE))
    big.save(full, "WEBP", quality=80, method=6)
    small = image.copy()
    small.thumbnail((THUMB_SIZE, THUMB_SIZE))
    small.save(thumb, "WEBP", quality=74, method=6)
    return big.size


def attach_photos(recipes):
    """Point every photo at its local copy; photos that fail to download keep the Blogger URL."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    urls = sorted({p["original"] for r in recipes for p in r["photos"]})
    with ThreadPoolExecutor(max_workers=8) as pool:
        sizes = dict(zip(urls, pool.map(download_photo, urls)))
    for r in recipes:
        r["photos"] = [p for p in r["photos"] if sizes.get(p["original"]) != "gone"]
        for p in r["photos"]:
            size, key = sizes.get(p["original"]), photo_key(p["original"])
            if size:
                p.update(src=f"photos/{key}.webp", thumb=f"photos/{key}-sm.webp", width=size[0], height=size[1])
            else:
                p.update(src=p["original"], thumb=sized(p["original"], THUMB_SIZE))
    stored = {u: size for u, size in sizes.items() if isinstance(size, tuple)}
    keep = {f"{photo_key(u)}{suffix}.webp" for u in stored for suffix in ("", "-sm")}
    removed = 0
    for file in PHOTO_DIR.glob("*.webp"):
        if file.name not in keep:
            file.unlink()
            removed += 1
    print(f"Photos: {len(stored)}/{len(urls)} stored locally"
          + (f", removed {removed} unused" if removed else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed-dir", help="read saved Blogger feed JSON pages instead of fetching")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    entries = load_feed_dir(args.feed_dir) if args.feed_dir else fetch_feed()
    if not entries:
        raise RuntimeError("No posts found; leaving the existing catalog untouched")
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    overrides.pop("_comment", None)
    recipes = build(entries, overrides)
    if not args.dry_run:
        attach_photos(recipes)
    cooks = sorted({c for r in recipes for c in r["cooks"]})
    data = {
        "schema_version": "2.0",
        "source": BLOG,
        "imported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total": len(recipes),
        "cooks": cooks,
        "recipes": recipes,
    }
    if args.dry_run:
        print(f"Would write {len(recipes)} recipes")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        old = json.loads(OUT.read_text())
        if {k: v for k, v in old.items() if k != "imported_at"} == {k: v for k, v in data.items() if k != "imported_at"}:
            print("No changes in the Blogger archive")
            return
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
    print(f"Wrote {len(recipes)} recipes to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        sys.exit(1)
