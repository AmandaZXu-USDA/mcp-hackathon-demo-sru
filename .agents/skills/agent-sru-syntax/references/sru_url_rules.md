# SRU URL rules (agent-sru-syntax)

Source of truth: the Unity Catalog Python function `users.amanda_xu.build_sru_url(correction_title STRING) RETURNS STRING`
(deterministic). Read it with `DESCRIBE FUNCTION EXTENDED users.amanda_xu.build_sru_url` before changing these rules.

## 1. URL format

Template (one line, no spaces or line breaks; replace `<title>` with the percent-encoded title):

```
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22<title>%22%20and%20alma.local_field_912%3D%22Article%22
```

Working example, for the title "The cardiovascular effects of shechita in cattle: a systematic review shows the fallacies that vertebral artery will preserve cerebral blood flow and false aneurysms occur in severed carotid arteries":

```
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22The%20cardiovascular%20effects%20of%20shechita%20in%20cattle%3A%20a%20systematic%20review%20shows%20the%20fallacies%20that%20vertebral%20artery%20will%20preserve%20cerebral%20blood%20flow%20and%20false%20aneurysms%20occur%20in%20severed%20carotid%20arteries%22%20and%20alma.local_field_912%3D%22Article%22
```

* Base is **production** (`nal.alma...`). The sandbox base `nal-psb.alma...` was replaced on 2026-11-18.
* No `maximumRecords` parameter.
* The query is CQL: `alma.title="<title>" and alma.local_field_912="Article"`.
* Percent-encode every character outside unreserved (`quote`, `safe=""`): space -> `%20`, `"` -> `%22`, `=` -> `%3D`,
  `(` -> `%28`, `)` -> `%29`.
* Replace any `"` or `\` inside the title with a space (they would end the CQL quoted term), then collapse whitespace.
* Return an empty string when no title remains.

## 2. Title extraction (in order)

| Case | Example input | Result | Rule name |
| --- | --- | --- | --- |
| Empty input | `""` | blank | `empty` |
| Issue-level notice | `Errata for articles ...`, `Corrections to Taxon 72(3)` | blank | `issue-level notice (no single article)` |
| Bare notice | `Correction` | blank | `bare notice (no title)` |
| Prefix + colon / dash | `Correction: <title>`, `Corrigendum - <title>` | `<title>` | `prefix removed` |
| Prefix + quotes | `Correction to “<title>”` | text inside the quotes | `prefix removed + quotes/citation removed` |
| `Correction for <authors>, <title>` | `Correction for Kuo and Chang, <title>` | `<title>` | `prefix + cited authors removed` |
| Quoted full citation | `Correction to “A B, C D, and E F. Title. Journal. ...”` | `Title` | `quoted citation: authors/journal removed` |
| Bibliographic corrigendum | `Corrigendum: Smith J, Lee K (2023) Title. Journal 12(3): 45-67. https://doi.org/...` | `Title` | `bibliographic: authors/year/journal/DOI removed` |
| Trailing citation | `... by Lee et al. Journal 2024;27(6):488-501`, trailing DOI, trailing `[...]` | title without the tail | `prefix removed + trailing citation removed` |
| Notice suffix | `<title>: Correction`, `<title>/Correction` | `<title>` | `notice suffix removed` |
| No notice wording | `<title>` | unchanged | `no correction prefix (kept as is)` |

Recognised prefixes (case-insensitive, optional `First/Second/Third` and `Publisher('s)`/`Author(s)'`):
`Correction(s)`, `Corrigendum/Corrigenda`, `Erratum/Errata`, `Addendum/Addenda`, `Addition`,
`(Editorial) Expression of Concern`, `Corrected and Republished`, `Correspondence`, optionally followed by
`to | of | for | in | on | from` and `Supplement`. Repeated prefixes (`Correction: Correction: <title>`) are all removed.

Guard against false positives: a prefix is stripped only if it is followed by `:`, a dash, a quote, `[`, the end
of the string, or the connector `to`/`for`. So a real title such as `Correction of hypocalcemia in ...` is kept.

## 3. Normalisation (after extraction)

* Unicode NFC.
* Dashes `‐ ‑ ‒ – — −` -> `-`; curly single quotes/primes -> `'`; curly double quotes -> `"`.
* Non-breaking/thin spaces -> space; soft hyphen, zero-width space and `¬` removed.
* Strip surrounding `"` and trailing ` .`.

## 4. Known differences from the older reference spreadsheet

`Correction-Sample2-1494-Extracted-Titles-FINAL.xlsx` (`SRU_Full_URL`) was built with the sandbox base, `maximumRecords=50`,
and some punctuation stripped (for example `Solastalgia Scale SOS` vs `Solastalgia Scale (SOS)` from the current rules).
Compare the decoded `alma.title` term, not whole URLs.
