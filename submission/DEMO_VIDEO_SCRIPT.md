# Demo video narration script

Two MCP apps on Databricks: **mcp-sru-syntax** and **mcp-erratum-note**.
Target length: about 2.5 minutes (about 140 words per minute).
Recorded in AI Playground with two panes side by side.

| Time | On screen | Narration |
| --- | --- | --- |
| 0:00-0:20 | Title slide: "MCP Tools for Correction Notices", NAL / USDA | At the National Agricultural Library, catalogers handle hundreds of correction notices: errata, corrigenda, and publisher corrections. Each one has to be matched to its original article in Alma, and that article's title annotated with an erratum note. Today this is manual and slow. We built two MCP apps on Databricks to automate it. |
| 0:20-0:40 | Diagram: notice -> SRU URL -> SRU response -> annotated title | The first app, mcp-sru-syntax, takes a correction notice title and builds the right Alma SRU search URL, following the library's own syntax rules. The second app, mcp-erratum-note, reads the SRU response, finds the original record, and writes the annotated title with the erratum note. Both are custom MCP servers hosted on Databricks Apps, so any MCP client, including an AI agent, can call them. |
| 0:40-1:20 | AI Playground, left pane (agent-sru-syntax, mas-c8629507-endpoint). Type the prompt. Cut the wait, caption "~50 seconds later". | Here is a real correction notice from our sample, MMS ID 9917175652607426. I ask the SRU syntax agent to build the Alma SRU search URL for this notice and its title. The agent calls the MCP tool, which applies the syntax rules: it cleans the title, escapes special characters, and builds the query. The URL it returns matches our ground truth exactly. |
| 1:20-1:50 | Right pane (agent-erratum-annotator, mas-c341c0aa-endpoint). Paste the prompt that names the saved file Sample1-Row42-...xml. | Now we take the SRU response that search returned. I ask the erratum annotator to annotate the original article. It calls process_sru_file, which separates the correction record from the original, extracts the erratum note, and attaches it to the original title. In about 13 seconds we get the annotated title, and it matches what a cataloger produced by hand. |
| 1:50-2:15 | Evaluation reports: SRU report results table, erratum report section 10 | We evaluated both tools with MLflow. The SRU agent got 135 of 142 notices right, with zero wrong URLs: when it is unsure, it returns nothing rather than guessing. The erratum annotator matched the ground-truth annotated title on 50 of 53 notices; two of the misses were the agent retyping a curly apostrophe as a straight one. |
| 2:15-2:35 | GitHub repo README, then thank-you slide | Both servers, tests, and evaluation notebooks are open source in our repo. Next, we will have librarians confirm the ground truth and connect live Alma lookups through USDA eAuth. Thank you. |

## Before recording

* Confirm the erratum annotator number (50 of 53, full rerun on 2026-11-20). Update it if the evaluation is re-run after the Sample 4 updates.
* In the app 1 segment, read out or show the actual correction notice title for Sample1 row 42.
* Warm up both endpoints with one test run so neither stalls on a cold start.
* If AI Playground asks to approve MCP tool calls, approve quickly or cut that moment in editing.
* Record at 1080p with the browser zoomed to 125-150%; hide bookmarks, other tabs, tokens, and email addresses.

## Tools

* Recording: Microsoft Teams or Zoom solo meeting recording, Clipchamp, Xbox Game Bar (Windows), QuickTime (Mac), Loom, or OBS Studio.
* Editing and captions: Clipchamp, Camtasia, or DaVinci Resolve.
