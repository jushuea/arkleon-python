# Quality benchmark plan

The check cannot establish that the SEC archive is itself correct, that the corpus is complete, or anything about facts that were not drawn. Agreement is a comparison with the archived fields under the stated sampling and query rules. Neither a passing draw nor the aggregate comparison establishes any claim beyond that scope.

## Constants and quarter whitelist

```constants
SEED = 20261118
QUARTERS = 2009q2..2026q1
FILINGS_PER_QUARTER = 5
N = 340
ATTEMPT_CEILING = 6000
RESERVE = 200
ATTEMPTS_PER_PAGE = 3
EXTRA_PAGES_PER_FACT = 3
PAGE_LIMIT = 1000
PERIOD_WINDOW_DAYS = 370
CONFIDENCE = 0.95
ALLOWED_RATE_LIMITS = 60,300
```

| 68 quarters | Quarter | Quarter | Quarter |
| --- | --- | --- | --- |
| 2009q2 | 2009q3 | 2009q4 | 2010q1 |
| 2010q2 | 2010q3 | 2010q4 | 2011q1 |
| 2011q2 | 2011q3 | 2011q4 | 2012q1 |
| 2012q2 | 2012q3 | 2012q4 | 2013q1 |
| 2013q2 | 2013q3 | 2013q4 | 2014q1 |
| 2014q2 | 2014q3 | 2014q4 | 2015q1 |
| 2015q2 | 2015q3 | 2015q4 | 2016q1 |
| 2016q2 | 2016q3 | 2016q4 | 2017q1 |
| 2017q2 | 2017q3 | 2017q4 | 2018q1 |
| 2018q2 | 2018q3 | 2018q4 | 2019q1 |
| 2019q2 | 2019q3 | 2019q4 | 2020q1 |
| 2020q2 | 2020q3 | 2020q4 | 2021q1 |
| 2021q2 | 2021q3 | 2021q4 | 2022q1 |
| 2022q2 | 2022q3 | 2022q4 | 2023q1 |
| 2023q2 | 2023q3 | 2023q4 | 2024q1 |
| 2024q2 | 2024q3 | 2024q4 | 2025q1 |
| 2025q2 | 2025q3 | 2025q4 | 2026q1 |

## Population and archive parsing

The population consists of numeric data rows in the whitelisted SEC Financial Statement Data Sets quarterly archives whose accession appears in the submissions table from the same archive. Each archive is a separate stratum. The excluded earlier archive has no submissions, and later archives are outside scope. Orphan numeric rows fall outside the population because their accession does not occur in the submissions table of the same archive. The customer supplies the archives and their own Arkleon API key.

Archive tables are tab-separated and are read by their header names, with empty fields preserved, exact string content retained, and physical data-row order kept intact. Missing segments and co-registrant columns are read as empty strings. A numeric data row whose field count differs from its header has no readable accession, even when a substring of that row appears to be an accession. Such rows are counted and their physical indices are listed in the manifest summary, and they are excluded from the population. Their positions are preserved when subsequent rows are indexed. Preparation stops before any preparation output when a required header is missing, when an archive is unreadable, or when a source field cannot supply the required key and query dates. Malformed numeric values remain eligible for the source outcome check.

| Rule | Fixed value or operation |
| --- | --- |
| Archive name | `<quarter>.zip`, containing header-bearing, tab-separated `sub.txt` and `num.txt` |
| Included archives | Exactly the whitelist above |
| Earlier exclusion | `2009q1`: `0` submissions; outside the whitelist |
| Later exclusion | Every archive after `2026q1` |
| Population membership | A readable `num.txt` row with `adsh` in the same archive's `sub.txt` |
| Header lookup | Column names, never column positions |
| Missing optional columns | `segments = ""`; `coreg = ""` |
| Bad row width | Split count differs from header count: no readable `adsh`, outside population, counted and listed by archive and row index in manifest summary |
| Physical data-row index | `0`-based, header excluded, including bad-width data rows in the index sequence |
| Blank archive value | Empty field, represented as a null sentinel for comparisons |
| Valid archive decimal | Nonblank text accepted by `decimal.Decimal` and finite; all other nonblank values are malformed |

