# Title extraction (Part 1)

`erratum_title_extractor.py` reads an Alma export of correction notice records, extracts the original article
title from each notice title, and writes a workbook with the SRU search URL for each one.

## Run it

```bash
pip install pandas openpyxl
python erratum_title_extractor.py Correction-Sample2-1494-20261021.xlsx
# -> Correction-Sample2-1494-20261021-Extracted-Titles.xlsx
```

Options: `-o OUTPUT.xlsx` for the output path, `--sheet NAME` for a sheet other than the first.

The input needs `Title` and `MMS ID` columns; other columns are ignored. Paths can be local, `/Volumes/...` or
`/Workspace/...`; on Databricks the script falls back to the Databricks SDK when a path cannot be opened directly.

In a Databricks notebook, install `openpyxl` first (`%pip install openpyxl`), then either run the script with
`%sh python erratum_title_extractor.py <input>` or import it and call `process()` on a DataFrame:

```python
import pandas as pd
import erratum_title_extractor as ete

out = ete.process(pd.DataFrame({"Title": ["Correction: <title>"], "MMS ID": ["991..."]}))
```

## Output (sheet "Extracted Titles")

| Column | Name | Contents |
| --- | --- | --- |
| A | `erratumn_article_title` | Correction notice title, as exported |
| B | `extracted_title` | Original article title after the extraction rules |
| C | `erratum_MMSID` | MMS ID of the correction notice record |
| D | `extracted_title_clean` | Extracted title after normalisation (dashes, quotes, spaces) |
| E | `SRU_Query_Syntax` | CQL query: `alma.title="<title>" and alma.local_field_912="Article"` |
| F | `SRU_Full_URL` | Full SRU searchRetrieve URL on NAL Alma production |
| G | `extraction_rule` | QA column: which rule produced the title |

Columns E and F are blank for bare and issue-level notices, which name no single article.

The rules, with an example for each, are in
[`sru_url_rules.md`](../sru-syntax-mcp/.agents/skills/agent-sru-syntax/references/sru_url_rules.md).

## Relationship to the Unity Catalog function

The Unity Catalog function `users.amanda_xu.build_sru_url` embeds the same extraction, normalisation and URL
code, and is the source of truth used by the agent and the MCP server. On the 1,494-record sample
(2026-11-18) this script and the function give the same `SRU_Full_URL` for every record, and columns B, D and G
match `Correction-Sample2-1494-Extracted-Titles-FINAL.xlsx`.

If you change the rules here, update the function too (and the reverse), then re-check both on the sample.

The older FINAL workbook's `SRU_Full_URL` column was built with the sandbox host (`nal-psb`) and
`maximumRecords=50`; this script uses production and no `maximumRecords`, as the function does.
