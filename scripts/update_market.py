#!/usr/bin/env python3
"""Refresh public daily coffee quotations and NBP FX; no API keys required."""
import argparse
import math
from datetime import date, datetime, timezone, timedelta
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://coffeeboard.gov.in/'
INVESTING = {
    'arabica': 'https://pl.investing.com/commodities/us-coffee-c-historical-data',
    'robusta': 'https://pl.investing.com/commodities/london-coffee-historical-data',
}
FT = {
    'arabica': 'https://markets.ft.com/data/commodities/tearsheet/historical?c=Coffee%20(Arabica)',
    'robusta': 'https://markets.ft.com/data/commodities/tearsheet/historical?c=Coffee%20(Robusta)',
}
MONTHS = dict(zip(('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'), range(1,13)))
CODES = dict(zip(range(1,13), 'FGHJKMNQUVXZ'))

class Spans(HTMLParser):
    def __init__(self):
        super().__init__(); self.values = {}; self.current = None
    def handle_starttag(self, tag, attrs):
        if tag == 'span':
            self.current = dict(attrs).get('id')
            if self.current: self.values[self.current] = ''
    def handle_data(self, text):
        if self.current: self.values[self.current] += text
    def handle_endtag(self, tag):
        if tag == 'span': self.current = None

def parse_board(html, today=None):
    p = Spans(); p.feed(html)
    def field(suffix):
        value = p.values.get('GridView1_' + suffix + '_0', '').strip()
        if not value: raise ValueError('Missing source field: ' + suffix)
        return value
    session = datetime.strptime(field('lbldate1'), '%d/%m/%Y').date()
    if session > (today or datetime.now(timezone.utc).date()):
        raise ValueError('Future session date in source')
    def contract(month, value, kind):
        match = re.fullmatch(r'([A-Z][a-z]{2})-(\d{4})', field(month))
        if not match or match[1] not in MONTHS: raise ValueError('Invalid delivery month')
        y, m = int(match[2]), MONTHS[match[1]]
        if kind=='a' and m not in (3,5,7,9,12): raise ValueError('Invalid arabica month')
        if kind=='r' and m not in (1,3,5,7,9,11): raise ValueError('Invalid robusta month')
        delivery = f'{y:04}-{m:02}'
        if delivery < session.strftime('%Y-%m') or y > session.year+4:
            raise ValueError('Invalid delivery date')
        price = float(field(value).replace(',', ''))
        if not (10 < price < 2000 if kind=='a' else 100 < price < 20000):
            raise ValueError('Price out of validation bounds')
        return dict(delivery=delivery, label=field(month), contract=('KC' if kind=='a' else 'RC')+CODES[m]+str(y)[-2:], price=price)
    a = [contract('lblmonth','lblmonthvalue','a'), contract('lblmonth1','lblmonth1value','a'), contract('lblmonth2','month1value','a')]
    r = [contract('month','monthvalue','r'), contract('month1','lblmonth2value','r'), contract('month2','month2value','r')]
    for curve in (a,r):
        deliveries = [x['delivery'] for x in curve]
        if deliveries != sorted(set(deliveries)): raise ValueError('Unordered/duplicate contracts')
    latest = dict(date=session.isoformat(), arabica=a[0]['price'], robusta=r[0]['price'],contractA=a[0]['contract'],contractR=r[0]['contract'],source='Coffee Board of India — Futures Price',sourceUrl=SOURCE)
    return latest, dict(date=session.isoformat(), arabica=a, robusta=r)

