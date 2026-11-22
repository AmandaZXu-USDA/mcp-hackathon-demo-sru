# Offline demo: Erratum Annotator

[`erratum-annotator-demo-offline.html`](erratum-annotator-demo-offline.html) is the `mcp-erratum-note` demo page as
one self-contained file, for NAL staff and sponsors who have no Databricks account. Download it (on GitHub: open
the file, then **Download raw file**) and open it in any browser. It needs no sign-in and no network, and sends
nothing anywhere.

It contains the results for all 75 saved SRU responses (48 from Sample 1, Sample 2 rows 3 and 14, and 25 from Sample 4,
rows 2 to 30 except 16, 19, 20 and 22, which have no SRU response), computed by the same
code as the live app (`../mcp_server/erratum_annotator.py`), and checked equal to the live app's output for all 75 (rebuilt 2026-11-22). It has the
quick examples, the list of notices and **See all saved notices at once**. It cannot annotate pasted SRU XML;
for that, use the live page <https://mcp-erratum-note-7474654188777746.aws.databricksapps.com> (needs a NAL
Databricks account with `CAN USE` on the app). The **View record** links open Alma's SRU XML and need network
access.

Rebuild after changing the code or the saved responses (on Databricks, from this folder):
`python build_offline_demo.py`.
