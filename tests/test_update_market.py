import importlib.util
from pathlib import Path
import unittest
from datetime import date
import json

spec=importlib.util.spec_from_file_location('update_market',Path(__file__).parents[1]/'scripts/update_market.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
FIELDS={'lbldate1':'21/10/2026','lblmonth':'Dec-2026','lblmonthvalue':'316.15','lblmonth1':'Mar-2027','lblmonth1value':'301.25','lblmonth2':'May-2027','month1value':'296.20','month':'Nov-2026','monthvalue':'3352','month1':'Jan-2027','lblmonth2value':'3364','month2':'Mar-2027','month2value':'3344'}
NOW=m.datetime(2026,10,23,6,tzinfo=m.timezone.utc)
def html(fields=None):
 return ''.join(f'<span id="GridView1_{k}_0">{v}</span>' for k,v in (fields or FIELDS).items())

class ParserTests(unittest.TestCase):
 def test_quotes_and_contract_mapping(self):
  latest,curve=m.parse_board(html(),date(2026,10,22))
  self.assertEqual((latest['date'],latest['arabica'],latest['robusta']),('2026-10-21',316.15,3352))
  self.assertEqual([x['contract'] for x in curve['arabica']],['KCZ26','KCH27','KCK27'])
  self.assertEqual([x['contract'] for x in curve['robusta']],['RCX26','RCF27','RCH27'])
  self.assertEqual(curve['robusta'][1]['price'],3364)
 def test_reject_future_date(self):
  with self.assertRaises(ValueError):m.parse_board(html(),date(2026,10,20))
 def test_reject_missing_quote(self):
  fields={**FIELDS};del fields['monthvalue']
  with self.assertRaises(ValueError):m.parse_board(html(fields),date(2026,10,22))
 def test_reject_zero_or_wrong_contract(self):
  for changes in ({'monthvalue':'0'},{'lblmonth1':'Feb-2027'},{'lblmonth1':'Dec-2026'}):
   with self.assertRaises(ValueError):m.parse_board(html({**FIELDS,**changes}),date(2026,10,22))
 def test_network_failure_preserves_prices_and_dates(self):
  latest,curve=m.parse_board(html(),date(2026,10,22))
  doc=dict(latest=latest,curve=curve,history=[latest],lastSuccessAt='2026-10-22T06:17:00+00:00')
  def fail(url):raise TimeoutError('Source timeout')
  out,failed=m.refresh(doc,fail,NOW)
  self.assertTrue(failed);self.assertEqual(out['latest'],latest)
  self.assertEqual(out['lastSuccessAt'],'2026-10-22T06:17:00+00:00');self.assertEqual(len(out['errors']),3)
 def test_same_session_does_not_duplicate_history(self):
  latest,curve=m.parse_board(html(),date(2026,10,22))
  def getter(url):
   return html() if url==m.SOURCE else json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-21','no':'205/A/NBP/2026'}]})
  doc,failed=m.refresh(dict(latest=latest,curve=curve,history=[latest]),getter,NOW)
  self.assertFalse(failed);self.assertEqual(len(doc['history']),1)
 def test_older_source_cannot_replace_newer_session(self):
  latest,curve=m.parse_board(html(),date(2026,10,22));latest['date']='2026-10-22'
  def getter(url):
   return html() if url==m.SOURCE else json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-21','no':'205/A/NBP/2026'}]})
  doc,failed=m.refresh(dict(latest=latest,curve=curve,history=[latest]),getter,NOW)
  self.assertTrue(failed);self.assertEqual(doc['latest']['date'],'2026-10-22')

 def investing_html(self, kind, day='2026-10-22', price=None):
  price = price or (311.4 if kind=='arabica' else 3280)
  title = "Kawa - Gru. '26 (KCZ6)" if kind=='arabica' else "Kawa - Lis. '26 (RCX6)"
  state={'pageInfoStore':{'titles':{'h1_head':title}},'historicalDataStore':{'historicalData':{'data':[{'rowDateTimestamp':day+'T00:00:00Z','last_closeRaw':str(price),'last_minRaw':str(price-1),'last_maxRaw':str(price+1)}]}}}
  return '<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':{'state':state}}})+'</script>'
 def test_investing_success_has_priority_and_preserves_curve(self):
  def getter(url):
   if url in m.INVESTING.values():return self.investing_html('arabica' if url==m.INVESTING['arabica'] else 'robusta')
   if url==m.SOURCE:return html()
   return json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-21','no':'test'}]})
  doc,failed=m.refresh({},getter,m.datetime(2026,10,23,6,tzinfo=m.timezone.utc))
  self.assertFalse(failed);self.assertEqual(doc['latest']['arabica'],311.4)
  self.assertEqual(doc['latest']['contractA'],'KCZ26');self.assertEqual(doc['latest']['contractR'],'RCX26')
  self.assertEqual(doc['curve']['date'],'2026-10-21');self.assertEqual(doc['latest']['date'],'2026-10-22')
 def test_investing_rejects_unfinished_session_and_bad_price(self):
  with self.assertRaises(ValueError):m.parse_investing(self.investing_html('robusta'),'robusta',date(2026,10,22))
  with self.assertRaises(ValueError):m.parse_investing(self.investing_html('robusta',price=1),'robusta',date(2026,10,23))
 def test_mismatched_investing_sessions_fall_back(self):
  def getter(url):
   if url==m.INVESTING['arabica']:return self.investing_html('arabica')
   if url==m.INVESTING['robusta']:return self.investing_html('robusta',day='2026-10-21')
   if url==m.SOURCE:return html()
   return json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-21','no':'test'}]})
  doc,failed=m.refresh({},getter,m.datetime(2026,10,23,6,tzinfo=m.timezone.utc))
  self.assertFalse(failed);self.assertEqual(doc['latest']['arabica'],316.15)
  self.assertIn('Coffee Board',doc['latest']['source']);self.assertTrue(doc['warnings'])