## Strata and deterministic draw

The seed in the constants block is used, and the specified hash inputs are used without added whitespace or line endings. Within each archive, eligible filings are ranked and the fixed allocation is selected without replacement. For each selected filing, its population rows are ranked and the first fact is selected. An accession that appears in more than one archive remains eligible separately within each archive. No other source of randomness is used. The eligibility count of every archive is checked before any preparation artifacts are written. If any archive cannot supply its allocation, preparation stops.

The draw is written once, in the fixed order, and the manifest bytes are pinned. Source evidence and the ranking inputs needed to reproduce each selection are preserved. The run reads the manifest and never performs a draw. A filing or fact is never replaced after selection, including when its source value is malformed, when its key has conflicting source values, when a query fails, or when paging ends inconclusively. The manifest summary is embedded in the first draw record, so every manifest line remains a draw.

| Operation | Fixed rule |
| --- | --- |
| Stratum | Each whitelisted archive separately |
| Eligible filings | Distinct `sub.txt.adsh` values having at least `1` population row in that archive |
| Preflight | Every archive must have at least `FILINGS_PER_QUARTER` eligible filings; otherwise preparation stops before writing any preparation artifact |
| Filing hash input | UTF-8 encoding of `"20261118\|<quarter>\|filing\|<adsh>"`; each escaped table pipe denotes a literal pipe with no backslash |
| Filing rank | Lowercase hexadecimal `sha256(input)`, ascending; ties by `adsh` string ascending |
| Filing selection | First `FILINGS_PER_QUARTER` distinct filings, without replacement within the archive |
| Fact hash input | UTF-8 encoding of `"20261118\|<quarter>\|fact\|<adsh>\|<row index>"`; literal pipes, row index in base `10` without leading zeros except `0` |
| Fact rank | Lowercase hexadecimal `sha256(input)`, ascending; ties by numeric row index ascending |
| Fact selection | First ranked population row of each selected filing |
| Manifest order | Chronological quarter order, then filing rank; draw IDs are consecutive integers starting at `0` |
| Replacement | Never, for any later outcome |
| Randomness | Only the specified hash ranking with `SEED` |

## Attempt budget and key admission

The allocation is the largest equal filing allocation across the whitelisted quarters that fits the request budget after the reserve under the specified worst case. Each fact can consume both initial query pages, the shared extra-page allowance, and all attempts on every page. The limit read has its own bounded attempt allowance. The ceiling assumes the daily quota shown in the budget table. This is a per-key budget, so other activity using the same key must be accounted for by the operator before starting.

| Quantity | Arithmetic |
| --- | --- |
| Base pages per fact | `2` |
| Worst-case attempts per fact | `(2 + EXTRA_PAGES_PER_FACT) * ATTEMPTS_PER_PAGE = (2 + 3) * 3 = 15` |
| Limit read allowance | `1 * ATTEMPTS_PER_PAGE = 3` |
| Chosen allocation | `68 * 5 = N = 340` |
| Chosen worst case | `340 * 15 + 3 = 5103` |
| Available budget after reserve | `ATTEMPT_CEILING - RESERVE = 6000 - 200 = 5800` |
| Budget comparison | `5103 <= 5800` |
| Next equal allocation | `68 * 6 = 408` |
| Next allocation's worst case | `408 * 15 + 3 = 6123 > 5800` |
| Ceiling assumption | `6000` attempts per UTC day, assuming a key with `10000` requests per day |

Before any fact is queried, the limit header is read using the specified companies request. Only a successful page envelope and a rate limit within the allowed set are accepted. A missing or unexpected limit stops the run as partial before any fact query. The allowed minute limits identify the standard and partner tiers with the daily quotas listed in the admission table. A key with another daily quota requires an operator-stated ceiling and a different frozen plan. The limit read and any retries are preserved in the attempt records.

