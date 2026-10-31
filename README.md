# AshkeSephard Family Recipes

A family cookbook with the same warm, responsive look and recipe browsing as The Family Table.

**GitHub Pages URL (once activated):** https://nighthawk6389.github.io/ashkesephard/

## Importing the original Blogger recipes

The recipes come from https://ashkesephardfamilyrecipes.blogspot.com/. Source retrieval was unavailable during initial setup, so the JSON starts empty intentionally. **No recipes were invented.**

The workflow at `.github/workflows/import-blogger.yml` fetches and paginates the public Blogger Atom/JSON feed, keeping each post’s title, source URL, date, labels, original HTML, plain text and image URLs. It sanitizes embedded content and writes `data/recipes.json`.

Run `Import Blogger Recipe Archive` in the GitHub Actions tab. It also tries weekly on Mondays. If the blog rejects access, the workflow fails visibly without overwriting the existing data.

## Website

The site lives in `site/` and loads `data/recipes.json`. It includes search, categories, recipe photos, favorites, shareable recipe URLs and printable posts.

To publish, use Settings → Pages → Build and deployment → Source → **GitHub Actions**. Run `Publish AshkeSephard Website` if it does not start automatically.

The repository is public and the resulting Pages site will also be public.
