"""Deterministic archive comparison using the frozen method beside this module."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace
import zipfile

import httpx
from arkleon.api import ArkleonAPIError, DataClient


class BenchmarkError(Exception):
    """A refusal whose message is safe to display."""


class Partial(Exception):
    """An accounted global stop, with resumable state."""


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(now=None):
    return (now or utcnow()).isoformat().replace('+00:00', 'Z')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_text(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def atomic_write(path, text):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_record(path, record):
    with Path(path).open('a', encoding='utf-8', newline='') as stream:
        stream.write(json_text(record) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def records(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def load_constants(plan_path=None):
    path = Path(plan_path) if plan_path else Path(__file__).with_name('PLAN.md')
    text = path.read_text(encoding='utf-8')
    blocks = re.findall(r'^```constants\s*\n(.*?)^```\s*$', text, re.M | re.S)
    if len(blocks) != 1:
        raise BenchmarkError('PLAN.md must contain exactly one constants block')
    integer_names = {
        'SEED', 'FILINGS_PER_QUARTER', 'N', 'ATTEMPT_CEILING', 'RESERVE',
        'ATTEMPTS_PER_PAGE', 'EXTRA_PAGES_PER_FACT', 'PAGE_LIMIT', 'PERIOD_WINDOW_DAYS',
    }
    expected = integer_names | {'QUARTERS', 'CONFIDENCE', 'ALLOWED_RATE_LIMITS'}
    values = {}
    try:
        for line in blocks[0].splitlines():
            if not line.strip():
                continue
            key, value = (part.strip() for part in line.split('=', 1))
            if key not in expected or key in values:
                raise ValueError('unknown or duplicate constant')
            if key in integer_names:
                values[key] = int(value)
            elif key == 'CONFIDENCE':
                values[key] = Fraction(value)
            elif key == 'ALLOWED_RATE_LIMITS':
                values[key] = tuple(int(item.strip()) for item in value.split(','))
            else:
                match = re.fullmatch(r'(\d{4})q([1-4])\.\.(\d{4})q([1-4])', value)
                if not match:
                    raise ValueError('invalid quarter range')
                y1, q1, y2, q2 = map(int, match.groups())
                start, end = y1 * 4 + q1 - 1, y2 * 4 + q2 - 1
                if end < start:
                    raise ValueError('reversed quarters')
                values[key] = tuple(f'{i // 4}q{i % 4 + 1}' for i in range(start, end + 1))
        if values.keys() != expected:
            raise ValueError('missing constants')
        c = SimpleNamespace(**values, plan_path=path, plan_text=text)
        if any(values[key] < 0 for key in integer_names):
            raise ValueError('negative constant')
        if min(c.FILINGS_PER_QUARTER, c.N, c.ATTEMPTS_PER_PAGE, c.PAGE_LIMIT) <= 0:
            raise ValueError('nonpositive allocation')
        if not 0 < c.CONFIDENCE < 1 or not c.ALLOWED_RATE_LIMITS or min(c.ALLOWED_RATE_LIMITS) <= 0:
            raise ValueError('invalid confidence or rate limits')
        worst = (2 + c.EXTRA_PAGES_PER_FACT) * c.ATTEMPTS_PER_PAGE
        available = c.ATTEMPT_CEILING - c.RESERVE
        if c.N != c.FILINGS_PER_QUARTER * len(c.QUARTERS):
            raise ValueError('N does not satisfy the draw sizing rules')
        if c.N * worst + c.ATTEMPTS_PER_PAGE > available:
            raise ValueError('allocation exceeds available attempt budget')
        if (c.FILINGS_PER_QUARTER + 1) * len(c.QUARTERS) * worst + c.ATTEMPTS_PER_PAGE <= available:
            raise ValueError('allocation is not the largest equal allocation')
        return c
    except (ValueError, ZeroDivisionError) as exc:
        raise BenchmarkError(f'Invalid constants: {exc}') from exc


def verify_plan(c):
    path = c.plan_path.with_name('PLAN.sha256')
    if not path.exists():
        raise BenchmarkError('PLAN.sha256 is missing; pin the final plan first')
    if path.read_text(encoding='utf-8') != f'{digest(c.plan_path)}  PLAN.md\n':
        raise BenchmarkError('PLAN.md hash mismatch with PLAN.sha256')


def hash_plan(c):
    if re.search(r'\{\{[A-Z]+\}\}', c.plan_text):
        raise BenchmarkError('Replace all PLAN.md paragraph placeholders before pinning')
    atomic_write(c.plan_path.with_name('PLAN.sha256'), f'{digest(c.plan_path)}  PLAN.md\n')


def external_directory(path):
    path = Path(path).resolve()
    root = Path(__file__).resolve().parents[2]
    if path == root or root in path.parents:
        raise BenchmarkError('The results directory must be outside the repository')
    return path


def archive_date(text):
    if not re.fullmatch(r'\d{8}', text):
        raise BenchmarkError('Invalid archive date')
    return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()


def source_value(text):
    if text == '':
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise BenchmarkError('Malformed source decimal') from None
    if not value.is_finite():
        raise BenchmarkError('Nonfinite source decimal')
    return value


def source_key(row):
    return (row['adsh'], row['tag'], row['version'], archive_date(row['ddate']),
            int(row['qtrs']), row['uom'], row.get('segments', ''), row.get('coreg', ''))


def table_rows(archive, member, required):
    with archive.open(member) as raw, io.TextIOWrapper(
        raw, encoding='utf-8', errors='strict', newline=''
    ) as stream:
        try:
            header = stream.readline().rstrip('\r\n').split('\t')
            if not required <= set(header) or len(set(header)) != len(header):
                raise BenchmarkError(f'{member}: missing required or duplicate header')
            for index, line in enumerate(stream):
                fields = line.rstrip('\r\n').split('\t')
                yield index, dict(zip(header, fields)) if len(fields) == len(header) else None
        except UnicodeDecodeError:
            raise BenchmarkError(f'{member}: unreadable archive text') from None


def query_parameters(draw, c, before=False):
    filed = date.fromisoformat(draw['filed'])
    period = date.fromisoformat(draw['ddate'])
    window = timedelta(days=c.PERIOD_WINDOW_DAYS)
    return {'as_of': (filed - timedelta(days=int(before))).isoformat(),
            'cik': draw['cik'], 'tag': draw['tag'],
            'period_start': (period - window).isoformat(),
            'period_end': (period + window).isoformat(), 'limit': c.PAGE_LIMIT}


def prepare(c, archives, out):
    verify_plan(c)
    out = external_directory(out)
    if (out / 'manifest.jsonl').exists():
        raise BenchmarkError('manifest.jsonl already exists; never redraw a handoff')
    archives = Path(archives)
    manifest, summary, archive_hashes = [], {}, []
    required = {'adsh', 'tag', 'version', 'ddate', 'qtrs', 'uom', 'value'}
    # All preflight and drawing finishes before creating any preparation artifact.
    for quarter in c.QUARTERS:
        path = archives / f'{quarter}.zip'
        if not path.is_file():
            raise BenchmarkError(f'Missing archive: {quarter}.zip')
        archive_hash = digest(path)
        with zipfile.ZipFile(path) as archive:
            submissions = {}
            for _, row in table_rows(archive, 'sub.txt', {'adsh', 'cik', 'filed'}):
                if row is None:
                    raise BenchmarkError('Malformed sub.txt row')
                entry = (int(row['cik']), archive_date(row['filed']))
                if row['adsh'] in submissions and submissions[row['adsh']] != entry:
                    raise BenchmarkError('Conflicting submission fields')
                submissions[row['adsh']] = entry
            counts, malformed, orphans, data_rows = Counter(), [], [], 0
            for index, row in table_rows(archive, 'num.txt', required):
                data_rows += 1
                if row is None:
                    malformed.append(index)
                elif row['adsh'] not in submissions:
                    orphans.append(index)
                else:
                    source_key(row)  # Every population row must supply usable key fields.
                    counts[row['adsh']] += 1
            ranking = sorted((hashlib.sha256(
                f'{c.SEED}|{quarter}|filing|{adsh}'.encode('utf-8')
            ).hexdigest(), adsh) for adsh in counts)
            if len(ranking) < c.FILINGS_PER_QUARTER:
                raise BenchmarkError(f'{quarter}: too few eligible filings')
            chosen = ranking[:c.FILINGS_PER_QUARTER]
            selected = {adsh: [] for _, adsh in chosen}
            for index, row in table_rows(archive, 'num.txt', required):
                if row is not None and row['adsh'] in selected:
                    selected[row['adsh']].append((index, row))
            summary[quarter] = {
                'zip_sha256': archive_hash, 'data_rows': data_rows,
                'malformed': len(malformed), 'malformed_row_indices': malformed,
                'orphans': len(orphans), 'orphan_row_indices': orphans,
                'population_rows': sum(counts.values()), 'eligible_filings': len(counts),
            }
            for filing_hash, adsh in chosen:
                fact_hash, index, row = min((hashlib.sha256(
                    f'{c.SEED}|{quarter}|fact|{adsh}|{index}'.encode('utf-8')
                ).hexdigest(), index, row) for index, row in selected[adsh])
                flag = None
                try:
                    value = source_value(row['value'])
                except BenchmarkError:
                    flag, value = 'SOURCE_MALFORMED', row['value']
                key = source_key(row)
                if flag is None:
                    for _, peer in selected[adsh]:
                        if source_key(peer) != key:
                            continue
                        try:
                            peer_value = source_value(peer['value'])
                        except BenchmarkError:
                            continue
                        if peer_value != value:
                            flag = 'SOURCE_DUPLICATE'
                            break
                cik, filed = submissions[adsh]
                draw = {
                    'draw_id': len(manifest), 'quarter': quarter, 'adsh': adsh,
                    'cik': cik, 'filed': filed, 'row_index': index, 'tag': row['tag'],
                    'version': row['version'], 'ddate': key[3], 'qtrs': key[4],
                    'uom': row['uom'], 'segments': key[6], 'coreg': key[7],
                    'value': row['value'], 'filing_rank_hash': filing_hash,
                    'fact_rank_hash': fact_hash, 'source_flag': flag,
                    'archive_sha256': archive_hash, 'raw_source_row': row,
                    'normalized_key': key, 'normalized_value': None if value is None else str(value),
                }
                draw['queries'] = {'on': query_parameters(draw, c),
                                   'before': query_parameters(draw, c, before=True)}
                manifest.append(draw)
        archive_hashes.append(f'{archive_hash}  {quarter}.zip\n')
        print(f'{quarter}: {len(counts)} eligible filings; draw prepared', file=sys.stderr)
    manifest[0]['manifest_summary'] = summary
    body = ''.join(json_text(draw) + '\n' for draw in manifest)
    artifacts = {
        'manifest-summary.json': json_text(summary) + '\n',
        'archives.sha256': ''.join(archive_hashes),
        'manifest.sha256': hashlib.sha256(body.encode('utf-8')).hexdigest() + '  manifest.jsonl\n',
        'manifest.jsonl': body,
    }
    out.mkdir(parents=True, exist_ok=True)
    try:
        for name, content in artifacts.items():
            with (out / (name + '.tmp')).open('w', encoding='utf-8', newline='') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        for name in artifacts:  # The immutable manifest is the final commit marker.
            os.replace(out / (name + '.tmp'), out / name)
    finally:
        for name in artifacts:
            (out / (name + '.tmp')).unlink(missing_ok=True)


def freeze(c, handoff, commit):
    verify_plan(c)
    handoff = external_directory(handoff)
    path = c.plan_path.with_name('FREEZE.md')
    if path.exists():
        raise BenchmarkError('FREEZE.md already exists')
    if not re.fullmatch(r'[0-9a-fA-F]{7,64}', commit):
        raise BenchmarkError('Commit must be a hexadecimal SHA')
    lines = ['# Freeze record', f'- plan commit: {commit}',
             f'- PLAN.md sha256: {digest(c.plan_path)}',
             f'- manifest.jsonl sha256: {digest(handoff / "manifest.jsonl")}',
             f'- archives.sha256 sha256: {digest(handoff / "archives.sha256")}',
             f'- seed: {c.SEED}', f'- n: {c.N}',
             f'- attempt ceiling per UTC day: {c.ATTEMPT_CEILING}',
             '- recorded (UTC): ' + utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')]
    with path.open('x', encoding='utf-8', newline='') as stream:
        stream.write('\n'.join(lines) + '\n')


def verify_freeze(c, handoff):
    path = c.plan_path.with_name('FREEZE.md')
    if not path.is_file():
        raise BenchmarkError('FREEZE.md is missing')
    fields = dict(line[2:].split(': ', 1) for line in path.read_text(encoding='utf-8').splitlines()
                  if line.startswith('- ') and ': ' in line)
    for name, target in [('PLAN.md', c.plan_path),
                         ('manifest.jsonl', handoff / 'manifest.jsonl'),
                         ('archives.sha256', handoff / 'archives.sha256')]:
        if fields.get(name + ' sha256') != digest(target):
            raise BenchmarkError(f'{name} hash mismatch with FREEZE.md')
    for name, expected in [('seed', c.SEED), ('n', c.N),
                           ('attempt ceiling per UTC day', c.ATTEMPT_CEILING)]:
        if fields.get(name) != str(expected):
            raise BenchmarkError(f'FREEZE.md {name} mismatch')
    root = Path(__file__).resolve().parents[2]
    if (root / '.git').exists():
        result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'],
                                capture_output=True, text=True, check=True)
        if result.stdout.strip():
            raise BenchmarkError('Repository must be clean from freeze through the last request')


def raw_json(raw):
    def invalid_constant(_):
        raise ValueError('Nonfinite JSON number')
    return json.loads(raw, parse_float=Decimal, parse_int=Decimal,
                      parse_constant=invalid_constant)


def envelope(body):
    return (isinstance(body, dict) and isinstance(body.get('data'), list)
            and 'next_cursor' in body and (body['next_cursor'] is None
            or isinstance(body['next_cursor'], str) and bool(body['next_cursor'])))


def numeric_equal(value, expected):
    return isinstance(value, Decimal) and value.is_finite() and value == expected


def value_equal(row, draw):
    if 'value' not in row:
        return False
    value = row['value']
    expected = source_value(draw['value'])
    return value is None if expected is None else numeric_equal(value, expected)


def key_comparisons(row, draw):
    mapping = {'accession_id': 'adsh', 'tag': 'tag', 'taxonomy': 'version',
               'period_end': 'ddate', 'unit': 'uom', 'segments': 'segments', 'coreg': 'coreg'}
    checks = {}
    for api, archive in mapping.items():
        value = row.get(api)
        if api in {'segments', 'coreg'} and value is None:
            value = ''
        checks[api] = api in row and isinstance(value, str) and value == draw[archive]
    checks['duration_quarters'] = numeric_equal(row.get('duration_quarters'), draw['qtrs'])
    return checks


def string_row(row):
    return {key: (value if isinstance(value, str) else str(value) if isinstance(value, Decimal)
                  else json_text(value)) for key, value in row.items()}


def page_evidence(rows, draw, query):
    evidence = {'unit': False, 'period': False, 'exact': None, 'selected_row': None,
                'compared_fields': None, 'difference_rows': []}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if query == 'before':
            if row.get('accession_id') == draw['adsh']:
                evidence['exact'] = 'PRESENT_BEFORE_FILING_DATE'
                evidence['selected_row'] = string_row(row)
                break
            continue
        checks = key_comparisons(row, draw)
        if all(checks.values()):
            value_matches = value_equal(row, draw)
            filing_matches = (row.get('filed') == draw['filed']
                              and numeric_equal(row.get('cik'), draw['cik']))
            evidence['exact'] = ('VALUE_DIFFERS' if not value_matches else
                                 'MATCH' if filing_matches else 'FILING_FIELDS_DIFFER')
            evidence['selected_row'] = string_row(row)
            evidence['compared_fields'] = dict(checks, value=value_matches,
                                               filed=row.get('filed') == draw['filed'],
                                               cik=numeric_equal(row.get('cik'), draw['cik']))
            break
        unit = (all(v for k, v in checks.items() if k != 'unit')
                and isinstance(row.get('unit'), str) and not checks['unit'])
        period_fields_valid = (isinstance(row.get('period_end'), str)
                               and isinstance(row.get('duration_quarters'), Decimal)
                               and row['duration_quarters'].is_finite()
                               and row['duration_quarters'] == row['duration_quarters'].to_integral_value())
        try:
            period_fields_valid = period_fields_valid and date.fromisoformat(row['period_end']).isoformat() == row['period_end']
        except (ValueError, KeyError):
            period_fields_valid = False
        period = (all(v for k, v in checks.items() if k not in {'period_end', 'duration_quarters'})
                  and period_fields_valid and value_equal(row, draw)
                  and not (checks['period_end'] and checks['duration_quarters']))
        evidence['unit'] |= unit
        evidence['period'] |= period
        if unit or period:
            evidence['difference_rows'].append(string_row(row))
    return evidence


def new_query():
    return {'pages': [], 'outcome': None, 'evidence': {'unit': False, 'period': False,
            'exact': None, 'selected_row': None, 'compared_fields': None, 'difference_rows': []}}


def make_http_client(hook):
    """The only HTTP factory; tests inject a MockTransport here."""
    return httpx.Client(timeout=30.0, follow_redirects=False, event_hooks={'response': [hook]})


class Runner:
    def __init__(self, c, handoff):
        self.c, self.handoff = c, handoff
        self.draws = records(handoff / 'manifest.jsonl')
        if len(self.draws) != c.N or [d['draw_id'] for d in self.draws] != list(range(c.N)):
            raise BenchmarkError('Manifest draw count or order differs from the plan')
        for draw in self.draws:
            if draw['queries'] != {'on': query_parameters(draw, c),
                                   'before': query_parameters(draw, c, True)}:
                raise BenchmarkError('Manifest query parameters differ from the plan')
        self.start_day = utcnow().date().isoformat()
        self.path = handoff / 'state.json'
        self.result_path = handoff / 'results.jsonl'
        self.outcome_path = handoff / 'outcomes.jsonl'
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            if self.result_path.exists() or self.outcome_path.exists():
                raise BenchmarkError('Missing state for existing run evidence; allowances cannot be reset')
            self.state = {'run_started_utc': timestamp(), 'attempts_by_day': {}, 'attempts_total': 0,
                          'current_utc_day': self.start_day, 'status': 'PARTIAL',
                          'limit_read': new_query(), 'rate_limit': min(c.ALLOWED_RATE_LIMITS),
                          'admitted': False, 'draws': {}, 'completed': [], 'pending': None,
                          'wait_until': None, 'last_attempt_utc': None, 'stop_reason': None}
        self.last_start = None
        self.captured = None
        self.http = make_http_client(self.hook)
        try:
            self.client = DataClient(api_key=None, max_rate_limit_retries=0, client=self.http)
        except (ArkleonAPIError, ValueError):
            self.http.close()
            raise BenchmarkError('Client admission failed; check ARKLEON_API_KEY') from None
        self.recover()

    def save(self):
        atomic_write(self.path, json_text(self.state) + '\n')

    def hook(self, response):
        self.captured = {'status': response.status_code,
                         'headers': {k.lower(): v for k, v in response.headers.items()
                                     if k.lower().startswith('ratelimit-') or k.lower() == 'retry-after'},
                         'body': None}
        response.read()
        self.captured['body'] = response.content

    def query_state(self, draw_id, query):
        if query == 'LIMIT_READ':
            return self.state['limit_read']
        return self.state['draws'][str(draw_id)]['queries'][query]

    def recover(self):
        pending = self.state['pending']
        if pending is not None:
            identity = lambda item: tuple(item[k] for k in ('draw_id', 'query', 'page', 'attempt'))
            found = [item for item in records(self.result_path) if identity(item) == identity(pending)]
            if len(found) > 1:
                raise BenchmarkError('Duplicate attempt records')
            if found:
                record = found[0]
            else:
                record = dict(pending, status=None, error='InterruptedAttempt', headers=None,
                              next_cursor_present=None, next_cursor=None, row_count=None,
                              accession_rows=[], failure_reason='interrupted send', action='retry',
                              evidence=None, wait_until=self.state['wait_until'])
                append_record(self.result_path, record)
            self.apply(record)
        finished = records(self.outcome_path)
        ids = [item['draw_id'] for item in finished]
        if len(ids) != len(set(ids)) or not set(ids) <= {d['draw_id'] for d in self.draws}:
            raise BenchmarkError('Invalid completed draw IDs')
        self.state['completed'] = ids
        self.save()

    def pace(self):
        interval = 60 / (0.8 * self.state['rate_limit'])
        delay = 0.0
        if self.last_start is not None:
            delay = max(delay, interval - (time.monotonic() - self.last_start))
        elif self.state['last_attempt_utc']:
            previous = datetime.fromisoformat(self.state['last_attempt_utc'])
            delay = max(delay, interval - (utcnow() - previous).total_seconds())
        if self.state['wait_until']:
            deadline = datetime.fromisoformat(self.state['wait_until'])
            delay = max(delay, (deadline - utcnow()).total_seconds())
        if delay > 0:
            time.sleep(delay)

    def reserve(self, draw_id, query, page):
        self.pace()
        today = utcnow().date().isoformat()
        if today != self.start_day:
            raise Partial('UTC day changed; resume explicitly on the later day')
        counts = self.state['attempts_by_day']
        if counts.get(today, 0) + 1 > self.c.ATTEMPT_CEILING:
            raise Partial('UTC-day attempt ceiling reached')
        counts[today] = counts.get(today, 0) + 1
        self.state['attempts_total'] += 1
        self.state['current_utc_day'] = today
        page['attempts'] += 1
        q = self.query_state(draw_id, query)
        pending = {'draw_id': draw_id, 'query': query, 'page': len(q['pages']),
                   'attempt': page['attempts'], 'utc': timestamp()}
        self.state['pending'] = pending
        self.state['last_attempt_utc'] = pending['utc']
        self.state['wait_until'] = None
        if draw_id is not None:
            self.state['draws'][str(draw_id)]['attempts_used'] += 1
        self.save()  # Reservation is durable before any send.
        self.last_start = time.monotonic()
        return pending

    def inspect(self, pending, draw, transport_error):
        captured = self.captured
        status = captured['status'] if captured else None
        headers = captured['headers'] if captured else None
        body = None
        if captured and captured['body'] is not None:
            try:
                body = raw_json(captured['body'])
            except (ValueError, UnicodeError):
                pass
        valid = envelope(body)
        rows = body.get('data') if isinstance(body, dict) else None
        raw_error = body.get('error') if isinstance(body, dict) else None
        error = raw_error if isinstance(raw_error, str) else transport_error
        header = headers.get('ratelimit-limit') if headers else None
        try:
            limit = int(header) if header is not None and re.fullmatch(r'[0-9]+', header) else None
        except ValueError:
            limit = None
        record = dict(pending, status=status, error=error, headers=headers,
                      next_cursor_present=('next_cursor' in body) if isinstance(body, dict) else
                      (False if captured and captured['body'] is not None else None),
                      next_cursor=body.get('next_cursor') if isinstance(body, dict) else None,
                      row_count=len(rows) if isinstance(rows, list) else None,
                      accession_rows=[string_row(row) for row in rows if isinstance(row, dict)
                                      and row.get('accession_id') == draw['adsh']]
                      if draw is not None and isinstance(rows, list) else [],
                      action='failed', failure_reason=None, evidence=None, wait_until=None)
        if status in {401, 403} or status == 429 and raw_error == 'quota_exceeded':
            record.update(action='stop', failure_reason='authorization or daily quota stop')
        elif transport_error or status is None or 500 <= status < 600:
            record.update(action='retry', failure_reason=transport_error or 'server failure')
        elif status == 429 and raw_error == 'rate_limited':
            try:
                delay = Decimal(headers.get('retry-after', ''))
                if not delay.is_finite() or delay < 0:
                    raise InvalidOperation
                rate = limit if limit in self.c.ALLOWED_RATE_LIMITS else self.state['rate_limit']
                interval = 60 / (0.8 * rate)
                remaining = max(0.0, interval - (time.monotonic() - self.last_start))
                deadline = utcnow() + timedelta(seconds=remaining + float(delay))
                record.update(action='retry', failure_reason='rate_limited', wait_until=timestamp(deadline))
            except (InvalidOperation, ValueError, OverflowError):
                record['failure_reason'] = 'missing or malformed Retry-After'
        elif 200 <= status < 300:
            if valid:
                record['action'] = 'accepted'
                if draw is not None:
                    record['evidence'] = page_evidence(rows, draw, pending['query'])
            else:
                record.update(action='retry', failure_reason='invalid page envelope')
        else:
            record['failure_reason'] = 'nonretryable HTTP response'
        if header is not None:
            if limit not in self.c.ALLOWED_RATE_LIMITS:
                record.update(action='stop', failure_reason='unrecognized RateLimit-Limit')
        elif pending['query'] == 'LIMIT_READ' and record['action'] == 'accepted':
            record.update(action='stop', failure_reason='missing RateLimit-Limit')
        return record

    def apply(self, record):
        q = self.query_state(record['draw_id'], record['query'])
        page = q['pages'][record['page'] - 1]
        headers = record['headers'] or {}
        header = headers.get('ratelimit-limit', '')
        if header.isdigit() and int(header) in self.c.ALLOWED_RATE_LIMITS:
            self.state['rate_limit'] = int(header)
        self.state['wait_until'] = record.get('wait_until')
        action = record['action']
        if action == 'accepted':
            page['done'], page['next_cursor'] = True, record['next_cursor']
            if record['query'] == 'LIMIT_READ':
                self.state['admitted'] = True
                q['outcome'] = 'ACCEPTED'
            else:
                incoming, evidence = record['evidence'], q['evidence']
                evidence['unit'] |= incoming['unit']
                evidence['period'] |= incoming['period']
                evidence['difference_rows'].extend(incoming['difference_rows'])
                if incoming['exact']:
                    for key in ('exact', 'selected_row', 'compared_fields'):
                        evidence[key] = incoming[key]
                    q['outcome'] = incoming['exact']
                elif record['next_cursor'] is None:
                    q['outcome'] = ('CLEAN' if record['query'] == 'before' else
                                    'UNIT_DIFFERS' if evidence['unit'] else
                                    'PERIOD_DIFFERS' if evidence['period'] else 'ABSENT')
        elif action == 'failed':
            q['outcome'] = 'FAILED'
        self.state['pending'] = None
        self.save()

    def fetch(self, draw, query, page, params):
        draw_id = draw['draw_id'] if draw is not None else None
        q = self.query_state(draw_id, query)
        while page['attempts'] < self.c.ATTEMPTS_PER_PAGE:
            try:
                pending = self.reserve(draw_id, query, page)
            except Partial:
                # An unsent base or continuation page has not consumed a page.
                if page['attempts'] == 0:
                    q['pages'].pop()
                    if draw_id is not None:
                        self.state['draws'][str(draw_id)]['pages_used'] -= 1
                raise
            self.captured = None
            transport_error = None
            try:
                if query == 'LIMIT_READ':
                    self.client.companies(limit=1)
                else:
                    self.client.facts(**params, cursor=page['cursor'])
            except httpx.RequestError as exc:
                transport_error = type(exc).__name__
            except ArkleonAPIError:
                pass  # Only the captured raw response determines classification.
            record = self.inspect(pending, draw, transport_error)
            append_record(self.result_path, record)
            self.apply(record)
            if record['action'] == 'stop':
                raise Partial(record['failure_reason'])
            if record['action'] != 'retry':
                return
        q['outcome'] = 'FAILED'
        self.save()

    def perform_query(self, draw, query):
        usage = self.state['draws'][str(draw['draw_id'])]
        q = usage['queries'][query]
        while q['outcome'] is None:
            pages = q['pages']
            if not pages or pages[-1].get('done'):
                extras = sum(max(0, len(item['pages']) - 1) for item in usage['queries'].values())
                if pages and extras >= self.c.EXTRA_PAGES_PER_FACT:
                    q['outcome'] = 'INCONCLUSIVE_PAGES'
                    self.save()
                    break
                cursor = pages[-1]['next_cursor'] if pages else None
                pages.append({'cursor': cursor, 'attempts': 0, 'done': False})
                usage['pages_used'] += 1
                self.save()
            self.fetch(draw, query, pages[-1], draw['queries'][query])
        return q['outcome']

    def execute(self):
        try:
            if len(self.state['completed']) == len(self.draws):
                self.state.update(status='COMPLETE', stop_reason=None)
                self.save()
                return 0
            limit = self.state['limit_read']
            if not self.state['admitted']:
                if limit['outcome'] == 'FAILED':
                    raise Partial('Limit-read attempt allowance exhausted')
                if not limit['pages']:
                    limit['pages'].append({'cursor': None, 'attempts': 0, 'done': False})
                self.fetch(None, 'LIMIT_READ', limit['pages'][0], {'limit': 1})
                if not self.state['admitted']:
                    raise Partial('Limit read failed')
            for draw in self.draws:
                if draw['draw_id'] in self.state['completed']:
                    continue
                usage = self.state['draws'].setdefault(str(draw['draw_id']), {
                    'pages_used': 0, 'attempts_used': 0,
                    'queries': {'on': new_query(), 'before': new_query()}})
                if draw['source_flag']:
                    on = draw['source_flag']
                    usage['queries']['on']['outcome'] = on
                else:
                    on = self.perform_query(draw, 'on')
                before = (self.perform_query(draw, 'before')
                          if on in {'MATCH', 'VALUE_DIFFERS', 'FILING_FIELDS_DIFFER'} else 'NOT_SENT')
                usage['queries']['before']['outcome'] = before
                outcome = {'draw_id': draw['draw_id'], 'on': on, 'before': before,
                           'pass_s1': on == 'MATCH', 'pass_s2': on == 'MATCH' and before == 'CLEAN',
                           'pages_used': usage['pages_used'], 'attempts_used': usage['attempts_used'],
                           'evidence': {name: q['evidence'] for name, q in usage['queries'].items()}}
                append_record(self.outcome_path, outcome)
                self.state['completed'].append(draw['draw_id'])
                self.save()
            self.state.update(status='COMPLETE', stop_reason=None)
            self.save()
            return 0
        except Partial as exc:
            self.state.update(status='PARTIAL', stop_reason=str(exc))
            self.save()
            print(f'PARTIAL: {exc}', file=sys.stderr)
            return 3
        finally:
            self.http.close()


def run(c, handoff):
    verify_plan(c)
    handoff = external_directory(handoff)
    verify_freeze(c, handoff)
    if 'ARKLEON_API_KEY' not in os.environ:
        raise BenchmarkError('ARKLEON_API_KEY is not set')
    return Runner(c, handoff).execute()


def rounded_bound(value):
    value = Fraction(value)
    if value == 0:
        return Decimal(0)
    exponent = 0
    while value < Fraction(10) ** exponent:
        exponent -= 1
    while value >= Fraction(10) ** (exponent + 1):
        exponent += 1
    step = Fraction(10) ** (exponent - 3)
    units = value / step
    # Decimal ROUND_CEILING acts on the exact integer quotient and remainder.
    whole, remainder = divmod(units.numerator, units.denominator)
    with localcontext() as ctx:
        ctx.prec = max(28, len(str(abs(whole))) + 8)
        scaled = Decimal(whole) + (Decimal('0.5') if remainder else Decimal(0))
        return scaled.to_integral_value(rounding=ROUND_CEILING).scaleb(exponent - 3)


def format_bound(value):
    rounded = rounded_bound(value)
    if not rounded:
        return '0'
    with localcontext() as ctx:
        ctx.prec = max(28, abs(rounded.adjusted()) + 8)
        return format(rounded.quantize(Decimal(1).scaleb(rounded.adjusted() - 3)), 'f')


def upper_bound(x, m, confidence):
    if type(x) is not int or type(m) is not int or not 0 <= x <= m or m <= 0:
        raise ValueError('Require integers 0 <= x <= m and m > 0')
    confidence = Fraction(confidence)
    if not 0 < confidence < 1:
        raise ValueError('Confidence must lie between zero and one')
    if x == m:
        return Fraction(1)
    alpha = 1 - confidence

    def cdf(p):
        # Sum with a common denominator to keep exact arithmetic inexpensive.
        a, denominator = p.numerator, p.denominator
        b = denominator - a
        return Fraction(sum(math.comb(m, k) * a ** k * b ** (m - k)
                            for k in range(x + 1)), denominator ** m)

    lo, hi = Fraction(0), Fraction(1)
    iterations = 0
    while True:
        mid = (lo + hi) / 2
        tail = cdf(mid)
        iterations += 1
        if tail > alpha:
            lo = mid
        elif tail < alpha:
            hi = mid
        else:
            lo = hi = mid
        if iterations >= 60:
            if rounded_bound(lo) == rounded_bound(hi):
                return hi
            boundary = Fraction(rounded_bound(lo))
            if lo <= boundary <= hi and cdf(boundary) == alpha:
                return boundary


def report(c, handoff):
    verify_plan(c)
    handoff = external_directory(handoff)
    draws, outcomes = records(handoff / 'manifest.jsonl'), records(handoff / 'outcomes.jsonl')
    attempts = records(handoff / 'results.jsonl')
    state_path = handoff / 'state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        print(f"run started (UTC) | {state.get('run_started_utc')}")
    else:
        print('run started (UTC) | none')
    print('UTC day | attempts')
    for day, count in sorted(Counter(item['utc'][:10] for item in attempts).items()):
        print(f'{day} | {count}')
    for query in ('on', 'before'):
        print(f'Q-{query} class | count')
        for name, count in sorted(Counter(item[query] for item in outcomes).items()):
            print(f'{name} | {count}')
    by_id = {draw['draw_id']: draw for draw in draws}
    print('quarter | outcomes | draws')
    completed = Counter(by_id[item['draw_id']]['quarter'] for item in outcomes if item['draw_id'] in by_id)
    total = Counter(draw['quarter'] for draw in draws)
    for quarter in c.QUARTERS:
        print(f'{quarter} | {completed[quarter]} | {total[quarter]}')
    ids = [item['draw_id'] for item in outcomes]
    if len(ids) != len(set(ids)) or not set(ids) <= set(by_id):
        raise BenchmarkError('Invalid outcomes: duplicate or unknown draw ID')
    missing = len(set(by_id) - set(ids))
    if missing:
        print(f'no bound: {missing} draws without an outcome')
        return
    if len(draws) != c.N:
        raise BenchmarkError('Manifest size differs from N')
    templates = re.findall(r'^```text\s*\n(.*?)^```', c.plan_text, re.M | re.S)
    if len(templates) != 2:
        raise BenchmarkError('PLAN.md must supply both result sentence templates')
    excluded = {'FAILED', 'INCONCLUSIVE_PAGES', 'SOURCE_MALFORMED', 'SOURCE_DUPLICATE'}
    cache = {}

    def bound(x, m):
        if not m:
            return 'undefined'
        if (x, m) not in cache:
            cache[x, m] = format_bound(upper_bound(x, m, c.CONFIDENCE))
        return cache[x, m]

    for index, predicate in enumerate(('pass_s1', 'pass_s2')):
        resolved = [item for item in outcomes if item['on'] not in excluded
                    and (index == 0 or item['before'] not in {'INCONCLUSIVE_PAGES', 'FAILED'})]
        x, m = sum(not item[predicate] for item in outcomes), c.N
        xr, mr = sum(not item[predicate] for item in resolved), len(resolved)
        values = {'x': x, 'm': m, 'U': bound(x, m), 'x_r': xr, 'm_r': mr,
                  'U_r': bound(xr, mr), 'confidence': str(Decimal(c.CONFIDENCE.numerator) / Decimal(c.CONFIDENCE.denominator))}
        print(f'S{index + 1} | non-passes | trials | upper bound')
        print(f'headline | {x} | {m} | {values["U"]}')
        print(f'resolved-only | {xr} | {mr} | {values["U_r"]}')
        sentence = templates[index].strip()
        for key, value in values.items():
            sentence = sentence.replace(f'<{key}>', str(value))
        if mr == 0:
            sentence = sentence.replace('mismatch fraction 0/0', 'mismatch fraction undefined')
        print(sentence)


def audit(c, handoff):
    verify_plan(c)
    handoff = external_directory(handoff)
    state = json.loads((handoff / 'state.json').read_text(encoding='utf-8'))
    attempts = records(handoff / 'results.jsonl')
    draws, outcomes = records(handoff / 'manifest.jsonl'), records(handoff / 'outcomes.jsonl')
    failures = []
    daily = Counter(item['utc'][:10] for item in attempts)
    if dict(daily) != state['attempts_by_day'] or len(attempts) != state['attempts_total']:
        failures.append('attempt journal and state counters differ')
    if any(count > c.ATTEMPT_CEILING for count in daily.values()):
        failures.append('UTC-day ceiling exceeded')
    ids = [item['draw_id'] for item in outcomes]
    manifest_ids = {item['draw_id'] for item in draws}
    if len(ids) != len(set(ids)) or not set(ids) <= manifest_ids:
        failures.append('duplicate or unknown outcome draw ID')
    grouped = {}
    for item in attempts:
        identity = (item['draw_id'], item['query'], item['page'])
        grouped.setdefault(identity, []).append(item['attempt'])
        if item['query'] not in {'LIMIT_READ', 'on', 'before'}:
            failures.append('unknown query name')
        if item['query'] == 'LIMIT_READ':
            if item['draw_id'] is not None or item['page'] != 1:
                failures.append('invalid limit-read allocation')
        elif item['draw_id'] not in manifest_ids:
            failures.append('unknown attempt draw ID')
    for numbers in grouped.values():
        if sorted(numbers) != list(range(1, len(numbers) + 1)) or len(numbers) > c.ATTEMPTS_PER_PAGE:
            failures.append('per-page attempt allowance or sequence violated')
    limit_pages = state['limit_read']['pages']
    limit_attempts = sum(page['attempts'] for page in limit_pages)
    if (len(limit_pages) > 1 or limit_attempts > c.ATTEMPTS_PER_PAGE
            or limit_attempts != len(grouped.get((None, 'LIMIT_READ', 1), []))):
        failures.append('limit-read allowance or state differs from journal')
    for draw_id, query, page in grouped:
        if query in {'on', 'before'}:
            usage = state['draws'].get(str(draw_id))
            if usage is None or not 1 <= page <= len(usage['queries'][query]['pages']):
                failures.append('journal page missing from persisted draw state')
    for draw_id, usage in state['draws'].items():
        extra = sum(max(0, len(q['pages']) - 1) for q in usage['queries'].values())
        if extra > c.EXTRA_PAGES_PER_FACT:
            failures.append(f'draw {draw_id}: extra-page allowance exceeded')
        page_count = sum(len(q['pages']) for q in usage['queries'].values())
        attempt_count = sum(p['attempts'] for q in usage['queries'].values() for p in q['pages'])
        if page_count != usage['pages_used'] or attempt_count != usage['attempts_used']:
            failures.append(f'draw {draw_id}: usage counters differ')
        for query, q in usage['queries'].items():
            for page, item in enumerate(q['pages'], 1):
                if item['attempts'] > c.ATTEMPTS_PER_PAGE or item['attempts'] != len(grouped.get((int(draw_id), query, page), [])):
                    failures.append(f'draw {draw_id}: page attempts differ')
    for draw_id in manifest_ids:
        extras = sum(max((page for d, q, page in grouped if d == draw_id and q == query), default=1) - 1
                     for query in ('on', 'before'))
        if extras > c.EXTRA_PAGES_PER_FACT:
            failures.append(f'draw {draw_id}: journal extra-page allowance exceeded')
    if state['pending'] is not None:
        failures.append('unreconciled interrupted reservation; resume first')
    if set(state['completed']) != set(ids):
        failures.append('completed draw state differs from outcomes')
    for outcome in outcomes:
        usage = state['draws'].get(str(outcome['draw_id']))
        if usage is None or any(outcome[key] != usage[key] for key in ('pages_used', 'attempts_used')):
            failures.append('outcome usage differs from draw state')
    for failure in failures:
        print(failure)
    if not failures:
        print('PASS')
    return 1 if failures else 0


def main(argv=None, *, plan_path=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('hash-plan')
    prep = commands.add_parser('prepare')
    prep.add_argument('--archives', type=Path, required=True)
    prep.add_argument('--out', type=Path, required=True)
    freezing = commands.add_parser('freeze')
    freezing.add_argument('--commit', required=True)
    freezing.add_argument('--handoff', type=Path, required=True)
    for name in ('run', 'report', 'audit'):
        sub = commands.add_parser(name)
        sub.add_argument('--handoff', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        c = load_constants(plan_path)
        if args.command == 'hash-plan':
            hash_plan(c)
        else:
            verify_plan(c)
            if args.command == 'prepare':
                prepare(c, args.archives, args.out)
            elif args.command == 'freeze':
                freeze(c, args.handoff, args.commit)
            elif args.command == 'run':
                return run(c, args.handoff)
            elif args.command == 'report':
                report(c, args.handoff)
            elif args.command == 'audit':
                return audit(c, args.handoff)
        return 0
    except (BenchmarkError, OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(f'Refused: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