| Admission item | Fixed rule |
| --- | --- |
| Limit read | `GET /v1/companies?limit=1`, with the customer's API key, before any fact query |
| Limit read budget | A single logical request, at most `ATTEMPTS_PER_PAGE` attempts across all continuations |
| Standard tier | `RateLimit-Limit = 60` per minute; server daily quota `10000` |
| Partner tier | `RateLimit-Limit = 300` per minute; server daily quota `100000` |
| Admitted header | Present integer `RateLimit-Limit` in `ALLOWED_RATE_LIMITS` on a successful, accepted limit-read response |
| Header rejected | Missing, malformed, or another value: `PARTIAL`, before any fact query |
| Limit read failure | `PARTIAL`, before any fact query; retain attempt history and remaining allowance |
| Different daily quota | Operator-stated ceiling and a different frozen plan required |

## Queries and paging

Query the drawn tag and company with a period-end window around the archive date. The filing-date query uses the archive filing date, and the day-before query subtracts a calendar day from that same date. The window bounds apply inclusively to the fact's period end. Send no other filters, so unit and period differences remain observable within the window. Match accession, segments, and co-registrant fields locally because the endpoint has no selectors for them. Send the day-before query only for the filing-date outcomes admitted in the outcome table.

| Parameter | Q-on | Q-before |
| --- | --- | --- |
| Method and endpoint | `GET /v1/facts` | `GET /v1/facts` |
| `as_of` | `sub.txt.filed`, parsed from `YYYYMMDD` and formatted `YYYY-MM-DD` | Same date minus `1` calendar day, formatted `YYYY-MM-DD` |
| `cik` | `int(sub.txt.cik)` | Same |
| `tag` | Drawn `num.txt.tag` | Same |
| `period_start` | `date(num.txt.ddate) - PERIOD_WINDOW_DAYS` calendar days, `YYYY-MM-DD` | Same |
| `period_end` | `date(num.txt.ddate) + PERIOD_WINDOW_DAYS` calendar days, `YYYY-MM-DD` | Same |
| Period-bound meaning | Inclusive lower and upper bounds on fact period end | Same |
| `limit` | `PAGE_LIMIT` | `PAGE_LIMIT` |
| Other filters | None: omit `unit`, `duration_quarters`, `taxonomy`, `form`, `concept_alias`, `attested`, `ticker`, and all other filters | Same |
| Initial `cursor` | Omitted | Omitted |
| Later `cursor` | Previous accepted page's opaque `next_cursor`; resend every initial parameter, including unchanged `as_of` | Same |
| Local-only selectors | No accession, `segments`, or `coreg` selector exists on this endpoint | Same |

The filing-date query is processed before the day-before query, and the shared extra pages are spent in that order. Each opaque next cursor is followed with the same query parameters and an unchanged cutoff date. Paging stops at the specified local match or at a null next cursor, and only a result set that ends in a null cursor establishes absence. A short or empty page that carries a non-null cursor remains a continuation. An envelope is rejected unless it is an object with a data list and a present next cursor that is either null or a non-empty string. Exhausted pages that yield neither a stopping match nor a complete result set are inconclusive.

| Paging rule | Fixed value or condition |
| --- | --- |
| Base allowance | `1` initial page for each query that is sent |
| Shared extra allowance | At most `EXTRA_PAGES_PER_FACT` additional logical pages across both queries |
| Extra-page priority | Q-on consumes extras first; Q-before receives only the remainder |
| Page allocation | Charge a logical page when first attempted; retries use that page's attempt allowance, not another page |
| Q-on early stop | First exact row encountered in page order and then row order, or accepted `next_cursor = null` |
| Q-before early stop | First returned row with `accession_id = drawn adsh`, or accepted `next_cursor = null` |
| Envelope acceptance | Successful HTTP response with JSON object, `data` list, and present `next_cursor` equal to null or a non-empty string |
| Short or empty page | Legal with non-null `next_cursor`; never evidence of absence |
| Complete search | Accepted result set ending with `next_cursor = null` |
| Exhausted extra pages | Without a stopping match or complete search: `INCONCLUSIVE_PAGES` |
| Failed page | `FAILED`, regardless of partial rows from earlier pages |

## Attempts, pacing, stops, and continuation

