# Setup

One-time steps for the admin. You need the `gh` command-line tool, signed in as the owner.

## 1. Create the repository

From the repository root:

    gh repo create olsonale/game-catalog --public --source . --push

## 2. DNS

Make sure `accessiblegames.net` uses Cloudflare DNS.

## 3. The mirror bucket

1. In Cloudflare, create an R2 bucket named `accessiblegames-files`.
2. Connect the custom domain `files.accessiblegames.net` to it: R2, then the bucket, then Settings, then Custom Domains.
3. Create an R2 API token with Object Read & Write on that bucket. Note the account id, access key id and secret access key.

## 4. Repository secrets

Each command prompts for the value:

    gh secret set R2_ACCOUNT_ID
    gh secret set R2_ACCESS_KEY_ID
    gh secret set R2_SECRET_ACCESS_KEY
    gh secret set R2_BUCKET

`R2_BUCKET` is `accessiblegames-files`.

## 5. GitHub Pages

1. In the repository settings, under Pages, set Source to GitHub Actions.
2. Set the custom domain to `catalog.accessiblegames.net`.
3. In Cloudflare DNS, add `CNAME catalog` pointing to `olsonale.github.io`, set to DNS-only (not proxied).
4. Turn on Enforce HTTPS once the certificate is ready.

## 6. Workflow permissions

In the repository settings, under Actions, then General, then Workflow permissions: choose read and write permissions, and tick Allow GitHub Actions to create and approve pull requests.

## 7. Labels

    gh label create link-health
    gh label create submission
    gh label create update
    gh label create problem
    gh label create removal
    gh label create mirror

## 8. First publish

Run the publish workflow by hand:

    gh workflow run publish.yml

When it finishes, confirm https://catalog.accessiblegames.net/index-meta.json loads.

## 9. Moving to an organization later

    gh repo transfer

The index and mirror URLs do not change. Update `REPO_URL` in `tools/catalog/config.py` to the new address.

## Known issues

- The `vb6-runtime` entry points at Microsoft's old download address, which now returns 404 (not found). Choose a replacement source. One way: upload a known-good copy of the runtime installer to the mirror, then add a Mirror source to `entries/vb6-runtime.json` with its `sha256` and `size`. Until then, link checks on that entry will report it as dead.
