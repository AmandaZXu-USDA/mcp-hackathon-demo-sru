# Librarian quick-start: correction notices in the NAL catalog

Two tools, one for each step of linking a publisher's correction notice to the article it corrects:

| Step | Tool | You give it | You get |
|---|---|---|---|
| 1 | [SRU search URL](#part-2-sru-search-url-from-a-correction-title) (`mcp-sru-syntax`) | A correction notice title | The NAL Alma SRU search URL for the original article |
| 2 | [Erratum annotator](#part-1-erratum-annotator-add-the-erratum-note-to-the-original-title) (`mcp-erratum-note`) | The SRU response for that search | The original article's title with an `[Erratum: ...]` note, ready for the catalog |

Start with Part 1 if you want to see the result: its demo web page needs no setup and answers in about a
second.

# Part 1: Erratum annotator (add the erratum note to the original title)

The annotator reads the Alma SRU response, finds the original article's record (the one whose DOI the
notice cites, otherwise the closest title), and adds the correction's date, volume, issue, pages and DOI to
the end of the original title. For example (Sample1 row 43):

* **Correction notice:** Publisher Correction: DNMT3A/TET2-mediated epigenetic alteration in Type-1 diabetes
  dysregulates the haematopoiesis
* **Annotated title for the original record (MMS ID 9917168304707426):** DNMT3A/TET2-mediated epigenetic
  alteration in Type-1 diabetes dysregulates the haematopoiesis
  [Erratum: Dec. 2026, v. 53, no. 1, 1310, 10.1007/s11033-026-12468-5]

Every option uses the same code, so the same SRU response always gives the same title:

| Option | Best for | Time | Access you need (ask the project owner) |
|---|---|---|---|
| [Demo web page](#erratum-annotator-demo-web-page) | Anyone; demos for staff and sponsors | under a second per notice | A user account in the workspace and `CAN USE` on app `mcp-erratum-note`; or none for the offline copy |
| [Chat with the agent](#erratum-annotator-chat-with-the-agent) | Asking in plain language | slower: the agent plans its tool calls | `CAN QUERY` on endpoint `mas-c341c0aa-endpoint` |
| [Genie Code with the MCP tools](#erratum-annotator-genie-code-with-the-mcp-tools) | While you work in Databricks | a few seconds plus Genie Code's own time | `CAN USE` on app `mcp-erratum-note` |
| [SQL function](#erratum-annotator-sql-function-lists) | Many saved SRU responses at once | about 20 s for all 48 saved responses | `EXECUTE` on `users.amanda_xu.process_sru_response`, `READ VOLUME` on `users.amanda_xu.erratum_files`, a SQL warehouse |

What the result means:

| Status on the page | Meaning | What to do |
|---|---|---|
| Ready for the catalog | One original article was found and the note was added | Copy the annotated title to the original record |
| Needs review | The match to the original is uncertain (for example, several possible original records) | Check the original by hand before you copy anything |
| No original article in Alma | The response holds only the correction notice (Sample1 rows 4 and 24) | Nothing to annotate yet; no title is shown |
| Already annotated | The original title already has an `[Erratum: ...]` note | No change needed |

The tools only read saved SRU responses in `/Volumes/users/amanda_xu/erratum_files/sru_responses`; they
never change Alma or any file.

## Erratum annotator: demo web page

1. Open <https://mcp-erratum-note-7474654188777746.aws.databricksapps.com> in your browser and sign in with
   your Databricks workspace account if asked. The first time, approve the app's request to know who you
   are.
2. Click a quick example: **Typical correction**, **Two corrections in one response**, **Title with a curly
   apostrophe** or **No original article in Alma**. Or choose any of the 48 saved notices from the list and
   click **Annotate this notice**.
3. Read the result from top to bottom: the correction notice, the original article found, the erratum
   note, and the annotated title with the note highlighted. **View record** opens the record's SRU XML in
   Alma; **Copy annotated title** copies the title.
4. Optional: **See all saved notices at once** annotates all 48 in one table (32 ready, 14 already
   annotated, 2 with no original in Alma). **Paste your own SRU response** accepts any SRU MODS XML.

If the page says you do not have access, ask the project owner for `CAN USE` on the app. If you see "Your
sign-in may have expired", reload the page.

**No Databricks account?** Open the offline copy instead: download
[`erratum-annotator-demo-offline.html`](erratum-annotator-demo-offline.html) (in this folder, and in
`erratum-annotator/demo/`) and open it in your browser. It has the same quick examples and all 48 saved
notices with their results, needs no sign-in or network, but cannot annotate pasted XML.

## Erratum annotator: chat with the agent

1. In Databricks, open **Agents** and select **agent-erratum-annotator**.
2. Click **Endpoint**, then **Open in playground**.
3. Ask, for example: `Annotate the original title for Sample1 row 43, correction MMS ID 9917175550407426.`
   If the chat asks you to approve a tool call, approve it.

The agent finds the saved SRU response, runs the same tools as the page, and returns the annotated title
with the original and correction MMS IDs. In the evaluation it returned the exact title for 50 of 53
notices; for the final check, use the page or the SQL function.

## Erratum annotator: Genie Code with the MCP tools

Add the Databricks App **mcp-erratum-note** as a custom MCP server, the same way as in
[Part 2, option 2](#option-2-genie-code-with-the-mcp-tool), and enable its tools. Then ask, for example:
`List the saved SRU files for Row41 and annotate the title.` Genie Code calls `list_sru_files` and
`process_sru_file`.

*Status: the tools are tested from a notebook (Inspector Gadget, 48 files, 0 errors); the Genie Code
connection has not been tested with a librarian account yet.*

## Erratum annotator: SQL function (lists)

Run in the **SQL editor** or a notebook. This annotates every saved SRU response in the folder; the
correction MMS ID is taken from the end of each file name:

```sql
SELECT regexp_extract(_metadata.file_name, '(Row[0-9]+)', 1) AS row_label,
       r.annotated_title, r.erratum_note, r.original_id, r.correction_id, r.needs_review
FROM (
  SELECT _metadata,
         users.amanda_xu.process_sru_response(
           value, '', regexp_extract(_metadata.file_name, '([0-9]{16})\\.xml$', 1)) AS r
  FROM read_files('/Volumes/users/amanda_xu/erratum_files/sru_responses/', format => 'text', wholeText => true)
)
ORDER BY CAST(regexp_extract(_metadata.file_name, 'Row([0-9]+)', 1) AS INT);
```

Pass `''` for an argument you do not know (the function has no default values). Click **Download** on the
result to save it as CSV or Excel. A blank `original_id` means there is no original article in the
response.

# Part 2: SRU search URL from a correction title

Paste an erratum/correction notice title (for example `Correction: Effects of drought stress on maize
grain yield and quality`) and get the NAL Alma production SRU searchRetrieve URL for the original
article. Open the URL in a browser to see the matching Alma record.

Every option below uses the same rules (the Unity Catalog function `users.amanda_xu.build_sru_url`),
so the same title always gives the same URL. Pick by how many titles you have:

| Option | Best for | Time per title | Access you need (ask the project owner) |
|---|---|---|---|
| [Browser page](#browser-page-no-setup) | One title, nothing to install | about 4 s (SQL function first; up to a minute only if it falls back to the agent) | A user account in the Databricks workspace and `CAN USE` on app `mcp-sru-syntax` |
| [1. Chat with the Supervisor Agent](#option-1-chat-with-the-supervisor-agent) | One title, no setup | about 15-25 s | `CAN QUERY` on endpoint `mas-c8629507-endpoint` |
| [2. Genie Code with the MCP tool](#option-2-genie-code-with-the-mcp-tool) | Titles while you work in Databricks | about 4 s for the tool, plus Genie Code's own time | `CAN USE` on app `mcp-sru-syntax` |
| [3. Call the app's agent](#option-3-call-the-apps-agent-scripts) | Scripts and other tools | about 7-10 s | `CAN USE` on app `mcp-sru-syntax` |
| [4. SQL function, no agent](#option-4-sql-function-no-agent-lists-of-titles) | Lists of titles (tens to thousands) | seconds for a whole list (up to a minute more if the SQL warehouse is starting) | `EXECUTE` on `users.amanda_xu.build_sru_url`, `USE CATALOG` on `users`, `USE SCHEMA` on `users.amanda_xu`, a SQL warehouse; for lists, also `READ VOLUME` and `WRITE VOLUME` on `users.amanda_xu.erratum_files` |

**What to expect from options 1-3 (the agent):**

* The reply is the URL only. Copy it as-is; do not edit the encoding (`%20`, `%22`, and so on).
* A bare notice with no article title (`Correction`, `Erratum`) gets a reply asking for the full title,
  or saying there is no single article. An issue-level notice (for example `Errata to taxon 59(5)`) gets
  "no SRU URL".
* Occasionally the reply is empty (about 3 in 41 titles in testing, including some titles about virus
  replication). The app's MCP tool and browser page already ask the agent a second time when this
  happens; in testing the same titles stayed empty on every try, so use option 4 for them.
* Most replies take 15-25 seconds; rarely up to a minute. Do not use options 1-3 for long lists: in a
  20-title batch test, 6 timed out.

## Browser page (no setup)

1. Open <https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com> in your browser.
2. Sign in with your Databricks workspace account if asked. The first time, approve the app's request to
   know who you are.
3. Paste one correction title and click **Get SRU URL**. Most answers take about 4 seconds: the page runs the
   SQL function `users.amanda_xu.build_sru_url` first and asks the AI agent only if that call fails. If the
   function finds no single original article, the page says so at once and offers **Ask the AI agent
   instead**.
4. Click the URL to open the Alma record, or click **Copy URL**.

If you see "Your sign-in may have expired", reload the page. If the page says you do not have access,
ask the project owner for `CAN USE` on the app. You need a user account in the workspace
(`https://dbc-aae0ba16-8727.cloud.databricks.com`); only a workspace admin can add one.

## Option 1: Chat with the Supervisor Agent

1. In Databricks, open **Agents** and select **agent-sru-syntax**.
2. Click **Endpoint**, then **Open in playground**.
3. Type or paste the correction title and press Enter.
4. Copy the URL from the reply.

You can paste one title per message in the same chat.

## Option 2: Genie Code with the MCP tool

One-time setup:

1. Open **Genie Code**. In the chat pane, click the **More** menu (⋮) in the header and select
   **Customizations**. In the full-page Genie Code view, open **Customizations** directly.
2. On the **Connectors** tab, add a server, choose **Custom MCP server**, and select the
   Databricks App **mcp-sru-syntax**.
3. Click **Save**. Make sure the `build_sru_search_url` tool is enabled.

The Databricks documentation calls this Genie Code **Settings** > **MCP Servers**; in this workspace
it is under **Customizations** > **Connectors**. Only Databricks Apps whose names start with `mcp-`
are listed as custom MCP servers, which is why the app is named `mcp-sru-syntax`. If the app is not
listed, ask the project owner for `CAN USE` on it.

Then ask in plain language, for example:

> Get the SRU search URL for "Correction to: Identification of JAZ1-MYC2 Complex in Lotus corniculatus".

Genie Code calls the `build_sru_search_url` tool and shows the URL. The app must be in the same
workspace (it is). Other MCP clients that support OAuth can connect to
`https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/mcp` the same way.

*Status: the tool is tested from a notebook (Inspector Gadget); the Genie Code connection follows the
Databricks documentation but has not been tested with a librarian account yet.*

## Option 3: Call the app's agent (scripts)

The `mcp-sru-syntax` Databricks App hosts the SRU syntax agent next to the MCP server (see
[`deploy/databricks/README.md`](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru/blob/main/deploy/databricks/README.md)).
You send it titles from a terminal or script; it calls the `build_sru_search_url` tool and replies
with the URLs.

| Item | Value |
|---|---|
| App URL | `https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com` |
| Agent endpoints | `POST /invocations` (same as `POST /responses`) |
| URL-only endpoint | `POST /api/sru-url` with `{"title": "..."}`; used by the browser page |
| Browser page | `GET /` |
| Health check | `GET /health` returns `{"status":"ok"}` |
| Workspace | `https://dbc-aae0ba16-8727.cloud.databricks.com` |
| Login | OAuth token only; personal access tokens are rejected |
| Access | `CAN USE` on the app `mcp-sru-syntax` (ask the project owner) |

### Step 1: One-time setup

1. Install the Databricks CLI (v0.205 or later), for example `brew tap databricks/tap && brew install databricks`
   on macOS; for Windows and Linux see the [install guide](https://docs.databricks.com/dev-tools/cli/install.html).
2. Log in with your NAL account (a browser window opens):

   ```bash
   databricks auth login --host https://dbc-aae0ba16-8727.cloud.databricks.com --profile nal
   databricks current-user me --profile nal     # shows your user name if login worked
   ```

   The CLI asks for a profile name; this guide uses `nal`. Use the same name in step 2.

### Step 2: Get a token and check the app

Tokens expire after about an hour; repeat this step when you get `401` or `302` (a redirect to the
login page).

```bash
export TOKEN="$(databricks auth token --profile nal --output json | jq -r .access_token)"
curl -s -H "Authorization: Bearer $TOKEN" \
  https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/health
```

Expected: `{"status":"ok"}`. Without `jq`, run `databricks auth token --profile nal` and copy the
`access_token` value into `TOKEN`.

### Step 3: Send a title

```bash
curl -s -X POST https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/invocations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --max-time 300 \
  -d '{"input": "Correction: Effects of drought stress on maize grain yield and quality"}'
```

To get only the URL as JSON (the endpoint the browser page uses), send one title to `/api/sru-url`:

```bash
curl -s -X POST https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/api/sru-url \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --max-time 300 \
  -d '{"title": "Correction: Effects of drought stress on maize grain yield and quality"}'
```

The reply is `{"text": "<reply>", "urls": ["https://nal.alma.exlibrisgroup.com/view/sru/..."], "source": "function"}`
(about 4 s). `source` is `function` or `agent` (the fallback); add `"use_agent": true` to ask the agent directly.
`urls` is empty when the reply has no SRU URL. Titles are limited to 1,000 characters.

For `/invocations`, `input` is either the title as a string or a chat-style list:
`{"input": [{"role": "user", "content": "Correction: <title>"}]}`. Keep `--max-time 300`: replies
usually take 7-10 seconds, longer only if the tool has to fall back to the Supervisor Agent. If the title contains an apostrophe (`'`), write it as `'\''` inside the
single-quoted `-d` text.

Reply (shortened):

```json
{
  "object": "response",
  "status": "completed",
  "output": [{
    "type": "message", "role": "assistant",
    "content": [{"type": "output_text",
      "text": "https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Effects%20of%20drought%20stress%20on%20maize%20grain%20yield%20and%20quality%22%20and%20alma.local_field_912%3D%22Article%22"}]
  }]
}
```

The URL is in `output[0].content[0].text`. To print only that text, add
`| jq -r '.output[0].content[0].text'` to the end of the `curl` command.

### Several titles in one request

Put one title per line in the string (`\n` between titles). The reply text lists one URL per title as
bullets (`- https://...`), in the same order. Two titles took about 35 seconds in testing. Keep
requests to a few titles; for lists use option 4.

```bash
curl -s -X POST https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/invocations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" --max-time 300 \
  -d '{"input": "Correction: Effects of drought stress on maize grain yield and quality\nCorrection to: Identification of JAZ1-MYC2 Complex in Lotus corniculatus"}' \
  | jq -r '.output[0].content[0].text'
```

### Python

```python
import subprocess, json, requests

APP = "https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com"
token = json.loads(subprocess.check_output(
    ["databricks", "auth", "token", "--profile", "nal", "--output", "json"]))["access_token"]

r = requests.post(f"{APP}/invocations", timeout=300,
                  headers={"Authorization": f"Bearer {token}"},
                  json={"input": "Correction: Effects of drought stress on maize grain yield and quality"})
r.raise_for_status()
print(r.json()["output"][0]["content"][0]["text"])
```

To call the MCP tool `build_sru_search_url` directly instead of the agent, see the test notebook
[`eval/databricks/inspector_gadget_mcp_test.py`](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru/blob/main/eval/databricks/inspector_gadget_mcp_test.py).

### Replies and errors

| You see | Meaning | What to do |
|---|---|---|
| `200` with a URL | Success | Copy the URL as-is |
| `200` with "names no article" or "covers a journal issue" | Bare or issue-level notice; no single article | Nothing to search |
| `200` with "returned an empty reply for this title" (`error empty_reply`) | The Supervisor Agent gave no answer, also after the app's one retry; for a few titles this happens every time | Use option 4 for that title; if it happens for many titles, send the error id to the project owner |
| `302` or `401` | Missing or expired token, or no `CAN USE` on the app | Repeat step 2; if it still fails, ask the project owner for `CAN USE` |
| `400` `Body must include 'input'` | The JSON has no `input` field | Check the `-d` text |
| `502` `agent_failed` with an id | The agent failed | Try again; send the id to the project owner if it repeats |
| `curl: (28)` timeout | No reply within `--max-time` | Try again, or use option 4 |

## Option 4: SQL function, no agent (lists of titles)

Use this for any list. It applies the same rules instantly and returns an empty string for bare and
issue-level notices.

One title, in the **SQL editor** or a notebook:

```sql
SELECT users.amanda_xu.build_sru_url('Correction: Effects of drought stress on maize grain yield and quality') AS sru_url;
```

A list: upload a CSV or Excel file with a `Title` column to the volume
`/Volumes/users/amanda_xu/erratum_files/` (Catalog > users > amanda_xu > erratum_files > Upload), then:

```sql
SELECT Title, users.amanda_xu.build_sru_url(Title) AS sru_url
FROM read_files('/Volumes/users/amanda_xu/erratum_files/<your_file>.csv', format => 'csv', header => true);
```

For Excel, use `format => 'excel'`. Click **Download** on the result to save it as CSV or Excel. The
1,494-title Sample2 results are already in the table `users.amanda_xu.sample2_sru_urls`.

## Help

* No reply, or "permission denied": you are missing the access listed in the table above.
* A URL finds no Alma record: check the original title in the notice; report the title to the project
  owner so the rules can be reviewed.
