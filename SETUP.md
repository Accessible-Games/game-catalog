# Setup

One-time steps for the admin. You need the `gh` command-line tool, signed in as the owner.

Do the steps in order. Pushing to `main` starts the publish and mirror workflows, so everything they need (secrets, labels and workflow permissions) is set up first, and the push comes last.

## 1. Merge the work into main

The tools and workflows are on the `feat/catalog-tools` branch. `main` holds only the first, empty commit. From the repository root:

    git checkout main
    git merge --ff-only feat/catalog-tools

## 2. Create the repository without pushing

    gh repo create Accessible-Games/game-catalog --public --source . --remote origin

This creates the empty GitHub repository and adds it as the `origin` remote. Nothing is pushed yet, so no workflow runs.

## 3. DNS

Make sure `accessiblegames.net` uses Cloudflare DNS.

## 4. The mirror bucket

1. In Cloudflare, create an R2 bucket named `accessiblegames-files`.
2. Connect the custom domain `files.accessiblegames.net` to it: R2, then the bucket, then Settings, then Custom Domains.
3. Create an R2 API token with Object Read & Write on that bucket. Note the account id, access key id and secret access key.

## 5. Repository secrets and variable

Only the account id and the two keys are secrets. Each command prompts for the value:

    gh secret set R2_ACCOUNT_ID
    gh secret set R2_ACCESS_KEY_ID
    gh secret set R2_SECRET_ACCESS_KEY

The bucket name is not secret, so it is a repository variable:

    gh variable set R2_BUCKET --body accessiblegames-files

## 6. Labels

    gh label create link-health
    gh label create submission
    gh label create update
    gh label create problem
    gh label create removal
    gh label create mirror

## 7. The catalog Worker

The index is served by a Cloudflare Worker named `game-catalog` (see `wrangler.jsonc`) at `https://catalog.accessiblegames.net/`. The publish workflow builds the index and deploys the Worker, and the first deploy attaches the domain and creates its DNS record. There is no GitHub Pages setup.

Create a Cloudflare API token for deploys. It needs, on the account: Workers Scripts Write and Account Settings Read; and on the `accessiblegames.net` zone: Workers Routes Write, DNS Write and Zone Read. Then store it, and the account id, as secrets:

    gh secret set CLOUDFLARE_API_TOKEN
    gh secret set CLOUDFLARE_ACCOUNT_ID

Do not create a `catalog` DNS record by hand: the Worker's custom domain creates it, and an existing record blocks it.

## 8. Workflow permissions

The mirror workflow pushes a branch and opens a pull request, so the workflow token needs write access and permission to open pull requests:

    gh api --method PUT repos/Accessible-Games/game-catalog/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true

Or, in the repository settings, under Actions, then General, then Workflow permissions: choose read and write permissions, and tick Allow GitHub Actions to create and approve pull requests.

## 9. Push main

    git push -u origin main

The push starts the publish workflow, and the mirror workflow because it adds files under `entries/`.

## 10. First publish and mirror

Watch the runs with `gh run list`. If either failed or did not start, run it by hand. Running one again is harmless: each waits for any earlier run of itself.

    gh workflow run publish.yml
    gh workflow run mirror.yml

When publish finishes, confirm https://catalog.accessiblegames.net/index-meta.json loads and shows the new `generated_at`. The certificate for a new custom domain can take a few minutes. If mirror found new files, it opens a pull request labelled `mirror`. Review and merge it.

## Mirror pull requests and the GITHUB_TOKEN

The mirror workflow opens its pull requests with the built-in `GITHUB_TOKEN`. GitHub does not start other workflows for events made with that token, so the validate workflow does not run on mirror pull requests.

- Do not make `validate` a required check in branch protection, or mirror pull requests can never be merged.
- To run the checks on a mirror pull request anyway, close it and reopen it yourself.
- Or store a personal access token or a GitHub App token as a secret and use it as `GH_TOKEN` in the step that opens the pull request. Checks then run on mirror pull requests, and `validate` can be a required check.

The mirror workflow runs one at a time. While a `mirror` pull request is open, it does nothing. Merge or close the open one first. The merge itself starts a new mirror run. Closing does not: after closing, run `gh workflow run mirror.yml`.

## Known issues

- The `vb6-runtime` entry points at Microsoft's old download address, which now returns 404 (not found). Choose a replacement source. One way: upload a known-good copy of the runtime installer to the mirror, then add a Mirror source to `entries/vb6-runtime.json` with its `sha256` and `size`. Until then, link checks on that entry will report it as dead.
