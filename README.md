# AshkeSephard Family Recipes

The family cookbook from [ashkesephardfamilyrecipes.blogspot.com](https://ashkesephardfamilyrecipes.blogspot.com/), rebuilt as a fast, mobile-friendly website with the same look and feel as [The Family Table](https://github.com/nighthawk6389/family-dinners).

All 188 blog posts are included, with their original photos. Each recipe is split into notes, tools, ingredients (with checkboxes) and numbered steps, and links back to its original post. Nothing is invented: every line of each post is kept.

Features: search across titles, ingredients and notes; filters by course, Shabbat, chagim and gluten free; filters by family cook (Ema, Savta, Orlee…) and by meat, dairy or pareve; saved favorites; shareable recipe links (`/?recipe=<slug>`); printable recipes; and a "Surprise me" button.

## Deploying to Vercel

The site is fully static, with no build step.

1. In Vercel, go to **Add New… → Project** and import `nighthawk6389/ashkesephard`.
2. Leave the framework preset as **Other**. `vercel.json` already sets the output directory to `site/`.
3. Click **Deploy**. Every push to `main` redeploys automatically.

To preview locally, run `python3 -m http.server -d site 8000` and open http://localhost:8000.

## Structure

- `site/`: the website (`index.html`, `styles.css`, `app.js`, `favicon.svg`).
- `site/data/recipes.json`: every recipe, generated from the blog.
- `scripts/import_blogger.py`: fetches the public Blogger feed and turns each post into a structured recipe.
- `data/overrides.json`: hand corrections, such as fixing a title or setting a course, keyed by the post's URL slug.
- `.github/workflows/import-blogger.yml`: re-imports the blog every Monday. You can also run it manually from the Actions tab. It commits only when something changed on the blog, which then triggers a Vercel redeploy.

## Updating recipes

Keep writing on Blogger as usual. The weekly import picks up new and edited posts. You can also import on demand:

```sh
pip install beautifulsoup4
python3 scripts/import_blogger.py
```

How the importer reads a post:

- Headings like "Ingredients", "Directions", "Notes" and "Cooking Tools" start sections. Lines such as "Sauce Ingredients" or "Directions for burekas" become sub-headings.
- Blogger labels set the family cook (Ema, Savta, Saba, Abba, Orlee, Alex, TanTan, Danish, Yatti, Doda Pnena, Amanda, Sue Zeitlin), the course, meat/dairy/pareve, Shabbat, chagim and gluten free.
- Titles marked "FIX", "needs editing" or "just photos" show as **Still being written up** on the site. Remove the marker on the blog once a recipe is finished.

Photos are loaded straight from Blogger's image servers, so the blog's images need to stay published.
