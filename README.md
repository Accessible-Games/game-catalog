# Game Catalog

A community catalog of accessible games for blind and low-vision players. Each game is one JSON file in `entries/`. Game Chooser reads the published index to find, download and launch games.

## Why this exists

- There was no central place to find audio games. New releases and updates show up as forum posts, and keeping up means reading the forum every day.
- Archives preserve the files but carry very little information about them.
- Access mods for mainstream games need the same thing: a catalog of installable things, with dependencies, installed into places the player already has.

The catalog only lists what can actually be downloaded and launched (or, for web games, opened). It does not list games that cannot be installed.

Games shipped only as source code (for example Python scripts with no runnable build) are not accepted; the catalog provides games to run, it doesn't preserve them.

## How to contribute

### Without Git: issue forms

Open a new issue and pick a form. The admin reviews each one and adds or changes the entry.

- Submit a game: needs a title, developer and a direct download URL. A direct download is a link to the file itself, not a web page about it.
- Suggest an update: a new version, a new download link, or a correction.
- Report a problem: a broken download, or a game that will not install or launch.
- Request removal: for developers and rights holders.

### With Git: pull requests

1. Add or edit a file in `entries/`. The file name is the entry id plus `.json`.
2. Run the checks below.
3. Open a pull request against `main`, the branch all work happens on. Automated checks validate the schema, run the tests, and check that links in new or changed entries respond.

The admin reviews and merges.

## Removal policy

Developers and rights holders can ask for their files to be removed from the mirror or the catalog, and requests are honored. Use the Request removal form.

## Entry field reference

The schema in `schema/entry.schema.json` is authoritative. An entry file holds one JSON object with these fields, written in this order. Unknown fields are rejected. Fields that are only ever `true` (`self_updating`, `unsupported`, `no_longer_sold`) are left out rather than set to false.

### Entry fields