def ft_html(kind, day='Friday, October 23, 2026', values=None):
 # Structure and first OHLC row observed in FT's public historical tables.
 values = values or (['310.05','314.90','305.30','306.00'] if kind=='arabica'
                     else ['3,296.00','3,409.00','3,221.00','3,224.00'])
 return (f'<h1>Coffee ({kind.title()})</h1>'
         '<table class="mod-ui-table mod-tearsheet-historical-prices__results">'
         '<thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr></thead>'
         f'<tbody><tr><td><span class="mod-ui-hide-small-below">{day}</span>'
         '<span class="mod-ui-hide-medium-above">Fri, Oct 23, 2026</span></td>'
         + ''.join(f'<td>{v}</td>' for v in values)
         + '<td>6,803</td></tr></tbody></table>')

class FinancialTimesTests(unittest.TestCase):
 def test_closes_not_open_or_high_and_separate_mobile_date(self):
  self.assertEqual(m.parse_ft(ft_html('arabica'),'arabica',date(2026,10,24)),{'2026-10-23':306})
  self.assertEqual(m.parse_ft(ft_html('robusta'),'robusta',date(2026,10,24)),{'2026-10-23':3224})

 def test_wrong_instrument_and_changed_table_fail(self):
  for text in (ft_html('robusta'),ft_html('robusta')+'<option>Coffee (Arabica)</option>',
               ft_html('arabica').replace('<th>Close</th>','<th>Settlement</th>'),
               '<h1>Coffee (Arabica)</h1><table><tr><td>306</td></tr></table>'):
   with self.subTest(text=text),self.assertRaises(ValueError):
    m.parse_ft(text,'arabica',date(2026,10,24))

 def test_invalid_prices_and_dates_are_rejected(self):
  for values in (['310','314','305','NaN'],['310','314','305','315'],
                 ['310','314','305','0'],['320','314','305','306'],['310','inf','305','306']):
   with self.subTest(values=values),self.assertRaises(ValueError):
    m.parse_ft(ft_html('arabica',values=values),'arabica',date(2026,10,24))
  for cutoff in (date(2026,10,22),date(2026,10,23)):
   with self.subTest(cutoff=cutoff),self.assertRaises(ValueError):
    m.parse_ft(ft_html('arabica'),'arabica',cutoff)

 def test_unfinished_row_does_not_hide_previous_close(self):
  text=ft_html('arabica').replace('</tbody>',
       '<tr><td>Thursday, October 22, 2026</td><td>310</td><td>315</td><td>305</td><td>312.45</td><td>100</td></tr></tbody>')
  self.assertEqual(m.parse_ft(text,'arabica',date(2026,10,23)),{'2026-10-22':312.45})

 def test_mismatched_latest_sessions_are_not_silently_joined(self):
  def getter(url):
   return ft_html('arabica') if url==m.FT['arabica'] else ft_html('robusta','Thursday, October 22, 2026')
  with self.assertRaises(ValueError):m.ft_latest(getter,date(2026,10,24))

 def test_live_workflow_uses_ft_without_investing_and_retains_curve(self):
  def getter(url):
   if url in m.FT.values():return ft_html('arabica' if url==m.FT['arabica'] else 'robusta')
   if url in m.INVESTING.values():self.fail('Working FT must not depend on Investing')
   if url==m.SOURCE:return html()
   return json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-23','no':'test'}]})
  now=m.datetime(2026,10,25,6,tzinfo=m.timezone.utc)
  doc,failed=m.refresh({},getter,now)
  self.assertFalse(failed)
  self.assertEqual(doc['warnings'],[])
  self.assertEqual((doc['latest']['arabica'],doc['latest']['robusta']),(306,3224))
  self.assertEqual(doc['latest']['contractA'],'')
  self.assertEqual(doc['latest']['contractR'],'')
  self.assertEqual(doc['curve']['date'],'2026-10-21')
  self.assertEqual(doc['lastSuccessAt'],now.isoformat(timespec='seconds'))
  doc,failed=m.refresh(doc,getter,now)
  self.assertFalse(failed);self.assertEqual(len(doc['history']),1)

 def test_stale_sources_cannot_report_success(self):
  def getter(url):
   if url in m.FT.values():return ft_html('arabica' if url==m.FT['arabica'] else 'robusta')
   if url==m.SOURCE:return html()
   raise TimeoutError('Unavailable')
  latest={'date':'2026-10-23','arabica':307.45,'robusta':3228}
  doc,failed=m.refresh({'latest':latest,'history':[latest],'lastSuccessAt':'unchanged'},getter,
                       m.datetime(2026,10,29,6,tzinfo=m.timezone.utc))
  self.assertTrue(failed);self.assertEqual(doc['latest'],latest)
  self.assertEqual(doc['lastSuccessAt'],'unchanged')

if __name__=='__main__':unittest.main()
