import importlib.util
from pathlib import Path
import unittest
from datetime import date
import json

spec=importlib.util.spec_from_file_location('update_market',Path(__file__).parents[1]/'scripts/update_market.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
FIELDS={'lbldate1':'21/10/2026','lblmonth':'Dec-2026','lblmonthvalue':'316.15','lblmonth1':'Mar-2027','lblmonth1value':'301.25','lblmonth2':'May-2027','month1value':'296.20','month':'Nov-2026','monthvalue':'3352','month1':'Jan-2027','lblmonth2value':'3364','month2':'Mar-2027','month2value':'3344'}
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
  out,failed=m.refresh(doc,fail)
  self.assertTrue(failed);self.assertEqual(out['latest'],latest)
  self.assertEqual(out['lastSuccessAt'],'2026-10-22T06:17:00+00:00');self.assertEqual(len(out['errors']),3)
 def test_same_session_does_not_duplicate_history(self):
  latest,curve=m.parse_board(html(),date(2026,10,22))
  def getter(url):
   return html() if url==m.SOURCE else json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-21','no':'205/A/NBP/2026'}]})
  doc,failed=m.refresh(dict(latest=latest,curve=curve,history=[latest]),getter)
  self.assertFalse(failed);self.assertEqual(len(doc['history']),1)
 def test_older_source_cannot_replace_newer_session(self):
  latest,curve=m.parse_board(html(),date(2026,10,22));latest['date']='2026-10-22'
  def getter(url):
   return html() if url==m.SOURCE else json.dumps({'rates':[{'mid':4,'effectiveDate':'2026-10-21','no':'205/A/NBP/2026'}]})
  doc,failed=m.refresh(dict(latest=latest,curve=curve,history=[latest]),getter)
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

if __name__=='__main__':unittest.main()
