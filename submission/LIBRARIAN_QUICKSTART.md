# Librarian quick-start: get an SRU search URL from a correction title

Paste an erratum/correction notice title (for example `Correction: Effects of drought stress on maize
grain yield and quality`) and get the NAL Alma production SRU searchRetrieve URL for the original
article. Open the URL in a browser to see the matching Alma record.

Every option below uses the same rules (the Unity Catalog function `users.amanda_xu.build_sru_url`),
so the same title always gives the same URL. Pick by how many titles you have:

| Option | Best for | Time per title | Access you need (ask the project owner) |
|---|---|---|---|
| [1. Chat with the Supervisor Agent](#option-1-chat-with-the-supervisor-agent) | One title, no setup | about 15-25 s | `CAN QUERY` on endpoint `mas-c8629507-endpoint` |
| [2. Genie Code with the MCP tool](#option-2-genie-code-with-the-mcp-tool) | Titles while you work in Databricks | about 15-25 s | `CAN USE` on app `mcp-sru-syntax` |
| [3. Call the app's agent](#option-3-call-the-apps-agent-scripts) | Scripts and other tools | about 15-45 s | `CAN USE` on app `mcp-sru-syntax` |
| [4. SQL function, no agent](#option-4-sql-function-no-agent-lists-of-titles) | Lists of titles (tens to thousands) | seconds for a whole list (up to a minute more if the SQL warehouse is starting) | `EXECUTE` on `users.amanda_xu.build_sru_url`, `USE CATALOG` on `users`, `USE SCHEMA` on `users.amanda_xu`, a SQL warehouse; for lists, also `READ VOLUME` and `WRITE VOLUME` on `users.amanda_xu.erratum_files` |

**What to expect from options 1-3 (the agent):**

* The reply is the URL only. Copy it as-is; do not edit the encoding (`%20`, `%22`, and so on).
* A bare notice with no article title (`Correction`, `Erratum`) gets a reply asking for the full title,
  or saying there is no single article. An issue-level notice (for example `Errata to taxon 59(5)`) gets
  "no SRU URL".
* Occasionally the reply is empty (about 3 in 41 titles in testing, including some titles about virus
  replication). Ask again, or use option 4.
* Most replies take 15-25 seconds; rarely up to a minute. Do not use options 1-3 for long lists: in a
  20-title batch test, 6 timed out.

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
[`deploy/databricks/README.md`](https://github.com/AmandaZXu-USDA/mcp-hackathon-template/blob/main/deploy/databricks/README.md)).
You send it titles from a terminal or script; it calls the `build_sru_search_url` tool and replies
with the URLs.

| Item | Value |
|---|---|
| App URL | `https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com` |
| Agent endpoints | `POST /invocations` (same as `POST /responses`) |
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

Tokens expire after about an hour; repeat this step when you get `401`.

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

`input` is either the title as a string or a chat-style list:
`{"input": [{"role": "user", "content": "Correction: <title>"}]}`. Keep `--max-time 300`: replies
usually take 15-45 seconds. If the title contains an apostrophe (`'`), write it as `'\''` inside the
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
[`eval/databricks/inspector_gadget_mcp_test.py`](https://github.com/AmandaZXu-USDA/mcp-hackathon-template/blob/main/eval/databricks/inspector_gadget_mcp_test.py).

### Replies and errors

| You see | Meaning | What to do |
|---|---|---|
| `200` with a URL | Success | Copy the URL as-is |
| `200` with "names no article" or "covers a journal issue" | Bare or issue-level notice; no single article | Nothing to search |
| `200` with "returned an empty reply for this title" | The Supervisor Agent gave no answer (happens for some titles, e.g. about virus replication) | Use option 4 for that title |
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
