#!/usr/bin/env python3
"""Demo-only entrypoint. Does not load .env, real Settings, or webhook routes."""
import argparse
import sys
import socket
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from emby_telegram_bot.demo import create_demo_app
parser=argparse.ArgumentParser()
parser.add_argument('--host',default='127.0.0.1')
parser.add_argument('--port',type=int,default=8093)
parser.add_argument('--db',default=str(Path(__file__).resolve().parents[1]/'data/emby004-demo.sqlite3'))
args=parser.parse_args()
def no_outbound(*a,**kw):raise OSError('Demo process forbids outbound connections')
socket.socket.connect=no_outbound
socket.socket.connect_ex=no_outbound
socket.create_connection=no_outbound
app=create_demo_app(args.db)
app.run(host=args.host,port=args.port,debug=False,use_reloader=False)
