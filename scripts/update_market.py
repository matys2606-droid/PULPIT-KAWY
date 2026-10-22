#!/usr/bin/env python3
"""Refresh public daily coffee quotations and NBP FX; no API keys required."""
import argparse
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://coffeeboard.gov.in/'
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

def download(url):
    req = Request(url, headers={'User-Agent':'CoffeeMarketDashboard/1.0 (daily public report reader)', 'Accept':'text/html,application/json'})
    with urlopen(req, timeout=30) as response:
        raw = response.read(2_000_001)
        if len(raw)>2_000_000: raise ValueError('Source response too large')
        return raw.decode('utf-8-sig')

def refresh(doc, getter=download, now=None):
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    doc['lastAttemptAt'] = stamp
    doc['errors'] = []
    failed = False
    try:
        latest, curve = parse_board(getter(SOURCE))
        if doc.get('latest',{}).get('date','') > latest['date']:
            raise ValueError('Source session is older than saved session')
        history = {x['date']:x for x in doc.get('history',[])}
        history[latest['date']] = latest
        doc.update(latest=latest,curve=curve,history=[history[k] for k in sorted(history)],lastSuccessAt=stamp)
    except Exception as exc:
        failed = True
        doc['errors'].append('Coffee Board: ' + str(exc))
    doc.setdefault('fx', {})
    for currency in ('usd','eur'):
        try:
            url=f'https://api.nbp.pl/api/exchangerates/rates/a/{currency}/?format=json'
            record=json.loads(getter(url))['rates'][0]
            day=date.fromisoformat(record['effectiveDate']); rate=float(record['mid'])
            if day>datetime.now(timezone.utc).date() or not 0<rate<100: raise ValueError('Invalid FX data')
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
    for err in doc['errors']: print(err,file=sys.stderr)
    if failed: return 1
    return 0
if __name__=='__main__': sys.exit(main())
