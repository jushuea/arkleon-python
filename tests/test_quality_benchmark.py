"""Network-free tests of the frozen archive comparison method."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import zipfile

import httpx
import pytest

MODULE = Path(__file__).resolve().parents[1] / 'examples' / 'quality-benchmark' / 'benchmark.py'
REAL_PLAN = MODULE.with_name('PLAN.md')
FAKE_KEY = 'ak' + '_' + 't' * 24


@pytest.fixture
def bench(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('quality_benchmark_under_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The run's repository-cleanliness check sees an isolated synthetic root.
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'repo' / 'examples' / 'quality-benchmark' / 'benchmark.py'))
    monkeypatch.setenv('ARKLEON_API_KEY', FAKE_KEY)

    def forbidden(*args, **kwargs):
        raise AssertionError('Network access is forbidden in benchmark tests')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    # Virtual wall and monotonic clocks make every wait observable without sleeping.
    clock = SimpleNamespace(now=datetime(2026, 1, 1, tzinfo=timezone.utc), monotonic=0.0, sleeps=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += timedelta(seconds=seconds)
        clock.monotonic += seconds

    monkeypatch.setattr(module, 'utcnow', lambda: clock.now)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock.monotonic)
    monkeypatch.setattr(module.time, 'sleep', sleep)
    module.test_clock = clock
    return module


def write_plan(tmp_path, **changes):
    values = dict(SEED=17, QUARTERS='2020q1..2020q2', FILINGS_PER_QUARTER=2, N=4,
                  ATTEMPT_CEILING=80, RESERVE=5, ATTEMPTS_PER_PAGE=3,
                  EXTRA_PAGES_PER_FACT=3, PAGE_LIMIT=7, PERIOD_WINDOW_DAYS=370,
                  CONFIDENCE='0.95', ALLOWED_RATE_LIMITS='60,300')
    values.update(changes)
    path = tmp_path / 'PLAN.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    text = '# Synthetic plan\n\n```constants\n'
    text += ''.join(f'{key} = {value}\n' for key, value in values.items()) + '```\n'
    for name in ('S1', 'S2'):
        text += f'\n```text\n{name}: <x> of <m>, <U>; <x_r> of <m_r>, <U_r>; <confidence>.\n```\n'
    path.write_text(text, encoding='utf-8')
    return path


def archives(tmp_path, quarters=('2020q1', '2020q2'), *, optional=True, rows=None, junk=False):
    directory = tmp_path / 'archives'
    directory.mkdir(exist_ok=True)
    header = ['adsh', 'tag', 'version', 'ddate', 'qtrs', 'uom', 'value']
    if optional:
        header += ['segments', 'coreg']
    for quarter in quarters:
        submissions = 'adsh\tcik\tfiled\n' + ''.join(f'filing-{i}\t{i + 10}\t20200515\n' for i in range(6))
        data = []
        for i in range(6):
            if rows is None:
                source_rows = [dict(tag=f'Tag{j}', value=str(1000 + i * 10 + j)) for j in range(3)]
            else:
                source_rows = rows(i)
            for supplied in source_rows:
                row = dict(adsh=f'filing-{i}', tag='Revenue', version='us-gaap/2020',
                           ddate='20200331', qtrs='1', uom='USD', value='1234.0000', segments='', coreg='')
                row.update(supplied)
                data.append('\t'.join(row[field] for field in header))
        if junk:
            orphan = dict(zip(header, data[0].split('\t')))
            orphan['adsh'] = 'orphan'
            data.insert(0, '\t'.join(orphan[field] for field in header))
            data.insert(1, 'bad\twidth')
        with zipfile.ZipFile(directory / f'{quarter}.zip', 'w') as archive:
            archive.writestr('sub.txt', submissions)
            archive.writestr('num.txt', '\t'.join(header) + '\r\n' + '\r\n'.join(data) + '\r\n')
    return directory


def setup_run(bench, tmp_path, *, rows=None, plan_changes=None):
    path = write_plan(tmp_path / 'method', **(plan_changes or {}))
    c = bench.load_constants(path)
    bench.hash_plan(c)
    source = archives(tmp_path, c.QUARTERS, rows=rows)
    handoff = tmp_path / 'handoff'
    bench.prepare(c, source, handoff)
    bench.freeze(c, handoff, 'a' * 40)
    return c, handoff, bench.records(handoff / 'manifest.jsonl')


def api_row(draw, **changes):
    row = dict(accession_id=draw['adsh'], tag=draw['tag'], taxonomy=draw['version'],
               period_end=draw['ddate'], duration_quarters=Decimal(draw['qtrs']),
               unit=draw['uom'], segments=draw['segments'], coreg=draw['coreg'],
               value=Decimal(draw['value']) if draw['value'] else None,
               filed=draw['filed'], cik=Decimal(draw['cik']))
    row.update(changes)
    return row


def encode_raw(value):
    # Emit Decimal tokens as JSON numbers, preserving all source digits.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + ':' + encode_raw(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(encode_raw(v) for v in value) + ']'
    return json.dumps(value)


def page(rows=None, cursor=None, *, status=200, headers=None, error=None):
    body = {'error': error} if error else {'data': rows or [], 'next_cursor': cursor}
    return httpx.Response(status, content=encode_raw(body).encode(),
                          headers={'RateLimit-Limit': '60', **(headers or {})})


def inject(bench, monkeypatch, handler):
    calls = []

    def capture(request):
        calls.append(request)
        return handler(request)

    def factory(hook):
        return httpx.Client(timeout=30.0, follow_redirects=False,
                            transport=httpx.MockTransport(capture), event_hooks={'response': [hook]})

    monkeypatch.setattr(bench, 'make_http_client', factory)
    return calls


def scripted(bench, monkeypatch, responses):
    iterator = iter(responses)
    return inject(bench, monkeypatch, lambda request: next(iterator))


def one_draw(bench, tmp_path, monkeypatch, responses, *, rows=None):
    c, handoff, draws = setup_run(bench, tmp_path, rows=rows)
    first = responses(draws[0])
    calls = scripted(bench, monkeypatch, [page(), *first, *[page() for _ in draws[1:]]])
    assert bench.run(c, handoff) == 0
    assert bench.audit(c, handoff) == 0
    return bench.records(handoff / 'outcomes.jsonl')[0], calls, handoff, draws


def test_real_constants_and_sizing(bench):
    c = bench.load_constants(REAL_PLAN)
    worst = (2 + c.EXTRA_PAGES_PER_FACT) * c.ATTEMPTS_PER_PAGE
    assert c.N == 340 == c.FILINGS_PER_QUARTER * len(c.QUARTERS)
    assert c.N * worst + c.ATTEMPTS_PER_PAGE == 5103 <= 5800
    assert (c.FILINGS_PER_QUARTER + 1) * len(c.QUARTERS) * worst + c.ATTEMPTS_PER_PAGE == 6123 > 5800
    assert c.CONFIDENCE == Fraction(95, 100)
    assert c.QUARTERS[0] == '2009q2' and c.QUARTERS[-1] == '2026q1'


def test_wrong_n_refused(bench, tmp_path):
    with pytest.raises(bench.BenchmarkError, match='N does not'):
        bench.load_constants(write_plan(tmp_path, N=5))


@pytest.mark.parametrize('command', ['prepare', 'freeze', 'run', 'report', 'audit'])
def test_plan_change_refuses_every_command(bench, tmp_path, capsys, command):
    plan = write_plan(tmp_path)
    assert bench.main(['hash-plan'], plan_path=plan) == 0
    plan.write_bytes(plan.read_bytes() + b' ')
    flags = ['--archives', str(tmp_path), '--out', str(tmp_path / 'output')] if command == 'prepare' else ['--handoff', str(tmp_path)]
    if command == 'freeze':
        flags += ['--commit', 'a' * 40]
    assert bench.main([command, *flags], plan_path=plan) == 1
    assert 'hash mismatch' in capsys.readouterr().err


def test_missing_pin_refused(bench, tmp_path):
    with pytest.raises(bench.BenchmarkError, match='missing'):
        bench.verify_plan(bench.load_constants(write_plan(tmp_path)))


def test_unfilled_plan_cannot_be_pinned(bench, tmp_path):
    path = write_plan(tmp_path)
    path.write_text(path.read_text() + '\n{{LIMITS}}\n')
    with pytest.raises(bench.BenchmarkError, match='placeholders'):
        bench.hash_plan(bench.load_constants(path))


def test_draw_determinism_seed_and_rank(bench, tmp_path):
    c = bench.load_constants(write_plan(tmp_path / 'method'))
    bench.hash_plan(c)
    source = archives(tmp_path)
    outputs = [tmp_path / name for name in ('first', 'second')]
    for out in outputs:
        bench.prepare(c, source, out)
    assert (outputs[0] / 'manifest.jsonl').read_bytes() == (outputs[1] / 'manifest.jsonl').read_bytes()
    draws = bench.records(outputs[0] / 'manifest.jsonl')
    assert [d['draw_id'] for d in draws] == list(range(c.N))
    for quarter in c.QUARTERS:
        expected = sorted((hashlib.sha256(f'{c.SEED}|{quarter}|filing|filing-{i}'.encode()).hexdigest(), f'filing-{i}') for i in range(6))[:c.FILINGS_PER_QUARTER]
        actual = [d for d in draws if d['quarter'] == quarter]
        assert [(d['filing_rank_hash'], d['adsh']) for d in actual] == expected
        for draw in actual:
            start = int(draw['adsh'].split('-')[1]) * 3
            fact_rank = min((hashlib.sha256(f'{c.SEED}|{quarter}|fact|{draw["adsh"]}|{i}'.encode()).hexdigest(), i) for i in range(start, start + 3))
            assert (draw['fact_rank_hash'], draw['row_index']) == fact_rank
    changed = bench.load_constants(write_plan(tmp_path / 'different', SEED=c.SEED + 1))
    bench.hash_plan(changed)
    bench.prepare(changed, source, tmp_path / 'different_draw')
    other = bench.records(tmp_path / 'different_draw' / 'manifest.jsonl')
    assert [(d['adsh'], d['row_index']) for d in draws] != [(d['adsh'], d['row_index']) for d in other]


def test_orphans_malformed_and_missing_segments(bench, tmp_path):
    c = bench.load_constants(write_plan(tmp_path / 'method'))
    bench.hash_plan(c)
    source = archives(tmp_path, optional=False, junk=True)
    out = tmp_path / 'out'
    bench.prepare(c, source, out)
    draws = bench.records(out / 'manifest.jsonl')
    summary = draws[0]['manifest_summary']
    for info in summary.values():
        assert info['malformed'] == info['orphans'] == 1
        assert info['malformed_row_indices'] == [1]
        assert info['population_rows'] == 18
        assert info['data_rows'] == 20
    assert all(d['adsh'] != 'orphan' and d['row_index'] >= 2 for d in draws)
    assert all(d['segments'] == d['coreg'] == '' for d in draws)


def test_prepare_refuses_existing_manifest(bench, tmp_path):
    c, out, _ = setup_run(bench, tmp_path)
    original = (out / 'manifest.jsonl').read_bytes()
    with pytest.raises(bench.BenchmarkError, match='already exists'):
        bench.prepare(c, tmp_path / 'archives', out)
    assert (out / 'manifest.jsonl').read_bytes() == original


def test_missing_zip_leaves_no_artifact(bench, tmp_path):
    c = bench.load_constants(write_plan(tmp_path / 'method'))
    bench.hash_plan(c)
    source = archives(tmp_path, quarters=c.QUARTERS[:1])
    out = tmp_path / 'out'
    with pytest.raises(bench.BenchmarkError, match='Missing archive'):
        bench.prepare(c, source, out)
    assert not out.exists()


def test_unreadable_archive_text_leaves_no_artifact(bench, tmp_path):
    c = bench.load_constants(write_plan(tmp_path / 'method'))
    bench.hash_plan(c)
    source = archives(tmp_path)
    path = source / f'{c.QUARTERS[0]}.zip'
    with zipfile.ZipFile(path) as archive:
        submissions = archive.read('sub.txt')
        data = archive.read('num.txt').replace(b'\tTag0\t', b'\t\xe9\t', 1)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('sub.txt', submissions)
        archive.writestr('num.txt', data)
    out = tmp_path / 'out'
    with pytest.raises(bench.BenchmarkError, match='unreadable archive text'):
        bench.prepare(c, source, out)
    assert not out.exists()


def test_source_malformed_sends_no_fact_queries(bench, tmp_path, monkeypatch):
    c, handoff, draws = setup_run(bench, tmp_path, rows=lambda i: [{'value': 'NaN'}])
    assert all(d['source_flag'] == 'SOURCE_MALFORMED' for d in draws)
    calls = scripted(bench, monkeypatch, [page()])
    assert bench.run(c, handoff) == 0
    assert len(calls) == 1 and calls[0].url.path.endswith('/companies')
    assert all(o['on'] == 'SOURCE_MALFORMED' and o['before'] == 'NOT_SENT' for o in bench.records(handoff / 'outcomes.jsonl'))


def test_source_duplicate_sends_no_fact_queries(bench, tmp_path, monkeypatch):
    c, handoff, draws = setup_run(bench, tmp_path, rows=lambda i: [{'value': ''}, {'value': '1'}])
    assert all(d['source_flag'] == 'SOURCE_DUPLICATE' for d in draws)
    calls = scripted(bench, monkeypatch, [page()])
    assert bench.run(c, handoff) == 0
    assert len(calls) == 1
    assert all(o['on'] == 'SOURCE_DUPLICATE' for o in bench.records(handoff / 'outcomes.jsonl'))


def test_duplicate_equal_decimals_not_flagged(bench, tmp_path):
    _, _, draws = setup_run(bench, tmp_path, rows=lambda i: [{'value': '1.000'}, {'value': '1'}])
    assert all(d['source_flag'] is None for d in draws)


def test_trailing_decimal_zeros_match(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, value=Decimal('1234'))]), page()], rows=lambda i: [{}])
    assert result['on'] == 'MATCH'
    assert result['pass_s1'] and result['pass_s2']


def test_twenty_five_digits_round_trip(bench, tmp_path, monkeypatch):
    number = '1234567890123456789012345'
    result, _, handoff, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d)]), page()], rows=lambda i: [{'value': number}])
    assert result['on'] == 'MATCH'
    attempt = bench.records(handoff / 'results.jsonl')[1]
    assert attempt['accession_rows'][0]['value'] == number
    assert Decimal(float(number)) != Decimal(number)  # a float round trip loses digits that the Decimal path keeps


def test_api_null_blank_matches(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, value=None)]), page()], rows=lambda i: [{'value': ''}])
    assert result['on'] == 'MATCH'


def test_api_null_number_differs(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, value=None)]), page()])
    assert result['on'] == 'VALUE_DIFFERS'


def test_segments_null_matches_empty(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, segments=None, coreg=None)]), page()])
    assert result['on'] == 'MATCH'


def test_filed_difference(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, filed='2020-05-14')]), page()])
    assert result['on'] == 'FILING_FIELDS_DIFFER'


def test_cik_difference(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, cik=Decimal(999))]), page()])
    assert result['on'] == 'FILING_FIELDS_DIFFER'


def test_unit_differs(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, lambda d: [page([api_row(d, unit='EUR')])])
    assert result['on'] == 'UNIT_DIFFERS'


def test_period_differs(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, lambda d: [page([api_row(d, period_end='2020-03-30')])])
    assert result['on'] == 'PERIOD_DIFFERS'


def test_duration_quarters_differs(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, duration_quarters=Decimal(4))])])
    assert result['on'] == 'PERIOD_DIFFERS'


@pytest.mark.parametrize('field', ['accession_id', 'tag', 'taxonomy', 'coreg'])
def test_different_key_field_is_absent(bench, tmp_path, monkeypatch, field):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, **{field: 'different'})])])
    assert result['on'] == 'ABSENT'


def test_absent_complete_only_and_not_vacuous(bench, tmp_path, monkeypatch):
    result, calls, _, _ = one_draw(bench, tmp_path, monkeypatch, lambda d: [page()])
    assert result['on'] == 'ABSENT' and result['before'] == 'NOT_SENT'
    assert not result['pass_s1'] and not result['pass_s2']
    assert len(calls) == 5


def test_never_null_cursor_is_inconclusive(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, lambda d: [page(cursor=str(i)) for i in range(4)])
    assert result['on'] == 'INCONCLUSIVE_PAGES' and result['pages_used'] == 4


def test_three_server_errors_fail_page(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, lambda d: [page(status=500) for _ in range(3)])
    assert result['on'] == 'FAILED' and result['attempts_used'] == 3


def test_before_any_accession_row_means_present(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d)]), page([{'accession_id': d['adsh']}], cursor='more')])
    assert result['before'] == 'PRESENT_BEFORE_FILING_DATE' and not result['pass_s2']


def test_before_clean_and_cutoff(bench, tmp_path, monkeypatch):
    result, calls, _, draws = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d)]), page(cursor='next'), page()])
    assert result['before'] == 'CLEAN'
    assert calls[2].url.params['as_of'] == calls[3].url.params['as_of'] == '2020-05-14'
    assert calls[1].url.params['as_of'] == draws[0]['filed']
    assert calls[3].url.params['cursor'] == 'next'
    assert dict(calls[1].url.params) == {k: str(v) for k, v in draws[0]['queries']['on'].items()}


def test_short_page_not_completion(bench, tmp_path, monkeypatch):
    result, calls, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([{'accession_id': 'different'}], cursor='opaque'), page([api_row(d)]), page()])
    assert result['on'] == 'MATCH' and result['pages_used'] == 3
    assert calls[2].url.params['cursor'] == 'opaque'


def test_shared_extra_page_allowance(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page(cursor='one'), page(cursor='two'), page(cursor='three'),
                   page([api_row(d)], cursor='four'), page(cursor='before-extra')])
    assert result['on'] == 'MATCH'
    assert result['before'] == 'INCONCLUSIVE_PAGES'
    assert result['pages_used'] == 5


def test_retry_and_limit_accounting(bench, tmp_path, monkeypatch):
    c, handoff, draws = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(status=500), page(),
        page(status=429, error='rate_limited', headers={'Retry-After': '7.5'}),
        page([api_row(draws[0])]), page(), *[page() for _ in draws[1:]]])
    assert bench.run(c, handoff) == 0
    attempts = bench.records(handoff / 'results.jsonl')
    state = json.loads((handoff / 'state.json').read_text())
    assert len(attempts) == len(calls) == state['attempts_total'] == 8
    assert sum(state['attempts_by_day'].values()) == 8
    assert attempts[0]['query'] == attempts[1]['query'] == 'LIMIT_READ'
    assert attempts[0]['draw_id'] is None
    assert attempts[2]['error'] == 'rate_limited' and attempts[3]['attempt'] == 2
    assert any(wait >= 7.5 + 1.25 for wait in bench.test_clock.sleeps)
    assert bench.audit(c, handoff) == 0


def test_unadmitted_limit_stops_before_fact_query(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(headers={'RateLimit-Limit': '10'})])
    assert bench.run(c, handoff) == 3
    assert len(calls) == 1 and calls[0].url.path.endswith('/companies')
    assert not (handoff / 'outcomes.jsonl').exists()


def test_quota_exceeded_stops_raw_error(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), page(status=429, error='quota_exceeded')])
    assert bench.run(c, handoff) == 3
    assert len(calls) == 2
    assert bench.records(handoff / 'results.jsonl')[-1]['error'] == 'quota_exceeded'


def test_daily_ceiling_stops_before_send(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [])
    runner = bench.Runner(c, handoff)
    runner.state['attempts_by_day'][runner.start_day] = c.ATTEMPT_CEILING
    runner.save()
    assert runner.execute() == 3
    assert not calls


def test_resume_preserves_completed_and_pending_allowances(bench, tmp_path, monkeypatch):
    c, handoff, draws = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), page(), page(status=403), page(), page(), page()])
    assert bench.run(c, handoff) == 3
    assert len(bench.records(handoff / 'outcomes.jsonl')) == 1
    bench.test_clock.now += timedelta(days=1)
    assert bench.run(c, handoff) == 0
    attempts = bench.records(handoff / 'results.jsonl')
    assert len(calls) == 6
    assert len([a for a in attempts if a['query'] == 'LIMIT_READ']) == 1
    assert len([a for a in attempts if a['draw_id'] == draws[0]['draw_id']]) == 1
    retried = [a for a in attempts if a['draw_id'] == draws[1]['draw_id']]
    assert [a['attempt'] for a in retried] == [1, 2]
    assert bench.run(c, handoff) == 0  # Completion causes no sends, including admission.
    assert len(calls) == 6
    assert bench.audit(c, handoff) == 0


def test_resume_exhausted_page_not_replenished(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), *[page(status=403) for _ in range(3)], *[page() for _ in range(3)]])
    for _ in range(3):
        assert bench.run(c, handoff) == 3
        bench.test_clock.now += timedelta(days=1)
    assert bench.run(c, handoff) == 0
    result = bench.records(handoff / 'outcomes.jsonl')[0]
    assert result['on'] == 'FAILED' and result['attempts_used'] == 3
    assert len(calls) == 7
    assert bench.audit(c, handoff) == 0


def test_limit_read_allowance_survives_resume(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(status=403) for _ in range(3)])
    for _ in range(4):
        assert bench.run(c, handoff) == 3
        bench.test_clock.now += timedelta(days=1)
    assert len(calls) == 3
    assert bench.audit(c, handoff) == 0


def test_day_rollover_stops(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)

    def handler(request):
        bench.test_clock.now += timedelta(days=1)
        return page()

    calls = inject(bench, monkeypatch, handler)
    assert bench.run(c, handoff) == 3
    assert len(calls) == 1
    state = json.loads((handoff / 'state.json').read_text())
    assert 'day changed' in state['stop_reason']


def test_changed_manifest_refused(bench, tmp_path):
    c, handoff, _ = setup_run(bench, tmp_path)
    path = handoff / 'manifest.jsonl'
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(bench.BenchmarkError, match='manifest.jsonl hash mismatch'):
        bench.run(c, handoff)


def test_missing_key_refused(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    monkeypatch.delenv('ARKLEON_API_KEY')
    with pytest.raises(bench.BenchmarkError, match='ARKLEON_API_KEY'):
        bench.run(c, handoff)


def test_exact_upper_bound_and_upward_rounding(bench):
    value = bench.upper_bound(0, 340, Fraction('0.95'))
    assert abs(float(value) - (1 - 0.05 ** (1 / 340))) < 1e-9
    assert bench.format_bound(value) == '0.008773'
    assert bench.format_bound(bench.upper_bound(1, 10, Fraction('0.95'))) == '0.3942'
    assert bench.upper_bound(10, 10, Fraction('0.95')) == 1
    assert bench.format_bound(Fraction(1)) == '1.000'
    # Exact boundary roots must not be nudged up to the next rounding bucket.
    assert bench.upper_bound(0, 1, Fraction(1, 2)) == Fraction(1, 2)
    assert bench.format_bound(Fraction(1, 10**30)) == '0.' + '0' * 29 + '1000'


def test_incomplete_report_has_no_bound(bench, tmp_path, capsys):
    c, handoff, _ = setup_run(bench, tmp_path)
    bench.report(c, handoff)
    output = capsys.readouterr().out
    assert 'no bound: 4 draws without an outcome' in output
    assert 'headline |' not in output


def test_report_run_start_before_any_run(bench, tmp_path, capsys):
    c, handoff, _ = setup_run(bench, tmp_path)
    assert not (handoff / 'state.json').exists()
    capsys.readouterr()
    bench.report(c, handoff)
    output = capsys.readouterr().out
    assert output.startswith('run started (UTC) | none\nUTC day | attempts\n')


def test_report_run_start_after_run(bench, tmp_path, monkeypatch, capsys):
    c, handoff, _ = setup_run(bench, tmp_path)
    started = bench.timestamp()
    scripted(bench, monkeypatch, [page() for _ in range(c.N + 1)])
    assert bench.run(c, handoff) == 0
    state = json.loads((handoff / 'state.json').read_text())
    assert state['run_started_utc'] == started
    capsys.readouterr()
    bench.report(c, handoff)
    output = capsys.readouterr().out
    assert output.startswith(f"run started (UTC) | {state['run_started_utc']}\nUTC day | attempts\n")


def test_complete_report_resolved_exclusions(bench, tmp_path, monkeypatch, capsys):
    c, handoff, _ = setup_run(bench, tmp_path, rows=lambda i: [{'value': 'not decimal'}])
    scripted(bench, monkeypatch, [page()])
    assert bench.run(c, handoff) == 0
    bench.report(c, handoff)
    output = capsys.readouterr().out
    assert output.count('headline | 4 | 4 | 1.000') == 2
    assert output.count('resolved-only | 0 | 0 | undefined') == 2
    assert 'S1: 4 of 4, 1.000' in output and 'S2: 4 of 4, 1.000' in output


@pytest.mark.parametrize('body', [b'not json', b'[]', b'{"data":[]}', b'{"data":[],"next_cursor":""}', b'{"data":{},"next_cursor":null}'])
def test_invalid_envelopes_are_retried(bench, tmp_path, monkeypatch, body):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [httpx.Response(200, content=body, headers={'RateLimit-Limit': '60'}), page()])
    assert result['on'] == 'ABSENT' and result['attempts_used'] == 2


@pytest.mark.parametrize('field,value', [('value', '1234'), ('value', True), ('duration_quarters', '1'), ('cik', '10')])
def test_no_string_or_boolean_numeric_coercion(bench, tmp_path, monkeypatch, field, value):
    responses = lambda d: [page([api_row(d, **{field: value})]), *([] if field == 'duration_quarters' else [page()])]
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, responses, rows=lambda i: [{}])
    expected = 'VALUE_DIFFERS' if field == 'value' else 'ABSENT' if field == 'duration_quarters' else 'FILING_FIELDS_DIFFER'
    assert result['on'] == expected


def test_missing_optional_api_field_cannot_match(bench, tmp_path, monkeypatch):
    def responses(draw):
        row = api_row(draw)
        del row['segments']
        return [page([row])]
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, responses)
    assert result['on'] == 'ABSENT'


def test_first_exact_row_wins_and_evidence_retains_both(bench, tmp_path, monkeypatch):
    result, _, handoff, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, value=Decimal('-1')), api_row(d)]), page()])
    assert result['on'] == 'VALUE_DIFFERS'
    assert len(bench.records(handoff / 'results.jsonl')[1]['accession_rows']) == 2


def test_unit_precedence_after_complete_search(bench, tmp_path, monkeypatch):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page([api_row(d, period_end='2020-03-30')], cursor='more'), page([api_row(d, unit='EUR')])])
    assert result['on'] == 'UNIT_DIFFERS'


@pytest.mark.parametrize('retry_after', [None, '-1', 'NaN', 'nonsense'])
def test_bad_retry_after_fails_without_retry(bench, tmp_path, monkeypatch, retry_after):
    headers = {} if retry_after is None else {'Retry-After': retry_after}
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch,
        lambda d: [page(status=429, error='rate_limited', headers=headers)])
    assert result['on'] == 'FAILED' and result['attempts_used'] == 1


def test_transport_error_is_recorded_and_retried(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 2:
            raise httpx.ReadTimeout('synthetic timeout')
        return page()

    inject(bench, monkeypatch, handler)
    assert bench.run(c, handoff) == 0
    failed = bench.records(handoff / 'results.jsonl')[1]
    assert failed['status'] is None and failed['error'] == 'ReadTimeout'
    assert failed['headers'] is None and failed['row_count'] is None
    assert failed['next_cursor_present'] is None
    assert bench.audit(c, handoff) == 0


def test_decoding_error_is_recorded_and_retried(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 2:
            raise httpx.DecodingError('synthetic decoding error')
        return page()

    calls = inject(bench, monkeypatch, handler)
    assert bench.run(c, handoff) == 0
    assert calls[1].url.path.endswith('/facts')
    failed = bench.records(handoff / 'results.jsonl')[1]
    assert failed['status'] is None and failed['error'] == 'DecodingError'
    result = bench.records(handoff / 'outcomes.jsonl')[0]
    assert result['on'] == 'ABSENT' and result['attempts_used'] == 2
    assert bench.audit(c, handoff) == 0


def test_interrupted_reservation_recovered_once(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), *[page() for _ in range(c.N)]])
    runner = bench.Runner(c, handoff)
    q = runner.state['limit_read']
    q['pages'].append({'cursor': None, 'attempts': 0, 'done': False})
    runner.reserve(None, 'LIMIT_READ', q['pages'][0])
    runner.http.close()  # Simulate process loss after the durable reservation.
    assert bench.run(c, handoff) == 0
    attempts = bench.records(handoff / 'results.jsonl')
    assert attempts[0]['error'] == 'InterruptedAttempt'
    assert attempts[1]['attempt'] == 2
    assert len(attempts) == len(calls) + 1
    assert bench.audit(c, handoff) == 0


def test_captured_journal_replayed_without_repeat_send(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), *[page() for _ in range(c.N)]])
    original = bench.Runner.apply
    crashed = False

    def crash(self, record):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError('simulated loss after journal fsync')
        return original(self, record)

    monkeypatch.setattr(bench.Runner, 'apply', crash)
    with pytest.raises(RuntimeError, match='simulated loss'):
        bench.run(c, handoff)
    assert bench.run(c, handoff) == 0
    assert len(calls) == c.N + 1
    assert bench.audit(c, handoff) == 0


def test_audit_rejects_counter_and_duplicate_outcome(bench, tmp_path, monkeypatch, capsys):
    c, handoff, _ = setup_run(bench, tmp_path)
    scripted(bench, monkeypatch, [page() for _ in range(c.N + 1)])
    assert bench.run(c, handoff) == 0
    state_path = handoff / 'state.json'
    state = json.loads(state_path.read_text())
    state['attempts_total'] += 1
    state_path.write_text(json.dumps(state))
    bench.append_record(handoff / 'outcomes.jsonl', bench.records(handoff / 'outcomes.jsonl')[0])
    assert bench.audit(c, handoff) == 1
    output = capsys.readouterr().out
    assert 'counters differ' in output and 'duplicate or unknown' in output


def test_freeze_label_record_is_immutable(bench, tmp_path):
    c, handoff, _ = setup_run(bench, tmp_path)
    lines = c.plan_path.with_name('FREEZE.md').read_text().splitlines()
    assert lines[0] == '# Freeze record' and len(lines) == 9
    assert all(line.startswith('- ') for line in lines[1:])
    with pytest.raises(bench.BenchmarkError, match='already exists'):
        bench.freeze(c, handoff, 'b' * 40)


def test_runtime_output_cannot_be_inside_repository(bench, tmp_path):
    c = bench.load_constants(write_plan(tmp_path / 'method'))
    bench.hash_plan(c)
    with pytest.raises(bench.BenchmarkError, match='outside the repository'):
        bench.prepare(c, tmp_path, Path(bench.__file__).parents[2] / 'results')


def test_missing_limit_header_stops(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    response = httpx.Response(200, content=b'{"data":[],"next_cursor":null}')
    calls = scripted(bench, monkeypatch, [response])
    assert bench.run(c, handoff) == 3
    assert len(calls) == 1


def test_later_missing_limit_retains_admission(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    responses = [page(headers={'RateLimit-Limit': '300'})]
    responses += [httpx.Response(200, content=b'{"data":[],"next_cursor":null}') for _ in range(c.N)]
    scripted(bench, monkeypatch, responses)
    assert bench.run(c, handoff) == 0
    state = json.loads((handoff / 'state.json').read_text())
    assert state['rate_limit'] == 300
    assert all(delay == 0.25 for delay in bench.test_clock.sleeps)


def test_later_unknown_limit_stops(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), page(headers={'RateLimit-Limit': '10'})])
    assert bench.run(c, handoff) == 3
    assert len(calls) == 2
    assert not bench.records(handoff / 'outcomes.jsonl')


def test_updated_limit_adds_full_retry_wait(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    scripted(bench, monkeypatch, [page(headers={'RateLimit-Limit': '300'}),
        page(status=429, error='rate_limited', headers={'RateLimit-Limit': '60', 'Retry-After': '200'}),
        *[page() for _ in range(c.N)]])
    assert bench.run(c, handoff) == 0
    assert 201.25 in bench.test_clock.sleeps


@pytest.mark.parametrize('status', [400, 404, 429, 302])
def test_nonretryable_http_fails_immediately(bench, tmp_path, monkeypatch, status):
    result, _, _, _ = one_draw(bench, tmp_path, monkeypatch, lambda d: [page(status=status)])
    assert result['on'] == 'FAILED' and result['attempts_used'] == 1


def test_resume_retains_cursor_and_prior_difference_evidence(bench, tmp_path, monkeypatch):
    c, handoff, draws = setup_run(bench, tmp_path)
    calls = scripted(bench, monkeypatch, [page(), page([api_row(draws[0], unit='EUR')], cursor='saved'),
        page(status=403), page(), *[page() for _ in draws[1:]]])
    assert bench.run(c, handoff) == 3
    bench.test_clock.now += timedelta(days=1)
    assert bench.run(c, handoff) == 0
    first = bench.records(handoff / 'outcomes.jsonl')[0]
    assert first['on'] == 'UNIT_DIFFERS' and first['pages_used'] == 2
    assert calls[2].url == calls[3].url
    assert calls[3].url.params['cursor'] == 'saved'
    assert bench.audit(c, handoff) == 0


def test_unsent_page_not_charged_on_day_rollover(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 2:
            bench.test_clock.now += timedelta(days=1)
            return page(cursor='pending-extra')
        return page()

    inject(bench, monkeypatch, handler)
    assert bench.run(c, handoff) == 3
    state = json.loads((handoff / 'state.json').read_text())
    assert state['draws']['0']['pages_used'] == 1
    assert bench.audit(c, handoff) == 0


def test_bad_source_key_stops_before_artifacts(bench, tmp_path):
    c = bench.load_constants(write_plan(tmp_path / 'method'))
    bench.hash_plan(c)
    source = archives(tmp_path, rows=lambda i: [{'ddate': 'bad date'}])
    with pytest.raises(bench.BenchmarkError, match='Invalid archive date'):
        bench.prepare(c, source, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_changed_archive_digest_file_refused(bench, tmp_path):
    c, handoff, _ = setup_run(bench, tmp_path)
    path = handoff / 'archives.sha256'
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(bench.BenchmarkError, match='archives.sha256 hash mismatch'):
        bench.run(c, handoff)


def test_dirty_repository_refused(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    (Path(bench.__file__).parents[2] / '.git').mkdir(parents=True)
    commands = []

    def status(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=' M tracked-file\n')

    monkeypatch.setattr(bench.subprocess, 'run', status)
    with pytest.raises(bench.BenchmarkError, match='Repository must be clean'):
        bench.run(c, handoff)
    assert commands[0][-2:] == ['status', '--porcelain']


def test_dirty_linked_worktree_refused(bench, tmp_path, monkeypatch):
    c, handoff, _ = setup_run(bench, tmp_path)
    root = Path(bench.__file__).parents[2]
    root.mkdir(parents=True)
    (root / '.git').touch()
    commands = []

    def status(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=' M tracked-file\n')

    monkeypatch.setattr(bench.subprocess, 'run', status)
    with pytest.raises(bench.BenchmarkError, match='Repository must be clean'):
        bench.run(c, handoff)
    assert commands == [['git', '-C', str(root), 'status', '--porcelain']]