Every outbound attempt is counted and persisted before it is sent, including the limit read, each page, and each retry. The daily ceiling check is applied before each send, and state is preserved on every global stop. Retries are made only for the cases listed in the ordered attempt table, and only within the original page allowance. A failed page fails its query, and the failed query is counted and reported without replacement. A global authorization or daily-quota stop preserves pending work and does not discard earlier outcomes.

| Priority | Condition | Action |
| ---: | --- | --- |
| 1 | Before every outbound attempt, `attempts_in_current_UTC_day + 1 > ATTEMPT_CEILING` | Stop whole run as `PARTIAL`; do not send |
| 2 | HTTP `401` or `403` | Stop whole run as `PARTIAL`; preserve all state |
| 3 | HTTP `429` with raw body `error = quota_exceeded` | Stop whole run as `PARTIAL`; preserve all state |
| 4 | Network error or timeout | Retry within the page's remaining attempt allowance |
| 5 | HTTP `5xx` | Retry within the page's remaining attempt allowance |
| 6 | HTTP `429` with raw body `error = rate_limited` | Wait `Retry-After` seconds, then retry within the remaining allowance |
| 7 | Any other HTTP `4xx` | Fail page immediately |
| 8 | Successful response with invalid JSON or invalid page envelope | Retry within the remaining allowance |
| 9 | Other non-success HTTP response, including an unfollowed redirect | Fail page immediately |
| 10 | Retryable failure with no attempt allowance left | Fail page |

Requests go through a request layer that exposes the raw response body, the headers, and every send. Numeric tokens are parsed directly as Decimal, and the raw error code is inspected before exception mapping. The existing client's ordinary JSON decoding and error mapping are insufficient for these comparisons and for quota stops without adaptation. Hidden retries, redirects, and unbounded iteration are disabled. Attempts are spaced by the pacing formula, and an admitted rate-limit retry adds the full retry-after wait. If that wait is missing or unusable, the page fails. Credentials are kept out of all evidence records.

| Transport rule | Fixed value or operation |
| --- | --- |
| Per-page attempts | At most `ATTEMPTS_PER_PAGE`, including the initial send |
| Attempt counter | Increment and persist before each send, including limit read, retries, and every page |
| Raw number parsing | Decode JSON number tokens directly with `decimal.Decimal`; no intermediate float for values |
| Error inspection | Read raw JSON body's `error` before SDK exception mapping |
| Hidden sends | No automatic transport retry, SDK retry, redirect following, or automatic unbounded pagination |
| Rate header updates | Apply admission check to any present later `RateLimit-Limit`; an unrecognized value stops as `PARTIAL`; a missing later header retains the last admitted value |
| Pacing interval | `60 / (0.8 * RateLimit-Limit)` seconds between attempt starts |
| Bootstrap pacing | Use `min(ALLOWED_RATE_LIMITS) = 60` until limit read succeeds |
| Rate-limit wait | Add the full nonnegative finite `Retry-After` seconds to ordinary pacing; no sleep cap |
| Missing or malformed `Retry-After` on `rate_limited` | Fail page; do not invent a wait or resend immediately |
| Client transport timeout | `30` seconds per attempt |

A stopped run resumes the same manifest on a later UTC day. The run retains completed outcomes, accepted-page evidence, pending cursors, used pages, used attempts, and outstanding waits. Completed draws are never queried again, and a draw's allowances are never replenished. A new day resets only the daily counter. An interrupted send remains charged even if no response was captured. Exhaustion of a pending page's attempt allowance yields a failed query. The accepted limit read is reused. Its bounded request allowance is never renewed. No bound is reported until every manifest draw has a final outcome.

