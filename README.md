# AshkeSephard Family Recipes

The family cookbook from [ashkesephardfamilyrecipes.blogspot.com](https://ashkesephardfamilyrecipes.blogspot.com/), rebuilt as a fast, mobile-friendly website with the same look and feel as [The Family Table](https://github.com/nighthawk6389/family-dinners).

All 188 blog posts are included, with their original photos (stored in this repo). Each recipe is split into notes, tools, ingredients (with checkboxes) and numbered steps, and links back to its original post. Nothing is invented: every line of each post is kept.

Features: search across titles, ingredients and notes; filters by course, Shabbat, chagim and gluten free; filters by family cook (Ema, Savta, Orlee…) and by meat, dairy or pareve; saved favorites; shareable recipe links (`/?recipe=<slug>`); printable recipes; and a "Surprise me" button.

## Deploying to Vercel

The site is fully static, with no build step.

1. In Vercel, go to **Add New… → Project** and import `nighthawk6389/ashkesephard`.
2. Leave the framework preset as **Other**. `vercel.json` already sets the output directory to `site/`.
3. Click **Deploy**. Every push to `main` redeploys automatically.

To preview locally, run `python3 -m http.server -d site 8000` and open http://localhost:8000.

## How the family adds things

There are no logins. Everything comes in by email to the recipe bot's Gmail address, and the bot puts it on the site:

| Send | What happens |
|---|---|
| **A new recipe**: a photo of the card or cookbook page, or typed out (the site's **＋ Add a recipe** form writes the email for you) | The bot types it up, adds it with the photos, marks any requests it answers, and replies with the link and anything it wasn't sure about |
| **"I made this"**: how it came out, what you changed, photos (button on every recipe) | Shows under **From the family's kitchens** on that recipe and on the home page; the recipe gets a "Tried by" badge |
| **A request**: a recipe nobody has written down (button in **Requested recipes**) | Goes on the wish list. Anyone can answer with "I have this one" |
| **A fix**: or just reply to the bot's confirmation with the correction | The bot edits that recipe and replies with what it changed |

Only addresses on the family list are read; anything else is filed away untouched. If the bot can't tell what an email is for, it replies with a question.

Every 15 minutes a GitHub Action (`.github/workflows/email-bot.yml`) checks the inbox, asks Claude to read each new email and its photos, commits the changes to `main` (Vercel redeploys automatically), replies, and files the email under the Gmail label `Processed-by-bot`. Emails it can't process are retried twice and then answered with an apology and copied to the admin.

### Setting up the recipe bot (once)

1. **Create the inbox.** Make a new Gmail account for the bot (for example `ashkesephard.recipes@gmail.com`). In that account turn on 2-Step Verification, then create an **App password** (Google Account → Security → App passwords). The bot logs in with this, not the real password.
2. **Get a Claude API key** at https://console.anthropic.com (add a little credit; each email costs roughly 5–15 cents).
3. **Add the secrets** in GitHub: repo → Settings → Secrets and variables → Actions.
   - Secrets:
     - `BOT_EMAIL_ADDRESS`: the bot's Gmail address
     - `BOT_EMAIL_APP_PASSWORD`: the app password from step 1
     - `ANTHROPIC_API_KEY`: the key from step 2
     - `FAMILY_SENDERS`: one person per line, the name shown on the site then their address, e.g.
       ```
       Orlee <orlee@example.com>
       Dana <dana@example.com>
       ```
       Add every address someone might send from.
     - `ADMIN_EMAIL` (optional): gets a copy of every new recipe and of anything the bot gives up on.
   - Variables tab: `SITE_URL` = the Vercel address, e.g. `https://ashkesephard.vercel.app`.
4. **Point the site's buttons at the inbox**: put the bot's address in `site/config.js` (`recipesEmail`).
5. **Test it**: Actions → Recipe Email Bot → Run workflow, tick **self test**. It logs in to Gmail, checks sending, and has Claude read a sample recipe, without changing anything. Then send a real email from a family address and wait for the reply.

To add someone later, edit the `FAMILY_SENDERS` secret.

Notes:
- Comments, photos and requests are public on the site, like the recipes. Family email addresses are kept only in the GitHub secret. The bot's log never prints addresses or email content, because Actions logs on a public repository are public.
- GitHub pauses scheduled workflows after 60 days without any repository activity and emails the repo owner; click "Enable workflow" in the Actions tab to resume.
- If `main` ever gets branch protection, allow GitHub Actions to push to it, or the bot can't publish.

## Structure

- `site/`: the website (`index.html`, `styles.css`, `app.js`, `config.js`, `favicon.svg`).
- `site/data/recipes.json`: every recipe. The site is the home for recipes now; the bot adds and edits them.
- `site/data/community.json`: "I made this" notes and recipe requests.
- `site/photos/`: photos as WebP (full size up to 1400px plus a 640px thumbnail). Blog photos are named by a hash of their original Blogger URL; photos emailed to the bot are in `site/photos/family/`, named by a hash of the image.
- `bot/`: the recipe email bot (`python -m bot.run`, or `python -m bot.run --check` for the self test) and its tests.
- `data/bot_state.json`: which emails the bot has handled (stored as hashes, not message contents).
- `data/overrides.json` and `scripts/import_blogger.py`: how the original 188 recipes were imported from the blog. That import is retired: the blog is now an archive, and the script refuses to run once recipes have been added by email.

### Running the bot's tests

```sh
pip install -r bot/requirements.txt pytest jsonschema
curl -o /tmp/greenmail.jar https://repo1.maven.org/maven2/com/icegreen/greenmail-standalone/2.1.3/greenmail-standalone-2.1.3.jar
GREENMAIL_JAR=/tmp/greenmail.jar python -m pytest bot/tests -q
```

The end-to-end test runs the bot against a real local mail server (GreenMail, needs Java) with Claude's answers scripted. It checks new recipes, comments with photos, requests, fixes by reply, ignored senders, retries and duplicate protection.
