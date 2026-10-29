"""Viewdesk UI: the page (HTML, CSS, JS), the local web server and the app window.

`serve(automation)` shows an `app.Automation` object in a desktop-style window and returns
when that window is closed. It has no automation logic of its own.
"""
import json
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import DATA_DIR, LeoFameError

NO_PING_EXIT_SECONDS = 120     # window never opened
LOST_PING_EXIT_SECONDS = 180   # window vanished without saying goodbye
BYE_GRACE_SECONDS = 6          # lets a page reload come back before we quit

PAGE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Viewdesk</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop stop-color='%236c7bff'/%3E%3Cstop offset='1' stop-color='%2322d3ee'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='32' height='32' rx='9' fill='url(%23g)'/%3E%3Cpath d='M6 16s3.6-6 10-6 10 6 10 6-3.6 6-10 6S6 16 6 16z' fill='none' stroke='white' stroke-width='2'/%3E%3Ccircle cx='16' cy='16' r='2.8' fill='white'/%3E%3C/svg%3E">
  <style>
    :root {
      --bg: #090d18;
      --bg-glow-a: rgba(108, 123, 255, .16);
      --bg-glow-b: rgba(34, 211, 238, .10);
      --surface: #111729;
      --surface-2: #171f37;
      --surface-3: #1e2847;
      --border: rgba(255, 255, 255, .08);
      --border-strong: rgba(255, 255, 255, .16);
      --text: #eaeefb;
      --muted: #8d97b5;
      --accent: #6c7bff;
      --accent-soft: rgba(108, 123, 255, .16);
      --ok: #34d399;
      --ok-soft: rgba(52, 211, 153, .14);
      --warn: #fbbf24;
      --warn-soft: rgba(251, 191, 36, .15);
      --info: #38bdf8;
      --info-soft: rgba(56, 189, 248, .15);
      --danger: #f87171;
      --danger-soft: rgba(248, 113, 113, .14);
      --shadow: 0 10px 30px rgba(0, 0, 0, .35);
      --grad: linear-gradient(135deg, #6c7bff 0%, #22d3ee 100%);
      color-scheme: dark;
    }
    :root[data-theme="light"] {
      --bg: #f3f5fb;
      --bg-glow-a: rgba(108, 123, 255, .14);
      --bg-glow-b: rgba(34, 211, 238, .10);
      --surface: #ffffff;
      --surface-2: #f6f8fd;
      --surface-3: #eaeef8;
      --border: rgba(20, 30, 70, .09);
      --border-strong: rgba(20, 30, 70, .18);
      --text: #141a33;
      --muted: #67718f;
      --accent: #4f5df0;
      --accent-soft: rgba(79, 93, 240, .10);
      --ok: #10a877;
      --ok-soft: rgba(16, 168, 119, .12);
      --warn: #b7791f;
      --warn-soft: rgba(201, 138, 5, .14);
      --info: #0284c7;
      --info-soft: rgba(2, 132, 199, .12);
      --danger: #dc4444;
      --danger-soft: rgba(220, 68, 68, .10);
      --shadow: 0 10px 30px rgba(30, 40, 90, .10);
      color-scheme: light;
    }

    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: var(--text);
      background:
        radial-gradient(900px 500px at 12% -10%, var(--bg-glow-a), transparent 60%),
        radial-gradient(800px 500px at 100% 0%, var(--bg-glow-b), transparent 55%),
        var(--bg);
      background-attachment: fixed;
      -webkit-font-smoothing: antialiased;
    }
    h1, h2, h3, p { margin: 0; }
    button, input, select { font: inherit; color: inherit; }
    button { cursor: pointer; }
    .muted { color: var(--muted); }
    .ico { width: 18px; height: 18px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes rise { from { opacity: 0; transform: translateY(6px); } }
    @keyframes shimmer { to { background-position: -200% 0; } }

    /* ---------- Buttons & forms ---------- */
    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      height: 40px; padding: 0 16px; border-radius: 11px; border: 1px solid transparent;
      font-weight: 600; background: var(--surface-3); transition: transform .12s, filter .15s;
    }
    .btn:hover:not(:disabled) { filter: brightness(1.08); }
    .btn:active:not(:disabled) { transform: translateY(1px); }
    .btn:disabled { opacity: .6; cursor: not-allowed; }
    .btn-primary { background: var(--grad); color: #fff; box-shadow: 0 6px 18px rgba(108, 123, 255, .35); }
    .btn-block { width: 100%; }
    .btn-ghost { background: var(--surface); border-color: var(--border); }
    .btn-ghost:hover:not(:disabled) { border-color: var(--border-strong); filter: none; }
    .spin .ico { animation: spin .8s linear infinite; }
    .card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 22px; box-shadow: var(--shadow); }
    .field { display: block; margin-bottom: 18px; }
    .field > span { display: block; font-size: 12.5px; font-weight: 600; color: var(--muted); margin-bottom: 8px; }
    .input {
      display: flex; align-items: center; gap: 10px; height: 46px; padding: 0 12px;
      background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; transition: border-color .15s, box-shadow .15s;
    }
    .input:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    .input .ico { color: var(--muted); }
    .input input { flex: 1; min-width: 0; height: 100%; background: transparent; border: 0; outline: 0; }
    .input input::placeholder { color: color-mix(in srgb, var(--muted) 70%, transparent); }
    .form-error { padding: 10px 12px; border-radius: 10px; background: var(--danger-soft); color: var(--danger); font-size: 13px; margin-bottom: 14px; }

    /* ---------- Splash & sign-in ---------- */
    .splash { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: var(--bg); transition: opacity .35s, visibility .35s; }
    .splash.gone { opacity: 0; visibility: hidden; }
    .splash-card { width: min(380px, 92vw); text-align: center; }
    .splash-logo, .login-logo { width: 64px; height: 64px; filter: drop-shadow(0 10px 24px rgba(108, 123, 255, .5)); }
    .splash-card h1 { margin-top: 16px; font-size: 26px; letter-spacing: -.02em; }
    .splash-sub { color: var(--muted); margin-top: 4px; }
    .splash-steps { list-style: none; margin: 28px auto 0; padding: 0; display: inline-flex; flex-direction: column; gap: 14px; text-align: left; }
    .splash-steps li { display: flex; align-items: center; gap: 12px; color: var(--muted); transition: color .2s; }
    .splash-steps .dot { width: 18px; height: 18px; border-radius: 50%; border: 2px solid var(--border-strong); flex: none; transition: all .2s; }
    .splash-steps li.active { color: var(--text); }
    .splash-steps li.active .dot { border-color: var(--accent); border-top-color: transparent; animation: spin .8s linear infinite; }
    .splash-steps li.done { color: var(--text); }
    .splash-steps li.done .dot { background: var(--ok) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m20 6-11 11-5-5'/%3E%3C/svg%3E") center/11px no-repeat; border-color: var(--ok); }
    .splash-error { margin-top: 26px; }
    .splash-error p { color: var(--danger); margin-bottom: 14px; }

    .login { min-height: 100%; display: grid; place-items: center; padding: 24px; }
    .login-card { width: min(420px, 100%); padding: 32px; }
    .login-card h1 { font-size: 22px; margin: 16px 0 6px; letter-spacing: -.02em; }
    .login-card .muted { margin-bottom: 24px; }
    .login-note { display: flex; gap: 8px; align-items: flex-start; margin-top: 18px; font-size: 12.5px; color: var(--muted); }
    .login-note .ico { color: var(--ok); margin-top: 1px; }

    /* ---------- Shell: sidebar + topbar ---------- */
    .shell { display: grid; grid-template-columns: 232px 1fr; grid-template-rows: minmax(0, 1fr); height: 100vh; overflow: hidden; }
    .sidebar { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; padding: 22px 16px; border-right: 1px solid var(--border); background: color-mix(in srgb, var(--surface) 70%, transparent); backdrop-filter: blur(10px); }
    .brand { display: flex; align-items: center; gap: 12px; padding: 0 8px 26px; }
    .brand svg { width: 38px; height: 38px; }
    .brand strong { display: block; font-size: 16px; letter-spacing: -.01em; }
    .brand span { display: block; font-size: 11.5px; color: var(--muted); }
    .nav { display: flex; flex-direction: column; gap: 4px; }
    .nav-item { display: flex; align-items: center; gap: 12px; height: 42px; padding: 0 12px; border: 0; border-radius: 11px; background: transparent; color: var(--muted); font-weight: 600; text-align: left; transition: background .15s, color .15s; }
    .nav-item:hover { background: var(--surface-2); color: var(--text); }
    .nav-item.active { background: var(--accent-soft); color: var(--accent); }

    .main { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; }
    .topbar { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 18px 32px; }
    .balance-chip { display: flex; align-items: center; gap: 8px; height: 38px; padding: 0 14px; border-radius: 11px; background: var(--surface); border: 1px solid var(--border); font-weight: 700; font-variant-numeric: tabular-nums; }
    .balance-chip .ico { color: var(--accent); }
    .icon-btn { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 11px; background: var(--surface); border: 1px solid var(--border); }
    .icon-btn:hover { border-color: var(--border-strong); }
    .avatar { width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; background: var(--grad); color: #fff; font-weight: 700; text-transform: uppercase; }
    .content { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 32px 32px; }
    .page { max-width: 1100px; margin: 0 auto; animation: rise .3s ease; }

    /* ---------- Orders ---------- */
    .page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    .page-head h2 { font-size: 22px; letter-spacing: -.02em; }
    .page-head p { font-size: 13px; margin-top: 2px; }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; margin-bottom: 16px; }
    .tabs { display: inline-flex; gap: 4px; padding: 4px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border); flex-wrap: wrap; }
    .tab { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border: 0; border-radius: 9px; background: transparent; color: var(--muted); font-weight: 600; }
    .tab:hover { color: var(--text); }
    .tab.on { background: var(--accent-soft); color: var(--accent); }
    .tab .count { min-width: 20px; padding: 0 6px; border-radius: 999px; background: var(--surface-3); color: var(--text); font-size: 11.5px; line-height: 18px; text-align: center; }
    .toolbar-end { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .search { display: flex; align-items: center; height: 40px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border); transition: border-color .15s, box-shadow .15s; }
    .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    .search .sel { position: relative; display: flex; align-items: center; height: 100%; border-right: 1px solid var(--border); }
    .search select { appearance: none; -webkit-appearance: none; height: 100%; padding: 0 30px 0 14px; border: 0; border-radius: 12px 0 0 12px; background: transparent; font-size: 13px; font-weight: 650; outline: 0; cursor: pointer; }
    .search select option { background: var(--surface); color: var(--text); }
    .search .sel .ico { position: absolute; right: 10px; width: 13px; height: 13px; color: var(--muted); pointer-events: none; }
    .search .input { flex: 1; width: 250px; height: 100%; border: 0; border-radius: 0 12px 12px 0; background: transparent; box-shadow: none; }
    .clear-btn { display: grid; place-items: center; width: 22px; height: 22px; border: 0; border-radius: 50%; background: var(--surface-3); color: var(--muted); }
    .clear-btn .ico { width: 13px; height: 13px; }

    .table-card { padding: 0; overflow: hidden; }
    .table-wrap { overflow-x: auto; }
    .table { width: 100%; border-collapse: collapse; }
    .table th { text-align: left; font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); padding: 14px 16px; background: var(--surface-2); border-bottom: 1px solid var(--border); white-space: nowrap; }
    .table td { padding: 14px 16px; border-top: 1px solid var(--border); vertical-align: top; }
    .table tbody tr:first-child td { border-top: 0; }
    .table tbody tr:hover td { background: color-mix(in srgb, var(--accent) 5%, transparent); }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 650; white-space: nowrap; background: var(--surface-3); color: var(--muted); }
    .badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .badge.ok { background: var(--ok-soft); color: var(--ok); }
    .badge.warn { background: var(--warn-soft); color: var(--warn); }
    .badge.info { background: var(--info-soft); color: var(--info); }
    .badge.err { background: var(--danger-soft); color: var(--danger); }

    .state { text-align: center; padding: 56px 16px; }
    .state-ico { width: 54px; height: 54px; margin: 0 auto 14px; border-radius: 16px; display: grid; place-items: center; background: var(--surface-2); color: var(--muted); }
    .state-ico .ico { width: 26px; height: 26px; }
    .state.error .state-ico { background: var(--danger-soft); color: var(--danger); }
    .state h3 { font-size: 16px; margin-bottom: 4px; }
    .state .btn { margin-top: 16px; }
    .state-actions { display: flex; justify-content: center; gap: 10px; margin-top: 18px; }
    .state-actions .btn { margin-top: 0; }
    .pager { display: flex; align-items: center; justify-content: center; gap: 6px; margin-top: 18px; flex-wrap: wrap; }
    .pg { min-width: 34px; height: 34px; padding: 0 10px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface-2); font-weight: 600; }
    .pg:hover:not(:disabled) { border-color: var(--border-strong); }
    .pg.on { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .pg:disabled { opacity: .5; cursor: default; }
    .updated { margin-top: 12px; font-size: 12.5px; text-align: right; }

    /* ---------- Home: several posts, each a self-contained card ---------- */
    #page-home { max-width: 1240px; }
    .workbench { display: flex; flex-direction: column; gap: 14px; padding-bottom: 8px; }
    .is-busy { opacity: .55; pointer-events: none; transition: opacity .2s; }

    /* command bar: package · delivery · link · pay */
    .bar { position: relative; z-index: 6; padding: 14px 16px 8px; overflow: visible; }
    .bar-row { display: grid; grid-template-columns: 196px 168px minmax(220px, 1fr) auto; gap: 10px; align-items: stretch; }
    .pop { position: relative; }
    .pop-btn { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; height: 52px; padding: 0 12px 0 14px; border-radius: 13px; border: 1px solid var(--border); background: var(--surface-2); text-align: left; transition: border-color .15s, box-shadow .15s; }
    .pop-btn:hover:not(:disabled) { border-color: var(--border-strong); }
    .pop-btn[aria-expanded="true"] { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    .pop-btn:disabled { opacity: .6; cursor: not-allowed; }
    .pop-text { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
    .pop-label { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
    .pop-value { font-size: 14px; font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .pop-value.placeholder { color: var(--muted); font-weight: 500; }
    .chev { color: var(--muted); transition: transform .2s; }
    .pop-btn[aria-expanded="true"] .chev { transform: rotate(180deg); }
    .pop-panel { position: absolute; top: calc(100% + 8px); left: 0; z-index: 40; min-width: 100%; padding: 10px; border-radius: 16px; background: var(--surface); border: 1px solid var(--border-strong); box-shadow: 0 18px 44px rgba(0, 0, 0, .28); animation: rise .18s ease; }
    .pkg-panel { width: 384px; }
    .del-panel { width: 280px; }

    .pkg-list { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .opt { position: relative; display: flex; flex-direction: column; gap: 3px; min-height: 52px; padding: 8px 12px; border-radius: 12px; border: 1.5px solid var(--border); background: var(--surface-2); text-align: left; transition: border-color .15s, background .15s; }
    .opt:hover { border-color: var(--border-strong); }
    .opt.on { border-color: var(--accent); background: var(--accent-soft); }
    .opt-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
    .opt-top b { font-size: 14.5px; font-weight: 750; letter-spacing: -.01em; }
    .opt-top b small { font-size: 11px; font-weight: 500; color: var(--muted); }
    .opt-price { font-weight: 700; font-size: 13px; font-variant-numeric: tabular-nums; }
    .opt-tags { display: flex; gap: 5px; min-height: 15px; }
    .tag { padding: 0 7px; border-radius: 999px; font-size: 10px; font-weight: 700; line-height: 15px; }
    .tag.save { background: var(--ok-soft); color: var(--ok); }
    .tag.best { background: var(--grad); color: #fff; }
    .opt-custom { margin-top: 10px; padding: 10px 12px; border-radius: 12px; border: 1.5px dashed var(--border-strong); transition: border-color .15s, background .15s; }
    .opt-custom.on { border-style: solid; border-color: var(--accent); background: var(--accent-soft); }
    .opt-custom label { display: block; font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }
    .custom-line { display: flex; align-items: center; gap: 10px; }
    .custom-line input { flex: 1; min-width: 0; height: 36px; padding: 0 10px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface); outline: 0; font-weight: 600; }
    .custom-line input:focus { border-color: var(--accent); }
    .custom-price { font-weight: 700; color: var(--accent); white-space: nowrap; font-variant-numeric: tabular-nums; }
    .hint { margin: 6px 0 0; font-size: 11.5px; color: var(--muted); }
    .hint.err { color: var(--danger); }

    .del-opt { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; padding: 9px 12px; border-radius: 10px; border: 0; background: transparent; text-align: left; }
    .del-opt:hover { background: var(--surface-2); }
    .del-opt.on { background: var(--accent-soft); }
    .del-opt b { font-size: 13.5px; font-weight: 650; }
    .del-opt span { font-size: 11.5px; color: var(--muted); }
    .del-opt.rec span { color: var(--ok); font-weight: 650; }

    .link-input { height: 52px; }
    .input-btn { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: var(--surface-3); border: 0; color: var(--muted); }
    .input-btn:hover { color: var(--text); }
    .link-input input::-webkit-calendar-picker-indicator { opacity: .35; cursor: pointer; }
    .link-state { display: grid; place-items: center; }
    .link-state .ico { width: 17px; height: 17px; }
    .link-state.ok .ico { color: var(--ok); }
    .link-state.err .ico { color: var(--danger); }
    .link-state .mini-spin { width: 15px; height: 15px; border: 2px solid var(--accent); border-top-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }

    .pay-btn { position: relative; display: inline-flex; align-items: center; justify-content: center; gap: 9px; min-width: 156px; height: 52px; padding: 0 20px; border: 0; border-radius: 13px; background: var(--surface-3); color: var(--muted); font-weight: 700; font-size: 15px; white-space: nowrap; transition: background .25s, color .25s, box-shadow .25s, transform .15s; }
    .pay-btn:disabled { cursor: not-allowed; }
    .pay-btn.ready { background: linear-gradient(135deg, #22c55e, #16a34a); color: #fff; cursor: pointer; animation: readyPulse 2.4s infinite; }
    .pay-btn.ready:hover { transform: translateY(-1px); filter: brightness(1.06); }
    .pay-btn.ready:active { transform: translateY(1px); }
    .pay-btn.busy { background: var(--accent-soft); color: var(--accent); }
    .pay-btn.waiting { background: var(--ok-soft); color: var(--ok); }
    .pay-spin { display: none; width: 16px; height: 16px; border: 2.5px solid currentColor; border-top-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }
    .pay-btn.busy .pay-spin { display: inline-block; }
    .pay-btn.busy .pay-ico { display: none; }
    @keyframes readyPulse { 0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, .5), 0 8px 22px rgba(34, 197, 94, .35); } 70% { box-shadow: 0 0 0 12px rgba(34, 197, 94, 0), 0 8px 22px rgba(34, 197, 94, .35); } 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0), 0 8px 22px rgba(34, 197, 94, .35); } }

    .bar-sub { display: flex; align-items: center; justify-content: space-between; gap: 6px 20px; flex-wrap: wrap; margin-top: 8px; min-height: 34px; }
    .verify-line { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 12.5px; color: var(--muted); min-width: 0; }
    .verify-line.ok { color: var(--ok); }
    .verify-line.err { color: var(--danger); }
    .bar-opts { display: flex; align-items: center; gap: 12px 18px; flex-wrap: wrap; }
    .mini-input { display: flex; align-items: center; gap: 7px; height: 30px; padding: 0 10px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--border); width: 210px; }
    .mini-input:focus-within { border-color: var(--accent); }
    .mini-input .ico { color: var(--muted); width: 14px; height: 14px; }
    .mini-input input { flex: 1; min-width: 0; background: transparent; border: 0; outline: 0; font-size: 12.5px; }
    .agree { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); cursor: pointer; white-space: nowrap; }
    .agree input { width: 16px; height: 16px; accent-color: #16a34a; }
    .agree a { color: var(--accent); }

    /* summary strip (turns into the payment status while paying) */
    .strip { display: flex; align-items: center; justify-content: space-between; gap: 8px 24px; flex-wrap: wrap; padding: 10px 16px; box-shadow: none; }
    .sum-left { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
    .sum-chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .sum-chip { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); font-size: 12.5px; font-weight: 600; }
    .sum-chip.empty { color: var(--muted); font-weight: 500; }
    .sum-note { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 11.5px; color: var(--muted); }
    .sum-note .ico { width: 13px; height: 13px; color: var(--ok); }
    .sum-right { text-align: right; }
    .sum-total { display: flex; align-items: baseline; justify-content: flex-end; gap: 10px; }
    .sum-total span { font-size: 12px; color: var(--muted); }
    .sum-total b { font-size: 22px; font-weight: 750; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
    .sum-fee { margin: 0; font-size: 11.5px; color: var(--warn); }

    .status-strip { align-items: flex-start; flex-direction: column; gap: 10px; }
    .steps { display: flex; flex-wrap: wrap; gap: 6px 4px; list-style: none; margin: 0; padding: 0; }
    .steps li { display: inline-flex; align-items: center; gap: 8px; padding: 3px 12px 3px 6px; border-radius: 999px; font-size: 12.5px; font-weight: 600; color: var(--muted); background: var(--surface-2); }
    .steps li::before { content: ""; width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--border-strong); flex: none; }
    .steps li.active { color: var(--text); }
    .steps li.active::before { border-color: var(--accent); border-top-color: transparent; animation: spin .8s linear infinite; }
    .steps li.done { color: var(--text); }
    .steps li.done::before { background: var(--ok); border-color: var(--ok); }
    .steps li.failed { color: var(--danger); background: var(--danger-soft); }
    .steps li.failed::before { background: var(--danger); border-color: var(--danger); }
    .status-body { display: flex; align-items: center; justify-content: space-between; gap: 10px 20px; flex-wrap: wrap; width: 100%; }
    .status-info { min-width: 0; font-size: 13px; }
    .status-info .found-order { display: inline-block; margin: 0 10px 0 0; padding: 6px 12px; border-radius: 10px; background: var(--surface-2); }
    .found-order.paid { background: var(--ok-soft) !important; }
    .found-order.failed { background: var(--danger-soft) !important; }
    .found-order strong { font-size: 13.5px; }
    .found-order.paid strong { color: var(--ok); }
    .found-order.failed strong { color: var(--danger); }
    .found-order span { margin-left: 8px; color: var(--muted); font-size: 12px; }
    .status-msg { display: inline; font-size: 12.5px; }
    .status-msg.err { color: var(--danger); }
    .status-msg.warn { color: var(--warn); }
    .card-line { display: inline-block; margin-right: 10px; padding: 5px 11px; border-radius: 10px; background: var(--surface-2); font-size: 12.5px; color: var(--muted); }
    .card-line b { color: var(--text); font-weight: 700; text-transform: capitalize; }
    .card-line.paid { background: var(--ok-soft); color: var(--ok); }
    .card-line.paid b { color: var(--ok); }
    .card-line.failed { background: var(--danger-soft); color: var(--danger); }
    .card-line.failed b { color: var(--danger); }
    .status-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .status-actions .btn { height: 34px; padding: 0 14px; font-size: 13px; }

    /* the "Select posts" popup reuses this styling */
    .ws-head { display: flex; align-items: center; gap: 8px 20px; flex-wrap: wrap; padding: 0 0 14px; margin-bottom: 14px; border-bottom: 1px solid var(--border); }
    .pv-user { display: flex; align-items: center; gap: 8px; }
    .pv-avatar { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; background: var(--surface-3); }
    .pv-user strong { font-size: 14px; }
    .pill { display: inline-flex; align-items: center; padding: 1px 9px; border-radius: 999px; font-size: 11px; font-weight: 650; background: var(--ok-soft); color: var(--ok); }
    .ws-count { font-size: 13px; color: var(--muted); flex: 1; min-width: 160px; }
    .ws-count b { color: var(--text); font-size: 14.5px; }
    .ws-count .warn { color: var(--warn); }
    .ws-tools { display: flex; align-items: center; gap: 12px; margin-left: auto; }
    .text-btn { padding: 0; border: 0; background: none; color: var(--accent); font-weight: 600; font-size: 12.5px; white-space: nowrap; }
    .text-btn:hover { text-decoration: underline; }
    .ws-tools select { height: 30px; padding: 0 8px; border-radius: 8px; background: var(--surface-2); border: 1px solid var(--border); font-size: 12.5px; }
    .size-btn { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-2); color: var(--muted); }
    .size-btn:hover { color: var(--text); }
    .posts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(116px, 1fr)); gap: 10px; }
    .posts-grid.small { grid-template-columns: repeat(auto-fill, minmax(88px, 1fr)); gap: 8px; }
    .post-card { position: relative; display: block; padding: 0; border: 2px solid transparent; border-radius: 12px; background: var(--surface-2); text-align: left; overflow: hidden; transition: border-color .15s, transform .15s, opacity .15s; }
    .post-card:hover { transform: translateY(-2px); }
    .post-card.on { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    .post-card.locked { opacity: .5; }
    .post-thumb { display: block; aspect-ratio: 4 / 5; background: var(--surface-3); }
    .post-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .post-tick { position: absolute; top: 6px; left: 6px; width: 21px; height: 21px; border-radius: 50%; display: grid; place-items: center; background: rgba(0, 0, 0, .35); border: 2px solid #fff; color: #fff; font-size: 11px; font-weight: 700; }
    .post-card.on .post-tick { background: var(--accent); border-color: var(--accent); }
    .post-tag { position: absolute; top: 6px; right: 6px; padding: 0 7px; border-radius: 999px; background: rgba(0, 0, 0, .55); color: #fff; font-size: 9.5px; font-weight: 700; line-height: 16px; }
    .post-tag.mine { background: var(--grad); }
    .post-meta { display: block; padding: 5px 8px 6px; font-size: 11.5px; color: var(--muted); line-height: 1.3; }
    .post-meta b { color: var(--text); font-size: 12.5px; }
    .post-meta em { display: block; font-style: normal; font-size: 10.5px; }
    .posts-grid.small .post-meta em { display: none; }
    .posts-grid.small .post-tag { display: none; }
    .posts-foot { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
    .posts-foot .btn { height: 34px; font-size: 13px; }
    .posts-note { font-size: 12.5px; color: var(--muted); }
    .posts-note.err { color: var(--danger); }
    .skel-card { aspect-ratio: 4 / 6; border-radius: 12px; background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 37%, var(--surface-2) 63%); background-size: 200% 100%; animation: shimmer 1.4s linear infinite; }

    .ws-empty { flex: 1; display: grid; place-items: center; padding: 26px 20px; text-align: center; }
    .ws-empty .ws-skel { width: 100%; align-self: stretch; padding: 0; }
    .empty-ico { width: 50px; height: 50px; margin: 0 auto 12px; border-radius: 15px; display: grid; place-items: center; background: var(--surface-2); color: var(--muted); }
    .empty-ico .ico { width: 24px; height: 24px; }
    .empty-ico.err { background: var(--danger-soft); color: var(--danger); }
    .ws-empty h3 { font-size: 15px; font-weight: 650; }
    .ws-empty p { margin-top: 4px; font-size: 13px; color: var(--muted); max-width: 440px; }
    .how { display: flex; gap: 10px 22px; justify-content: center; flex-wrap: wrap; margin-top: 18px; }
    .how span { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); }
    .how i { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; background: var(--accent-soft); color: var(--accent); font-style: normal; font-weight: 700; font-size: 11px; }


    /* several posts at once: a toolbar + a stack of self-contained cards, one per post */
    .jobs-toolbar { display: flex; align-items: center; gap: 12px 20px; flex-wrap: wrap; }
    .jobs-status { font-size: 12.5px; color: var(--muted); }
    .jobs-status b { color: var(--text); font-weight: 700; }
    .lock-note { margin: 0; }
    .jobs-stack { display: flex; flex-direction: column; gap: 12px; }

    .job-card {
      --tone: var(--muted); --tone-soft: var(--surface-3);
      position: relative; padding: 14px 16px 16px 20px; border-radius: 16px;
      background: var(--surface); border: 1px solid var(--border); transition: border-color .15s;
    }
    .job-card::before { content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 4px; border-radius: 0 4px 4px 0; background: var(--tone); }
    .job-card:hover { border-color: var(--border-strong); }
    .job-card.has-pop { z-index: 20; }
    .job-card.t-info { --tone: var(--info); }
    .job-card.t-ready { --tone: var(--accent); }
    .job-card.t-paying { --tone: var(--warn); }
    .job-card.t-done { --tone: var(--ok); }
    .job-card.t-failed { --tone: var(--danger); }

    .job-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .job-dot { width: 9px; height: 9px; flex: none; border-radius: 50%; background: var(--tone); }
    .job-dot.spin { background: transparent; border: 2px solid var(--tone); border-top-color: transparent; animation: spin .8s linear infinite; }
    .job-title { display: flex; align-items: baseline; gap: 8px; min-width: 0; flex: 1; }
    .job-title b { font-size: 13px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .job-title span { font-size: 12px; color: var(--muted); white-space: nowrap; }
    .job-head .text-btn { flex: none; }
    .job-close { display: grid; place-items: center; width: 24px; height: 24px; flex: none; border: 0; border-radius: 50%; background: transparent; color: var(--muted); }
    .job-close:hover { background: var(--danger-soft); color: var(--danger); }
    .job-close .ico { width: 12px; height: 12px; }

    .job-sub { display: flex; align-items: center; justify-content: space-between; gap: 8px 16px; flex-wrap: wrap; margin-top: 8px; }
    .job-sub .verify-line { flex: 1 1 180px; min-width: 0; }

    .post-strip { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
    .strip-track { display: flex; gap: 6px; flex: 1; min-width: 0; overflow-x: auto; scroll-behavior: smooth; cursor: grab; touch-action: pan-x; padding: 2px 1px; }
    .strip-track:active { cursor: grabbing; }
    .strip-track.empty { color: var(--muted); font-size: 12.5px; align-items: center; cursor: default; }
    .strip-thumb { position: relative; flex: none; width: 40px; height: 50px; border-radius: 8px; overflow: hidden; background: var(--surface-3); border: 1.5px solid var(--border); }
    .strip-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; }
    .strip-thumb i { position: absolute; left: 2px; top: 2px; min-width: 14px; height: 14px; padding: 0 3px; border-radius: 999px; background: rgba(0, 0, 0, .55); color: #fff; font-style: normal; font-size: 9px; font-weight: 700; line-height: 14px; text-align: center; }
    .strip-manage { display: inline-flex; align-items: center; gap: 8px; flex: none; height: 42px; padding: 0 14px; border-radius: 12px; border: 1.5px dashed var(--border-strong); background: transparent; color: var(--text); font-weight: 650; font-size: 12.5px; white-space: nowrap; transition: border-color .15s, background .15s; }
    .strip-manage:hover { border-color: var(--accent); background: var(--accent-soft); }
    .strip-manage b { color: var(--accent); }
    .strip-manage .ico { width: 15px; height: 15px; color: var(--muted); }

    .add-job { display: inline-flex; align-items: center; gap: 7px; height: 34px; padding: 0 14px 0 6px; border-radius: 999px; border: 1.5px dashed var(--border-strong); background: transparent; color: var(--accent); font-weight: 650; font-size: 12.5px; white-space: nowrap; transition: background .15s, border-color .15s; }
    .add-job:hover { background: var(--accent-soft); }
    .add-job .plus { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; background: var(--accent); color: #fff; }
    .add-job .plus .ico { width: 12px; height: 12px; stroke-width: 2.6; }

    .strip.nested { margin-top: 10px; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); box-shadow: none; }

    @media (max-width: 620px) { .post-strip { flex-wrap: wrap; } .strip-manage { width: 100%; justify-content: center; } }

    @media (max-width: 1100px) { .bar-row { grid-template-columns: 1fr 1fr; } .link-input { grid-column: 1 / -1; order: 3; } .pay-btn { grid-column: 1 / -1; order: 4; } .pkg-panel { width: min(384px, 92vw); } }
    @media (max-width: 620px) { .pkg-list { grid-template-columns: 1fr; } .mini-input { width: 100%; } .ws-tools { margin-left: 0; flex-wrap: wrap; } }


    /* ---------- Orders: live status, rich rows, actions, dialogs ---------- */
    .live-tools { display: flex; align-items: center; gap: 10px; }
    .live { display: inline-flex; align-items: center; gap: 8px; height: 40px; padding: 0 14px; border-radius: 11px; background: var(--surface); border: 1px solid var(--border); font-size: 12.5px; color: var(--muted); white-space: nowrap; }
    .live b { color: var(--text); font-weight: 650; }
    .live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); animation: pulse 2s infinite; }
    .live.busy .live-dot { background: var(--warn); animation: none; }
    .live.err .live-dot { background: var(--danger); animation: none; }
    /* --- order cards --- */
    .orders-list { display: grid; gap: 12px; container-type: inline-size; }
    .order {
      --tone: var(--muted); --tone-soft: var(--surface-3);
      position: relative; display: grid; align-items: start; gap: 14px 26px;
      grid-template-columns: minmax(0, 1fr) 128px 244px; grid-template-areas: "main mid acts";
      padding: 18px 20px 18px 26px; border-radius: 16px; background: var(--surface); border: 1px solid var(--border);
      transition: border-color .15s, box-shadow .2s;
    }
    .order::before { content: ""; position: absolute; left: 0; top: 18px; bottom: 18px; width: 4px; border-radius: 0 4px 4px 0; background: var(--tone); }
    .order:hover { border-color: var(--border-strong); box-shadow: var(--shadow); }
    .order.t-ok { --tone: var(--ok); --tone-soft: var(--ok-soft); }
    .order.t-warn { --tone: var(--warn); --tone-soft: var(--warn-soft); }
    .order.t-info { --tone: var(--info); --tone-soft: var(--info-soft); }
    .order.t-err { --tone: var(--danger); --tone-soft: var(--danger-soft); }
    .orders-list.enter .order { animation: rise .35s ease both; animation-delay: calc(var(--i, 0) * 35ms); }
    .order.flash { animation: orderflash 2.6s ease-out; }
    @keyframes orderflash { 0%, 35% { background: color-mix(in srgb, var(--accent) 12%, var(--surface)); border-color: var(--accent); } }

    .o-main { grid-area: main; display: flex; gap: 14px; min-width: 0; }
    .o-ico { display: grid; place-items: center; flex: none; width: 44px; height: 44px; border-radius: 13px; background: var(--tone-soft); color: var(--tone); }
    .o-ico .ico { width: 21px; height: 21px; }
    .o-body { display: grid; flex: 1; gap: 9px; min-width: 0; align-content: start; }
    .o-title { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; min-height: 26px; }
    .o-title h3 { font-size: 15.5px; font-weight: 700; letter-spacing: -.01em; line-height: 1.3; }
    .o-part { padding: 1px 9px; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); font-size: 11.5px; font-weight: 650; white-space: nowrap; }
    .o-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 9px; margin-top: -4px; font-size: 12.5px; color: var(--muted); }
    .o-id { display: inline-flex; align-items: center; gap: 6px; }
    .o-id b { color: var(--text); font-weight: 700; font-variant-numeric: tabular-nums; }
    .o-meta .sep { width: 3px; height: 3px; border-radius: 50%; background: var(--border-strong); }
    .o-when { white-space: nowrap; }
    .o-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px; min-width: 0; }
    .o-link { display: inline-flex; align-items: center; gap: 7px; max-width: 100%; min-width: 0; padding: 5px 11px 5px 9px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border); color: var(--accent); font-size: 12.5px; font-weight: 650; text-decoration: none; transition: border-color .15s, background .15s; }
    a.o-link:hover { border-color: var(--accent); background: var(--accent-soft); }
    .o-link .ico { width: 14px; height: 14px; }
    .o-link .ico:last-child:not(:first-child) { width: 12px; height: 12px; color: var(--muted); }
    .o-link .who { white-space: nowrap; }
    .o-link .vid { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-weight: 500; }
    .o-link.plain { color: var(--text); }
    .o-stats { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 12.5px; color: var(--muted); }
    .o-stats b { margin-left: 6px; color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }
    .o-progress { display: flex; align-items: center; gap: 10px; max-width: 320px; }
    .o-bar { flex: 1; height: 6px; border-radius: 6px; background: var(--surface-3); overflow: hidden; }
    .o-bar i { display: block; height: 100%; border-radius: 6px; background: linear-gradient(90deg, var(--info), var(--accent)); transition: width .6s ease; }
    .o-progress b { font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .o-note { display: flex; align-items: flex-start; gap: 7px; font-size: 12.5px; line-height: 1.45; color: var(--muted); }
    .o-note .ico { width: 14px; height: 14px; margin-top: 2px; }
    .o-note span { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .o-note.warn { color: var(--warn); }
    .o-note.ok { color: var(--ok); }
    .o-note.info { color: var(--info); }
    .o-note.err { color: var(--danger); }

    .o-mid { grid-area: mid; display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding-top: 1px; }
    .o-status .badge { padding: 4px 12px; font-size: 12.5px; }
    .badge.mute { background: var(--surface-3); color: var(--muted); }
    .o-price { font-size: 21px; font-weight: 750; letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1; white-space: nowrap; }

    .o-actions { grid-area: acts; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
    .act-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
    .act { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 32px; padding: 0 13px; border-radius: 10px; border: 1px solid var(--border-strong); background: var(--surface); font-size: 12.5px; font-weight: 650; white-space: nowrap; transition: background .15s, border-color .15s, color .15s; }
    .act:hover { border-color: var(--accent); color: var(--accent); }
    .act .ico { width: 14px; height: 14px; }
    .act.danger { color: var(--danger); background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 35%, transparent); }
    .act.danger:hover { color: var(--danger); background: color-mix(in srgb, var(--danger) 24%, transparent); border-color: var(--danger); }
    .act.warn { color: var(--warn); background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 35%, transparent); }
    .act.warn:hover { color: var(--warn); background: color-mix(in srgb, var(--warn) 26%, transparent); border-color: var(--warn); }
    .act.cancelling { color: var(--warn); background: var(--warn-soft); border-color: transparent; cursor: default; }
    .act.cancelling .mini-spin { width: 12px; height: 12px; border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }
    .mini-btn { display: inline-grid; place-items: center; width: 30px; height: 30px; flex: none; border-radius: 9px; border: 1px solid var(--border); background: var(--surface-2); color: var(--muted); transition: color .15s, border-color .15s, background .15s; }
    .mini-btn:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
    .mini-btn .ico { width: 15px; height: 15px; }
    .mini-btn.pay-toggle.on { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
    .o-id .mini-btn { width: 24px; height: 24px; border-radius: 7px; }
    .o-id .mini-btn .ico { width: 12px; height: 12px; }

    .pay-note { display: grid; gap: 5px; padding: 10px 12px; border-radius: 12px; background: var(--surface-2); font-size: 12px; animation: rise .2s ease; }
    .pn-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .pn-method { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-weight: 650; text-transform: capitalize; }
    .pn-method .ico { width: 14px; height: 14px; }
    .pn-amount { font-size: 14px; font-weight: 750; font-variant-numeric: tabular-nums; }
    .pn-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 650; color: var(--muted); }
    .pn-status i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .pn-status.ok { color: var(--ok); }
    .pn-status.warn { color: var(--warn); }
    .pn-status.info { color: var(--info); }
    .pn-status.err { color: var(--danger); }
    .pay-note small { color: var(--muted); font-size: 11.5px; }
    .pn-none { color: var(--muted); }
    .pn-full { display: grid; gap: 7px; margin: 4px 0 0; padding-top: 9px; border-top: 1px dashed var(--border-strong); font-size: 11.5px; }
    .pn-full div { display: grid; gap: 1px; }
    .pn-full dt { color: var(--muted); font-size: 10.5px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
    .pn-full dd { margin: 0; font-weight: 650; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }

    /* the card follows the width of the list, not of the window */
    @container (max-width: 880px) {
      .order { grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "main mid" "acts acts"; gap: 14px 20px; }
      .o-mid { align-items: flex-end; }
      .o-actions { padding-top: 14px; border-top: 1px solid var(--border); }
      .pay-note { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; }
      .pn-full { flex-basis: 100%; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
    }
    @container (max-width: 560px) {
      .order { grid-template-columns: 1fr; grid-template-areas: "main" "mid" "acts"; padding: 16px 16px 16px 20px; }
      .o-ico { display: none; }
      .o-mid { flex-direction: row; align-items: center; justify-content: space-between; }
    }

    .o-skeleton { display: grid; gap: 12px; }
    .o-skel { display: grid; grid-template-columns: 44px minmax(0, 1fr) 150px; gap: 16px; align-items: center; padding: 18px 20px 18px 26px; border-radius: 16px; background: var(--surface); border: 1px solid var(--border); }
    .o-skel i { display: block; border-radius: 8px; background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 37%, var(--surface-2) 63%); background-size: 200% 100%; animation: shimmer 1.4s linear infinite; }
    .o-skel .a { width: 44px; height: 44px; border-radius: 13px; }
    .o-skel .b { height: 14px; width: 40%; }
    .o-skel .c { height: 11px; width: 26%; margin-top: 10px; }
    .o-skel .d { height: 28px; width: 58%; margin-top: 12px; border-radius: 10px; }
    .o-skel .e { height: 44px; border-radius: 12px; }
    .btn-danger { background: var(--danger); color: #fff; box-shadow: 0 6px 18px rgba(248, 113, 113, .3); }
    .btn .btn-spin { display: none; width: 14px; height: 14px; border: 2.5px solid currentColor; border-top-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }
    .btn.is-loading .btn-spin { display: inline-block; }

    .modal { position: fixed; inset: 0; z-index: 90; display: grid; place-items: center; padding: 20px; background: rgba(5, 8, 20, .55); backdrop-filter: blur(3px); animation: fade .15s ease; }
    @keyframes fade { from { opacity: 0; } }
    .modal-card { width: min(500px, 100%); max-height: 88vh; overflow: auto; padding: 22px; border-radius: 18px; background: var(--surface); border: 1px solid var(--border-strong); box-shadow: 0 30px 80px rgba(0, 0, 0, .45); animation: rise .18s ease; }
    .modal-card.wide { width: min(880px, 96vw); }
    .modal-card h3 { font-size: 17px; font-weight: 700; letter-spacing: -.01em; margin-bottom: 6px; }
    .modal-card p { font-size: 13.5px; }
    .modal-order { display: grid; gap: 3px; margin: 14px 0 4px; padding: 12px 14px; border-radius: 12px; background: var(--surface-2); font-size: 13px; }
    .modal-order span { color: var(--muted); overflow-wrap: anywhere; }
    .modal-card textarea { width: 100%; min-height: 96px; margin-top: 12px; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface-2); resize: vertical; outline: 0; }
    .modal-card textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
    .modal-error { margin-top: 12px; padding: 9px 12px; border-radius: 10px; background: var(--danger-soft); color: var(--danger); font-size: 13px; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }


    .bulk { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; padding: 11px 14px 11px 14px; border-radius: 14px; background: color-mix(in srgb, var(--warn) 9%, var(--surface)); border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent); animation: rise .25s ease; }
    .bulk-ico { display: grid; place-items: center; flex: none; width: 34px; height: 34px; border-radius: 10px; background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
    .bulk p { flex: 1; min-width: 0; font-size: 12.5px; line-height: 1.4; color: var(--muted); }
    .bulk p b { margin-right: 4px; color: var(--text); font-size: 13.5px; font-weight: 700; }
    .cancel-all { height: 36px; padding: 0 14px; flex: none; font-size: 13px; color: var(--danger); background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 35%, transparent); }
    @media (max-width: 720px) { .bulk { flex-wrap: wrap; } .cancel-all { width: 100%; } }
    .cancel-all .ico { width: 14px; height: 14px; }
    .modal-error details { margin-top: 8px; }
    .modal-error summary { cursor: pointer; font-size: 12px; font-weight: 650; }
    .modal-error pre { margin: 6px 0 0; padding: 8px 10px; border-radius: 8px; background: rgba(0, 0, 0, .12); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11.5px; color: var(--text); }

    /* ---------- Toasts ---------- */
    .toasts { position: fixed; right: 20px; bottom: 20px; z-index: 80; display: flex; flex-direction: column; gap: 10px; }
    .toast { display: flex; align-items: flex-start; gap: 10px; min-width: 260px; max-width: 380px; padding: 12px 14px; border-radius: 12px; background: var(--surface-3); border: 1px solid var(--border-strong); box-shadow: var(--shadow); animation: rise .25s ease; }
    .toast .ico { margin-top: 1px; color: var(--ok); }
    .toast.err .ico { color: var(--danger); }
    .toast.out { opacity: 0; transform: translateY(6px); transition: all .25s; }

    @media (max-width: 900px) {
      .shell { grid-template-columns: 68px 1fr; }
      .sidebar { padding: 18px 10px; align-items: center; }
      .brand div, .nav-item span { display: none; }
      .brand { padding: 0 0 22px; }
      .nav-item { width: 46px; justify-content: center; padding: 0; }
      .search .input { width: 160px; }
    }
    @media (max-width: 620px) { .topbar, .content { padding-left: 16px; padding-right: 16px; } }
    @media (prefers-reduced-motion: reduce) { * { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
  </style>
  <script>
    try {
      const saved = localStorage.getItem("theme");
      const light = window.matchMedia("(prefers-color-scheme: light)").matches;
      document.documentElement.dataset.theme = saved || (light ? "light" : "dark");
    } catch (e) {}
  </script>
</head>
<body>
  <svg width="0" height="0" style="position:absolute" aria-hidden="true">
    <defs>
      <linearGradient id="brandGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6c7bff"/><stop offset="1" stop-color="#22d3ee"/></linearGradient>
      <symbol id="i-logo" viewBox="0 0 32 32"><rect width="32" height="32" rx="9" fill="url(#brandGrad)"/><path d="M6 16s3.6-6 10-6 10 6 10 6-3.6 6-10 6S6 16 6 16z" fill="none" stroke="#fff" stroke-width="2"/><circle cx="16" cy="16" r="2.8" fill="#fff"/></symbol>
      <symbol id="i-home" viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></symbol>
      <symbol id="i-orders" viewBox="0 0 24 24"><path d="M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1z"/><path d="M8 6H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-2"/><path d="M8 12h8M8 16h5"/></symbol>
      <symbol id="i-refresh" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></symbol>
      <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></symbol>
      <symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></symbol>
      <symbol id="i-inbox" viewBox="0 0 24 24"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z"/></symbol>
      <symbol id="i-alert" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5h.01"/></symbol>
      <symbol id="i-wallet" viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h13v4"/><path d="M3 7v11a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H5a2 2 0 0 1-2-2z"/><circle cx="16.5" cy="14.5" r="1"/></symbol>
      <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></symbol>
      <symbol id="i-moon" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></symbol>
      <symbol id="i-mail" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></symbol>
      <symbol id="i-key" viewBox="0 0 24 24"><circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 9.2-9.2M16 7l3 3M14 9l2 2"/></symbol>
      <symbol id="i-check" viewBox="0 0 24 24"><path d="m20 6-11 11-5-5"/></symbol>
      <symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3 4 6v6c0 4.5 3.2 8.2 8 9 4.8-.8 8-4.5 8-9V6z"/><path d="m9 12 2 2 4-4"/></symbol>
      <symbol id="i-link" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></symbol>
      <symbol id="i-clipboard" viewBox="0 0 24 24"><rect x="8" y="3" width="8" height="4" rx="1"/><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/></symbol>
      <symbol id="i-lock" viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></symbol>
      <symbol id="i-card" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/></symbol>
      <symbol id="i-chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
      <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
      <symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></symbol>
      <symbol id="i-cart" viewBox="0 0 24 24"><circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.7 12.4a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.5L21 8H6"/></symbol>
      <symbol id="i-refund" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v8M9.5 10.5c.5-.7 1.4-1 2.5-1 1.4 0 2.5.6 2.5 1.6 0 2-5 1.2-5 3.3 0 1 1.1 1.6 2.5 1.6 1.1 0 2-.3 2.5-1"/></symbol>
      <symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5h.01"/></symbol>
      <symbol id="i-grid" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></symbol>
      <symbol id="i-eye" viewBox="0 0 24 24"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></symbol>
      <symbol id="i-ext" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></symbol>
      <symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
      <symbol id="i-heart" viewBox="0 0 24 24"><path d="M12 20s-7.5-4.6-9.2-9.6C1.6 7 4 4 7.2 4c1.9 0 3.6 1 4.8 2.6C13.2 5 14.9 4 16.8 4 20 4 22.4 7 21.2 10.4 19.5 15.4 12 20 12 20z"/></symbol>
      <symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></symbol>
      <symbol id="i-chat" viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></symbol>
      <symbol id="i-box" viewBox="0 0 24 24"><path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/></symbol>
      <symbol id="i-tiktok" viewBox="0 0 24 24"><path d="M15 3v10.5a4 4 0 1 1-4-4"/><path d="M15 3c.4 2.7 2.2 4.5 5 4.7"/></symbol>
    </defs>
  </svg>

  <!-- Startup: automatic sign-in -->
  <div id="splash" class="splash">
    <div class="splash-card">
      <svg class="splash-logo"><use href="#i-logo"/></svg>
      <h1>Viewdesk</h1>
      <p class="splash-sub" id="splash-sub">Getting things ready</p>
      <ol class="splash-steps" id="splash-steps">
        <li data-step="connecting"><span class="dot"></span>Connecting to leofame.com</li>
        <li data-step="signing_in"><span class="dot"></span>Signing in automatically</li>
        <li data-step="ready"><span class="dot"></span>Loading your account</li>
      </ol>
      <div class="splash-error" id="splash-error" hidden>
        <p id="splash-error-text"></p>
        <button class="btn btn-primary" id="splash-retry" type="button">Try again</button>
      </div>
    </div>
  </div>

  <!-- Sign in (first run, or when the saved account stops working) -->
  <main id="login-view" class="login" hidden>
    <form class="login-card card" id="login-form" autocomplete="on">
      <svg class="login-logo"><use href="#i-logo"/></svg>
      <h1>Sign in to your account</h1>
      <p class="muted">You only need to do this once. Next time the app signs in for you.</p>
      <label class="field">
        <span>Email</span>
        <div class="input"><svg class="ico"><use href="#i-mail"/></svg><input type="email" name="email" placeholder="you@example.com" required autocomplete="username"></div>
      </label>
      <label class="field">
        <span>Password</span>
        <div class="input"><svg class="ico"><use href="#i-key"/></svg><input type="password" name="password" placeholder="Your leofame.com password" required autocomplete="current-password"></div>
      </label>
      <p class="form-error" id="login-error" hidden></p>
      <button class="btn btn-primary btn-block" id="login-submit" type="submit">Sign in</button>
      <p class="login-note"><svg class="ico"><use href="#i-shield"/></svg>Credentials are stored only on this computer.</p>
    </form>
  </main>

  <!-- App -->
  <div id="shell" class="shell" hidden>
    <aside class="sidebar">
      <div class="brand"><svg><use href="#i-logo"/></svg><div><strong>Viewdesk</strong><span>TikTok views console</span></div></div>
      <nav class="nav" id="nav">
        <button class="nav-item active" data-page="home" type="button"><svg class="ico"><use href="#i-home"/></svg><span>Home</span></button>
        <button class="nav-item" data-page="orders" type="button"><svg class="ico"><use href="#i-orders"/></svg><span>Orders</span></button>
      </nav>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="balance-chip" title="Account balance"><svg class="ico"><use href="#i-wallet"/></svg><span id="chip-balance">$0.00</span></div>
        <button class="icon-btn" id="theme-toggle" type="button" title="Toggle theme" aria-label="Toggle theme"><svg class="ico"><use href="#i-moon"/></svg></button>
        <div class="avatar" id="avatar"></div>
      </header>

      <div class="content">
        <!-- Home: buy TikTok views (one compact workbench) -->
        <section class="page" id="page-home">
          <div class="workbench">
            <div class="jobs-toolbar">
              <button class="add-job" id="add-job" type="button" title="Add another post — work on several at once" aria-label="Add another post">
                <span class="plus"><svg class="ico"><use href="#i-plus"/></svg></span><span>Add post</span>
              </button>
              <div class="jobs-status" id="jobs-status" hidden></div>
              <label class="agree"><input type="checkbox" id="agree"><span>I agree to the <a href="https://leofame.com/terms" target="_blank" rel="noopener">Terms</a> &amp; <a href="https://leofame.com/refund-policy" target="_blank" rel="noopener">Refund Policy</a></span></label>
            </div>
            <p class="sum-note lock-note"><svg class="ico"><use href="#i-lock"/></svg>Card details are typed only on Mastercard's secure page — this app never sees them.</p>
            <div class="jobs-stack" id="jobs-stack"></div>
            <datalist id="recent-links"></datalist>
          </div>
        </section>


        <!-- Orders -->
        <section class="page" id="page-orders" hidden>
          <div class="page-head">
            <div><h2>Orders</h2><p class="muted" id="orders-sub">Your order history from leofame.com</p></div>
            <div class="live-tools">
              <span class="live" id="orders-live" title="This list stays in step with leofame.com by itself"><i class="live-dot"></i><span id="orders-live-text">Live</span></span>
              <button class="btn btn-ghost" id="orders-refresh" type="button"><svg class="ico"><use href="#i-refresh"/></svg>Refresh</button>
            </div>
          </div>

          <div class="toolbar">
            <div class="tabs" id="orders-tabs">
              <button class="tab on" data-status="all" type="button">All</button>
              <button class="tab" data-status="pending" type="button">Pending</button>
              <button class="tab" data-status="processing" type="button">Processing</button>
              <button class="tab" data-status="completed" type="button">Completed</button>
              <button class="tab" data-status="canceled" type="button">Canceled</button>
            </div>
            <div class="toolbar-end">
              <form class="search" id="orders-search">
                <div class="sel">
                  <select id="search-type" aria-label="Search by">
                    <option value="1">Order ID</option>
                    <option value="3">Order link</option>
                  </select>
                  <svg class="ico"><use href="#i-chevron"/></svg>
                </div>
                <div class="input">
                  <svg class="ico"><use href="#i-search"/></svg>
                  <input type="text" id="search-q" placeholder="Search orders…" autocomplete="off" spellcheck="false">
                  <button class="clear-btn" id="search-clear" type="button" aria-label="Clear search" hidden><svg class="ico"><use href="#i-x"/></svg></button>
                </div>
              </form>
            </div>
          </div>

          <div class="bulk" id="cancel-bar" hidden>
            <span class="bulk-ico"><svg class="ico"><use href="#i-clock"/></svg></span>
            <p><b id="cancel-bar-count">2 unpaid orders</b>are waiting for payment. Not needed any more? Cancel them all at once.</p>
            <button class="btn cancel-all" id="cancel-all" type="button"></button>
          </div>

          <div class="orders-panel">
            <div class="o-skeleton" id="orders-loading" aria-hidden="true">
              <div class="o-skel"><i class="a"></i><div><i class="b"></i><i class="c"></i><i class="d"></i></div><i class="e"></i></div>
              <div class="o-skel"><i class="a"></i><div><i class="b"></i><i class="c"></i><i class="d"></i></div><i class="e"></i></div>
              <div class="o-skel"><i class="a"></i><div><i class="b"></i><i class="c"></i><i class="d"></i></div><i class="e"></i></div>
            </div>
            <div class="orders-list" id="orders-body" role="list" hidden></div>
            <div class="card table-card" id="orders-generic" hidden>
              <div class="table-wrap"><table class="table"><thead id="orders-head"></thead><tbody id="orders-generic-body"></tbody></table></div>
            </div>
            <div class="card state" id="orders-empty" hidden>
              <div class="state-ico"><svg class="ico"><use href="#i-inbox"/></svg></div>
              <h3 id="orders-empty-title">No orders yet</h3>
              <p class="muted" id="orders-empty-text">Orders placed on your account will show up here.</p>
              <div class="state-actions" id="orders-empty-actions"></div>
            </div>
            <div class="card state error" id="orders-error" hidden>
              <div class="state-ico"><svg class="ico"><use href="#i-alert"/></svg></div>
              <h3>Could not load orders</h3>
              <p class="muted" id="orders-error-text"></p>
              <button class="btn btn-primary" id="orders-retry" type="button">Try again</button>
            </div>
            <nav class="pager" id="orders-pager" hidden></nav>
          </div>
        </section>
      </div>
    </div>
  </div>

  <div class="modal" id="modal" hidden role="dialog" aria-modal="true"><div class="modal-card" id="modal-card"></div></div>
  <div id="toasts" class="toasts" aria-live="polite"></div>
  <script>
    "use strict";

    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    async function api(path, body) {
      const opts = body === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      };
      const res = await fetch(path, opts);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { const err = new Error(data.error || `Request failed (${res.status})`); err.details = data.details || ""; throw err; }
      return data;
    }

    let state = null;

    function toast(message, kind = "ok") {
      const node = document.createElement("div");
      node.className = `toast ${kind}`;
      node.innerHTML = `<svg class="ico"><use href="#i-${kind === "ok" ? "check" : "alert"}"/></svg><span>${esc(message)}</span>`;
      $("#toasts").append(node);
      setTimeout(() => { node.classList.add("out"); setTimeout(() => node.remove(), 300); }, 4200);
    }

    /* ---------- Startup / automatic sign-in ---------- */
    const STEP_ORDER = ["connecting", "signing_in", "ready"];

    function renderSplash(s) {
      const at = STEP_ORDER.indexOf(s.stage);
      $$("#splash-steps li").forEach((li) => {
        const i = STEP_ORDER.indexOf(li.dataset.step);
        li.className = at > i || s.stage === "ready" ? "done" : at === i ? "active" : "";
      });
      const failed = s.stage === "offline";
      $("#splash-error").hidden = !failed;
      $("#splash-error-text").textContent = s.error;
      $("#splash-sub").textContent = failed ? "Could not connect" : s.message || "Getting things ready";
    }

    async function boot() {
      for (;;) {
        try { state = await api("/api/state"); } catch { await sleep(500); continue; }
        renderSplash(state);
        if (state.stage === "ready") break;
        if (state.stage === "needs_login") { showLogin(state.error); return; }
        await sleep(state.stage === "offline" ? 1200 : 450);
      }
      await sleep(350);
      enterApp();
    }

    function showLogin(error) {
      $("#splash").classList.add("gone");
      $("#shell").hidden = true;
      $("#login-view").hidden = false;
      const box = $("#login-error");
      box.hidden = !error;
      box.textContent = error || "";
      setTimeout(() => $("#login-form [name=email]").focus(), 50);
    }

    function enterApp() {
      $("#login-view").hidden = true;
      $("#shell").hidden = false;
      $("#splash").classList.add("gone");
      renderTopbar();
      initHome();
    }

    $("#splash-retry").addEventListener("click", async () => {
      await api("/api/retry", {});
      boot();
    });

    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = $("#login-submit");
      const form = new FormData(e.target);
      btn.disabled = true; btn.textContent = "Signing in…";
      $("#login-error").hidden = true;
      try {
        state = await api("/api/login", { email: form.get("email"), password: form.get("password") });
        e.target.reset();
        enterApp();
        toast("Signed in successfully");
      } catch (err) {
        $("#login-error").textContent = err.message;
        $("#login-error").hidden = false;
      } finally {
        btn.disabled = false; btn.textContent = "Sign in";
      }
    });

    /* ---------- Topbar: balance chip, theme, avatar ---------- */
    function renderTopbar() {
      $("#chip-balance").textContent = (state.account && state.account.balance_text) || "$0.00";
      $("#avatar").textContent = (state.email || "?")[0];
      $("#avatar").title = state.email;
    }

    function applyThemeIcon() {
      const dark = document.documentElement.dataset.theme === "dark";
      $("#theme-toggle use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
    }
    $("#theme-toggle").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch { /* storage unavailable */ }
      applyThemeIcon();
    });
    applyThemeIcon();

    // Keep the balance fresh when the window comes back into view.
    let lastRefresh = Date.now();
    document.addEventListener("visibilitychange", async () => {
      if (document.hidden || $("#shell").hidden || Date.now() - lastRefresh < 30000) return;
      lastRefresh = Date.now();
      try {
        state = await api("/api/refresh", {});
        if (state.stage === "ready") renderTopbar(); else showLogin(state.error);
      } catch { /* keep showing the last balance */ }
    });

    /* ---------- Navigation ---------- */
    let currentPage = "home";
    function go(page) {
      currentPage = page;
      $$(".page").forEach((p) => { p.hidden = p.id !== `page-${page}`; });
      $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.page === page));
      if (page === "orders") loadOrders(); else clearTimeout(orders.timer);
    }
    $("#nav").addEventListener("click", (e) => { const b = e.target.closest(".nav-item"); if (b) go(b.dataset.page); });

    /* ---------- Modal ---------- */
    const modal = { busy: false };
    function openModal(html, cls = "") {
      modal.busy = false;
      $("#modal-card").className = "modal-card" + (cls ? ` ${cls}` : "");
      $("#modal-card").innerHTML = html;
      $("#modal").hidden = false;
    }
    function closeModal() { if (!modal.busy) { $("#modal").hidden = true; modalJob = null; } }
    function setModalBusy(busy) {
      modal.busy = busy;
      $$("#modal-card button, #modal-card textarea").forEach((el) => { el.disabled = busy; });
      const go = $("#modal-go");
      if (go) go.classList.toggle("is-loading", busy);
    }
    function showModalError(text, details = "") {
      const box = $("#modal-error");
      if (!box) return;
      box.hidden = !text;
      box.innerHTML = `${esc(text)}${details ? `<details><summary>Technical details</summary><pre>${esc(details)}</pre></details>` : ""}`;
    }
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-close]")) closeModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal").hidden) closeModal(); });

    // A confirmation (optionally with a text field) that stays open, with a spinner, while `run` works.
    function confirmAction({ title, html = "", confirmLabel, cancelLabel = "Keep", danger = false, field = null, run }) {
      openModal(`<h3>${esc(title)}</h3>${html}
        ${field ? `<textarea id="modal-field" rows="3" placeholder="${esc(field.placeholder)}"></textarea>` : ""}
        <div class="modal-error" id="modal-error" hidden></div>
        <div class="modal-actions">
          <button class="btn btn-ghost" data-close type="button">${esc(cancelLabel)}</button>
          <button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="modal-go" type="button"><span class="btn-spin"></span>${esc(confirmLabel)}</button>
        </div>`);
      (field ? $("#modal-field") : $("#modal-go")).focus();
      $("#modal-go").addEventListener("click", async () => {
        const value = field ? $("#modal-field").value.trim() : "";
        if (field && field.required && !value) return showModalError(field.requiredMessage || "Please fill this in.");
        showModalError(""); setModalBusy(true);
        try { await run(value); modal.busy = false; closeModal(); }
        catch (err) { setModalBusy(false); showModalError(err.message, err.details); }
      });
    }

    async function copyText(text) {
      try { await navigator.clipboard.writeText(text); }
      catch {
        const area = document.createElement("textarea");
        area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
        document.body.append(area); area.select(); document.execCommand("copy"); area.remove();
      }
      toast(`Copied ${text.length > 40 ? "the link" : text}`);
    }

    /* ---------- Orders (live) ---------- */
    const orders = { status: "all", q: "", type: "1", url: "", seq: 0, loaded: false, list: [], snapshot: null, fetchedAt: 0, loading: false, failed: false, timer: 0, flash: new Set(), payOpen: new Set(), payLoading: new Set(), cancelling: new Map(), cards: new Map(), enterTimer: 0 };
    const ACTIVE_RE = /await|pending|process|progress|partial|start/i;

    function ordersQuery() {
      const p = new URLSearchParams();
      if (orders.url) p.set("url", orders.url);
      else if (orders.q) { p.set("q", orders.q); p.set("type", orders.type); }
      else p.set("status", orders.status);
      return p;
    }

    function setOrdersView(view) {
      $("#orders-loading").hidden = view !== "loading";
      $("#orders-body").hidden = view !== "list";
      $("#orders-generic").hidden = view !== "generic";
      $("#orders-empty").hidden = view !== "empty";
      $("#orders-error").hidden = view !== "error";
      if (view !== "list" && view !== "generic") $("#orders-pager").hidden = true;
    }

    // Keeps the list in step with leofame.com: quick while something is still moving, slower otherwise.
    function scheduleOrders() {
      clearTimeout(orders.timer);
      if (currentPage !== "orders") return;
      const moving = orders.list.some((o) => ACTIVE_RE.test(o.status.text));
      orders.timer = setTimeout(() => { if (!document.hidden) loadOrders({ silent: true }); else scheduleOrders(); }, orders.cancelling.size ? 3000 : moving ? 8000 : 40000);
    }

    function updateLive() {
      const el = $("#orders-live");
      const secs = orders.fetchedAt ? Math.max(0, Math.round((Date.now() - orders.fetchedAt) / 1000)) : null;
      const ago = secs == null ? "" : secs < 5 ? "just now" : secs < 60 ? `${secs}s ago` : `${Math.floor(secs / 60)}m ago`;
      el.className = "live" + (orders.loading ? " busy" : orders.failed ? " err" : "");
      $("#orders-live-text").innerHTML = orders.loading ? "Syncing…" : orders.failed ? `Offline · last sync <b>${ago || "never"}</b>` : `Live · updated <b>${ago || "…"}</b>`;
    }
    setInterval(updateLive, 1000);

    async function loadOrders({ silent = false } = {}) {
      const seq = ++orders.seq;
      if (!silent) setOrdersView("loading");
      orders.loading = true; updateLive();
      $("#orders-refresh").classList.add("spin");
      try {
        const data = await api(`/api/orders?${ordersQuery()}`);
        if (seq !== orders.seq) return;
        orders.loaded = true; orders.failed = false; orders.fetchedAt = Date.now();
        renderOrders(data);
      } catch (err) {
        if (seq !== orders.seq) return;
        orders.failed = true;
        if (!silent || !orders.loaded) {
          $("#orders-error-text").textContent = err.message;
          setOrdersView("error");
        }
      } finally {
        if (seq === orders.seq) { orders.loading = false; $("#orders-refresh").classList.remove("spin"); updateLive(); scheduleOrders(); }
      }
    }

    // What changed since the last sync (new orders, new statuses): flash the row and say so.
    function diffOrders(list) {
      const previous = orders.snapshot, changed = new Set();
      const now = new Map(list.map((o) => [o.id, o.status.text]));
      if (previous && !orders.url) {
        for (const o of list) {
          if (!previous.has(o.id)) { changed.add(o.id); }
          else if (previous.get(o.id) !== o.status.text) { changed.add(o.id); toast(`Order #${o.id} is now ${o.status.text}`); }
        }
      }
      orders.snapshot = orders.url ? null : now;
      return changed;
    }

    const ICONS = { copy: "i-copy", cart: "i-cart", card: "i-card", x: "i-x", refund: "i-refund", info: "i-info", link: "i-link", ext: "i-ext", clock: "i-clock", alert: "i-alert",
      eye: "i-eye", heart: "i-heart", user: "i-user", chat: "i-chat", box: "i-box", tiktok: "i-tiktok", plus: "i-plus" };
    const icon = (name) => `<svg class="ico"><use href="#${ICONS[name]}"/></svg>`;
    const isTikTok = (url) => /^https?:\/\/([\w-]+\.)?tiktok\.com\//i.test(url || "");
    const shortUrl = (url) => String(url).replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    // "2026-09-19 21:41:24" -> { day: "19 Sep", time: "21:41" } (the year only shows for other years)
    function whenParts(text) {
      const m = String(text || "").match(/^(\d{4})-(\d{2})-(\d{2})[ T]+(\d{2}):(\d{2})/);
      if (!m) return { day: text || "—", time: "" };
      const year = Number(m[1]);
      return { day: `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] || m[2]}${year === new Date().getFullYear() ? "" : ` ${year}`}`, time: `${m[4]}:${m[5]}` };
    }

    // "500 tiktok views (1 of 3)" -> title "500 TikTok views" + part "1 of 3"
    function serviceParts(o) {
      const raw = String(o.service || "").trim(), m = raw.match(/^(.*?)\s*\((\d+\s+of\s+\d+)\)\s*$/i);
      const base = (m ? m[1] : raw).replace(/\btiktok\b/gi, "TikTok");
      return { title: base ? base.charAt(0).toUpperCase() + base.slice(1) : "Order", part: m ? m[2] : "" };
    }
    const serviceIcon = (text) => (/like/i.test(text) ? "heart" : /follow|subscrib/i.test(text) ? "user" : /comment/i.test(text) ? "chat" : /view|watch|play/i.test(text) ? "eye" : "box");

    // Cancelled orders are calm grey; only real failures are red.
    function toneOf(o) {
      const s = o.status.text || "";
      if (/cancel/i.test(s)) return "mute";
      if (/fail|refus|reject|error/i.test(s)) return "err";
      return ["ok", "warn", "info", "err"].includes(o.status.tone) ? o.status.tone : "mute";
    }

    // The TikTok post an order is for: @account · …last digits, opens on TikTok.
    function postChip(f) {
      const raw = String(f.url || f.value || ""), link = isTikTok(f.url) ? f.url : "";
      const m = raw.match(/tiktok\.com\/(@[^/?#\s]+)(?:\/video\/(\d+))?/i);
      let who = m ? m[1] : shortUrl(raw);
      try { who = decodeURIComponent(who); } catch { /* keep the text as it is */ }
      const vid = m && m[2] ? `…${m[2].slice(-6)}` : "";
      const inner = `${icon(m ? "tiktok" : "link")}<span class="who">${esc(who)}</span>${vid ? `<span class="vid">${esc(vid)}</span>` : ""}`;
      return link
        ? `<a class="o-link" href="${esc(link)}" target="_blank" rel="noopener noreferrer" title="Open the post on TikTok">${inner}${icon("ext")}</a>`
        : `<span class="o-link plain" title="${esc(raw)}">${inner}</span>`;
    }

    const statsHtml = (o, skip) => {
      const items = o.facts.filter((f) => f !== skip && !f.payment && f.value && f.value !== "—");
      return items.length ? `<div class="o-stats">${items.map((f) => `<span>${esc(f.label)}<b>${esc(f.value)}</b></span>`).join("")}</div>` : "";
    };

    const noteHtml = (n, tone) => {
      const text = String(n.text || "").replace(/^[\s*•·-]+/, "").trim();
      if (!text) return "";
      const t = tone === "mute" && n.tone === "err" ? "mute" : (n.tone || "mute");
      return `<p class="o-note ${esc(t)}" title="${esc(text)}">${icon(t === "warn" ? "clock" : t === "err" ? "alert" : "info")}<span>${esc(text)}</span></p>`;
    };

    function actionButton(o, a) {
      const cls = a.kind === "cancel" ? "danger" : a.kind === "refund" ? "warn" : "";
      const ic = a.kind === "cancel" ? "x" : a.kind === "refund" ? "refund" : a.kind === "info" ? "info" : "link";
      return `<button class="act ${cls}" type="button" data-do="${esc(a.kind)}" data-id="${esc(o.id)}" data-label="${esc(a.label)}">${icon(ic)}${esc(a.label)}</button>`;
    }

    const money = (text) => { const m = String(text || "").match(/-?\d[\d,]*(?:\.\d+)?/); return m ? `$${Number(m[0].replace(/,/g, "")).toFixed(2)}` : String(text || "—"); };

    // The payment behind an order, right under its buttons: method, amount, status, refunds - and more on demand.
    function payNoteHtml(o) {
      const pay = o.payment, open = orders.payOpen.has(o.id);
      if (!pay) return open ? `<div class="pay-note"><span class="pn-none">${orders.payLoading.has(o.id) ? "Loading from leofame.com…" : "No payment record on leofame.com."}</span></div>` : "";
      const others = pay.shared.length;
      const rows = [["Transaction", pay.trx ? `#${pay.trx}` : ""], ["Reference", pay.reference || ""],
        ["Created", (pay.created || "").replace(" ", " · ")], ["Orders", others ? pay.order_ids.map((i) => `#${i}`).join(", ") : ""]].filter(([, v]) => v);
      return `<div class="pay-note">
        <div class="pn-top"><span class="pn-method">${icon("card")}${esc(pay.method || "payment")}</span><b class="pn-amount">${esc(money(pay.amount))}</b></div>
        <span class="pn-status ${esc(pay.status.tone)}"><i></i>${esc(pay.status.text || "—")}</span>
        <small>Refunded ${esc(money(pay.refunded || "0"))}${others ? ` · covers ${others + 1} orders` : ""}</small>
        ${open && rows.length ? `<dl class="pn-full">${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
      </div>`;
    }

    function actionCell(o) {
      const open = orders.payOpen.has(o.id);
      const buttons = o.actions.map((a) => (a.kind === "cancel" && orders.cancelling.has(o.id)
        ? '<span class="act cancelling"><span class="mini-spin"></span>Cancelling…</span>' : actionButton(o, a))).join("");
      return `<div class="o-actions"><div class="act-row">${buttons}
        <button class="mini-btn" type="button" data-reorder="${esc(o.id)}" title="Order again" aria-label="Order again">${icon("cart")}</button>
        <button class="mini-btn pay-toggle${open ? " on" : ""}" type="button" data-payment="${esc(o.id)}" aria-expanded="${open}" title="Payment details" aria-label="Payment details">${icon("card")}</button></div>
        ${payNoteHtml(o)}</div>`;
    }

    function orderCardHtml(o, index) {
      const tone = toneOf(o), svc = serviceParts(o), when = whenParts(o.created);
      const linkFact = o.facts.find((f) => /link/i.test(f.label) && (f.url || f.value));
      const showBar = o.progress != null && /process|progress|start|partial|complet|running/i.test(o.status.text);
      const line = `${linkFact ? postChip(linkFact) : ""}${statsHtml(o, linkFact)}`;
      return `<article class="order t-${tone}" role="listitem" data-id="${esc(o.id)}" style="--i:${Math.min(index, 8)}">
        <div class="o-main">
          <span class="o-ico" aria-hidden="true">${icon(serviceIcon(o.service))}</span>
          <div class="o-body">
            <div class="o-title"><h3>${esc(svc.title)}</h3>${svc.part ? `<span class="o-part">${esc(svc.part)}</span>` : ""}</div>
            <div class="o-meta">
              <span class="o-id"><b>#${esc(o.id)}</b><button class="mini-btn" type="button" data-copy="${esc(o.id)}" title="Copy order ID" aria-label="Copy order ID">${icon("copy")}</button></span>
              <span class="sep"></span><time class="o-when" title="${esc(o.created)}">${esc(when.day)}${when.time ? ` · ${esc(when.time)}` : ""}</time>
            </div>
            ${line ? `<div class="o-line">${line}</div>` : ""}
            ${showBar ? `<div class="o-progress" title="${o.progress}% delivered"><div class="o-bar"><i style="width:${o.progress}%"></i></div><b>${o.progress}%</b></div>` : ""}
            ${o.notes.map((n) => noteHtml(n, tone)).join("")}
          </div>
        </div>
        <div class="o-mid">
          <span class="o-status"><span class="badge ${esc(tone)}">${esc(o.status.text || "—")}</span></span>
          <span class="o-price">${esc(o.price || "—")}</span>
        </div>
        ${actionCell(o)}
      </article>`;
    }

    // A layout we do not recognise: show the site's table as plain text rather than nothing.
    function genericRowsHtml(rows) {
      return rows.map((row) => `<tr>${row.map((c) => `<td>${esc(c.lines.join(" · ") || "—")}</td>`).join("")}</tr>`).join("");
    }

    // Only the cards that changed are replaced: nothing flickers and a text selection in another card survives a sync.
    function renderOrderRows() {
      const host = $("#orders-body");
      const items = orders.list.map((o, i) => [o.id, orderCardHtml(o, i)]);
      const cards = [...host.children];
      if (cards.length === items.length && cards.every((c, i) => c.dataset.id === items[i][0])) {
        items.forEach(([id, html], i) => {
          if (orders.cards.get(id) === html) return;
          const focused = cards[i].contains(document.activeElement) ? document.activeElement : null;   // keep the keyboard where it was
          const key = !focused ? "" : ["data-copy", "data-reorder", "data-payment"].map((a) => (focused.hasAttribute(a) ? `[${a}]` : "")).find(Boolean) || (focused.dataset.do ? `[data-do="${focused.dataset.do}"]` : "");
          cards[i].outerHTML = html;
          if (key) { const again = host.querySelector(`.order[data-id="${id}"] ${key}`); if (again) again.focus(); }
        });
      } else {
        host.innerHTML = items.map(([, html]) => html).join("");
        host.classList.add("enter");
        clearTimeout(orders.enterTimer);
        orders.enterTimer = setTimeout(() => host.classList.remove("enter"), 900);
      }
      orders.cards = new Map(items);
      const flashing = orders.flash; orders.flash = new Set();          // each highlight is shown once and clears itself
      flashing.forEach((id) => {
        const card = host.querySelector(`.order[data-id="${id}"]`);
        if (!card) return;
        card.classList.add("flash");
        setTimeout(() => card.classList.remove("flash"), 3000);
      });
      updateCancelAll();
    }

    const cancellable = (o) => o.actions.some((a) => a.kind === "cancel") && !/cancel/i.test(o.status.text);
    function updateCancelAll() {
      const open = orders.list.filter((o) => cancellable(o) && !orders.cancelling.has(o.id));
      $("#cancel-bar").hidden = open.length < 2;
      $("#cancel-bar-count").textContent = `${open.length} unpaid orders `;
      $("#cancel-all").innerHTML = `${icon("x")}Cancel all unpaid (${open.length})`;
    }

    function renderOrders(data) {
      state.account = data.account;
      renderTopbar();
      const structured = data.orders.length > 0, count = structured ? data.orders.length : data.rows.length;
      orders.list = data.orders;
      orders.flash = diffOrders(data.orders);
      for (const [id, since] of orders.cancelling) {          // a cancellation is over once the site shows it (or after 3 minutes)
        const o = data.orders.find((x) => x.id === id);
        if (!o || !cancellable(o) || Date.now() - since > 180000) orders.cancelling.delete(id);
      }

      $$("#orders-tabs .tab").forEach((tab) => {
        const s = tab.dataset.status;
        tab.classList.toggle("on", !orders.q && s === orders.status);
        const label = tab.dataset.label || (tab.dataset.label = tab.textContent);
        tab.innerHTML = data.counts[s] != null ? `${esc(label)} <span class="count">${data.counts[s]}</span>` : esc(label);
      });

      if (structured) renderOrderRows();
      else if (count) {
        $("#orders-head").innerHTML = `<tr>${data.columns.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>`;
        $("#orders-generic-body").innerHTML = genericRowsHtml(data.rows);
      }
      const open = data.orders.filter((o) => ACTIVE_RE.test(o.status.text)).length;
      $("#orders-sub").textContent = count
        ? `${count} order${count === 1 ? "" : "s"} on this page${open ? ` · ${open} in progress` : ""}`
        : "Your order history from leofame.com";

      if (!count) {
        const searching = !!orders.q, filtered = orders.status !== "all";
        $("#orders-empty-title").textContent = data.notice || (searching ? "No matching orders" : !filtered ? "No orders yet" : `No ${orders.status} orders`);
        $("#orders-empty-text").textContent = searching ? "Try another order ID or link." : filtered ? "Nothing here right now. Try another tab." : "Orders placed on your account will show up here.";
        $("#orders-empty-actions").innerHTML = searching ? '<button class="btn btn-ghost" data-empty="clear" type="button">Clear search</button>'
          : filtered ? '<button class="btn btn-ghost" data-empty="all" type="button">Show all orders</button>'
          : `<button class="btn btn-primary" data-empty="new" type="button">${icon("plus")}Place an order</button>`;
        return setOrdersView("empty");
      }
      setOrdersView(structured ? "list" : "generic");

      const pager = $("#orders-pager");
      pager.hidden = data.pages.length < 2;
      pager.innerHTML = data.pages.map((p) =>
        `<button class="pg${p.active ? " on" : ""}" type="button" ${p.url && !p.active && !p.disabled ? `data-url="${esc(p.url)}"` : "disabled"}>${esc(p.label)}</button>`).join("");
    }

    // The fresh copy of an order (from an action) replaces the old row straight away.
    function applyOrderUpdate(order) {
      if (!order) return;
      const at = orders.list.findIndex((o) => o.id === order.id);
      if (at >= 0) { orders.list[at] = order; if (orders.snapshot) orders.snapshot.set(order.id, order.status.text); orders.flash = new Set([order.id]); renderOrderRows(); }
    }

    /* --- what the buttons do --- */
    const findOrder = (id) => orders.list.find((o) => o.id === String(id));
    const orderSummary = (o) => `<div class="modal-order"><b>${esc(o.service)}</b>
      ${o.facts.filter((f) => /quantity|link/i.test(f.label) && f.value).map((f) => `<span>${esc(f.label)}: ${esc(f.url ? shortUrl(f.value) : f.value)}</span>`).join("")}
      <span>Price: ${esc(o.price)} · Status: ${esc(o.status.text)}</span></div>`;

    async function doOrderAction(o, kind, reason) {
      const res = await api("/api/orders/action", { order_id: o.id, kind, reason });
      if (res.account) { state.account = res.account; renderTopbar(); }
      if (res.pending) orders.cancelling.set(o.id, Date.now());      // accepted by leofame.com, still being processed
      applyOrderUpdate(res.order);
      toast(res.message);
      loadOrders({ silent: true });
      return res;
    }

    function runAction(o, kind, label) {
      if (kind === "info") {
        const a = o.actions.find((x) => x.kind === "info");
        return openModal(`<h3>${esc(label)}</h3><p class="muted">${esc((a && a.text) || "No more details for this order.")}</p>
          <div class="modal-actions"><button class="btn btn-primary" data-close type="button">OK</button></div>`);
      }
      if (kind === "cancel") {
        return confirmAction({
          title: `Cancel order #${o.id}?`, confirmLabel: "Cancel order", cancelLabel: "Keep order", danger: true,
          html: `<p class="muted">Would you like to cancel and receive a refund to your Leofame account?</p>${orderSummary(o)}`,
          run: () => doOrderAction(o, "cancel"),
        });
      }
      if (kind === "refund") {
        return confirmAction({
          title: `Request a refund for order #${o.id}`, confirmLabel: "Send request", cancelLabel: "Close",
          html: orderSummary(o), field: { placeholder: "Let us know why you canceled…", required: true, requiredMessage: "Please enter a reason for the refund." },
          run: (reason) => doOrderAction(o, "refund", reason),
        });
      }
      return confirmAction({
        title: `${label} — order #${o.id}`, confirmLabel: label, cancelLabel: "Close", html: orderSummary(o),
        run: () => doOrderAction(o, "link"),
      });
    }

    const paymentFromRecord = (orderId, r) => ({
      trx: "", order_ids: [orderId], method: r.fields["Payment method"] || "", amount: r.fields["Amount"] || "", refunded: r.fields["Refunded"] || "",
      created: r.fields["Created"] || "", reference: r.fields["Transaction ID"] || "", shared: [], status: { text: r.fields["Status"] || "", tone: r.tone },
    });

    // The card button (or the Transaction ID link) shows / hides the full payment record right in the row.
    async function togglePayment(orderId) {
      const o = findOrder(orderId);
      if (!o) return;
      if (orders.payOpen.has(orderId)) orders.payOpen.delete(orderId); else orders.payOpen.add(orderId);
      if (orders.payOpen.has(orderId) && !o.payment && !orders.payLoading.has(orderId)) {     // older than the billing list we already have
        orders.payLoading.add(orderId); renderOrderRows();
        try {
          const d = await api(`/api/orders/payment?order_id=${encodeURIComponent(orderId)}`);
          if (d.records[0]) o.payment = paymentFromRecord(orderId, d.records[0]);
        } catch (err) { toast(err.message, "err"); }
        orders.payLoading.delete(orderId);
      }
      renderOrderRows();
    }

    // Cancel every unpaid order at once (e.g. all orders of an abandoned multi-post payment).
    $("#cancel-all").addEventListener("click", () => {
      const open = orders.list.filter((o) => cancellable(o) && !orders.cancelling.has(o.id));
      if (open.length < 2) return;
      confirmAction({
        title: `Cancel ${open.length} unpaid orders?`, confirmLabel: `Cancel ${open.length} orders`, cancelLabel: "Keep them", danger: true,
        html: `<p class="muted">Would you like to cancel these orders and receive a refund to your Leofame account?</p>
          <div class="modal-order">${open.map((o) => `<span><b>#${esc(o.id)}</b> · ${esc(o.service)} · ${esc(o.price)} · ${esc(o.status.text)}</span>`).join("")}</div>`,
        run: async () => {
          const res = await api("/api/orders/cancel", { order_ids: open.map((o) => o.id) });
          if (res.account) { state.account = res.account; renderTopbar(); }
          let done = 0;
          for (const r of res.results) {
            if (!r.ok) continue;
            done++; if (r.pending) orders.cancelling.set(r.id, Date.now());
            applyOrderUpdate(r.order);
          }
          toast(`${done} order${done === 1 ? "" : "s"} cancelled${res.results.some((r) => r.pending) ? " (some are still being processed)" : ""}`);
          loadOrders({ silent: true });
          const failed = res.results.filter((r) => !r.ok);
          if (failed.length) { const err = new Error(`${failed.length} could not be cancelled: ${failed[0].error}`); err.details = failed[0].details; throw err; }
        },
      });
    });

    // "Order again": reuse an empty post if there is one, otherwise add a new one, ready to verify.
    async function reorder(rec) {
      go("home");
      if (!catalog) await initHome();
      if (!catalog) return;
      let job = jobs.find((j) => !j.order.link.trim() && j.order.verify.status === "idle" && !busyPay(j.order));
      if (!job) { job = addJob(); if (!job) return; }
      renderJobsStack();
      const root = cardRoot(job);
      const pkg = catalog.packages.find((p) => p.id === rec.item_id), qty = rec.quantity, limits = catalog.custom;
      if (qty && rec.item_id === limits.item_id && qty >= limits.min && qty <= limits.max && !(pkg && qty === pkg.quantity)) {
        const qtyInput = root.querySelector(".custom-qty");
        qtyInput.value = String(qty);
        qtyInput.dispatchEvent(new Event("input", { bubbles: true }));
      } else if (pkg) {
        job.order.custom = false; job.order.pkgId = pkg.id; renderJobCard(job);
      }
      if (rec.link) setLink(job, rec.link); else renderJobCard(job);
      root.scrollIntoView({ block: "center", behavior: "smooth" });
      toast(`Order #${rec.id} copied into a new order`);
    }

    $("#orders-body").addEventListener("click", (e) => {
      const copy = e.target.closest("[data-copy]"), re = e.target.closest("[data-reorder]"), pay = e.target.closest("[data-payment]"), act = e.target.closest("[data-do]");
      if (copy) return copyText(copy.dataset.copy);
      if (re) { const o = findOrder(re.dataset.reorder); if (o) reorder(o); return; }
      if (pay) return togglePayment(pay.dataset.payment);
      if (act) { const o = findOrder(act.dataset.id); if (o) runAction(o, act.dataset.do, act.dataset.label); }
    });

    $("#orders-tabs").addEventListener("click", (e) => {
      const tab = e.target.closest(".tab");
      if (!tab) return;
      Object.assign(orders, { status: tab.dataset.status, q: "", url: "", snapshot: null });
      $("#search-q").value = ""; $("#search-clear").hidden = true;
      loadOrders();
    });

    $("#orders-search").addEventListener("submit", (e) => {
      e.preventDefault();
      Object.assign(orders, { q: $("#search-q").value.trim(), type: $("#search-type").value, url: "", snapshot: null });
      $("#search-clear").hidden = !orders.q;
      loadOrders();
    });
    $("#search-q").addEventListener("input", () => { $("#search-clear").hidden = !$("#search-q").value; });
    $("#search-clear").addEventListener("click", () => {
      $("#search-q").value = ""; $("#search-clear").hidden = true;
      Object.assign(orders, { q: "", url: "", snapshot: null });
      loadOrders();
    });

    $("#orders-pager").addEventListener("click", (e) => {
      const b = e.target.closest("[data-url]");
      if (!b) return;
      orders.url = b.dataset.url;
      loadOrders();
      $(".content").scrollTo({ top: 0, behavior: "smooth" });
    });

    $("#orders-refresh").addEventListener("click", () => loadOrders());
    $("#orders-retry").addEventListener("click", () => loadOrders());
    $("#orders-empty-actions").addEventListener("click", (e) => {
      const b = e.target.closest("[data-empty]");
      if (!b) return;
      if (b.dataset.empty === "new") return go("home");
      if (b.dataset.empty === "clear") return $("#search-clear").click();
      $('#orders-tabs .tab[data-status="all"]').click();
    });

    // Coming back to the window: sync right away instead of waiting for the next tick.
    const resync = () => { if (currentPage === "orders" && !document.hidden && Date.now() - orders.fetchedAt > 4000) loadOrders({ silent: true }); };
    document.addEventListener("visibilitychange", resync);
    window.addEventListener("focus", resync);

    /* ---------- Home: several posts, each a self-contained card ---------- */
    const usd = (n) => `$${Number(n).toFixed(2)}`;
    const number = (n) => Number(n || 0).toLocaleString("en-US");
    const compact = (n) => (n == null ? "—" : new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n));
    const TT_LINK_RE = /^(https?:\/\/)?((www|m|vm|vt)\.)?tiktok\.com\/\S+/i;
    const LINK_FINDER = /(?:https?:\/\/)?(?:[a-z0-9-]+\.)?tiktok\.com\/[^\s"'<>]+/gi;
    const POPUP_FEATURES = "popup=yes,width=540,height=820";
    const MAX_JOBS = 10;
    const store = {
      get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
      set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } },
    };

    let jobs = [], jobSeq = 0, catalog = null, agree = !!store.get("agree", false);
    let modalJob = null, openPop = null, dragScroll = null, lastDragWasMove = false;
    let order = null, posts = null;         // aliases for whichever job's "Select posts" popup is open
    let verifyChain = Promise.resolve();
    const recent = store.get("recentLinks", []);

    function makeJob(from) {
      const f = from ? from.order : null;
      return {
        id: ++jobSeq, closed: false, timers: { verify: 0, quote: 0 },
        order: {
          pkgId: f ? f.pkgId : "", custom: f ? f.custom : false, customQty: f ? f.customQty : "", quote: f ? f.quote : null,
          delivery: f ? f.delivery : "", link: "", email: f ? f.email : (state.email || ""),
          verify: { status: "idle" }, pay: { status: "idle" }, seq: 0, quoteSeq: 0, watch: 0,
        },
        posts: { user: "", link: "", pasted: "", items: [], cursor: null, pages: 1, selected: [], min: 100, sort: "site", small: store.get("postSize", "large") === "small", loading: false, note: "", noteErr: false },
      };
    }

    function selected(o) {
      if (!catalog) return null;
      if (o.custom) {
        const quote = o.quote;
        return quote && quote.quantity === Number(o.customQty)
          ? { id: catalog.custom.item_id, quantity: quote.quantity, price: quote.price, delivery: quote.delivery, custom: true } : null;
      }
      const pkg = catalog.packages.find((p) => p.id === o.pkgId);
      return pkg ? { ...pkg, delivery: catalog.delivery[pkg.id] || [], custom: false } : null;
    }
    const hasPackage = (o) => (o.custom ? !!o.customQty : !!o.pkgId);

    // The site's own price formula for custom quantities (a preview until the exact quote arrives).
    function estimateCustom(qty) {
      const prices = catalog.custom.prices, keys = Object.keys(prices).map(Number).sort((a, b) => a - b);
      if (!(qty > 0) || !keys.length) return null;
      if (qty <= keys[0]) return (prices[keys[0]] / keys[0]) * qty;
      let lo = 0, hi = Infinity;
      for (const k of keys) { if (k >= qty) { hi = k; break; } lo = k; }
      const lowP = lo > 0 ? prices[lo] : 0;
      if (hi === Infinity) return (lowP / lo) * qty;
      const lowU = lowP / lo, highU = prices[hi] / hi;
      return (lowU + ((highU - lowU) * (qty - lo)) / (hi - lo)) * qty;
    }

    function totals(o) {
      const s = selected(o);
      if (!s) return null;
      const balance = Math.max(0, (state.account && state.account.balance) || 0);
      const due = Math.max(0, +(s.price - balance).toFixed(2));
      const charge = due === 0 ? 0 : Math.max(due, catalog.card_minimum);
      return { price: s.price, applied: Math.min(balance, s.price), due, charge, credit: +(charge - due).toFixed(2) };
    }

    function syncDelivery(o) {
      const s = selected(o), options = s ? s.delivery : [];
      if (!options.some((d) => d.value === o.delivery)) o.delivery = (options.find((d) => d.recommended) || options[0] || {}).value || "";
    }

    function renderRecent() {
      $("#recent-links").innerHTML = recent.map((r) => `<option value="${esc(r.link)}" label="@${esc(r.user)}"></option>`).join("");
    }
    function rememberLink(link, user) {
      const clean = link.split("?")[0];
      const at = recent.findIndex((r) => r.link === clean);
      if (at >= 0) recent.splice(at, 1);
      recent.unshift({ link: clean, user });
      recent.length = Math.min(recent.length, 8);
      store.set("recentLinks", recent); renderRecent();
    }

    async function initHome() {
      if (!jobs.length) jobs.push(makeJob());
      $("#agree").checked = agree;
      renderRecent();
      if (catalog) return renderJobsStack();
      $("#jobs-stack").innerHTML = '<div class="card state"><p class="muted">Loading your packages…</p></div>';
      try {
        catalog = await api("/api/catalog");
        renderJobsStack();
      } catch (err) {
        catalog = null;
        $("#jobs-stack").innerHTML = `<div class="card state error"><div class="state-ico"><svg class="ico"><use href="#i-alert"/></svg></div><h3>Couldn't load packages</h3><p class="muted">${esc(err.message)}</p><button class="btn btn-primary" id="retry-catalog" type="button">Try again</button></div>`;
        $("#retry-catalog").addEventListener("click", initHome);
      }
    }

    /* --- jobs (one card per post) --- */
    const busyPay = (o) => ["creating", "waiting", "blocked"].includes(o.pay.status);
    function jobState(job) {
      const p = job.order.pay.status, v = job.order.verify.status;
      if (p === "found") return "done";
      if (p === "failed" || p === "error") return "failed";
      if (["creating", "waiting", "blocked", "closed"].includes(p)) return "paying";
      if (v === "checking") return "checking";
      if (v === "ok") return "ready";
      if (v === "error") return "failed";
      return "idle";
    }
    // Cards of the same account are told apart by the last digits of the post they were started from.
    function jobName(job, i) {
      if (job.order.verify.status !== "ok") return `Post ${i + 1}`;
      const clash = jobs.filter((j) => j.order.verify.status === "ok" && j.posts.user === job.posts.user).length > 1;
      return `@${job.posts.user}${clash ? ` …${String(job.posts.pasted).split(":")[0].slice(-4)}` : ""}`;
    }
    function jobMeta(job) {
      const st = jobState(job), s = selected(job.order), n = job.posts.selected.length;
      return { idle: s ? `${number(s.quantity)} views` : "Empty", checking: "Checking…", ready: `${s ? number(s.quantity) : ""} · ${n} post${n === 1 ? "" : "s"}`,
        paying: "Paying…", done: "Order placed", failed: job.order.verify.status === "error" ? "Link problem" : "Needs attention" }[st];
    }
    const jobLabel = (job) => (jobs.length > 1 ? `${jobName(job, jobs.indexOf(job))}: ` : "");
    const JOB_TONE = { idle: "", checking: "info", ready: "ready", paying: "paying", done: "done", failed: "failed" };
    const jobTone = (job) => JOB_TONE[jobState(job)];
    const cardRoot = (job) => $(`.job-card[data-job-id="${job.id}"]`);

    function addJob(link) {
      if (jobs.length >= MAX_JOBS) { toast(`You can work on ${MAX_JOBS} posts at once.`, "err"); return null; }
      const job = makeJob(jobs[jobs.length - 1]);   // a new post starts from whatever was picked last, for convenience
      if (link) job.order.link = link;
      jobs.push(job);
      return job;
    }

    function closeJob(job) {
      if (busyPay(job.order)) return toast("Finish or cancel this payment first.", "err");
      if (modalJob === job) closeModal();
      job.closed = true; clearTimeout(job.timers.verify); clearTimeout(job.timers.quote); job.order.watch++;
      jobs.splice(jobs.indexOf(job), 1);
      if (!jobs.length) jobs.push(makeJob());
      renderJobsStack();
    }

    function copyPackage(from, to) {
      Object.assign(to, { pkgId: from.pkgId, custom: from.custom, customQty: from.customQty, quote: from.quote, delivery: from.delivery });
    }
    // A post with no package yet simply follows whichever one was just picked elsewhere.
    function shareDefaults(fromJob) {
      for (const j of jobs) if (j !== fromJob && !hasPackage(j.order) && !busyPay(j.order)) { copyPackage(fromJob.order, j.order); invalidate(j, 150); }
    }
    function copyToAll(job) {
      if (!hasPackage(job.order)) return;
      let n = 0;
      for (const j of jobs) if (j !== job && !busyPay(j.order) && j.order.pay.status !== "found") { copyPackage(job.order, j.order); invalidate(j, 150 + n * 40); n++; }
      toast(n ? `Package and speed applied to ${n} other order${n === 1 ? "" : "s"}` : "No other orders to update");
    }

    $("#add-job").addEventListener("click", () => {
      const job = addJob();
      if (!job) return;
      renderJobsStack();
      const root = cardRoot(job);
      root.scrollIntoView({ block: "center", behavior: "smooth" });
      root.querySelector(".link-field").focus();
    });

    /* --- popups (package / delivery), one open at a time across every card --- */
    function closePops() {
      if (!openPop) return;
      const root = cardRoot(openPop.job);
      if (root) {
        root.classList.remove("has-pop");
        root.querySelectorAll(".pop-panel").forEach((p) => { p.hidden = true; });
        root.querySelectorAll(".pop-btn").forEach((b) => b.setAttribute("aria-expanded", "false"));
      }
      openPop = null;
    }
    function togglePop(job, name, btnEl) {
      const panel = btnEl.parentElement.querySelector(".pop-panel");
      const willOpen = panel.hidden;
      closePops();
      if (!willOpen || btnEl.disabled) return;
      panel.hidden = false; btnEl.setAttribute("aria-expanded", "true");
      cardRoot(job).classList.add("has-pop");
      openPop = { job, name };
      if (name === "pkg" && job.order.custom) cardRoot(job).querySelector(".custom-qty").focus();
    }
    document.addEventListener("click", (e) => { if (!e.target.closest(".pop")) closePops(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePops(); });

    /* --- rendering: one template per card, refreshed in place so typing is never interrupted --- */
    function cardHtml(job) {
      const o = job.order;
      return `<div class="job-card" data-job-id="${job.id}">
        <div class="job-head">
          <span class="job-dot"></span>
          <div class="job-title"><b></b><span></span></div>
          <button class="text-btn copy-pkg-btn" type="button" title="Copy this package and speed to every other post">Copy to all</button>
          <button class="job-close" type="button" aria-label="Remove this post"><svg class="ico"><use href="#i-x"/></svg></button>
        </div>
        <div class="bar-row">
          <div class="pop">
            <button class="pop-btn pkg-btn" type="button" data-pop="pkg" aria-haspopup="listbox" aria-expanded="false">
              <span class="pop-text"><span class="pop-label">1 · Package</span><span class="pop-value placeholder">Choose a package</span></span>
              <svg class="ico chev"><use href="#i-chevron"/></svg>
            </button>
            <div class="pop-panel pkg-panel" role="listbox" hidden>
              <div class="pkg-list"></div>
              <div class="opt-custom">
                <label for="custom-qty-${job.id}">Custom quantity</label>
                <div class="custom-line">
                  <input type="number" id="custom-qty-${job.id}" class="custom-qty" inputmode="numeric" placeholder="e.g. 1500" autocomplete="off" value="${esc(o.customQty)}">
                  <span class="custom-price"></span>
                </div>
                <p class="hint custom-hint"></p>
              </div>
            </div>
          </div>
          <div class="pop">
            <button class="pop-btn del-btn" type="button" data-pop="del" aria-haspopup="listbox" aria-expanded="false" disabled>
              <span class="pop-text"><span class="pop-label">2 · Delivery</span><span class="pop-value placeholder">Pick a package first</span></span>
              <svg class="ico chev"><use href="#i-chevron"/></svg>
            </button>
            <div class="pop-panel del-panel" role="listbox" hidden></div>
          </div>
          <div class="input link-input">
            <svg class="ico"><use href="#i-link"/></svg>
            <input type="url" class="link-field" list="recent-links" placeholder="3 · Paste a TikTok post link" autocomplete="off" spellcheck="false" value="${esc(o.link)}">
            <span class="link-state"></span>
            <button class="input-btn paste-btn" type="button" title="Paste from clipboard" aria-label="Paste from clipboard"><svg class="ico"><use href="#i-clipboard"/></svg></button>
          </div>
          <button class="pay-btn" type="button" disabled><span class="pay-spin"></span><svg class="ico pay-ico"><use href="#i-lock"/></svg><span class="pay-label">Pay</span></button>
        </div>
        <div class="job-sub">
          <p class="verify-line"></p>
          <label class="mini-input"><svg class="ico"><use href="#i-mail"/></svg><input type="email" class="email-field" placeholder="Receipt email" autocomplete="off" aria-label="Receipt email" value="${esc(o.email)}"></label>
        </div>
        <div class="post-strip-wrap"></div>
        <div class="job-foot"></div>
      </div>`;
    }

    function renderJobsStack() {
      if (!catalog) return;
      const host = $("#jobs-stack");
      const ids = jobs.map((j) => j.id);
      const have = [...host.children].map((c) => Number(c.dataset.jobId));
      const same = have.length === ids.length && have.every((id, i) => id === ids[i]);
      if (!same) host.innerHTML = jobs.map((j) => cardHtml(j)).join("");
      jobs.forEach((j) => renderJobCard(j));
      renderJobsStatus();
    }

    function renderJobsStatus() {
      $("#add-job").title = jobs.length >= MAX_JOBS ? `You can work on ${MAX_JOBS} posts at once` : "Add another post — work on several at once";
      const box = $("#jobs-status");
      box.hidden = jobs.length < 2;
      if (box.hidden) return;
      const ready = jobs.filter((j) => ["ready", "done"].includes(jobState(j))).length;
      box.innerHTML = `<b>${ready}</b> of ${jobs.length} ready`;
    }

    // The post-thumbnails strip: a quick preview, always visible, that opens the full picker on a click.
    function stripHtml(job) {
      const o = job.order, ps = job.posts;
      if (o.verify.status !== "ok") {
        const hint = o.verify.status === "checking" ? "Checking your post…" : o.verify.status === "error" ? "Fix the link above to choose posts"
          : !o.link.trim() ? "Paste a link to choose which posts get the views" : "Choose a package, then paste a link";
        return `<div class="post-strip"><span class="strip-track empty">${esc(hint)}</span></div>`;
      }
      const max = maxPosts(o, ps), n = ps.selected.length, byKey = new Map(ps.items.map((p) => [p.key, p]));
      const thumbs = ps.selected.map((k, i) => {
        const p = byKey.get(k);
        return p ? `<span class="strip-thumb" title="#${i + 1} · ${esc(compact(p.views))} views">${p.thumbnail ? `<img referrerpolicy="no-referrer" loading="lazy" alt="" src="${esc(p.thumbnail)}" onerror="this.remove()">` : ""}<i>${i + 1}</i></span>` : "";
      }).join("");
      return `<div class="post-strip">
        <div class="strip-track">${thumbs}</div>
        <button class="strip-manage" type="button"><svg class="ico"><use href="#i-grid"/></svg><span><b>${n}</b> of ${max} selected</span></button>
      </div>`;
    }

    const PAY_STEPS = ["Creating order", "Payment window", "Waiting for payment", "Confirmed"];

    // What leofame.com says about the order(s) that belong to this payment (a multi-post payment is several orders).
    const phaseOf = (o) => {
      const text = `${o.status.text} ${(o.notes || []).map((n) => n.text).join(" ")}`.toLowerCase();
      return /cancel|fail|declin|refund|reject/.test(text) ? "failed" : /process|progress|complet|partial|deliver/.test(o.status.text.toLowerCase()) ? "paid" : "pending";
    };
    // leofame.com's billing record for this payment: the truth about the card, next to the order's own status.
    const PAY_PHASES = [[/refus|declin|fail|error|cancel/i, "failed"], [/paid|success|complete|received|captur/i, "paid"], [/wait|pend|process|author/i, "pending"]];
    function paymentInfo(pay) {
      if (!pay) return null;
      const text = pay.status && pay.status.text ? pay.status.text : "";
      const phase = (PAY_PHASES.find(([re]) => re.test(text)) || [, "pending"])[1];
      return { phase, text: text || "—", tone: pay.status ? pay.status.tone : "", method: pay.method || "card", amount: money(pay.amount), refunded: money(pay.refunded || "0"), trx: pay.trx || "" };
    }

    function orderInfo(list) {
      if (!list || !list.length) return null;
      const phases = list.map(phaseOf);
      const phase = phases.includes("pending") ? "pending" : phases.includes("paid") ? "paid" : "failed";
      const ids = list.map((o) => `#${o.id}`);
      return {
        phase, ids, status: [...new Set(list.map((o) => o.status.text))].join(" / "),
        label: list.length === 1 ? `Order ${ids[0]}` : `${list.length} orders`, price: list.length === 1 ? list[0].price : "",
      };
    }

    // Order summary while idle, or the payment's progress once it has started — shown below the strip.
    function footHtml(job) {
      const o = job.order;
      if (o.pay.status !== "idle") return payStatusHtml(job);
      const s = selected(o), t = totals(o), v = o.verify, ps = job.posts, n = ps.selected.length;
      if (!s && !o.link.trim()) return "";
      const opt = s && s.delivery.find((d) => d.value === o.delivery);
      const chips = [s ? `<span class="sum-chip">${number(s.quantity)} views</span>` : '<span class="sum-chip empty">No package yet</span>'];
      if (opt) chips.push(`<span class="sum-chip">${esc(opt.label)}</span>`);
      if (v.status === "ok") chips.push(`<span class="sum-chip">@${esc(v.data.account.username)} · ${n} post${n === 1 ? "" : "s"}${n > 1 && s ? ` · ≈ ${number(perPost(o, ps))} each` : ""}</span>`);
      let fee = "";
      if (t) {
        if (t.credit > 0) fee = `Card minimum ${usd(catalog.card_minimum)} — the extra ${usd(t.credit)} is added to your balance`;
        else if (t.charge === 0) fee = "Your balance covers this order — finish it on leofame.com";
        else if (t.applied > 0) fee = `balance −${usd(t.applied)}`;
      }
      return `<div class="strip nested">
        <div class="sum-left"><div class="sum-chips">${chips.join("")}</div></div>
        <div class="sum-right">
          <div class="sum-total"><span>Total</span><b>${t ? usd(t.charge) : "—"}</b></div>
          ${fee ? `<p class="sum-fee">${esc(fee)}</p>` : ""}
        </div>
      </div>`;
    }

    function payStatusHtml(job) {
      const p = job.order.pay;
      const marks = {
        creating: ["active", "", "", ""], blocked: ["done", "active", "", ""], waiting: ["done", "done", "active", ""],
        closed: ["done", "done", "active", ""], failed: ["done", "done", "failed", ""], error: ["failed", "", "", ""],
        found: ["done", "done", "done", "done"],
      }[p.status];
      const info = orderInfo(p.orders);
      const cancellable = (p.orders || []).filter((x) => x.actions.some((a) => a.kind === "cancel")).length;
      const btn = (act, label, cls = "btn-ghost") => `<button class="btn ${cls}" data-act="${act}" type="button">${label}</button>`;
      let msg = "", actions = "";
      if (p.status === "creating") msg = "Reserving your package on leofame.com…";
      if (p.status === "error") { msg = `<span class="status-msg err">${esc(p.message)}</span>`; actions = btn("retry", "Try again", "btn-primary"); }
      if (p.status === "blocked") { msg = '<span class="status-msg warn">Your payment window was blocked — open it manually to continue.</span>'; actions = btn("open", "Open payment window", "btn-primary") + btn("cancel", "Cancel"); }
      if (p.status === "waiting") { msg = "Complete the payment in the secure window. This updates by itself."; actions = btn("open", "Reopen window") + btn("cancel", "Cancel payment"); }
      if (p.status === "closed") {
        msg = `<span class="status-msg warn">The window is closed${info ? ` and ${info.ids.length > 1 ? "the orders are" : "the order is"} still “${esc(info.status)}”` : ""}. If you paid, it can take a minute to update.</span>`;
        actions = btn("recheck", "Check again", "btn-primary") + (cancellable ? btn("cancel", cancellable > 1 ? "Cancel unpaid orders" : "Cancel unpaid order") : "") + btn("orders", "View in Orders") + btn("reset", "Start over");
      }
      if (p.status === "failed") { msg = `<span class="status-msg err">leofame.com cancelled ${info && info.ids.length > 1 ? "these orders" : "this order"} because the payment did not go through.</span>`; actions = btn("retry", "Try again", "btn-primary") + btn("orders", "View in Orders"); }
      if (p.status === "found") actions = btn("orders", "View in Orders", "btn-primary") + btn("reset", "New order");
      if (p.windowLeft && ["found", "failed"].includes(p.status)) {
        msg += ' <span class="status-msg warn">The payment window is still open — you can close it.</span>';
        actions = btn("close-window", "Close payment window") + actions;
      }
      const card = paymentInfo(p.payment);
      if (card && ["waiting", "closed", "found", "failed"].includes(p.status)) {
        const extra = card.phase === "paid" && p.credit > 0 ? ` · ${usd(p.credit)} added to your balance` : card.refunded !== "$0.00" ? ` · refunded ${card.refunded}` : "";
        msg = `<span class="card-line ${esc(card.phase)}"><b>${esc(card.method)} ${esc(card.amount)}</b> · ${esc(card.text)}${esc(extra)}</span>` + (p.status === "waiting" ? "" : " " + msg);
      }
      const found = info && ["waiting", "closed", "found", "failed"].includes(p.status)
        ? `<span class="found-order ${info.phase}"><strong>${esc(info.label)} · ${esc(info.status || "—")}</strong>${info.ids.length > 1 ? `<span>${esc(info.ids.join(", "))}</span>` : info.price ? `<span>${esc(info.price)}</span>` : ""}</span>` : "";
      return `<div class="strip nested status-strip">
        <ol class="steps">${PAY_STEPS.map((t, i) => `<li class="${marks[i]}">${t}</li>`).join("")}</ol>
        <div class="status-body"><div class="status-info">${found}${msg}</div><div class="status-actions">${actions}</div></div>
      </div>`;
    }

    function refresh(job) {
      if (!job) return;
      renderJobCard(job);
      if (modalJob === job) renderPosts();
    }

    function renderJobCard(job) {
      if (!catalog) return;
      const root = cardRoot(job);
      if (!root) return;
      const o = job.order, i = jobs.indexOf(job);
      syncDelivery(o);
      const s = selected(o), t = totals(o), v = o.verify;

      const tone = jobTone(job);
      root.className = "job-card" + (tone ? ` t-${tone}` : "") + (busyPay(o) ? " is-busy" : "") + (root.classList.contains("has-pop") ? " has-pop" : "");

      root.querySelector(".job-dot").classList.toggle("spin", ["checking", "paying"].includes(jobState(job)));
      root.querySelector(".job-title b").textContent = jobName(job, i);
      root.querySelector(".job-title span").textContent = jobMeta(job);
      root.querySelector(".copy-pkg-btn").hidden = jobs.length < 2 || !hasPackage(o);
      root.querySelector(".job-close").hidden = jobs.length < 2 || busyPay(o);

      const pkgValue = root.querySelector(".pkg-btn .pop-value");
      pkgValue.classList.toggle("placeholder", !s);
      pkgValue.textContent = s ? `${number(s.quantity)} views · ${usd(s.price)}` : o.custom && o.customQty ? `${number(o.customQty)} views…` : "Choose a package";
      root.querySelector(".pkg-list").innerHTML = catalog.packages.map((p) => `
        <button type="button" class="opt${!o.custom && o.pkgId === p.id ? " on" : ""}" data-id="${esc(p.id)}" role="option">
          <span class="opt-top"><b>${number(p.quantity)} <small>views</small></b><span class="opt-price">${usd(p.price)}</span></span>
          <span class="opt-tags">${p.best ? '<span class="tag best">Best value</span>' : ""}${p.save ? `<span class="tag save">${esc(p.save)}</span>` : ""}</span>
        </button>`).join("");
      root.querySelector(".opt-custom").classList.toggle("on", o.custom);
      const custom = catalog.custom, qty = Number(o.customQty), inRange = qty >= custom.min && qty <= custom.max;
      const est = o.custom && inRange && !s ? estimateCustom(qty) : null;
      root.querySelector(".custom-price").textContent = o.custom && s ? usd(s.price) : est ? `≈ ${usd(est)}` : "";
      const hint = root.querySelector(".custom-hint");
      hint.className = "hint custom-hint" + (o.customQty && !inRange ? " err" : "");
      hint.textContent = o.customQty && !inRange ? `Enter between ${number(custom.min)} and ${number(custom.max)} views.` : `${number(custom.min)} – ${number(custom.max)} views. Exact price is confirmed by leofame.com.`;

      const delBtn = root.querySelector(".del-btn");
      delBtn.disabled = !s;
      const delValue = delBtn.querySelector(".pop-value"), opt = s && s.delivery.find((d) => d.value === o.delivery);
      delValue.classList.toggle("placeholder", !opt);
      delValue.textContent = opt ? opt.label : s ? "Choose speed" : "Pick a package first";
      root.querySelector(".del-panel").innerHTML = s ? s.delivery.map((d) => `
        <button type="button" class="del-opt${d.value === o.delivery ? " on" : ""}${d.recommended ? " rec" : ""}" data-value="${esc(d.value)}" role="option">
          <b>${esc(d.label)}</b><span>${esc(d.hint || "")}</span>
        </button>`).join("") : "";

      const linkState = root.querySelector(".link-state");
      linkState.className = "link-state " + (v.status === "ok" ? "ok" : v.status === "error" ? "err" : "");
      linkState.innerHTML = v.status === "checking" ? '<span class="mini-spin"></span>'
        : v.status === "ok" ? '<svg class="ico"><use href="#i-check"/></svg>'
        : v.status === "error" ? '<svg class="ico"><use href="#i-alert"/></svg>' : "";

      const verifyLine = root.querySelector(".verify-line");
      let vcls = "", vhtml = "Choose a package, then paste the link of a TikTok video.";
      if (s && !o.link) vhtml = "Paste a TikTok video link — or several at once, one per line.";
      if (v.status === "checking") vhtml = "Checking your post with leofame.com…";
      else if (v.status === "ok") { vcls = "ok"; vhtml = `✓ Post found · @${esc(v.data.account.username)}`; }
      else if (v.status === "error") { vcls = "err"; vhtml = esc(v.error); }
      else if (o.link && !TT_LINK_RE.test(o.link.trim())) { vcls = "err"; vhtml = "That doesn't look like a TikTok link."; }
      else if (!s && o.link) vhtml = "Choose a package to check your post.";
      verifyLine.className = "verify-line " + vcls; verifyLine.innerHTML = vhtml; verifyLine.title = verifyLine.textContent;

      const payBtn = root.querySelector(".pay-btn");
      let label = "Pay", cls = "", disabled = true;
      if (o.pay.status === "creating") { label = "Opening…"; cls = "busy"; }
      else if (o.pay.status === "waiting" || o.pay.status === "blocked") { label = "Paying…"; cls = "waiting"; }
      else if (!s) label = "Select a package";
      else if (!o.link.trim()) label = "Paste your link";
      else if (v.status === "checking") { label = "Checking…"; cls = "busy"; }
      else if (v.status === "ok" && t && t.charge === 0) label = "Covered by balance";
      else if (v.status === "ok") { label = `Pay ${usd(t.charge)}`; if (agree) { cls = "ready"; disabled = false; } }
      payBtn.className = "pay-btn " + cls; payBtn.disabled = disabled;
      payBtn.querySelector(".pay-label").textContent = label;
      payBtn.title = cls === "ready" ? "Open the secure payment window" : v.status === "ok" && !agree ? "Accept the terms first" : "";

      root.querySelector(".post-strip-wrap").innerHTML = stripHtml(job);
      root.querySelector(".job-foot").innerHTML = footHtml(job);
      renderJobsStatus();
    }

    /* --- inputs (delegated: cards are rebuilt only when a post is added or removed) --- */
    function invalidate(job, delay = 150) {
      const o = job.order;
      clearTimeout(job.timers.verify);
      const want = ++o.seq;
      o.verify = { status: "idle" };
      refresh(job);
      if (selected(o) && o.delivery && TT_LINK_RE.test(o.link.trim())) job.timers.verify = setTimeout(() => queueVerify(job, want), delay);
    }

    // Verifications run one after another, so pasting many links never floods leofame.com.
    function queueVerify(job, want) { verifyChain = verifyChain.then(() => runVerify(job, want)).catch(() => {}); }

    async function runVerify(job, want) {
      const o = job.order;
      if (job.closed || o.seq !== want) return;
      const s = selected(o);
      if (!s || !o.delivery || !TT_LINK_RE.test(o.link.trim())) return;
      o.verify = { status: "checking" }; refresh(job);
      try {
        const data = await api("/api/order/verify", orderBody(o, s));
        if (o.seq === want) { o.verify = { status: "ok", data }; adoptPosts(job, data); rememberLink(o.link.trim(), data.account.username); }
      } catch (err) {
        if (o.seq === want) o.verify = { status: "error", error: err.message };
      }
      if (o.seq === want) refresh(job);
    }

    const orderBody = (o, s) => ({ item_id: s.id, custom_quantity: s.custom ? s.quantity : null, delivery: o.delivery, link: o.link.trim(), email: o.email.trim() });
    const cleanLink = (l) => l.replace(/[.,;)\]]+$/, "");
    const extractLinks = (text) => [...new Set((String(text).match(LINK_FINDER) || []).map(cleanLink))];

    function setLink(job, link) {
      job.order.link = link;
      const root = cardRoot(job);
      if (root) root.querySelector(".link-field").value = link;
      invalidate(job, 100);
    }
    // Several links pasted at once become one post each.
    function applyLinks(job, links) {
      if (links.length < 2) return setLink(job, links[0] || "");
      setLink(job, links[0]);
      const added = [];
      for (const link of links.slice(1)) {
        if (jobs.some((j) => j.order.link.trim() === link)) continue;
        const nj = addJob(link);
        if (!nj) break;
        added.push(nj);
      }
      renderJobsStack();
      added.forEach((nj, i) => invalidate(nj, 100 + i * 30));
      if (added.length) toast(`Added ${added.length} more order${added.length === 1 ? "" : "s"} from your paste`);
    }
    async function pasteLink(job) {
      try {
        const text = (await navigator.clipboard.readText()).trim();
        const links = extractLinks(text);
        if (links.length > 1) applyLinks(job, links); else setLink(job, links[0] || text);
      } catch { toast("Clipboard access was blocked — paste with Ctrl+V instead.", "err"); }
    }

    /* --- select posts (a wide popup with every post on the account) --- */
    function maxPosts(o, ps) {
      const s = selected(o);
      return s ? Math.max(1, Math.floor(s.quantity / ps.min)) : 1;
    }
    const perPost = (o, ps) => (ps.selected.length && selected(o) ? Math.round(selected(o).quantity / ps.selected.length) : 0);

    // Called after every successful verification. Keeps the user's choices while the account stays the same.
    function adoptPosts(job, data) {
      const o = job.order, ps = job.posts;
      const same = ps.user === data.account.username, link = o.link.trim(), linkChanged = ps.link !== link;
      if (!same) Object.assign(ps, { user: data.account.username, items: [], cursor: null, pages: 1, selected: [] });
      const known = new Set(ps.items.map((p) => p.key));
      ps.items = ps.items.concat(data.posts.filter((p) => !known.has(p.key)));
      if (!same || ps.pages <= 1) ps.cursor = data.cursor;   // keep the deeper cursor if more pages were loaded
      const keys = new Set(ps.items.map((p) => p.key));
      let chosen = (same && !linkChanged ? ps.selected : []).filter((k) => keys.has(k));
      if (!chosen.length) chosen = [data.selected_key];
      Object.assign(ps, { pasted: data.selected_key, link, min: data.min_per_post, note: "", noteErr: false });
      ps.selected = chosen.slice(0, maxPosts(o, ps));
    }

    function sortedPosts() {
      const list = posts.items.slice();
      const by = { views: (a, b) => (b.views || 0) - (a.views || 0), likes: (a, b) => (b.likes || 0) - (a.likes || 0),
        new: (a, b) => String(b.created || "9").localeCompare(String(a.created || "9")) };
      return posts.sort === "site" ? list : list.sort(by[posts.sort]);
    }

    function postDate(created) {
      const d = created ? new Date(created.replace(" ", "T")) : null;
      return d && !isNaN(d) ? d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
    }

    function postsModalHtml() {
      return `
        <div class="ws-head">
          <div class="pv-user" id="posts-user"></div>
          <span class="ws-count" id="posts-count"></span>
          <div class="ws-tools">
            <button class="text-btn" data-posts="all" type="button">Select all loaded</button>
            <button class="text-btn" data-posts="reset" type="button">Only my link</button>
            <select id="posts-sort" aria-label="Sort posts">
              <option value="site">As listed</option><option value="views">Most views</option>
              <option value="likes">Most likes</option><option value="new">Newest</option>
            </select>
            <button class="size-btn" id="posts-size" type="button" title="Card size" aria-label="Change card size"><svg class="ico"><use href="#i-grid"/></svg></button>
          </div>
        </div>
        <div class="posts-grid" id="posts-grid"></div>
        <div class="posts-foot">
          <button class="btn btn-ghost" id="posts-more" type="button">Load more posts</button>
          <span class="posts-note" id="posts-note"></span>
        </div>
        <div class="modal-actions"><button class="btn btn-primary" data-close type="button">Done</button></div>`;
    }

    function openPostsModal(job) {
      if (job.order.verify.status !== "ok") return;
      modalJob = job; order = job.order; posts = job.posts;
      openModal(`<h3>Select posts</h3>${postsModalHtml()}`, "wide");
      $("#posts-sort").value = posts.sort;
      renderPosts();
    }

    function renderPosts() {
      const d = order.verify.data, max = maxPosts(order, posts), n = posts.selected.length, s = selected(order);
      $("#posts-user").innerHTML = `${d.account.image ? `<img class="pv-avatar" referrerpolicy="no-referrer" alt="" src="${esc(d.account.image)}" onerror="this.remove()">` : ""}
        <strong>@${esc(d.account.username)}</strong><span class="pill">Verified</span>`;
      const countEl = $("#posts-count");
      countEl.innerHTML = `<b>${n}</b> of ${max} post${max === 1 ? "" : "s"} selected${n && s ? ` · ≈ <b>${number(perPost(order, posts))}</b> views each` : ""}`
        + (max === 1 ? ' <span class="warn">· one post only — pick a bigger package for more</span>' : "");
      countEl.title = `Views are split evenly between the selected posts, at least ${posts.min} per post. ${number(s.quantity)} views can cover up to ${max} post${max === 1 ? "" : "s"}.`;

      const full = n >= max, grid = $("#posts-grid");
      grid.classList.toggle("small", posts.small);
      grid.innerHTML = sortedPosts().map((p) => {
        const idx = posts.selected.indexOf(p.key), on = idx >= 0, date = postDate(p.created);
        return `<button type="button" class="post-card${on ? " on" : ""}${!on && full ? " locked" : ""}" data-key="${esc(p.key)}" aria-pressed="${on}" title="${esc(compact(p.views))} views · ${esc(compact(p.likes))} likes${date ? " · " + esc(date) : ""}">
          <span class="post-thumb">${p.thumbnail ? `<img referrerpolicy="no-referrer" loading="lazy" alt="" src="${esc(p.thumbnail)}" onerror="this.remove()">` : ""}</span>
          <span class="post-tick">${on ? idx + 1 : ""}</span>
          ${p.key === posts.pasted ? '<span class="post-tag mine">Your link</span>' : p.pinned ? '<span class="post-tag">Pinned</span>' : ""}
          <span class="post-meta"><b>${compact(p.views)}</b> views<em>${compact(p.likes)} likes${date ? " · " + esc(date) : ""}</em></span>
        </button>`;
      }).join("");

      const more = $("#posts-more");
      more.hidden = !posts.cursor;
      more.disabled = posts.loading;
      more.textContent = posts.loading ? "Loading…" : "Load more posts";
      const note = $("#posts-note");
      note.className = "posts-note" + (posts.noteErr ? " err" : "");
      note.textContent = posts.note || `${posts.items.length} post${posts.items.length === 1 ? "" : "s"} loaded${posts.cursor ? "" : " — that's all of them"}`;
    }

    function flashNote(text, isErr = false) { posts.note = text; posts.noteErr = isErr; renderPosts(); }

    function togglePost(key) {
      const max = maxPosts(order, posts);
      const at = posts.selected.indexOf(key);
      if (at >= 0) {
        if (posts.selected.length === 1) return flashNote("Keep at least one post selected.", true);
        posts.selected.splice(at, 1);
      } else {
        if (posts.selected.length >= max) return flashNote(`${number(selected(order).quantity)} views can cover at most ${max} post${max === 1 ? "" : "s"} (${posts.min} views each). Deselect one or pick a bigger package.`, true);
        posts.selected.push(key);
      }
      posts.note = ""; refresh(modalJob);
    }

    async function loadMorePosts() {
      const job = modalJob, ps = job.posts;
      if (!ps.cursor || ps.loading) return;
      ps.loading = true; refresh(job);
      try {
        const r = await api(`/api/order/posts?cursor=${encodeURIComponent(ps.cursor)}&account=${encodeURIComponent(ps.user)}`);
        const known = new Set(ps.items.map((p) => p.key));
        ps.items = ps.items.concat(r.posts.filter((p) => !known.has(p.key)));
        ps.cursor = r.cursor; ps.pages += 1; ps.note = ""; ps.noteErr = false;
      } catch (err) { ps.note = err.message; ps.noteErr = true; }
      ps.loading = false; refresh(job);
    }

    $("#modal-card").addEventListener("click", (e) => {
      if (!modalJob) return;
      const post = e.target.closest("#posts-grid .post-card");
      if (post) { togglePost(post.dataset.key); return; }
      const b = e.target.closest("[data-posts]");
      if (b) {
        if (b.dataset.posts === "reset") { posts.selected = [posts.pasted]; posts.note = ""; refresh(modalJob); return; }
        const max = maxPosts(order, posts), keep = posts.selected.slice();
        for (const p of sortedPosts()) { if (keep.length >= max) break; if (!keep.includes(p.key)) keep.push(p.key); }
        posts.selected = keep;
        refresh(modalJob);
        flashNote(keep.length >= max && posts.items.length > max ? `Selected ${keep.length} — the most ${number(selected(order).quantity)} views can cover.` : `Selected ${keep.length} post${keep.length === 1 ? "" : "s"}.`);
        return;
      }
      if (e.target.closest("#posts-size")) { posts.small = !posts.small; store.set("postSize", posts.small ? "small" : "large"); renderPosts(); return; }
      if (e.target.closest("#posts-more")) loadMorePosts();
    });
    $("#modal-card").addEventListener("change", (e) => {
      if (!modalJob) return;
      if (e.target.id === "posts-sort") { posts.sort = e.target.value; renderPosts(); }
    });

    /* --- delegated events for the card stack (cards are built once, then only their contents change) --- */
    const jobFromEl = (el) => { const root = el.closest("[data-job-id]"); return root && jobs.find((j) => j.id === Number(root.dataset.jobId)); };

    $("#jobs-stack").addEventListener("click", (e) => {
      const pop = e.target.closest("[data-pop]");
      if (pop) { const job = jobFromEl(pop); if (job) togglePop(job, pop.dataset.pop, pop); return; }

      if (e.target.closest(".opt-custom")) {
        const job = jobFromEl(e.target);
        if (job && !job.order.custom) { clearTimeout(job.timers.quote); job.order.custom = true; job.order.quote = null; invalidate(job); }
        return;
      }
      const opt = e.target.closest(".pkg-list .opt");
      if (opt) {
        const job = jobFromEl(opt);
        if (job) {
          clearTimeout(job.timers.quote);                    // a quote fetch left over from "custom" must not land after switching away from it
          job.order.custom = false; job.order.pkgId = opt.dataset.id;
          closePops(); shareDefaults(job); invalidate(job);
          if (!job.order.link) cardRoot(job).querySelector(".link-field").focus();
        }
        return;
      }
      const delOpt = e.target.closest(".del-panel .del-opt");
      if (delOpt) {
        const job = jobFromEl(delOpt);
        if (job) { job.order.delivery = delOpt.dataset.value; closePops(); invalidate(job); }
        return;
      }
      if (e.target.closest(".paste-btn")) { const job = jobFromEl(e.target); if (job) pasteLink(job); return; }
      if (e.target.closest(".strip-manage, .strip-track")) {
        if (lastDragWasMove) { lastDragWasMove = false; return; }   // the tail end of a drag-scroll, not a click
        const job = jobFromEl(e.target); if (job) openPostsModal(job);
        return;
      }
      if (e.target.closest(".copy-pkg-btn")) { const job = jobFromEl(e.target); if (job) copyToAll(job); return; }
      if (e.target.closest(".job-close")) { const job = jobFromEl(e.target); if (job) closeJob(job); return; }
      if (e.target.closest(".pay-btn")) { const job = jobFromEl(e.target); if (job) startPayment(job); return; }

      const act = e.target.closest("[data-act]");
      if (act) {
        const job = jobFromEl(act);
        if (!job) return;
        const p = job.order.pay;
        if (act.dataset.act === "retry") { job.order.pay = { status: "idle" }; renderJobCard(job); }
        if (act.dataset.act === "open") openPayWindow(job);
        if (act.dataset.act === "recheck") { p.status = "waiting"; renderJobCard(job); watchPayment(job); }
        if (act.dataset.act === "cancel") cancelPayment(job);
        if (act.dataset.act === "close-window") {
          const win = p.popup;
          try { if (stillOpen(win)) win.close(); } catch { /* ignore */ }
          setTimeout(() => { if (!stillOpen(win)) { p.windowLeft = false; renderJobCard(job); } else toast("Your browser keeps that window; please close it yourself.", "err"); }, 400);
        }
        if (act.dataset.act === "reset") resetOrder(job);
        if (act.dataset.act === "orders") { resetOrder(job); go("orders"); }
      }
    });

    $("#jobs-stack").addEventListener("input", (e) => {
      const job = jobFromEl(e.target);
      if (!job) return;
      if (e.target.classList.contains("link-field")) { job.order.link = e.target.value; invalidate(job, 700); return; }
      if (e.target.classList.contains("email-field")) { job.order.email = e.target.value; invalidate(job, 900); return; }
      if (e.target.classList.contains("custom-qty")) {
        const o = job.order;
        o.custom = true; o.customQty = e.target.value; o.quote = null;
        clearTimeout(job.timers.quote);
        invalidate(job);
        const qty = Number(o.customQty);
        if (!(qty >= catalog.custom.min && qty <= catalog.custom.max)) return;
        const id = ++o.quoteSeq;
        job.timers.quote = setTimeout(async () => {
          try {
            const quote = await api(`/api/order/quote?qty=${qty}`);
            if (id !== o.quoteSeq) return;
            o.quote = quote; invalidate(job);
          } catch (err) {
            if (id === o.quoteSeq) { const h = cardRoot(job)?.querySelector(".custom-hint"); if (h) { h.className = "hint err"; h.textContent = err.message; } }
          }
        }, 500);
      }
    });
    $("#jobs-stack").addEventListener("change", (e) => {
      const job = jobFromEl(e.target);
      if (job && e.target.classList.contains("link-field") && e.target.value !== job.order.link) { job.order.link = e.target.value; invalidate(job, 100); }
    });
    $("#jobs-stack").addEventListener("keydown", (e) => {
      const job = jobFromEl(e.target);
      if (!job) return;
      if (e.target.classList.contains("link-field") && e.key === "Enter") {
        const btn = cardRoot(job).querySelector(".pay-btn");
        if (!btn.disabled) startPayment(job);
      }
      if (e.target.classList.contains("custom-qty") && e.key === "Enter" && selected(job.order)) { closePops(); cardRoot(job).querySelector(".link-field").focus(); }
    });
    $("#jobs-stack").addEventListener("paste", (e) => {
      const job = jobFromEl(e.target);
      if (!job || !e.target.classList.contains("link-field")) return;
      const links = extractLinks(e.clipboardData ? e.clipboardData.getData("text") : "");
      if (links.length > 1) { e.preventDefault(); return applyLinks(job, links); }
      setTimeout(() => { job.order.link = e.target.value; invalidate(job, 100); }, 0);
    });

    // Dragging the strip scrolls it; a plain click (no drag) opens the "Select posts" popup instead.
    $("#jobs-stack").addEventListener("pointerdown", (e) => {
      const track = e.target.closest(".strip-track");
      if (!track || e.button !== 0 || track.scrollWidth <= track.clientWidth) return;
      dragScroll = { track, startX: e.clientX, startLeft: track.scrollLeft };
      track.setPointerCapture(e.pointerId);
    });
    $("#jobs-stack").addEventListener("pointermove", (e) => {
      if (!dragScroll) return;
      const dx = e.clientX - dragScroll.startX;
      if (Math.abs(dx) > 3) lastDragWasMove = true;
      dragScroll.track.scrollLeft = dragScroll.startLeft - dx;
    });
    const endDragScroll = () => { dragScroll = null; };
    $("#jobs-stack").addEventListener("pointerup", endDragScroll);
    $("#jobs-stack").addEventListener("pointercancel", endDragScroll);

    $("#agree").addEventListener("change", (e) => { agree = e.target.checked; store.set("agree", agree); jobs.forEach(renderJobCard); });

    /* --- payment (per post; several can be open at once) --- */
    function safeGatewayUrl(url) {
      const u = new URL(url);
      if (u.protocol !== "https:" || !u.hostname.endsWith(".gateway.mastercard.com")) throw new Error("Unexpected payment address.");
      return u.href;
    }

    function popupMessage(win, text) {
      try {
        win.document.write(`<!doctype html><title>Secure payment</title><body style="margin:0;height:100vh;display:grid;place-items:center;background:#0b1020;color:#e8ecf7;font:16px system-ui,sans-serif"><div style="text-align:center"><div style="width:34px;height:34px;margin:0 auto 16px;border:3px solid #6c7bff;border-top-color:transparent;border-radius:50%;animation:s .8s linear infinite"></div>${text}</div><style>@keyframes s{to{transform:rotate(360deg)}}</style></body>`);
        win.document.close();
      } catch { /* the window may already be gone */ }
    }
    const payWindowName = (job) => `viewdesk-pay-${job.id}`;

    async function startPayment(job) {
      const o = job.order, ps = job.posts, s = selected(o);
      if (!s || o.verify.status !== "ok" || !agree || o.pay.status !== "idle") return;
      const win = window.open("about:blank", payWindowName(job), POPUP_FEATURES);   // opened now, while the click still counts
      if (win) popupMessage(win, "Preparing your secure payment…");
      o.pay = { status: "creating", popup: win, windowLeft: false }; refresh(job);
      try {
        const r = await api("/api/order/pay", { ...orderBody(o, s), agree: true, posts: ps.selected.slice() });
        const url = safeGatewayUrl(r.payment_url);
        Object.assign(o.pay, { url, baseline: r.baseline, orderIds: r.order_ids, trx: r.trx || "", charge: r.charge, credit: r.credit, total: r.total });
        if (win && !win.closed) { win.location.href = url; o.pay.status = "waiting"; watchPayment(job); }
        else o.pay.status = "blocked";
      } catch (err) {
        try { if (win) win.close(); } catch { /* ignore */ }
        o.pay = { status: "error", message: err.message };
      }
      refresh(job);
    }

    function openPayWindow(job) {
      const o = job.order, win = window.open(o.pay.url, payWindowName(job), POPUP_FEATURES);
      if (!win) return toast("The payment window was blocked by the browser.", "err");
      o.pay.popup = win; o.pay.status = "waiting"; refresh(job); watchPayment(job);
    }

    // leofame.com creates the order(s) when payment starts and cancels them if the payment fails, so their
    // status tells us what happened: Canceled = failed, Processing/Completed = paid, Awaiting = still open.
    async function watchPayment(job) {
      const o = job.order, id = ++o.watch, started = Date.now();
      let quiet = 0, first = true;
      while (id === o.watch) {
        const closed = !o.pay.popup || o.pay.popup.closed;
        const age = Date.now() - started;
        if (!first) await sleep(age > 5 * 60 * 1000 ? 20000 : age > 2 * 60 * 1000 ? 10000 : closed ? 4000 : 6000);
        first = false;
        if (id !== o.watch) return;
        try {
          const r = await api("/api/order/payment-check", { baseline: o.pay.baseline, order_ids: o.pay.orderIds, trx: o.pay.trx || "" });
          if (r.account) { state.account = r.account; renderTopbar(); }
          o.pay.payment = r.payment || o.pay.payment;
          const card = paymentInfo(o.pay.payment);
          if (r.orders.length) {
            o.pay.orders = r.orders; o.pay.orderIds = r.orders.map((x) => x.id);
            const info = orderInfo(r.orders);
            if (info.phase === "paid") return paymentDone(job, "found", `${jobLabel(job)}${info.label.toLowerCase()} confirmed`);
            if (info.phase === "failed") return paymentDone(job, "failed", `${jobLabel(job)}${info.label.toLowerCase()} cancelled`);
            refresh(job);
          } else if (card) refresh(job);
          if (card && card.phase === "failed") return paymentDone(job, "failed", `The card payment was ${card.text.toLowerCase()}`);
        } catch { /* try again on the next tick */ }
        quiet = closed ? quiet + 1 : 0;
        // A payment can still land after the window is gone (3-D Secure, slow banks), so keep looking for a while.
        if (quiet >= 30 || Date.now() - started > 25 * 60 * 1000) { o.pay.status = "closed"; return refresh(job); }
      }
    }

    // Cancelling a payment also cancels the unpaid order(s) it created, so nothing stays "Awaiting" on the site.
    function cancelPayment(job) {
      const o = job.order, p = o.pay;
      const open = (p.orders || []).filter((x) => x.actions.some((a) => a.kind === "cancel"));
      const stop = () => { o.watch++; try { if (p.popup) p.popup.close(); } catch { /* ignore */ } o.pay = { status: "idle" }; refresh(job); };
      if (!open.length) return stop();
      const many = open.length > 1;
      confirmAction({
        title: "Cancel this payment?", confirmLabel: many ? "Cancel orders" : "Cancel order", cancelLabel: "Keep waiting", danger: true,
        html: `<p class="muted">The unpaid ${many ? "orders" : "order"} <b>${esc(open.map((x) => "#" + x.id).join(", "))}</b> will be cancelled on leofame.com, so nothing is left waiting for payment.</p>`,
        run: async () => {
          const res = await api("/api/orders/cancel", { order_ids: open.map((x) => x.id) });
          const failed = res.results.filter((r) => !r.ok);
          if (failed.length) { const err = new Error(failed[0].error); err.details = failed[0].details; throw err; }
          stop(); toast(`Cancelled ${open.length} unpaid order${many ? "s" : ""}`);
        },
      });
    }

    const stillOpen = (win) => { try { return !!win && !win.closed; } catch { return false; } };

    function closePayWindow(job, win, delay = 2500) {
      if (!stillOpen(win)) return;
      const tryClose = () => { try { if (stillOpen(win)) win.close(); } catch { /* the browser may say no */ } };
      setTimeout(tryClose, delay);
      setTimeout(() => {                                   // it is still there: ask the person to close it
        tryClose();
        if (stillOpen(win) && job.order.pay.popup === win) { job.order.pay.windowLeft = true; refresh(job); }
      }, delay + 1500);
    }

    function paymentDone(job, status, message) {
      const win = job.order.pay.popup;
      job.order.pay.status = status;
      closePayWindow(job, win);
      toast(message.charAt(0).toUpperCase() + message.slice(1), status === "failed" ? "err" : "ok");
      refresh(job);
    }

    function resetOrder(job) {
      const o = job.order;
      o.watch++; o.pay = { status: "idle" }; o.link = ""; o.verify = { status: "idle" };
      const root = cardRoot(job);
      if (root) root.querySelector(".link-field").value = "";
      refresh(job);
    }


    /* ---------- Keep the local server alive while this window is open ---------- */
    const ping = () => fetch("/api/ping", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
    ping();
    setInterval(ping, 5000);
    window.addEventListener("pagehide", () => navigator.sendBeacon("/api/bye", new Blob(["{}"], { type: "application/json" })));

    boot();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Viewdesk"

    def log_message(self, fmt, *args):
        pass

    @property
    def automation(self):
        return self.server.automation

    # -- helpers -------------------------------------------------------------

    def _origin_ok(self):
        """Only our own page may talk to us (blocks other sites and DNS rebinding)."""
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc in allowed

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            raise ValueError("Invalid JSON body.")
        return data if isinstance(data, dict) else {}

    def _guarded(self, handler):
        """Run a route, turning automation errors into JSON error responses."""
        if not self._origin_ok():
            return self._send(403, {"error": "Forbidden"})
        try:
            handler()
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except LeoFameError as exc:
            self._send(502, {"error": str(exc), "details": exc.details})
        except ConnectionError:
            pass                                        # the window went away (or dropped an outdated request) while the answer was being sent
        except Exception as exc:                        # a bug or a page we do not know: say so instead of dropping the connection
            trace = traceback.format_exc()
            self.automation._log("error", route=self.path, error=f"{type(exc).__name__}: {exc}", trace=trace[-1500:])
            try:
                self._send(500, {"error": f"Unexpected error ({type(exc).__name__}: {exc})", "details": trace[-1200:]})
            except OSError:
                pass

    # -- routing -------------------------------------------------------------

    def do_GET(self):
        self._guarded(self._get)

    def do_POST(self):
        self._guarded(lambda: self._post(urlparse(self.path).path, self._json_body()))

    def _get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, self.automation.state())
        query = parse_qs(parsed.query)
        arg = lambda name, default="": (query.get(name) or [default])[0]
        if path == "/api/orders":
            return self._send(200, self.automation.orders(
                status=arg("status", "all"), query=arg("q"), search_type=arg("type", "1"), url=arg("url"), with_payments=True))
        if path == "/api/catalog":
            return self._send(200, self.automation.catalog())
        if path == "/api/orders/payment":
            return self._send(200, self.automation.payment_details(arg("order_id")))
        if path == "/api/order/quote":
            return self._send(200, self.automation.quote(arg("qty")))
        if path == "/api/order/posts":
            return self._send(200, self.automation.more_posts(arg("cursor"), arg("account")))
        self._send(404, {"error": "Not found"})

    def _post(self, path, body):
        auto, server = self.automation, self.server
        if path == "/api/ping":
            server.last_ping, server.bye_at = time.time(), 0.0
            return self._send(200, {"ok": True})
        if path == "/api/bye":
            server.bye_at = time.time()
            return self._send(200, {"ok": True})
        if path == "/api/retry":
            auto.start_bootstrap()
            return self._send(200, {"ok": True})
        if path == "/api/login":
            auto.sign_in(body.get("email"), body.get("password"))
            return self._send(200, auto.state())
        if path == "/api/refresh":
            auto.refresh_account()
            return self._send(200, auto.state())
        if path in ("/api/order/verify", "/api/order/pay"):
            args = (body.get("item_id"), body.get("link"), body.get("email"), body.get("delivery"), body.get("custom_quantity"))
            if path == "/api/order/verify":
                return self._send(200, auto.verify_order(*args))
            return self._send(200, auto.pay_order(*args, agree=body.get("agree") is True, posts=body.get("posts")))
        if path == "/api/order/payment-check":
            return self._send(200, auto.payment_check(body.get("baseline"), body.get("order_ids"), body.get("order_id"), body.get("trx", "")))
        if path == "/api/orders/cancel":
            return self._send(200, auto.cancel_orders(body.get("order_ids")))
        if path == "/api/orders/action":
            return self._send(200, auto.order_action(body.get("order_id"), body.get("kind"), body.get("reason")))
        self._send(404, {"error": "Not found"})


