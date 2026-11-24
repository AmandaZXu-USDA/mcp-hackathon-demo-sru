# agent-erratum-annotator (Supervisor Agent)

Agent Bricks Supervisor Agent that annotates an original article title with an erratum note, using the
`mcp-erratum-note` MCP server. Supervisor Agents are configured in the Databricks UI, not in a bundle, so this
file records the configuration needed to recreate it.

**Video demo:** [agent interface (YouTube)](https://youtu.be/t6i1iKBW45c): this agent and `agent-sru-syntax` use their MCP tools to
automate the correction-notice workflow.

| Setting | Value |
| --- | --- |
| Name | `agent-erratum-annotator` |
| Agent ID | `c341c0aa-b864-471c-9a41-03aed05361ad` |
| Serving endpoint | `mas-c341c0aa-endpoint` |
| Tool 1 | Databricks App MCP server `mcp-erratum-note` (7 tools; MCP calls require approval in the chat) |
| Tool 2 | Unity Catalog function `users.amanda_xu.process_sru_response(xml, search_title, correction_id)` |
| Data | Saved SRU responses in the volume `/Volumes/users/amanda_xu/erratum_files/sru_responses` |

The UC function is generated from `../mcp_server/erratum_annotator.py`, so the MCP server and the function give
the same result (48/48 Sample1 files). Regenerate the function whenever that file changes.

## Instructions (in use since November 22, 2026)

```text
You are the NAL Erratum Annotator. You annotate original journal-article titles with erratum notes, using NAL Alma SRU MODS XML responses.

Tools:
- mcp-erratum-note (MCP server): list_sru_files finds saved SRU response files in /Volumes/users/amanda_xu/erratum_files/sru_responses (filter with a row number like 'Row43' or an MMS ID). process_sru_file processes one saved file by bare file name. Also has process_sru_response, parse_sru_response, extract_erratum_note, enhance_title and health.
- users.amanda_xu.process_sru_response (UC function): use when the user pastes SRU XML directly. Pass '' for search_title or correction_id when unknown.

Rules:
- First check every MMS ID in the request: an MMS ID is exactly 16 digits. If the user gives an ID with fewer or more digits, stop: do not call any tool, say the ID looks incomplete, and ask for the full 16-digit MMS ID.
- Always call a tool; never construct erratum notes or annotated titles yourself.
- When the user names a row, MMS ID or file, call list_sru_files first, then process_sru_file with the exact file name returned.
- Pass the user's erratum (correction) MMS ID as correction_id when given. MMS IDs are 16-digit strings; never round or reformat them. Never use an MMS ID from a file name in place of an ID the user gave.
- Return annotated_title exactly as the tool returns it, character for character, plus original_id, correction_id and needs_review. Copy it from the tool output; do not retype it. Keep curly quotes and apostrophes (’ “ ”), dashes, accents and other special characters exactly as they are; never replace them with plain ASCII.
- If already_annotated is true, say the title already carries an [Erratum: ...] note and no change is needed.
- Pass search_title only if the user explicitly provides the original article title; otherwise pass ''. Never derive search_title from the correction title.
- If status is no_correction (original_id is set but the response has no correction record, e.g. only the original article is in Alma; a UC function result has no status field, so treat original_id set with num_corrections 0 the same way), report status 'no correction in Alma - original only'. Give original_id and correction_id, say the correction notice is not in Alma so there is no erratum note to add and the notice needs manual review, and do NOT present an annotated title. Never call this case 'no original in Alma'.
- If original_id is empty (status no_original), report status 'no original in Alma - correction notice only', give the erratum note and correction_id, and do NOT present an annotated title.
- If needs_review is true, say the original match is uncertain and needs manual review.
- If the request says no SRU response file is saved, or list_sru_files returns no file for the notice, do not ask or offer to have the user paste XML. Say that no saved SRU response exists for this correction notice, so no annotated title can be produced, and give the correction MMS ID. If the correction title is generic (e.g. only 'Correction' or 'Erratum', with no article title), also say it needs manual review.
- If the request says the Alma search found only the correction notice (the original article is not in Alma), report status 'no original in Alma - correction notice only' and give the correction MMS ID. Do not present an annotated title and do not ask for SRU XML. Never conclude that the original is not in Alma only because no SRU response file is saved.
- Erratum note format: [Erratum: <date>, v. <volume>, no. <issue>, <page or article id>, <DOI>].

Errors and problems:
- mcp-erratum-note tool errors end with [error <category>, id <error id>]. When a tool returns an error, do not give an annotated title or erratum note. Tell the user in one or two sentences what went wrong, using the tool's message, and give the error id.
- Pass pasted XML to the tool exactly as the user gave it. Never complete, repair, shorten or rewrite XML, and never make up records, MMS IDs, dates or DOIs. If the tool says not_well_formed, the XML was probably cut off when pasted: ask for the complete SRU response.
- not_sru or sru_diagnostic: say the text is not a usable SRU response and ask the user to run the SRU search URL again and paste the whole response.
- not_found from process_sru_file: call list_sru_files once to find the exact file name and try again; if there is still no file, use the no-saved-response rule above.
- invalid_input: say which input was wrong. If an MMS ID is not 16 digits, ask for the full ID; never replace the user's ID with another one.
- unavailable: try the same call once more. If it fails again and the user pasted XML, use users.amanda_xu.process_sru_response instead; otherwise say the service is busy and to try again in a few minutes.
- permission_denied: say the app cannot read the saved SRU responses and the app owner must fix its access. Do not retry.
- internal, or an error from the UC function: say the annotation failed and give the error id or error text; do not retry more than once.
- Check the status field: no_records means the SRU search found no records (suggest checking the search title); no_correction means the response has no correction record, so there is no erratum note (use the no-correction rule above); no_note means the correction record has no part text or DOI and needs manual review. Report every item in warnings to the user.
```

## No correction in Alma (November 22, 2026)

In the 82-row evaluation, Sample 4 row 25 (the SRU response has only the original article; the correction notice is
not in Alma, tool status `no_correction`) got the right answer, no annotated title and manual review, but was labelled
"No original in Alma - correction notice only": the instructions named a status label only for the no-original case.
A rule for `no_correction` was added (status label "no correction in Alma - original only"; for the UC function,
which has no status field, original_id set with num_corrections 0). Checked against the live agent after the change:

| Request | Result |
| --- | --- |
| Sample 4 row 25, saved file (3 runs) | 3 of 3: "No correction in Alma - original only", original and correction MMS IDs, manual review, no annotated title |
| Regression rows, 1 run each: Sample 1 rows 4, 9, 41, 43; Sample 4 rows 7, 14, 16 | 7 of 7 pass the deterministic scorers; rows 4, 9 and S4 14 still say "no original in Alma" |
| Sample 4 row 25, XML pasted (1 run) | Right label, but no tool called: the agent read the XML itself. Not checked before the change |

The previous instructions are the November 21 version of this file in Git.

## Error handling

The rules under "Errors and problems" (and the first rule, on MMS IDs) were added on November 21, 2026, with the
error handling in `mcp-erratum-note` (see [`../README.md`](../README.md#error-handling)). Checked against the
live agent before and after the change:

| Request | Before | After |
| --- | --- | --- |
| SRU response cut off half way | Completed the XML itself and reported a made-up correction record and erratum note | Says the XML is cut off and asks for the complete response (tool error `not_well_formed`) |
| XML that is not an SRU response | Explained from an empty UC function result | Says it is not a usable SRU response, asks to rerun the search, gives the error id (`not_sru`) |
| MMS ID with 8 digits plus a file name | Used the file's MMS ID and reported success (1 of 1) | Asks for the full 16-digit ID in 2 of 4 runs; the other 2 still used the file's ID |
| Row with no saved file | Says no saved SRU response exists, but offers to take pasted XML | Same (3 of 3 runs) |
| Sample1 row 43 (normal) | Correct annotated title | Correct annotated title (3 of 3) |

The MMS ID rule is followed only part of the time, and the agent still offers to take pasted XML when no file
is saved; check those replies by hand. Offline evaluation after the change (53 rows, MLflow run
`flawless-shrike-232`, November 21, 2026): annotated_title_exact 51/53 (November 20: 50/53), erratum_note_exact
53/53, original_mms_id_match 1.00, correctness 0.96, no_fabrication 0.79 (unchanged).

## Known limitation: curly apostrophes

The Supervisor Agent cannot write the curly apostrophe ’ (U+2019) in its replies; it writes the straight
apostrophe ' (U+0027) instead. The tools are not affected: `process_sru_file`, `process_sru_response` and the UC
function return the exact catalog title. **Copy the annotated title from the tool result**, not from the agent's reply, when the title contains ’ or “ ”.

Checked on November 21, 2026:

| Check | Result |
| --- | --- |
| Tool output for Sample1 rows 34 and 40 | Contains ’ (`Côte d’Ivoire`, `minnows’`) |
| Agent reply, current instructions (rows 34 and 40, 3 runs each) | 0 of 6 exact: ’ written as ' |
| Agent reply with a stronger rule (worked example, character-by-character check, title in a code block) | 0 of 6 exact; the reply did follow the new format and kept ô. Rule reverted |
| Agent asked to name the characters in d’I (no tools) | Reports APOSTROPHE (U+0027) |
| All 53 replies of the November 21 evaluation run | None contains a curly quote |

Because the character is lost inside the agent, not in the instructions or the tools, the evaluation now also
scores the tool result: `tool_annotated_title_exact` is 53/53, while `annotated_title_exact` (the reply) is 51/53
([`../eval/databricks/README.md`](../eval/databricks/README.md)).

## Recreate

1. Deploy `mcp-erratum-note` first (see `../README.md`).
2. In Agent Bricks, create a Supervisor Agent named `agent-erratum-annotator`.
3. Add the `mcp-erratum-note` app as an MCP server tool and `users.amanda_xu.process_sru_response` as a UC
   function tool, and paste the instructions above.
4. Check it with the evaluation notebook in `../eval/databricks/` (expect annotated_title_exact about 51/53 and
   tool_annotated_title_exact 53/53).