def parse_investing(html, kind, today=None):
    # Read only public server-rendered historical data, never the live headline quote.
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match: raise ValueError('Missing historical data JSON')
    state = json.loads(match[1])['props']['pageProps']['state']
    title = state['pageInfoStore']['titles']['h1_head']
    prefix = 'KC' if kind == 'arabica' else 'RC'
    contract = re.search(r"'([0-9]{2})\s*\((" + prefix + r"[FGHJKMNQUVXZ])[0-9]{1,2}\)", title)
    if not contract: raise ValueError('Unrecognized coffee contract')
    code = contract[2] + contract[1]
    records = {}
    for row in state['historicalDataStore']['historicalData']['data']:
        day = date.fromisoformat(row['rowDateTimestamp'][:10])
        # Morning daily job: today's row may still be an unfinished session.
        if day >= (today or datetime.now(timezone.utc).date()): continue
        price = round(float(row['last_closeRaw']), 2)
        low, high = float(row['last_minRaw']), float(row['last_maxRaw'])
        if not (10 < price < 2000 if kind == 'arabica' else 100 < price < 20000):
            raise ValueError('Historical close outside validation bounds')
        if not low <= price <= high: raise ValueError('Close outside session range')
        records[day.isoformat()] = price
    if not records: raise ValueError('No completed sessions')
    return code, records

def investing_latest(getter, today=None):
    a, ah = parse_investing(getter(INVESTING['arabica']), 'arabica', today)
    r, rh = parse_investing(getter(INVESTING['robusta']), 'robusta', today)
    common = sorted(set(ah) & set(rh))
    if not common: raise ValueError('No common coffee session')
    day = common[-1]
    # Do not silently select an old overlap when one market has newer data.
    if day != max(ah) or day != max(rh): raise ValueError('Coffee session dates differ')
    return dict(date=day, arabica=ah[day], robusta=rh[day], contractA=a, contractR=r,
                source='Investing.com — historyczne ceny zamknięcia (dane pochodne)',
                sourceUrl=INVESTING['robusta'], sourceUrls=INVESTING,
                priceType='historical_close')

class HistoricalTable(HTMLParser):
    """Read only FT's historical table, preserving separate mobile date labels."""
    def __init__(self):
        super().__init__()
        self.active = False
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.active = 'mod-tearsheet-historical-prices__results' in dict(attrs).get('class', '').split()
        if not self.active:
            return
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, text):
        if self.active and self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.active and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            self.active = False

def parse_ft(html, kind, today=None):
    headings = re.findall(r'<h1\b[^>]*>(.*?)</h1>', html, re.I | re.S)
    identity = ' '.join(re.sub(r'<[^>]+>', ' ', heading) for heading in headings)
    if kind not in FT or not re.search(r'Coffee\s*\(' + kind + r'\)', identity, re.I):
        raise ValueError('Wrong FT coffee instrument')
    table = HistoricalTable()
    table.feed(html)
    if not table.rows or table.rows[0] != ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']:
        raise ValueError('Missing or changed FT historical price table')
    cutoff = today or datetime.now(timezone.utc).date()
    records = {}
    for row in table.rows[1:]:
        if len(row) != 6:
            raise ValueError('Invalid FT historical row')
        match = re.match(r'[A-Za-z]+, ([A-Za-z]+ \d{1,2}, \d{4})(?:\s|$)', row[0])
        if not match:
            raise ValueError('Missing FT session date')
        day = datetime.strptime(match[1], '%B %d, %Y').date()
        if day > cutoff:
            raise ValueError('Future FT session date')
        if day == cutoff:
            continue  # Today's row may still be an unfinished session.
        opening, high, low, close = (float(value.replace(',', '')) for value in row[1:5])
        lower, upper = (10, 2000) if kind == 'arabica' else (100, 20000)
        if not all(math.isfinite(value) and lower < value < upper for value in (opening, high, low, close)):
            raise ValueError('FT price outside validation bounds')
        if not low <= opening <= high or not low <= close <= high:
            raise ValueError('FT price outside session range')
        key = day.isoformat()
        if key in records and records[key] != close:
            raise ValueError('Conflicting FT prices for the same session')
        records[key] = close
    if not records:
        raise ValueError('No completed FT coffee sessions')
    return records

def ft_latest(getter, today=None):
    a = parse_ft(getter(FT['arabica']), 'arabica', today)
    r = parse_ft(getter(FT['robusta']), 'robusta', today)
    if max(a) != max(r):
        raise ValueError('FT coffee session dates differ')
    day = max(a)
    # FT's selected commodity series does not identify the delivery month.
    # Never reuse a contract code from a different source or an older session.
    return dict(date=day, arabica=a[day], robusta=r[day], contractA='', contractR='',
                source='Financial Times / LSEG — historyczne ceny zamknięcia; seria wybrana przez dostawcę',
                sourceUrl=FT['arabica'], sourceUrls=FT, priceType='historical_close_unspecified_contract')