| State rule | Fixed behavior |
| --- | --- |
| Run status | `PARTIAL` while a stop leaves draws without final outcomes; complete only when every draw has an outcome |
| Failed query | Count and report `FAILED`; never omit or redraw |
| Global-stop response | Retain pending query and charge the attempt; resume only within unused page and attempt allowance; if exhausted, finalize as `FAILED` |
| Day rollover | Stop as `PARTIAL` at a UTC date change before another send; explicitly resume on the later UTC day |
| Resume | Same frozen plan, archives, manifest, cursors, accepted-page evidence, and query parameters |
| Daily counter | New UTC day starts a fresh daily attempt counter; cumulative and per-draw counters remain |
| Completed draws | Never queried again |
| Draw allowances | Used attempts and pages are never replenished |
| Limit read on resume | Resume the original request if allowance remains; do not allocate another limit-read request after acceptance or exhaustion |
| Interrupted send | Already charged; append an interrupted-attempt record if no response was captured; retry only within remaining allowance |
| Reporting gate | No bound until every draw has a final outcome |
| Runs per freeze | A fresh state for a frozen manifest is a new run; every run started under a freeze is reported with its start time, and no run is withdrawn or replaced by another; the tool cannot detect a run started in another results directory |

## Field comparisons and exact row key

An exact row agrees on every key field listed in the key table. Its value and filing fields are compared separately. Strings retain their original case and content. Only the stated dates, integers, optional null fields, and decimals are normalized. Decimal equality ignores insignificant trailing decimal zeros, and it never passes through a binary float. A null API value equals a blank source value and differs from a numeric source value. Multiple exact API rows are resolved by first encounter, without selecting whichever value would pass. The accession-matching rows are preserved as evidence.

| API field | Archive field | Comparison |
| --- | --- | --- |
| `accession_id` | `num.txt.adsh` | String equal |
| `tag` | `num.txt.tag` | String equal |
| `taxonomy` | `num.txt.version` | String equal |
| `period_end` | `num.txt.ddate` | Archive `YYYYMMDD` parsed as date `YYYY-MM-DD`, equal |
| `duration_quarters` | `num.txt.qtrs` | Integer equal |
| `unit` | `num.txt.uom` | String equal |
| `segments` | `num.txt.segments` | String equal; null read as empty string; absent archive column read as empty string |
| `coreg` | `num.txt.coreg` | String equal; null read as empty string; absent archive column read as empty string |
| `value` | `num.txt.value` | Raw JSON number token parsed with Python `decimal.Decimal`, archive text parsed with `decimal.Decimal`; Decimal equality, never floats; `1234.0000 = 1234`; null equals blank, null versus number differs |
| `filed` | `sub.txt.filed` | API date `YYYY-MM-DD` equals archive date parsed from `YYYYMMDD` |
| `cik` | `sub.txt.cik` | API integer equals archive integer |

| Key or tie rule | Definition |
| --- | --- |
| Exact row key | The `8` fields `accession_id`, `tag`, `taxonomy`, `period_end`, `duration_quarters`, `unit`, `segments`, `coreg`, with the comparisons above |
| Value and filing fields | Compared on the exact row, separately from the key |
| Multiple returned exact rows | Use the first exact row in accepted page order and row order; retain other rows from the drawn accession as evidence |
| Source duplicate scope | Every population row in the same archive with the drawn row's normalized exact key, across the entire archive |
| Duplicate value equality | Decimal equality for finite numbers, blank equals blank, blank differs from any number; malformed peer values do not establish a differing decimal pair |
| Non-object API row | Cannot match; retain it in the row count |
| Missing API key field | Cannot form an exact key; missing is not null |
| Malformed API comparison value | Not equal; no coercion from a numeric string or boolean to a JSON number |
| Missing or malformed API filing field | Not equal |

## Outcomes

The filing-date outcome is assigned exactly once, using the stated precedence, and the drawn source value and archive duplicate key are checked before any query is run. Duplicate keys with equal decimal values do not trigger the duplicate outcome. Unit and period categories require a complete search with no exact row. Every finalized draw receives exactly one day-before outcome, and where the filing-date outcome does not admit that query, that day-before outcome is not-sent. Any returned row from the drawn accession establishes presence before the filing date, regardless of its other fields.

