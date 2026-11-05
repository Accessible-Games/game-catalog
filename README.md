# Game Catalog

A community catalog of accessible games for blind and low-vision players. Each game is one JSON file in `entries/`. Game Chooser reads the published index to find, download and launch games.

## Why this exists

- There was no central place to find audio games. New releases and updates show up as forum posts, and keeping up means reading the forum every day.
- Archives preserve the files but carry very little information about them.
- Access mods for mainstream games need the same thing: a catalog of installable things, with dependencies, installed into places the player already has.

The catalog only lists what can actually be downloaded and launched (or, for web games, opened). It does not list games that cannot be installed.

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
3. Open a pull request. Automated checks validate the schema, run the tests, and check that links in new or changed entries respond.

The admin reviews and merges.

## Removal policy

Developers and rights holders can ask for their files to be removed from the mirror or the catalog, and requests are honored. Use the Request removal form.

## Entry field reference

The schema in `schema/entry.schema.json` is authoritative. An entry file holds one JSON object with these fields. Unknown fields are rejected.

### Entry fields

- `id`: required. Lowercase letters, digits and single hyphens, such as `shades-of-doom`. Must match the file name.
- `kind`: required. One of `game`, `extra`, `runtime`, `access-mod`. Access mods are reserved for later.
- `title`: required. The display name.
- `developer`: optional list of developer names.
- `genres`: optional list of genre names.
- `year`: optional release year, from 1970 to 2100.
- `description`: optional Markdown text.
- `version`: optional version text.
- `flags`: optional list of `abandoned`, `demo`, `beta`, `multiplayer`, `requires-registration`, `registration`. No repeats.
- `links`: optional object. Keys are `homepage`, `purchase`, `audiogames_net` and `agarchive`, each a URL. The `agarchive` link is credit to a page only, never a download.
- `sources`: required list with at least one source. The first is the most preferred.
- `launch`: optional object keyed by platform (`windows`, `macos`, `linux`, `web`). Each value has a required `path`, relative to the install folder, and an optional `args`. When missing, the app finds the executable after install.
- `dependencies`: optional list of entry ids that must be installed first, such as runtimes.
- `extends`: optional entry id of the parent game, or null. Used by extras.
- `install_into`: optional entry id whose install folder receives the files, or null. Usually the same as `extends`.
- `required`: optional true or false. When true, an extra is installed automatically with its parent.
- `approval`: optional object with a required `note` and an optional `url`. Records that the creator approved distribution.
- `detect`: optional object with a hint for spotting an existing install, such as a file path for a runtime.
- `checkver`: optional rule for spotting new versions. Either `{"github": "owner/repo"}` or `{"url": "...", "regex": "..."}`.

### Registration approval rule

An extra flagged `registration` (a registration patch or key generator) must have an `approval` note. These are only allowed for abandoned games, and only with the creator's approval. Set `required` to true on them so they install with the game.

### Source fields

- `label`: required. Shown to the user, such as `Developer site` or `Mirror`.
- `url`: required. A direct file download, or for a web game the playable address. Use percent-encoding for spaces and special characters. Landing pages belong in `links.homepage`.
- `platform`: required. One of `windows`, `macos`, `linux`, `web`.
- `install`: required. See below.
- `size`: optional size in bytes.
- `sha256`: optional lowercase hex checksum. Required on mirror sources, where a mismatch is an error. On developer downloads you can leave both out: when a change is merged, the publish workflow downloads the file once and records them. If a pull request changes a download whose recorded values no longer match the file, the checks fail and show the right values.

The app uses these values to verify what it installs and to notice updates. When the weekly link check reports that a developer's file changed and the new file is the one players should get, accept it with `uv run catalog-checksums --refresh --only ID` and open a pull request with the result.
- `steps`: optional list of install steps, run in order after files are in place.

Web sources (platform `web`) and sources whose install method is `url` are never mirrored.

### Install fields

- `method`: required. One of `zip`, `7z`, `installer`, `cab`, `none` (a single executable), `url` (a web game).
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
