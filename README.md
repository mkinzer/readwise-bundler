# readwise-bundler

Joins short articles from Readwise Reader into one long document, so they can
be listened to with Reader's text-to-speech without choosing a new article
every few minutes.

Every night it keeps **five unfinished bundles waiting in Later**. Each bundle
holds 2-4 articles, 40-80 minutes in total, all saved within about two months of
one another. Listening to one and archiving it is all there is to do; the next
morning a new one takes its place.

## What a bundle sounds like

1. **Intro:** "Bundle 12, bundled on November 8, 2026. This bundle includes
   three different articles, about 62 minutes in total. They are: First:
   *title*, by *author*, from *publication*, published *date*. About 14
   minutes. *Readwise's summary*. Second: ..."
2. **Each article:** a heading, "Article 1 of 3: *title*", then the byline and
   length, then the article itself.
3. **After each article:** six seconds of silence, "End of article one:
   *title*.", and three more seconds before the next heading.

The silences are lines reading `<break time="3s" />`. Reader passes a
paragraph's text to the voice, and its Lifelike voices (such as Deborah) treat
that as a three-second pause. It has to be visible text: as real markup,
Reader drops it before speaking. Other voices, such as Unreal Speech's, may
read the line aloud instead. Dashes, ellipses, hums and blank lines were all
tried and either made odd sounds or did nothing. See `LONG_PAUSE` and
`SHORT_PAUSE` in `readwise_bundler/compose.py`.
4. **The end:** "End of bundle 12. That was all three articles."

Images, captions and embedded media are left out, because they read badly
aloud. In Reader the bundle is titled like `Bundle 12 · 3 articles · 62 min`.

## How articles are chosen

* Only from **Later**: articles, newsletters, and feed items moved to Later.
  Not PDFs, books, videos, podcasts or tweets.
* Never anything tagged **`interactive`**.
* Anything Readwise labels at **40 minutes or more** stays on its own.
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

1. **Add your token.** In this repository on GitHub go to **Settings >
   Secrets and variables > Actions > New repository secret**. Name it
   `READWISE_TOKEN`; the value is the token from
   <https://readwise.io/access_token>. Until it is there, the nightly job
   finishes green and does nothing.
2. **Try a dry run.** **Actions > Make listening bundles > Run workflow**, tick
   *Only show what would happen*, and run. The log lists the bundles it would
   make without changing anything.
3. **Run it for real** the same way with the box unticked, or wait for the
   nightly run at about 3 am Eastern.

To change the time, edit the `cron` line in `.github/workflows/bundle.yml`
(it is in UTC). To pause it, disable the workflow on the Actions page.

## Running it on a computer

Python 3.10 or newer, nothing to install:

```bash
export READWISE_TOKEN=...                     # Windows: set READWISE_TOKEN=...
python -m readwise_bundler run --dry-run --preview preview
python -m readwise_bundler run
python -m unittest discover -s tests -t tests
```

`--preview DIR` writes each bundle as an HTML page. `--seed N` makes the random
choices repeatable. `--target N` keeps a different number of bundles waiting.

A run reads the whole of Later (about 2½ minutes for 5,000 documents, because
the API allows 20 list requests a minute) and fetches the text only of the
articles it picks.

## Layout

| File | Does |
|---|---|
| `readwise_bundler/api.py` | Reader API client, paced under the rate limits |
| `readwise_bundler/picking.py` | Which articles qualify, and which go together |
| `readwise_bundler/compose.py` | Cleans article HTML and writes the spoken structure |
| `readwise_bundler/run.py` | The nightly run: settle finished bundles, make new ones |
| `.github/workflows/bundle.yml` | The schedule |
