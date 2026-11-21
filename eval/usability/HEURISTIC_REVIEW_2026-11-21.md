# Expert walkthrough, 2026-11-21 (n=0 target users; NOT a usability study)

No librarian took part. The four librarian tasks below were walked through on the live apps through the demo
pages' JSON APIs and the MCP tool replies (the same text the pages show), recorded in
[`../results/`](../results/README.md). The visual layout of the pages was not reviewed. It finds problems a
librarian would likely meet; it cannot say how often, or how much they matter. Sessions with librarians are
specified in [`PROTOCOL.md`](PROTOCOL.md) and have not been held.

## Tasks walked through

| # | Task | Path | Outcome in the walkthrough |
| --- | --- | --- | --- |
| T1 | Get the SRU search URL for one correction notice | SRU demo page (`/api/sru-url`) | Done; one URL in 3.77 s |
| T2 | Find out why a notice gets no URL | MCP tool with a bare `Correction` | The reply says the notice does not name one original article |
| T3 | Get the annotated title for a saved notice | Erratum demo page (`/api/annotate`), row 43 | Done; status, both MMS IDs, note and annotated title returned |
| T4 | Check a whole batch | Erratum demo page (`/api/annotate-all`) | Done; 48 rows with a status each |

## Findings

**U1: the two pages are separate.** After T1 the librarian must run the SRU search in Alma, save the response and
switch to the second page, which has its own address. Suggestion: link the pages and say
what to do with the SRU response.

**U2: the erratum page only works on saved responses or pasted XML.** A librarian cannot paste the SRU URL from
T1. This follows from the missing live Alma access (USDA eAuth), not from the page.

**U3: error messages say what to do (positive).** Every rejected input in the errors suite returned a sentence with
the next step, for example "Paste the complete SRU searchRetrieveResponse, from its first line to its last."
The trailing `[error <category>, id ...]` is for support and may look technical to a librarian.

**U4: every notice gets a status (positive).** The 48 saved notices returned `ready` (32), `already_annotated` (14)
and `no_original` (2). The codes are short and readable, but use underscores; the page could show them as words.

**U5: the agent path asks for approval on every MCP call.** In the `agent-erratum-annotator` chat the
`mcp-erratum-note` tools need approval each time ([agent configuration](../../erratum-annotator/agent/README.md)). This is a safety feature, but it adds clicks in a batch.

**U6: response time.** About 4 s for a URL and under 0.1 s for an annotation on the page; both feel immediate for
one notice. For hundreds of notices the SQL functions are the better path.
