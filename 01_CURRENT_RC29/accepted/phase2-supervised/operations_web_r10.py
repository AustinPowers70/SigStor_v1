#!/usr/bin/env python3
"""Read-only local web view of Phase 2 R9 evidence. No control actions."""
import argparse
import datetime as dt
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FEED=Path('/opt/sigenstor/data/rtm/phase2-dashboard-r9.json')
SCHEMA='SIGEN_PHASE2_DASHBOARD_R9'
PAGE=Path(__file__).with_name('operations.html')

def snapshot(feed=FEED, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    try:
        if feed.is_symlink() or not feed.is_file():raise ValueError('Feed missing or unsafe')
        obj=json.loads(feed.read_text(encoding='utf-8'))
        if obj.get('schema')!=SCHEMA:raise ValueError('Feed schema mismatch')
        stamp=dt.datetime.fromisoformat(obj['timestamp_utc'].replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('Feed time lacks timezone')
        age=(now-stamp.astimezone(dt.timezone.utc)).total_seconds()
        if not -30<=age<=180:raise ValueError('Feed stale or future dated')
        if obj.get('dispatch_enabled') is not False or obj.get('plant_writes')!=0:
            raise ValueError('Unexpected dispatch status')
        return {'ok':True,'age_seconds':round(max(0,age),1),'feed':obj}
    except (OSError,ValueError,TypeError,KeyError) as exc:
        return {'ok':False,'error':str(exc),'feed':None}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/':
            data=PAGE.read_bytes();media='text/html; charset=utf-8';code=200
        elif path=='/api/status':
            result=snapshot()
            data=json.dumps(result,sort_keys=True).encode();media='application/json; charset=utf-8';code=200 if result['ok'] else 503
        elif path=='/healthz':
            result=snapshot();data=(b'OK\n' if result['ok'] else b'NOT_READY\n');media='text/plain';code=200 if result['ok'] else 503
        else:
            self.send_error(404);return
        self.send_response(code)
        self.send_header('Content-Type',media)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers();self.wfile.write(data)
    def do_POST(self): self.send_error(405,'Read-only endpoint')
    def log_message(self,fmt,*args):pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--bind',default='192.168.0.251');p.add_argument('--port',type=int,default=8113);a=p.parse_args()
    ThreadingHTTPServer((a.bind,a.port),Handler).serve_forever()
if __name__=='__main__': main()
