# readwise-bundler

Joins short articles from Readwise Reader into one long document, so they can
be listened to with Reader's text-to-speech without choosing a new article
every few minutes.

Every night it keeps **ten unfinished bundles waiting in Later**. Each bundle
holds 2-4 articles, 40-80 minutes in total, all saved within about two months of
one another. Listening to one and archiving it is all there is to do; the next
run puts a new one in its place.

## What a bundle looks like in Reader

**Title:** `Bundle 6 (2019) | FP Books | Tunisia | Equality Philosopher | Mexican Cartels`:
the bundle number, the year or years the articles were published, and a one-
to three-word label for each article, under 15 words in all. Claude writes the
labels from the article titles alone. Without an Anthropic API key, or if that
request fails, labels are taken from the first words of the titles instead.

**Thumbnail:** a card with the bundle number and the articles' labels
(the `list` style). A `collage` of the articles' own pictures is also
available, and `alternate` mixes the two by bundle number; see the options
below.

## What a bundle sounds like

1. **Intro:** "Bundle 12, bundled on November 8, 2026. This bundle includes
   three different articles, about 62 minutes in total. They are: First:
   *title*, by *author*, from *publication*, published *date*. About 14
   minutes. *Readwise's summary*. Second: ..."
2. **Each article:** a heading, "Article 1 of 3: *title*", then the byline and
   length, then the article itself.
3. **After each article:** six seconds of silence, "End of article one:
   *title*.", and three more seconds before the next heading.
4. **The end:** "End of bundle 12. That was all three articles."

The silences are lines reading `<break time="3s" />`. Reader passes a
paragraph's text to the voice, and its Lifelike voices (such as Deborah) treat
that as a three-second pause. It has to be visible text: as real markup,
Reader drops it before speaking. Other voices, such as Unreal Speech's, may
read the line aloud instead. Dashes, ellipses, hums and blank lines were all
tried and either made odd sounds or did nothing. See `LONG_PAUSE` and
`SHORT_PAUSE` in `readwise_bundler/compose.py`.

Images, captions and embedded media are left out of the text, because they
read badly aloud.

## How articles are chosen

* Only from **Later**: articles, newsletters, and feed items moved to Later.
  Not PDFs, books, videos, podcasts or tweets.
* Never anything tagged **`interactive`** or **`jobpost`** (spelling
  variants like "job post" count too; the list is `SKIP_TAGS` in
  `readwise_bundler/picking.py`).
* Anything Readwise labels at **40 minutes or more** stays on its own, and
  anything **under 2 minutes** is left out.
* An article whose Readwise title is just its web address gets a title made
  from the address ("clinton-brazile-hacks-2016" becomes "Clinton Brazile Hacks
  2016"), or is left out if the address has no words in it.
* One article is picked at random, and its companions come from what was saved
  within **30 days either side** of it. Picking an article rather than a date
  means bundles come most often from the stretches when the most was saved.
* Within a bundle, the oldest publication goes first.
* Lengths are Readwise's own reading-time labels.

## Tags it uses

| Tag | On | Meaning |
|---|---|---|
| `listen-bundle` | bundles | This is a bundle. |
| `bundled` | originals | In a bundle; never used again. Left in Later. |
| `bundle-heard` | bundles and their originals | The bundle was archived, so it was listened to. |

Everything the tool knows lives in Reader. Each bundle's note lists links to its
originals, which is how the tool finds them again. There is no database.

* **Finished a bundle?** Archive it. On the next run it and its originals get
  `bundle-heard`.
* **Want an article back in the pool?** Remove its `bundled` tag *and* delete
  the bundle that lists it.
* **Want an article never bundled?** Tag it `interactive`.

## Setup

1. **Readwise token.** In this repository on GitHub go to **Settings >
   Secrets and variables > Actions > New repository secret**. Name it
   `READWISE_TOKEN`; the value is the token from
   <https://readwise.io/access_token>. Until it is there, the nightly job
   finishes green and does nothing.
2. **Anthropic API key** (for the title labels). Add it the same way, named
   `ANTHROPIC_API_KEY`; keys are made at console.anthropic.com under Settings >
   API Keys. Labels cost well under a cent a bundle with Claude Opus 5.5.
3. **Make the repository public.** Reader takes a thumbnail only as a web
   address, so the job saves thumbnails to this repository's `thumbnails`
   branch and gives Reader their raw.githubusercontent.com addresses, which
   work only while the repository is public (**Settings > General > Danger
   Zone > Change visibility**). That makes the code, README and run logs
   (which list article titles) public; the secrets stay secret.
4. **Try a dry run.** **Actions > Make listening bundles > Run workflow**, tick
   *Only show what would happen*, and run. The log lists the bundles it would
   make without changing anything.
5. **Run it for real** the same way with the box unticked, or wait for the
   nightly run at about 3 am Eastern. GitHub often starts scheduled jobs hours
   late.

**Run workflow options:** *Thumbnail style* (list, collage, alternate or none)
and *Refresh waiting bundles*, which first gives the bundles already waiting
the current title format and a thumbnail. To change the nightly style, add a
repository variable `BUNDLER_THUMBNAILS` (Settings > Secrets and variables >
Actions > Variables) set to `list` (the default), `collage`, `alternate` or
`none`. A refresh keeps the labels a bundle already has, redraws only
thumbnails whose style changed, and leaves up-to-date bundles alone.

To change the time, edit the `cron` line in `.github/workflows/bundle.yml`
(it is in UTC). To pause it, disable the workflow on the Actions page.

## Running it on a computer

Python 3.10 or newer:

```bash
python -m pip install -r requirements.txt
export READWISE_TOKEN=...                     # Windows: set READWISE_TOKEN=...
export ANTHROPIC_API_KEY=...                  # optional
python -m readwise_bundler run --dry-run --preview preview
python -m readwise_bundler run
python -m readwise_bundler refresh --dry-run
python -m unittest discover -s tests -t tests
```

`--preview DIR` writes each bundle as an HTML page and its thumbnail as a JPEG.
`--seed N` makes the random choices repeatable. `--target N` keeps a different
number of bundles waiting. `--thumbnails` picks the style. Thumbnails are only
uploaded inside GitHub Actions, where `GITHUB_REPOSITORY` and `GITHUB_TOKEN`
are set.

A run reads the whole of Later (about 2½ minutes for 5,000 documents, because
the API allows 20 list requests a minute) and fetches the text only of the
articles it picks.

## Layout

| File | Does |
|---|---|
| `readwise_bundler/api.py` | Reader API client, paced under the rate limits |
| `readwise_bundler/picking.py` | Which articles qualify, and which go together |
| `readwise_bundler/compose.py` | Cleans article HTML, writes the spoken structure and the title |
| `readwise_bundler/labels.py` | Short topic labels from Claude, with a fallback from the titles |
| `readwise_bundler/thumbs.py` | Draws the collage and list thumbnails |
| `readwise_bundler/hosting.py` | Saves thumbnails to the `thumbnails` branch |
| `readwise_bundler/run.py` | The nightly run: settle finished bundles, make new ones, refresh |
| `readwise_bundler/fonts/` | Inter, under the SIL Open Font License |
| `.github/workflows/bundle.yml` | The schedule |