def download(url):
    req = Request(url, headers={'User-Agent':'CoffeeMarketDashboard/1.0 (daily public report reader)', 'Accept':'text/html,application/json'})
    with urlopen(req, timeout=30) as response:
        raw = response.read(2_000_001)
        if len(raw)>2_000_000: raise ValueError('Source response too large')
        return raw.decode('utf-8-sig')

def refresh(doc, getter=download, now=None):
    instant = now or datetime.now(timezone.utc)
    stamp = instant.isoformat(timespec='seconds')
    doc['lastAttemptAt'] = stamp
    doc['errors'] = []
    failed = False
    doc['warnings'] = []
    latest = None
    # Both coffee sessions have ended by 21:00 UTC; otherwise use prior days.
    cutoff = instant.date() + timedelta(days=int(instant.hour >= 21))
    def validate_session(record):
        if doc.get('latest', {}).get('date', '') > record['date']:
            raise ValueError('Source session is older than saved session; retained saved prices')
        if (instant.date() - date.fromisoformat(record['date'])).days > 4:
            raise ValueError('Coffee session is more than four days old')
        return record
    for name, fetch in (('Financial Times', ft_latest), ('Investing', investing_latest)):
        try:
            latest = validate_session(fetch(getter, cutoff))
            break
        except Exception as exc:
            doc['warnings'].append(name + ': ' + str(exc) + '. Próba źródła zapasowego.')
    try:
        board, curve = parse_board(getter(SOURCE), instant.date())
        if curve['date'] >= doc.get('curve', {}).get('date', ''):
            doc['curve'] = curve
        if latest is None:
            latest = validate_session(board)
            doc['warnings'].append('Użyto źródła zapasowego: Coffee Board of India.')
    except Exception as exc:
        if latest is None:
            failed = True
            doc['errors'].append('Coffee Board: ' + str(exc))
        else:
            doc['warnings'].append('Krzywa kontraktów Coffee Board: ' + str(exc))
    if latest is not None:
        history = {x['date']:x for x in doc.get('history',[])}
        history[latest['date']] = latest
        doc.update(latest=latest,history=[history[k] for k in sorted(history)],lastSuccessAt=stamp)
    doc.setdefault('fx', {})
    for currency in ('usd','eur'):
        try:
            url=f'https://api.nbp.pl/api/exchangerates/rates/a/{currency}/?format=json'
            record=json.loads(getter(url))['rates'][0]
            day=date.fromisoformat(record['effectiveDate']); rate=float(record['mid'])
            if day>instant.date() or not 0<rate<100: raise ValueError('Invalid FX data')
            previous=doc['fx'].get(currency,{})
            if previous.get('date','')>day.isoformat(): raise ValueError('FX date moved backwards')
            doc['fx'][currency]=dict(rate=rate,date=day.isoformat(),no=record['no'],source='NBP tabela A')
        except Exception as exc:
            doc['errors'].append('NBP '+currency.upper()+': '+str(exc)); failed=True
    doc['schemaVersion']=1
    return doc, failed

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--file',type=Path,default=ROOT/'data/market.json'); parser.add_argument('--html',type=Path)
    args=parser.parse_args()
    doc=json.loads(args.file.read_text()) if args.file.exists() else {}
    def getter(url):
        if args.html and url==SOURCE: return args.html.read_text()
        return download(url)
    doc, failed=refresh(doc,getter)
    if not doc.get('latest'): raise RuntimeError('No validated coffee data to publish')
    args.file.parent.mkdir(parents=True,exist_ok=True)
    temp=args.file.with_suffix('.tmp'); temp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n'); temp.replace(args.file)
    print('Session:',doc['latest']['date'],'Arabica:',doc['latest']['arabica'],'Robusta:',doc['latest']['robusta'])
    for warning in doc.get('warnings', []): print('Warning:', warning, file=sys.stderr)
    for err in doc['errors']: print(err,file=sys.stderr)
    if failed: return 1
    return 0
if __name__=='__main__': sys.exit(main())
