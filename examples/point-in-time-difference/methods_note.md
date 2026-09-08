# Filing Dates and Point-in-Time Financial Data

Financial facts have at least two relevant temporal coordinates: the reporting period they describe and the filing date on which they enter the public record. This note distinguishes those coordinates and describes a point-in-time reading rule. A compact example using Apple's SEC-filed Assets observations illustrates why a period identifier alone does not determine the value available to a historical reader. The discussion is a methodological starting point, not a classification of the reasons for differences between filings.

## 1. Temporal model and information availability

The reporting-period end identifies the economic interval or balance-sheet date to which a fact refers. The filing date identifies when the filing containing that observation became available. These dates answer different questions. A fact describing an earlier period can appear in a substantially later filing, so its period end cannot establish that it was knowable at the earlier date.

The core rule is that `as_of` filters on the filing date, never on the period a fact describes. An observation is eligible only if its filing date is on or before the requested cutoff. A separate period selection can identify the subject of the query, but it does not replace this availability condition. Consequently, a historical query cannot observe information from filings that did not yet exist at its cutoff. This separation makes a point-in-time read faithful to what was knowable at the time, within the records represented by the data source and the date-level resolution of the rule.

## 2. One period, four filing observations

The companion script, `apple_point_in_time.py`, selects Apple (CIK 320193), the `us-gaap` tag `Assets`, and the reporting-period end 2008-09-27. It restricts the selection to observations without segment or co-registrant qualifiers and orders the results by filing date. Its four expected (filing date, value) observations are:

| Filing date | Assets, as filed (USD) |
| --- | ---: |
| 2009-07-22 | 39,572,000,000 |
| 2009-10-27 | 39,572,000,000 |
| 2010-01-25 | 36,171,000,000 |
| 2010-10-27 | 36,171,000,000 |

The evidence supports a narrow description: the as-filed value for the same period changed between filings. At a cutoff of 2009-10-27, the listed 2009 observations are eligible and carry 39,572,000,000; neither listed 2010 observation is eligible. The filings dated in 2010 carry 36,171,000,000 for that same period. These are SEC-filed figures, presented as filed. The comparison does not establish why the values differ. The script exhibits the filing-date evidence rather than directly executing an `as_of` query.

## 3. Source and corpus boundaries

The free layer is best-effort against live SEC EDGAR and reflects only what SEC currently serves. Applying a historical filing-date cutoff to that source does not establish that today's available records constitute a complete reconstruction of an earlier source state. The availability rule and the coverage of the underlying source are separate methodological conditions.

The paid layer is a fixed certified corpus through 2026q1. Its fixed scope must not be extended by implication to later filings or to material outside that corpus. Neither layer warrants conclusions beyond its stated boundary.

## 4. Toward a reproducible research record

A claim dated to a point in time is only checkable if the supporting data can be read as of that date. Recording the company, tag, period, filing-date cutoff, and source or corpus boundary makes that temporal premise explicit. This note supplies the seed of a fuller treatment of how such records can support research reproducibility without confusing the period described with the information available.
