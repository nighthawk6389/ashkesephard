"""The site's data files and the changes each kind of email makes to them."""
import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime, timezone

from PIL import Image, ImageOps

from .config import ROOT

RECIPES = ROOT / "site" / "data" / "recipes.json"
COMMUNITY = ROOT / "site" / "data" / "community.json"
STATE = ROOT / "data" / "bot_state.json"
FAMILY_PHOTOS = ROOT / "site" / "photos" / "family"
FULL_SIZE, THUMB_SIZE = 1400, 640
SECTION_KINDS = ["intro", "notes", "tools", "ingredients", "directions"]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def slugify(value):
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:80] or "recipe"


def save_photo(data, caption=""):
    """Store a photo as full-size and thumbnail WebP named by its content, like the blog photos."""
    key = hashlib.sha256(data).hexdigest()[:16]
    full, thumb = FAMILY_PHOTOS / f"{key}.webp", FAMILY_PHOTOS / f"{key}-sm.webp"
    FAMILY_PHOTOS.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    big = image.copy()
    big.thumbnail((FULL_SIZE, FULL_SIZE))
    if not full.exists():
        big.save(full, "WEBP", quality=80, method=6)
    if not thumb.exists():
        small = image.copy()
        small.thumbnail((THUMB_SIZE, THUMB_SIZE))
        small.save(thumb, "WEBP", quality=74, method=6)
    photo = {"src": f"photos/family/{key}.webp", "thumb": f"photos/family/{key}-sm.webp",
             "width": big.size[0], "height": big.size[1]}
    if caption:
        photo["caption"] = caption
    return photo


