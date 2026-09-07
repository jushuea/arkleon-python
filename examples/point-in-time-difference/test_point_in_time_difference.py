import json
import os
from pathlib import Path

import nbformat
from nbclient import NotebookClient

os.environ.setdefault("SEC_EDGAR_USER_AGENT", "arkleon point-in-time example (founder@arkleon.com)")


def test_point_in_time_difference():
    nb = nbformat.read(Path(__file__).with_name("point_in_time_difference.ipynb"), as_version=4)
    client = NotebookClient(nb, timeout=180, kernel_name="python3")
    client.execute()

    result_line = next(
        line.strip()
        for cell in nb.cells
        if cell.cell_type == "code"
        for output in cell.get("outputs", [])
        if output.output_type == "stream"
        for line in output.text.splitlines()
        if line.startswith("RESULTS_JSON=")
    )
    results = json.loads(result_line.removeprefix("RESULTS_JSON="))
    by_cik = {row["cik"]: row for row in results}

    assert by_cik[4447]["as_of_value"] == -2000000
    assert by_cik[4447]["as_of_filed"] == "2015-08-07"
    assert by_cik[4447]["today_value"] == 8000000
    assert by_cik[4447]["today_filed"] == "2016-08-05"
    assert by_cik[4447]["differs"] is True

    assert by_cik[3570]["as_of_value"] == 2000000
    assert by_cik[3570]["as_of_filed"] == "2022-02-24"
    assert by_cik[3570]["today_value"] == -8000000
    assert by_cik[3570]["today_filed"] == "2023-02-23"
    assert by_cik[3570]["differs"] is True

    assert sum(row["differs"] for row in results) == 2