- `id`: required. Lowercase letters, digits and single hyphens, such as `shades-of-doom`. Must match the file name.
- `kind`: required. One of `game`, `extra`, `runtime`, `access-mod`. Access mods are reserved for later.
- `title`: required. The display name.
- `developer`: optional list of developer names.
- `genres`: optional list of one to three genres, no repeats. The first is the main genre. Each is one of `Action`, `Adventure`, `Arcade`, `Board and dice`, `Card`, `Casino`, `Educational`, `Fighting`, `Incremental`, `Interactive fiction`, `Music and rhythm`, `Platformer`, `Puzzle`, `Racing`, `Role-playing`, `Shooter`, `Simulation`, `Sports`, `Strategy`, `Trivia`, `Word`. Narrower kinds go in `tags`.
- `year`: optional release year, from 1970 to 2100.
- `description`: optional Markdown text. Things with no field of their own go here: a beta or early access release, a planned price change, a demo on one platform and the full game on another, port credits, speech or braille requirements, and rights notes.
- `version`: optional version text of what the sources install.
- `self_updating`: optional, `true` when the game updates itself. The app then doesn't treat a changed version or checksum as an update to install.
- `pricing`: optional object saying what the game costs and how you pay. See Pricing fields. Leave it out when the price isn't recorded yet.
- `tags`: optional list of narrower kinds of game and what it offers, no repeats. Each is one of `Multiplayer`, `Roguelike`, `Idle`, `Survival`, `Horror`, `Side-scroller`. The list grows when a real game needs a new tag.
- `languages`: optional list of the languages the game can be played in, as two-letter ISO 639-1 codes such as `en`, `fr`, `ja`, `pt`. No repeats. Leave it out when not known.
- `contains`: optional list of the titles of the games inside a collection or launcher, so search finds each one.
- `unsupported`: optional, `true` when the developer no longer supports the game.
- `warning`: optional single sentence the install dialog shows before installing, such as a risk of an account ban or an antivirus false alarm.
- `links`: optional list of web pages about the game, such as its homepage, AudioGames.net topic, agarchive credit page, community or source code. Never downloads. Players see them in the order listed. Each link has a required `url`, an http or https address, and an optional `label` that players see, such as `Homepage` or `Discord`. Without a label the app shows the site's name. The same URL can't be listed twice.
- `sources`: required list with at least one source. The first is the most preferred.
- `persist`: optional list, games only, of files or folders in the install folder that always hold the player's own data, such as saves. Updates, repairs and adding extras never replace or remove them. Each item is a path relative to the install folder: end it with `/` for a folder and everything in it (`Saves/`), or name a file, which may use the wildcards `*`, `?` and `[...]` (`*.sav`). A name without wildcards also covers everything inside a folder of that name. Case doesn't matter, and `\` counts as `/`. Absolute paths, drive letters, `..` and two items that name the same path are refused, and so are items starting with `./` or with a space before or after them, because the app would never match them. An empty list, `[]`, means someone checked and the game keeps nothing of the player's in its folder; leave the field out when that hasn't been checked.
- `launch`: optional object keyed by platform (`windows`, `macos`, `linux`, `web`). Each value has a required `path`, relative to the install folder, and an optional `args`. When missing, the app finds the executable after install. On Windows the path must end in `.exe`, `.bat`, `.cmd`, `.html` or `.htm`. A `.html` or `.htm` file opens in the player's web browser. The app never guesses a page, so a web page game must name it.
- `dependencies`: optional list of entry ids that must be installed first, such as runtimes.
- `extends`: list of the games an extra belongs to, as entry ids, with at least one id and no repeats. Write a single game as a one-item list, such as `["entombed"]`. One extra can belong to several games, such as a patch shared by a developer's whole series. Required on `extra` entries, allowed on `access-mod` entries and not allowed on any other kind. Each id must name an existing entry whose kind is `game`. The extra installs into the folder of whichever game it's added to. An extra that belongs to more than one game can't use `registry` or `register` steps, because uninstalling it from one game would undo them for the others.
- `required`: optional true or false, only on `extra` entries. When true, the extra is installed automatically with each game it belongs to.
- `detect`: optional hint for spotting a runtime that is already installed, so it is skipped. Either `{"file": "..."}`, present when that file exists (environment variables such as `%WINDIR%` are expanded), or `{"registry": {"hive": "...", "key": "...", "name": "..."}}`, present when that registry value exists. `hive` is one of `HKCR`, `HKLM`, `HKCU`. `name` is optional; without it the key's default value is checked.
- `checkver`: optional rule for spotting new versions. Either `{"github": "owner/repo"}` or `{"url": "...", "regex": "..."}`.

### Pricing fields

- `model`: required. How you pay. One of `free`, `free-to-try` (shareware, demos and timed trials), `pay-what-you-want`, `one-time` (buy once), `subscription`, `free-with-purchases` (free, with optional purchases).
- `price`: optional amount, 0 or more. The unlock price for `free-to-try`, the minimum for `pay-what-you-want`, the price for `one-time`, or the price each period for `subscription`.
- `suggested`: optional amount, 0 or more. The developer's suggested amount for `pay-what-you-want`.
- `currency`: three-letter ISO 4217 code such as `USD`, `EUR` or `GBP`, for `price` and `suggested`. Required with `price`.
- `period`: `month` or `year`. How often a subscription charges. Required with `subscription`.
- `checked`: optional date the price was last confirmed, written `YYYY-MM-DD`.
- `no_longer_sold`: optional, `true` when the full version can't be bought anymore.
- `url`: optional page where you buy, subscribe or register. The install dialog links to it.
- `donate_url`: optional page where you support the developer, usually of a free game.
- `note`: optional short line in the developer's words for what the model can't say, such as `Full version adds 12 levels`.

### Pricing rules

- `price` and `currency` go together: set both or neither.
- `price` isn't used with `free` or `free-with-purchases`.
- `suggested` is only used with `pay-what-you-want`.
- `period` is required with `subscription` and not used with any other model.
- `no_longer_sold` is only used with `free-to-try`, `one-time` or `subscription`.
- `url` and `donate_url` must be http or https addresses with a host.

### Source fields

- `label`: required. Shown to the user, such as `Developer site` or `Mirror`.
- `url`: required. A direct file download, or for a web game the playable address. Use percent-encoding for spaces and special characters. Landing pages belong in `links`.
- `platform`: required. One of `windows`, `macos`, `linux`, `web`.
- `arch`: optional processor the build runs on. One of `x64`, `x86`, `arm64`, `universal`. Leave it out when the build runs on any processor for its platform.
- `install`: required. See below.
- `size`: optional size in bytes.
- `first_run_download_size`: optional number of bytes the game downloads the first time it starts, 0 or more, so the app can show the real total.
- `sha256`: optional lowercase hex checksum. Required on mirror sources, where a mismatch is an error. On developer downloads you can leave both out: when a change is merged, the publish workflow downloads the file once and records them. If a pull request changes a download whose recorded values no longer match the file, the checks fail and show the right values.
- `steps`: optional list of install steps, run in order after files are in place.

The app uses `size` and `sha256` to verify what it installs and to notice updates. When the weekly link check reports that a developer's file changed and the new file is the one players should get, accept it with `uv run catalog-checksums --refresh --only ID` and open a pull request with the result.

Web sources (platform `web`) and sources whose install method is `url` are never mirrored.

### Install fields

- `method`: required. One of `zip`, `7z`, `installer`, `cab`, `tar` (a `.tar.gz`, `.tar.xz` or `.tar.bz2` file), `none` (a single executable, including a Linux AppImage), `url` (a web game).
- `password`: optional password for an encrypted archive, or null.
- `extract_dir`: optional folder inside the archive to use as the root.
- `installer`: used when `method` is `installer`.

### Installer fields

- `type`: required. One of `inno`, `nsis`, `msi`, `installshield`, `other`.
- `mode`: required. `extract` unpacks the files without running the installer. `run` runs it. Extract is the default choice for `inno`, `nsis` and `msi`. Run is the default for `installshield` and `other`.
- `silent_args`: optional arguments for `run` mode. If omitted, the defaults are `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="{dir}"` for Inno, `/S /D={dir}` for NSIS and `/qn TARGETDIR="{dir}"` for MSI. `{dir}` is the folder the app chose.
- `elevation`: optional true or false. True if installing needs administrator rights.

### Steps

Steps come from a fixed list. They are never scripts. Paths are relative to the install folder.

- `copy`: needs `from` and `to`.
- `move`: needs `from` and `to`.
- `delete`: needs `path`.
- `registry`: sets a value. Needs `hive` (`HKCU` or `HKLM`), `key`, `name`, `type` (`REG_SZ` or `REG_DWORD`) and `value`.
- `register`: registers a COM component (DLL or OCX). Needs `path`.
- `run`: runs a file shipped with the game. Needs `path`, with optional `args`.

## Where things are published

- Index: https://catalog.accessiblegames.net/index.json.gz
- Index metadata, a small file for cheap change checks: https://catalog.accessiblegames.net/index-meta.json
- Mirror files: `https://files.accessiblegames.net/files/<sha256>/<file name>`. Mirror files are named by checksum and are never overwritten.

