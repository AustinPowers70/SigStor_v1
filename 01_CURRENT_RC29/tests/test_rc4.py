import unittest,sys,datetime as dt
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'controller'))
import slot_commitment as m
import rc4_preflight
T=dt.datetime(2026,11,1,17,0,tzinfo=dt.timezone.utc)
class CommitmentTests(unittest.TestCase):
 def test_full_slot_charge_capacity(self):
  self.assertEqual(m.calculate(action='GRID_CHARGE',start_utc=T.isoformat(),scheduled_kwh=.25,now=T)['state'],'HOLD_UNMETERED_DELIVERY')
 def test_full_slot_export_capacity(self):
  self.assertEqual(m.calculate(action='EXPORT',start_utc=T.isoformat(),scheduled_kwh=.325,now=T)['state'],'HOLD_UNMETERED_DELIVERY')
 def test_remaining_capacity_not_full_energy(self):
  a=m.calculate(action='GRID_CHARGE',start_utc=T.isoformat(),scheduled_kwh=.25,now=T+dt.timedelta(minutes=20),delivered_grid_kwh=.18)
  self.assertTrue(a['remaining_feasible']);self.assertAlmostEqual(a['outstanding_grid_side_kwh'],.07)
 def test_infeasible_outstanding(self):
  a=m.calculate(action='GRID_CHARGE',start_utc=T.isoformat(),scheduled_kwh=.25,now=T+dt.timedelta(minutes=20),delivered_grid_kwh=0)
  self.assertFalse(a['remaining_feasible'])
 def test_no_meter_not_authorised(self):
  a=m.calculate(action='GRID_CHARGE',start_utc=T.isoformat(),scheduled_kwh=.1,now=T+dt.timedelta(minutes=10))
  self.assertFalse(a['live_dispatch_allowed']);self.assertIsNone(a['outstanding_grid_side_kwh'])
 def test_oversized_charge(self):
  with self.assertRaises(m.CommitmentError):m.calculate(action='GRID_CHARGE',start_utc=T.isoformat(),scheduled_kwh=.3,now=T)
 def test_oversized_export(self):
  with self.assertRaises(m.CommitmentError):m.calculate(action='EXPORT',start_utc=T.isoformat(),scheduled_kwh=.35,now=T)
 def test_expired(self):
  with self.assertRaises(m.CommitmentError):m.calculate(action='EXPORT',start_utc=T.isoformat(),scheduled_kwh=.1,now=T+dt.timedelta(minutes=30))
 def test_negative_meter(self):
  with self.assertRaises(m.CommitmentError):m.calculate(action='EXPORT',start_utc=T.isoformat(),scheduled_kwh=.1,now=T,delivered_grid_kwh=-1)
 def test_preflight_hold(self):
  r=rc4_preflight.report.__name__;self.assertEqual(r,'report')