def _find_browser():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return next((c for c in candidates if Path(c).exists()), None)


def _open_window(url):
    """Open the UI as a chrome-less app window (Edge/Chrome --app), else the default browser."""
    browser = _find_browser()
    if not browser:
        webbrowser.open(url)
        return
    subprocess.Popen([
        browser, f"--app={url}", "--window-size=1240,820",
        f"--user-data-dir={DATA_DIR / 'window-profile'}", "--no-first-run", "--no-default-browser-check",
    ])


def _watchdog(server):
    """Stop serving once the window is gone (never in the middle of a request)."""
    while True:
        time.sleep(1)
        now = time.time()
        gone = (
            (server.bye_at and now - server.bye_at > BYE_GRACE_SECONDS)
            or (server.last_ping and now - server.last_ping > LOST_PING_EXIT_SECONDS)
            or (not server.last_ping and now - server.started > NO_PING_EXIT_SECONDS)
        )
        if gone and not server.automation.active_job:
            server.shutdown()
            return


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        """The window closing (or a dropped keep-alive connection) can abort a request before it is even
        parsed, outside do_GET/do_POST's own guard. That is not a bug, so do not print a scary traceback for it.
        """
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def serve(automation, open_window=True):
    server = _Server(("127.0.0.1", 0), Handler)
    server.automation = automation
    server.started, server.last_ping, server.bye_at = time.time(), 0.0, 0.0
    url = f"http://127.0.0.1:{server.server_port}/"
    threading.Thread(target=_watchdog, args=(server,), daemon=True).start()
    if open_window:
        _open_window(url)
    print(f"Viewdesk running at {url}  (close the window to quit)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