Sources are listed with the developer's own site first and the mirror second, so developers keep their traffic and the mirror is the fallback. The mirror is for preservation, not a copy of every catalog file: most entries point only at the developer's download. The admin preserves files that are at risk of disappearing, such as abandoned freeware or a shaky developer site, by running the mirror workflow for those entries. Paid games are treated like any other entry, since their download is the free installer players use before buying.

The mirror workflow adds the new Mirror sources through a pull request labelled `mirror`. It opens that pull request with the built-in `GITHUB_TOKEN`, and GitHub does not start other workflows for it, so the automated checks do not run on mirror pull requests. For that reason `validate` is not a required check. See `SETUP.md` for ways around this.

## Local commands

Install [uv](https://docs.astral.sh/uv/), then from the repository root:

- `uv sync` installs dependencies.
- `uv run pytest -q` runs the tests.
- `uv run catalog-validate` checks every entry against the schema and the cross-entry rules.
- `uv run catalog-index --out site` builds the index into `site/`.
- `uv run catalog-links` checks every source link. Add `--only ID` to check certain entries, or `--changed-from REF` to check entries changed since a git ref. `--report FILE` writes a Markdown report, and `--fail-on-dead` exits with an error if a link is dead.
- `uv run catalog-checksums` records missing `sha256` and `size` values of developer downloads. `--check` changes nothing and fails on a stale value, `--refresh --only ID` accepts a changed file, and `--changed-from REF` limits it to entries changed since a git ref. Files are hashed as they download and are not kept.
- `uv run catalog-mirror --only ID [ID ...] --dry-run` shows what would be mirrored for those entries without uploading. A real run uses the R2 API keys when `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_BUCKET` are set (as in CI), and otherwise your Wrangler login (`npx wrangler login`, once).
- `uv run catalog-put FILE [FILE ...]` uploads local files, such as repacks, to the mirror and prints each one's `url`, `sha256` and `size` for the entry's source.
- `uv run catalog-prune --since REF` lists mirror files that entries referenced at commit `REF` and no longer reference. Add `--delete` to delete them.

See `SETUP.md` for the one-time admin setup.

## License

The catalog data is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0). The full text is in `LICENSE` and at https://creativecommons.org/licenses/by/4.0/.

- Covered: the catalog data, meaning the entry files in `entries/` and the published index.
- Not covered: the code of the tools in this repository, and the games themselves. The games, including the files on the mirror, belong to their developers.

You may copy, share and adapt the catalog data, for any purpose, as long as you give credit. To give credit:

- Name the source as "Game Catalog" and link to https://catalog.accessiblegames.net/.
- Say that the data is licensed under CC BY 4.0, with a link to the license.
- Say so if you changed the data.
