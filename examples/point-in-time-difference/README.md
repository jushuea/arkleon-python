# Point-in-time difference

This example shows the same SEC figure pulled two ways for the same reporting period, once as it stands today and once as of a historical filing date, side by side with the filing dates that produced each. It is a data-integrity demonstration, not a strategy result.

Install: `pip install -r requirements.txt`

Set `SEC_EDGAR_USER_AGENT` to your own contact string because SEC requires it for automated access.

Runtime: a few seconds. It makes live requests to SEC EDGAR.

Run:

`jupyter nbconvert --to notebook --execute point_in_time_difference.ipynb --output executed.ipynb`

Test:

`pytest -q test_point_in_time_difference.py`

The corpus contains 426,003 filings, 181,350,662 facts, 16,811 companies, 69 quarters (2009q1 to 2026q1).