| Q-on order | Code | Definition |
| ---: | --- | --- |
| 1 | `SOURCE_MALFORMED` | Drawn archive value is neither blank nor a valid finite decimal; send no query |
| 2 | `SOURCE_DUPLICATE` | Drawn exact key occurs more than once in the archive population with differing values under the source duplicate comparison; send no query |
| 3 | `FAILED` | A required Q-on page fails |
| 4 | `MATCH` | Exact row found, value equal, `filed` and `cik` equal |
| 5 | `VALUE_DIFFERS` | Exact row found, value not equal, regardless of filing-field equality |
| 6 | `FILING_FIELDS_DIFFER` | Exact row found, value equal, `filed` or `cik` not equal |
| 7 | `UNIT_DIFFERS` | Complete result set, no exact row, but a row has equal `accession_id`, `tag`, `taxonomy`, `period_end`, `duration_quarters`, `segments`, `coreg`, and another unit |
| 8 | `PERIOD_DIFFERS` | Complete result set, no exact row or unit-difference outcome, but a row has equal `accession_id`, `tag`, `taxonomy`, `unit`, `segments`, `coreg`, equal value, and another `period_end` or `duration_quarters` |
| 9 | `ABSENT` | Complete result set with no exact row and neither preceding difference category |
| 10 | `INCONCLUSIVE_PAGES` | Pages exhausted before an exact row or a complete result set |

| Q-before code | Definition |
| --- | --- |
| `NOT_SENT` | Q-on is outside `MATCH`, `VALUE_DIFFERS`, `FILING_FIELDS_DIFFER`; no Q-before request |
| `PRESENT_BEFORE_FILING_DATE` | Any returned row has `accession_id` string-equal to drawn `adsh`; no other field equality required |
| `CLEAN` | Complete result set, no returned row from drawn accession |
| `INCONCLUSIVE_PAGES` | Page allowance exhausted before a row from drawn accession or a complete result set |
| `FAILED` | A required Q-before page fails |

## Estimands, denominators, and bounds

The filing-date check passes only on a match. The point-in-time check passes only when that match holds and a day-before query comes back clean, which removes the vacuous pass from an accession missing on both dates. For each headline, every non-pass counts as a mismatch across every draw, including source issues, failures, and inconclusive paging. Beside each headline, report the resolved-only fraction, computed after removing that headline's specified exclusions from both the numerator and the denominator. An empty resolved set has no fraction or bound. Report all outcome counts, including failures and exclusions, separately from these summary fractions.

| Sentence | Pass predicate | Headline denominator | Resolved-only exclusions |
| --- | --- | --- | --- |
| S1: filing-date match | `Q-on = MATCH` | All `N` draws | Q-on in `FAILED`, `INCONCLUSIVE_PAGES`, `SOURCE_MALFORMED`, `SOURCE_DUPLICATE` |
| S2: point in time | `Q-on = MATCH AND Q-before = CLEAN` | All `N` draws | Same Q-on exclusions, plus Q-before in `INCONCLUSIVE_PAGES`, `FAILED` |

| Quantity | Definition |
| --- | --- |
| Headline trials | `m = N` |
| Headline non-passes | `x = sum(not pass(draw) for every manifest draw)` |
| Headline mismatch fraction | `x / m` |
| Resolved set | `R = {draw: no applicable resolved-only exclusion}` |
| Resolved trials | `m_r = len(R)` |
| Resolved non-passes | `x_r = sum(not pass(draw) for draw in R)` |
| Resolved mismatch fraction | `x_r / m_r` when `m_r > 0`; undefined otherwise |
| Resolved empty set | If `m_r = 0`, report `<U_r>` and resolved fraction as `undefined`, without a bound |

The one-sided Clopper-Pearson upper bound is computed exactly under the binomial model by bisection of the exact rational binomial cumulative probability. The procedure keeps both a lower and an upper root bracket, and the bound is rounded upward at the precision given in the bound table. Where a decimal rounding boundary must be decided, the comparison is made in exact rational arithmetic, including the case of equality at the boundary. The stated endpoint cases apply. The reciprocal approximation is never labeled as exact. The same computation is applied separately to the headline and to each nonempty resolved set. No bound is reported while any draw remains pending.

