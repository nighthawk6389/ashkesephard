#!/usr/bin/env python3
"""Import the complete public Blogger Atom feed without inventing recipe content."""
import argparse, json, re, sys, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlencode
import requests
from bs4 import BeautifulSoup
import bleach

BLOG = "https://ashkesephardfamilyrecipes.blogspot.com"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "recipes.json"
ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {"p","br","h1","h2","h3","h4","h5","div","span","img","table","thead","tbody","tr","th","td","hr","center","figure","figcaption","b","i","u"}
ALLOWED_ATTRS = {"a":["href","title"],"img":["src","alt","width","height"],"td":["colspan","rowspan"],"th":["colspan","rowspan"]}

def slugify(value):
    s = unicodedata.normalize("NFKD", value).encode("ascii","ignore").decode().lower()
    return re.sub(r"-+","-",re.sub(r"[^a-z0-9]+","-",s)).strip("-")[:100] or "recipe"

def fetch_all(session, max_pages=50):
    items, seen = [], set()
    for page in range(max_pages):
        params={"alt":"json","max-results":"150","start-index":str(page*150+1)}
        url=BLOG+"/feeds/posts/default?"+urlencode(params)
        for attempt in range(3):
            try:
                response=session.get(url,timeout=35,headers={"User-Agent":"AshkeSephardFamilyRecipeArchiver/1.0"})
                response.raise_for_status()
                payload=response.json()
                break
            except (requests.RequestException,ValueError) as exc:
                if attempt==2: raise RuntimeError(f"Cannot fetch Blogger feed page {page+1}: {exc}") from exc
                time.sleep(2*(attempt+1))
        entries=payload.get("feed",{}).get("entry",[])
        for entry in entries:
            ident=entry.get("id",{}).get("$t")
            if not ident or ident in seen: continue
            seen.add(ident);items.append(entry)
        print(f"Feed page {page+1}: {len(entries)} entries; total {len(items)}")
        if len(entries)<150: return items
    raise RuntimeError("Blog feed exceeded max_pages; refusing to claim complete export")

def get_source(entry):
    for link in entry.get("link",[]):
        if link.get("rel")=="alternate" and "html" in link.get("type",""): return link.get("href","")
    return ""

def classify(title, labels):
    s=" ".join([title]+labels).lower()
    if re.search(r"cake|cookie|dessert|brownie|sweet|pudding|ice cream|chocolate|pie|baklava|halva|rugelach",s): return "desserts","Desserts"
    if re.search(r"bread|challah|babka|roll|bagel|muffin|pastry|dough",s): return "baking","Baking"
    if re.search(r"pesach|passover|purim|rosh hashana|chanukah|hanukkah|holiday|sukkot|shavuot|yom kippur",s): return "holidays","Holidays"
    if re.search(r"salad|dip|appetizer|side|sauce|pickles|rice|potato|vegetable|hummus",s): return "sides","Sides"
    return "main","Mains"

def sanitize(raw):
    soup=BeautifulSoup(raw,"html.parser")
    for tag in soup(["script","style","iframe","object","embed","form","button","input","video","audio","noscript"]): tag.decompose()
    for image in soup.find_all("img"):
        src=image.get("data-src") or image.get("src") or ""
        if src.startswith("//"): src="https:"+src
        if src.startswith("/") and not src.startswith("//"): src=urljoin(BLOG,src)
        if not src.startswith(("https://","http://")): image.decompose();continue
        image["src"]=src
    for a in soup.find_all("a"):
        href=a.get("href","")
        if href.startswith("/"): a["href"]=urljoin(BLOG,href)
    safe=bleach.clean(str(soup),tags=ALLOWED_TAGS,attributes=ALLOWED_ATTRS,protocols=["http","https","mailto"],strip=True)
    plain=soup.get_text(" ",strip=True)
    img=next((i.get("src") for i in soup.find_all("img") if i.get("src","").startswith(("https://","http://"))),None)
    return safe,plain,img

def build(entries):
    result=[]; used=set()
    for entry in entries:
        title=entry.get("title",{}).get("$t","").strip()
        if not title: continue
        raw=entry.get("content",{}).get("$t") or entry.get("summary",{}).get("$t") or ""
        safe,plain,image=sanitize(raw)
        labels=[x.get("term","").strip() for x in entry.get("category",[]) if x.get("term")]
        source=get_source(entry)
        if not source: continue
        link_slug=slugify(urlparse(source).path.split("/")[-1].removesuffix(".html"))
        stable=entry["id"]["$t"]
        slug=link_slug
        if slug in used: slug=link_slug+"-"+slugify(stable)[-14:]
        used.add(slug)
        course_key,course=classify(title,labels)
        result.append({"source_id":stable,"title":title,"slug":slug,"summary":plain[:250],
            "blog_html":safe,"blog_text":plain,"source_url":source,
            "published":entry.get("published",{}).get("$t"),"updated":entry.get("updated",{}).get("$t"),
            "labels":labels,"course_key":course_key,"course":course,"image_url":image})
    result.sort(key=lambda r:r.get("published") or "")
    for idx,item in enumerate(result,1):item["number"]=idx
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--dry-run",action="store_true");args=parser.parse_args()
    with requests.Session() as session: entries=fetch_all(session)
    recipes=build(entries)
    if not recipes: raise RuntimeError("No public Blogger posts found. Leaving the existing catalog untouched.")
    current=json.loads(OUT.read_text()) if OUT.exists() else {"recipes":[]}
    old_ids={r.get("source_id"):r for r in current.get("recipes",[])}
    for recipe in recipes:
        old=old_ids.get(recipe["source_id"])
        if old and old.get("slug"):recipe["slug"]=old["slug"]
    existing=set();
    for recipe in recipes:
        if recipe["slug"] in existing: raise RuntimeError("Duplicate slugs encountered")
        existing.add(recipe["slug"])
    data={"schema_version":"1.0","source":BLOG,"updated_at":datetime.now(timezone.utc).isoformat(),
          "total":len(recipes),"recipes":recipes}
    if args.dry_run: print(f"Would write {len(recipes)} imported posts");return
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(f"Imported {len(recipes)} posts to {OUT}")

if __name__=="__main__":
    try:main()
    except Exception as exc:print(f"Import failed: {exc}",file=sys.stderr);sys.exit(1)
