# Demo runbook (about 6 minutes)

The live demo shows both MCP apps, first as a librarian sees them and then as an agent's tools. Replay it from a
notebook with [`../inspector_gadget/`](../inspector_gadget/README.md) or check the last recorded replay in
[`../results/demo/`](../results/README.md#demo-replay).

## Before the demo (10 minutes ahead)

1. Open both demo pages once so the apps are warm:
   * <https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com>
   * <https://mcp-erratum-note-7474654188777746.aws.databricksapps.com>
2. If you will show step 5, add both apps as MCP servers in Genie Code and try one request.
3. Have the evaluation reports and [`../results/README.md`](../results/README.md) open in tabs.

Demo notice (Sample 1, row 43; erratum MMS ID 9917175550407426):
`Publisher Correction: DNMT3A/TET2-mediated epigenetic alteration in Type-1 diabetes dysregulates the haematopoiesis`

## Script

| Step | Show | Say | Expected result |
| --- | --- | --- | --- |
| 1 (1 min) | SRU demo page: paste the demo notice, click the button | The librarians' title rules run as a governed function; no model writes the URL. | One NAL Alma SRU URL in about 4 s (3.77 s in the replay) |
| 2 (30 s) | Open the URL | The search finds the correction notice and the original article. | Alma SRU response with 2 records |
| 3 (1 min) | Erratum demo page: pick row 43 | The second app reads the saved response, picks the original record and builds the note. | Status ready; original MMS ID 9917168304707426; title ending `[Erratum: Dec. 2026, v. 53, no. 1, 1310, 10.1007/s11033-026-12468-5]` |
| 4 (30 s) | Erratum page: **See all saved notices at once** | All 48 notices in one table. | 32 ready, 14 already annotated, 2 no original in Alma |
| 5 (1.5 min) | Genie Code: "Build the SRU search URL for this correction notice: ..." then "Annotate Sample 1 row 43" | The same tools serve agents through MCP. | Same URL and annotated title as steps 1 and 3 (this step is not in the recorded replay) |
| 6 (1 min) | [`../results/README.md`](../results/README.md) | Tested from outside as Inspector Gadget: 55/55 and 89/89. | |

## If something goes wrong

| Problem | Do this |
| --- | --- |
| A page asks you to sign in or shows 401 | Sign in with a workspace account that has `CAN USE` on the app |
| Step 1 takes more than 20 s | The function warmed up slowly; send the title again, or show the recorded replay |
| Genie Code does not list a server | Show the demo page instead; the tools and the page run the same code |
| An erratum tool returns `[error ...]` | Read the message aloud: it says what to do next. That is the error handling working |