| Bound element | Formula or operation |
| --- | --- |
| Confidence | Exact one-sided `CONFIDENCE = 0.95` Clopper-Pearson upper bound under the binomial model |
| Tail target | `alpha = 1 - CONFIDENCE = Fraction(1, 20)` |
| Domain | Integers `0 <= x <= m`, `m > 0`; solve for `p` in `[0, 1]` |
| Exact CDF | `F(p; x, m) = sum(Fraction(comb(m, k)) * p**k * (1 - p)**(m - k) for k in range(x + 1))` |
| Root for `x < m` | `F(p; x, m) = alpha` |
| Bisection start | `lo = Fraction(0); hi = Fraction(1)` |
| Bisection step | `mid = (lo + hi) / 2`; if `F(mid) > alpha`, set `lo = mid`; if `F(mid) < alpha`, set `hi = mid`; equality gives the exact root |
| Exact evaluation | Python `fractions.Fraction` for every candidate probability and CDF term; integer binomial coefficients; no float CDF |
| Upward rounding | `ceil4(0) = 0`; for positive `p`, find integer `e` by exact comparisons such that `10**e <= p < 10**(e + 1)`; `step = 10**(e - 3)` as an exact rational; `ceil4(p) = ceil(p / step) * step` |
| Bisection termination | Stop when both bracket endpoints have the same upward-rounded `4`-significant-digit value; if a rounding boundary lies inside the bracket, evaluate its CDF exactly and return it when equality holds; otherwise continue |
| Reported upper bound | `U = ceil4(p)`; retain `4` significant digits; repeat with `(x_r, m_r)` for `U_r` if `m_r > 0` |
| No non-passes | At `x = 0`, exact bound `p = 1 - 0.05**(1 / m)`; rational-CDF bisection still supplies the reported bound |
| Every draw non-passing | At `x = m`, `p = 1`, reported as `1.000` |
| Approximation only | `3 / m` approximates the `x = 0` bound; never label it exact |

The exact binomial calculation does not establish binomial sampling assumptions. Fixed allocations by quarter and sampling filings without replacement are a stratified design. They do not guarantee independent and identically distributed Bernoulli outcomes. The bound is a binomial-model summary, and it carries no design-based coverage claim for the entire corpus. Resolved-only exclusion can depend on outcomes, and it does not repair this limitation. The filing allocation and the single fact per filing also prevent interpretation as a fact-weighted corpus estimate.

## Result sentence templates

The filing-date statement and the point-in-time statement are reported separately, each under its own pass predicate, exclusions, and bounds. The sample holds equal numbers of filings in each populated quarter, with one fact drawn per filing. The rate is weighted by filing, not by fact, and it is never a share of all facts in the corpus. Both statements cover only facts drawn by this procedure. Template fields are populated only after every draw has reached a final outcome, and an undefined resolved bound is kept when nothing resolves.

### S1: Filing-date match

```text
For the filing-date match check, <x> of <m> draws were non-passes (mismatch fraction <x>/<m>; exact one-sided binomial-model confidence <confidence> upper bound <U>); the resolved-only figure is <x_r> of <m_r> (mismatch fraction <x_r>/<m_r>; upper bound <U_r>, undefined if no draws resolve), with equal filings per populated quarter and one fact per filing, so the rate is filing-weighted and not fact-weighted, is never a share of all facts in the corpus, and covers facts drawn this way only.
```

### S2: Point in time

```text
For the point-in-time check requiring a filing-date MATCH and a day-before CLEAN outcome, <x> of <m> draws were non-passes (mismatch fraction <x>/<m>; exact one-sided binomial-model confidence <confidence> upper bound <U>); the resolved-only figure is <x_r> of <m_r> (mismatch fraction <x_r>/<m_r>; upper bound <U_r>, undefined if no draws resolve), with equal filings per populated quarter and one fact per filing, so the rate is filing-weighted and not fact-weighted, is never a share of all facts in the corpus, and covers facts drawn this way only.
```

## Limits of the day-before query

A day-before query that comes back clean can arise for reasons other than the intended temporal behavior. Its company, tag, or period window can exclude the accession's rows. The API's filing date for the accession can differ from the submissions table. The accession can be absent altogether, which is why the point-in-time pass requires a filing-date match first. The query covers only the drawn tag within its period window, not every fact in the filing. The check accepts the server's null next cursor as proof that the day-before result set is complete, so a truncated result that the server reports as complete would also come back clean. The check therefore cannot rule out behavior outside those filters, and it cannot establish when an entire filing became available.