class SiteData:
    def __init__(self):
        self.catalog = json.loads(RECIPES.read_text())
        self.community = json.loads(COMMUNITY.read_text()) if COMMUNITY.exists() else {"comments": [], "requests": []}
        self.state = json.loads(STATE.read_text()) if STATE.exists() else {"processed": {}, "threads": {}, "failures": {}}
        self.changed_site = False

    @property
    def recipes(self):
        return self.catalog["recipes"]

    def recipe(self, slug):
        return next((r for r in self.recipes if r["slug"] == slug), None)

    def save(self):
        if self.changed_site:
            self.catalog["total"] = len(self.recipes)
            self.catalog["cooks"] = sorted({c for r in self.recipes for c in r.get("cooks", [])})
            RECIPES.write_text(json.dumps(self.catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
            COMMUNITY.write_text(json.dumps(self.community, indent=1, ensure_ascii=False) + "\n", encoding="utf8")
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(self.state, indent=1, sort_keys=True) + "\n", encoding="utf8")

    # ------------------------------------------------------------ bookkeeping

    def seen(self, message_id):
        return digest(message_id) in self.state["processed"]

    def mark_processed(self, message_id, outcome, slug=None):
        self.state["processed"][digest(message_id)] = {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "outcome": outcome, **({"recipe": slug} if slug else {})}
        self.state["failures"].pop(digest(message_id), None)

    def record_failure(self, message_id):
        key = digest(message_id)
        self.state["failures"][key] = self.state["failures"].get(key, 0) + 1
        return self.state["failures"][key]

    def remember_thread(self, reply_message_id, slug):
        self.state["threads"][digest(reply_message_id)] = slug

    def thread_slug(self, incoming):
        for ref in reversed(incoming.in_reply_to):
            slug = self.state["threads"].get(digest(ref))
            if slug and self.recipe(slug):
                return slug
        return None

    # ------------------------------------------------------------ conversions

    @staticmethod
    def to_sections(model_recipe):
        sections = []
        for kind in SECTION_KINDS:
            items = []
            for entry in model_recipe.get(kind) or []:
                if isinstance(entry, dict):
                    text = (entry.get("text") or "").strip().rstrip(":") if entry.get("heading") else (entry.get("text") or "").strip()
                    if text:
                        items.append({"text": text, "sub": True} if entry.get("heading") else {"text": text})
                elif str(entry).strip():
                    items.append({"text": str(entry).strip()})
            if items:
                sections.append({"kind": kind, "items": items})
        return sections

    @staticmethod
    def for_model(recipe):
        """The parts of a site recipe the model may edit, in the model's schema."""
        out = {k: recipe.get(k) for k in ("slug", "title", "cooks", "courses", "kashrut", "shabbat", "holiday",
                                          "pesach", "gluten_free", "summary", "facts")}
        out["adapted_from"] = recipe.get("adapted_from") or ""
        by_kind = {s["kind"]: s["items"] for s in recipe.get("sections", [])}
        method = by_kind.pop("method", [])
        for kind in ("intro", "notes", "tools", "ingredients", "directions"):
            items = by_kind.get(kind, []) + (method if kind == "directions" else [])
            out[kind] = [{"text": i["text"], "heading": bool(i.get("sub"))} for i in items]
        return out

    def apply_recipe_fields(self, recipe, model_recipe):
        recipe["title"] = model_recipe["title"].strip() or recipe["title"]
        recipe["cooks"] = [c.strip() for c in model_recipe.get("cooks", []) if c.strip()]
        recipe["courses"] = model_recipe.get("courses") or recipe.get("courses") or ["mains"]
        for flag in ("shabbat", "holiday", "pesach", "gluten_free"):
            recipe[flag] = bool(model_recipe.get(flag))
        recipe["kashrut"] = model_recipe.get("kashrut") or "pareve"
        recipe["summary"] = model_recipe.get("summary", "").strip() or recipe.get("summary", "")
        recipe["facts"] = [f.strip() for f in model_recipe.get("facts", []) if f.strip()]
        recipe["adapted_from"] = model_recipe.get("adapted_from", "").strip() or None
        recipe["sections"] = self.to_sections(model_recipe)
        kinds = {s["kind"] for s in recipe["sections"]}
        recipe["complete"] = {"ingredients", "directions"} <= kinds
        recipe["in_progress"] = not recipe["complete"]

    # ------------------------------------------------------------ actions

    def add_recipe(self, model_recipe, sender_name, date, photos, request_ids):
        title = model_recipe["title"].strip() or "Untitled family recipe"
        slugs = {r["slug"] for r in self.recipes}
        base = slugify(title)
        slug, n = base, 2
        while slug in slugs:
            slug, n = f"{base}-{n}", n + 1
        recipe = {
            "number": max((r["number"] for r in self.recipes), default=0) + 1,
            "title": title, "slug": slug, "cooks": [], "kashrut": "pareve", "courses": ["mains"],
            "shabbat": False, "holiday": False, "pesach": False, "gluten_free": False, "vegetarian": False,
            "complete": False, "in_progress": False, "labels": [], "sections": [], "photos": photos, "facts": [],
            "adapted_from": None, "source_url": None, "source": "email", "added_by": sender_name,
            "published": f"{date:%Y-%m-%d}", "updated": f"{date:%Y-%m-%d}", "summary": "",
        }
        self.apply_recipe_fields(recipe, model_recipe)
        if not recipe["cooks"]:
            recipe["cooks"] = [sender_name]
        if not recipe["summary"]:
            recipe["summary"] = f"A recipe from {recipe['cooks'][0]}’s kitchen."
        self.recipes.append(recipe)
        for request in self.community["requests"]:
            if request["id"] in request_ids and request["status"] == "open":
                request.update(status="found", recipe=slug, found=f"{date:%Y-%m-%d}")
        self.changed_site = True
        return recipe

    def update_recipe(self, recipe, model_recipe, new_photos, date):
        self.apply_recipe_fields(recipe, model_recipe)
        recipe["photos"] = recipe.get("photos", []) + new_photos
        recipe["updated"] = f"{date:%Y-%m-%d}"
        self.changed_site = True

    def add_comment(self, slug, sender_name, date, comment, photos, message_id):
        entry = {
            "id": "c-" + digest(message_id)[:10], "recipe": slug, "name": sender_name, "date": f"{date:%Y-%m-%d}",
            "made_it": bool(comment.get("made_it")), "verdict": comment.get("verdict") or "none",
            "text": comment.get("text", "").strip(), "changes": comment.get("changes", "").strip(), "photos": photos,
        }
        self.community["comments"].append(entry)
        self.changed_site = True
        return entry

    def add_request(self, sender_name, date, request, message_id):
        entry = {"id": "q-" + digest(message_id)[:8], "title": request.get("title", "").strip() or "A family recipe",
                 "details": request.get("details", "").strip(), "name": sender_name, "date": f"{date:%Y-%m-%d}",
                 "status": "open", "recipe": None}
        self.community["requests"].append(entry)
        self.changed_site = True
        return entry
