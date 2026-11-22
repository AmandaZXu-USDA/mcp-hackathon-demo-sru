# scripts

Command-line scripts for the routine jobs of this project. The same four scripts are in
both repositories: [AmandaZXu-USDA/NAL](https://github.com/AmandaZXu-USDA/NAL) (branch
`add-mcp-servers`, which the live apps are deployed from) and
[AmandaZXu-USDA/mcp-hackathon-demo-sru](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru)
(the hackathon fork). Run them from the repository root. Each one prints what it would
do and writes nothing unless you add `--upload`, `--fixture` or `--apply`. None of them
deletes, commits or pushes.

| Script | What it does | Writes only with |
| --- | --- | --- |
| [`add_sru_response.py`](add_sru_response.py) | Checks a new saved SRU response (a correction-notice sample) with the code the live app runs, shows the original MMS ID, erratum note and annotated title, then saves it to the volume and the test fixtures | `--upload`, `--fixture` |
| [`recreate_uc_function.py`](recreate_uc_function.py) | Recreates a Unity Catalog function from its `.sql` file and restores its grants, which `CREATE OR REPLACE FUNCTION` drops | `--apply` |
| [`sync_to_fork.py`](sync_to_fork.py) | Copies changed files from NAL to the fork, only when the fork's copy has not changed on its own | `--apply` |
| [`check_live.py`](check_live.py) | Calls both live MCP apps and compares the answers with known results (read-only) | never writes |

Requirements: Python 3.11+ and `databricks-sdk` (`requests` comes with it). The
scripts use the Databricks SDK's default credentials. Databricks Apps accept only
OAuth, so for `check_live.py` sign in with `databricks auth login` (or use a service
principal's `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`); a personal access token
gets 401 from the apps. SQL warehouse used below: `50d2bd4ddf65e0f5`.

Unit tests: `tests/test_scripts.py` in the hackathon repo (21 tests, run by its CI on
every push; no Databricks credentials needed, workspace calls are faked).

## Add a new correction-notice sample

Name the file `Sample<N>-Row<R>-<16-digit correction MMS ID>.xml`, then:

    python scripts/add_sru_response.py Sample2-Row14-9917224359507426.xml
    python scripts/add_sru_response.py Sample2-Row14-9917224359507426.xml --upload --fixture

The first command only checks. It refuses a bad name, a file whose correction record
does not match the MMS ID in the name, and invalid UTF-8. Compare the printed annotated
title with the librarian's result before you add `--upload`. A file already saved with
the same bytes is skipped; one with different bytes is refused, never overwritten. The
live tools and the demo page see an uploaded file at once, with no restart. Then add a
test for it in `erratum-annotator/tests/` and rebuild the offline demo
(`erratum-annotator/demo/build_offline_demo.py`).

## Recreate a Unity Catalog function

    python scripts/recreate_uc_function.py sru-syntax-mcp/uc_functions/build_sru_url.sql \
        --warehouse-id 50d2bd4ddf65e0f5
    python scripts/recreate_uc_function.py sru-syntax-mcp/uc_functions/build_sru_url.sql \
        --warehouse-id 50d2bd4ddf65e0f5 --apply

Only grants made on the function itself are recorded and restored. Grants inherited from
the catalog or schema are not affected by a recreate. For `build_sru_url` that is EXECUTE
for the `mcp-sru-syntax` app's service principal; without it the app cannot call the
function. The script fails (exit code 1) if the grants after the recreate differ from
those before. For the erratum functions, change `erratum-annotator/mcp_server/erratum_annotator.py`,
run `erratum-annotator/uc_functions/build_uc_functions.py`, then recreate each
function with this script.

## Copy a change from NAL to the fork

    python scripts/sync_to_fork.py --changed            # NAL edits not committed yet
    python scripts/sync_to_fork.py --since HEAD~1        # files in NAL's last commit
    python scripts/sync_to_fork.py --changed --apply

Both clones must sit side by side (`NAL/` and `mcp-hackathon-demo-sru/`), as in the
Databricks workspace. A file is copied only if the fork's committed copy equals NAL's
earlier version, so a change made in the fork is never overwritten. Each file is
reported as `copy`, `same`, `new`, `diverged`, `dirty` (uncommitted, untracked or deleted
in the fork) or `manual`. `sru-syntax-mcp/.agents/` in NAL is `.agents/` in the fork.
`title-extraction/erratum_title_extractor.py` is always `manual`: the fork keeps a
ruff-formatted version, so port the change by hand and run `ruff check .` there. After
`--apply`, review `git diff` in the fork, run its tests and ruff, then commit.

## Check the live apps

    python scripts/check_live.py --warehouse-id 50d2bd4ddf65e0f5

Five checks (about 30 seconds):

* the erratum app lists its 7 tools, all read-only;
* it gives the librarian's annotated title for Sample 1 row 1;
* its demo page lists every file in the volume;
* the SRU app gives the URL for the original title of a curly-quoted correction title;
* that URL is the same as the one from the UC function.

The demo-page and UC-function checks also need READ VOLUME on
`users.amanda_xu.erratum_files` and EXECUTE on `users.amanda_xu.build_sru_url`; without
them they fail with the permission error. The Inspector Gadget service principal has
both.

The Databricks job "NAL MCP apps daily live check" (job ID 531572408825586) runs this
script once a day on serverless from the NAL workspace clone, signed in as Inspector
Gadget:

    python scripts/check_live.py --warehouse-id 50d2bd4ddf65e0f5 \
        --uc-secret models.ai.inspector-gadget

`--uc-secret` reads the service principal's OAuth credentials from that Unity Catalog
secret with `dbutils`, so it works only on Databricks. The run fails, and emails
amanda.xu@usda.gov, if any check fails. The full test suites are in
[`../eval/inspector_gadget/`](../eval/inspector_gadget/).