## Records outside the repository

All runtime records are written to the directory the user names, outside the repository. The manifest and archive digests are preserved. Every outbound attempt, every final draw outcome, and the resumable counters are preserved. The raw error code is recorded before client exception mapping takes place. The distinction between an absent cursor field and a present null cursor is retained. Returned rows from the drawn accession are saved, and their decimal values are stored as strings. Unavailable response fields are kept null, and no evidence is invented to fill them. The attempt reservation is persisted before a request is sent. Interrupted reservations are reconciled on continuation, so that each send remains represented once.

| Record | Required content |
| --- | --- |
| `manifest.jsonl` | Exactly `1` line per draw, in draw order: draw ID, quarter, archive digest, row index, raw source row fields, normalized key and value, `sub.txt` filing fields, both query parameters, and filing/fact ranking digests; first draw also carries `manifest_summary` with per-archive population and eligible-filing counts and counts plus row-index lists of bad-width rows |
| `manifest.sha256` | SHA-256 of exact `manifest.jsonl` bytes |
| `archives.sha256` | SHA-256 of every whitelisted zip, in whitelist order, paired with its archive filename |
| `results.jsonl` | Exactly `1` row per outbound HTTP attempt: draw ID, query, page, attempt, UTC time, HTTP status, raw error code, all `RateLimit-*` headers, whether `next_cursor` was present, row count, and all returned rows whose `accession_id` equals drawn `adsh`, with decimal values as strings; also retain `Retry-After`, returned cursor, and failure reason |
| Limit-read result | `draw_id = null`, `query = LIMIT_READ`; same attempt schema, accession rows empty |
| No captured response | Status, unavailable headers, cursor presence, and row count are null, not invented; record network, timeout, or interruption reason |
| `outcomes.jsonl` | Exactly `1` final row per draw: Q-on and Q-before outcomes, compared fields, selected exact row or difference evidence, attempts/pages used, and both pass predicates |
| `state.json` | Daily and cumulative attempt counters, current UTC day, limit-read allowance and admission, per-draw/per-query page and attempt usage, completed draw IDs, pending draw/query/page/cursor, accumulated search evidence, required wait deadline, and stop reason |
| Numeric representation | Decimal values serialized as strings; structural counters remain integers |
| Authentication | Customer supplies their own key; key is never written to records |

## Pinning and freeze order

The final plan is pinned before any draw or request. Preparation checks the pin before it produces the immutable manifest and the archive hashes. The run refuses changed plan bytes, changed manifest bytes, or changed archive hashes. The freeze record is committed after the plan and the code and before any API request. Nothing in the repository changes from that freeze through the last request, including continuations. Runtime records and state remain outside the repository.

The freeze record identifies the plan commit, the plan digest, the manifest digest, the archive-digest-file digest, the seed, the draw count, and the attempt ceiling. The plan digest file sits beside the plan. Freeze commits are never amended, rebased, or squashed. Any change that affects the frozen method requires a separate plan and freeze before a new draw or request.

| Order | Artifact or action | Rule |
| ---: | --- | --- |
| 1 | Complete plan and benchmark code | Plan and code complete; no draw or API request yet |
| 2 | `PLAN.sha256` beside `PLAN.md` | SHA-256 of the final `PLAN.md` bytes; pin before any draw or request; commit plan, code, and pin |
| 3 | Preparation | Check pinned plan, whitelist, archive parsing, and eligible-filing counts before writing any preparation outputs; create the immutable ordered manifest and archive hashes outside the repository; no API request |
| 4 | `FREEZE.md` | Commit after the plan and code; record plan commit, `PLAN.md` SHA-256, manifest SHA-256, SHA-256 of `archives.sha256`, `SEED`, `N`, and `ATTEMPT_CEILING` |
| 5 | Run admission | Refuse to run if plan digest differs from `PLAN.sha256` or freeze record; refuse changed manifest or archive digests |
| 6 | Requests and any continuation | Nothing in the repository changes between the freeze commit and the last request; all runtime writes go to the user-named external directory |
| 7 | History | Never amend, rebase, or squash freeze commits |
