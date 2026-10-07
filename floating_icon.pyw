"""
floating_icon.pyw  –  SAP Warehouse Chat — fully native, no browser
  • Starts hidden in background (auto-launched via Windows Startup folder)
  • Ctrl+Alt+W        → show / hide the SAP circle from anywhere
  • Left-click circle → open compact chat popup above the button
  • Ctrl+Alt+J        → open popup + switch agent to D4H-200
  • ⊟ button in popup → hide entire widget (same as Ctrl+Alt+W)
  • 🌐 button in popup → open warehouse-agent-ui in browser
  • ✕ button in popup → close popup only (circle stays)
  • Right-click circle → Quit (fully exits process)
  • Drag circle       → reposition anywhere on screen
  • Enter sends, Shift+Enter inserts newline
"""

# ── DPI awareness must be set BEFORE tkinter initialises ─────────────────────
import ctypes, ctypes.wintypes as wt
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import threading
import tkinter as tk

# ── Win32 helpers ─────────────────────────────────────────────────────────────
def _screen_w():
    return ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN

def _screen_h():
    return ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN

# Win32 hotkey constants
MOD_ALT      = 0x0001
MOD_CTRL     = 0x0002
MOD_SHIFT    = 0x0004
MOD_NOREPEAT = 0x4000
VK_J         = 0x4A
VK_W         = 0x57
WM_HOTKEY    = 0x0312
HOTKEY_ID       = 1   # Ctrl+Alt+W — toggle popup
HOTKEY_ID_D4H   = 2   # Ctrl+Alt+J — switch to D4H-200

# Trigger button
SIZE        = 56
TRANSPARENT = '#010203'

# Chat popup dimensions
PANEL_W = 380
PANEL_H = 520

# Colours
C_BRAND   = '#0070F2'
C_BRAND2  = '#0057c2'
C_WHITE   = '#ffffff'
C_PANEL   = '#ffffff'
C_BORDER  = '#e0e0e0'
C_HINT    = '#999999'
C_USER_BG = '#0070F2'
C_USER_FG = '#ffffff'
C_AGNT_BG = '#eef2ff'
C_AGNT_FG = '#1a1a1a'
C_ERR_BG  = '#fff0f0'
C_ERR_FG  = '#cc0000'
MARGIN    = 16   # gap between popup and screen/button edge


# =============================================================================
# AGENT INTEGRATION — replace send_to_agent() with your real A2A call
# =============================================================================
AGENT_URL = 'https://warehouse-agent.cfapps.us10-001.hana.ondemand.com/'
AGENT_UI_URL = 'https://warehouse-agent-ui.cfapps.us10-001.hana.ondemand.com/'

# Set to a BTP destination name to silently switch on startup, e.g. 'D4H-200'
# Leave blank ('') to use the agent's default destination
STARTUP_DESTINATION = 'D4H-200'

# Token cache — refreshed automatically via `cf oauth-token` when expired
_token_cache  = {'token': None}
# Conversation context — persists for the lifetime of the widget process
_context_id   = {'value': None}

def _get_token():
    import subprocess
    cf = r'C:\Users\I584630\bin\cf.exe'
    result = subprocess.run(
        [cf, 'oauth-token'],
        capture_output=True, text=True
    )
    raw = result.stdout.strip()
    if raw.lower().startswith('bearer '):
        raw = raw[7:]
    _token_cache['token'] = raw
    return raw

def _parts_text(parts):
    """Join the text of A2A message/artifact parts (kind or type == 'text')."""
    return '\n'.join(
        p.get('text', '') for p in (parts or [])
        if p.get('kind') == 'text' or p.get('type') == 'text'
    ).strip()


def stream_to_agent(message, on_progress, on_final):
    """Call the agent via A2A `message/stream` (SSE) and stream step progress.

    on_progress(text)  — called for each intermediate `working` status update
    on_final(text)     — called once with the final answer (artifact / input-required)

    Both callbacks run on THIS (background) thread; the caller marshals them to
    the Tk UI thread via root.after().
    """
    import urllib.request, urllib.error, json, uuid

    token = _token_cache['token'] or _get_token()

    msg = {
        'messageId': str(uuid.uuid4()),
        'role': 'user',
        'parts': [{'type': 'text', 'text': message}]
    }
    if _context_id['value']:
        msg['contextId'] = _context_id['value']

    body = json.dumps({
        'jsonrpc': '2.0', 'id': '1',
        'method': 'message/stream',
        'params': {'message': msg}
    }).encode()

    def _open(tok):
        req = urllib.request.Request(
            AGENT_URL, data=body,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
                'Authorization': 'Bearer ' + tok
            }
        )
        return urllib.request.urlopen(req, timeout=120)

    try:
        resp = _open(token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            resp = _open(_get_token())
        else:
            raise

    final_text = None
    data_buf = []

    def _dispatch(payload):
        nonlocal final_text
        try:
            evt = json.loads(payload)
        except Exception:
            return
        res = evt.get('result') or {}
        cid = res.get('contextId')
        if cid and not _context_id['value']:
            _context_id['value'] = cid
        kind = res.get('kind')
        if kind == 'status-update':
            status = res.get('status') or {}
            txt = _parts_text((status.get('message') or {}).get('parts', []))
            if status.get('state') == 'input-required' and txt:
                final_text = txt          # question back to the user = final
            elif txt:
                on_progress(txt)          # 🔧 step progress
        elif kind == 'artifact-update':
            txt = _parts_text((res.get('artifact') or {}).get('parts', []))
            if txt:
                final_text = txt          # the actual answer

    try:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            if line.startswith('data:'):
                data_buf.append(line[5:].lstrip())
            elif line == '':
                if data_buf:
                    _dispatch('\n'.join(data_buf))
                    data_buf = []
        if data_buf:                      # flush a trailing event with no blank line
            _dispatch('\n'.join(data_buf))
    finally:
        resp.close()

    on_final(final_text or '(no response)')



# =============================================================================
# CHAT POPUP
# =============================================================================
class ChatPopup:

    def __init__(self, root, on_hide=None):
        self.root  = root
        self._open = False
        self._busy = False
        self._on_hide = on_hide
        self._dot_after = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.geometry(f'{PANEL_W}x{PANEL_H}+9999+9999')
        self.win.configure(bg=C_PANEL)
        self.win.withdraw()

        self._build()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build(self):
        # Drop-shadow effect via outer frame
        outer = tk.Frame(self.win, bg='#b0b0b0', bd=1)
        outer.pack(fill='both', expand=True, padx=1, pady=1)

        # ── Header — drag here to move the window ──
        hdr = tk.Frame(outer, bg=C_BRAND, height=48)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)

        tk.Label(hdr, text='SAP', bg=C_BRAND, fg=C_WHITE,
                 font=('Arial', 12, 'bold')).pack(side='left', padx=(14, 4))
        tk.Label(hdr, text='Warehouse Assistant', bg=C_BRAND, fg=C_WHITE,
                 font=('Arial', 10)).pack(side='left')
        tk.Button(hdr, text='✕', bg=C_BRAND, fg=C_WHITE,
                  activebackground=C_BRAND2, activeforeground=C_WHITE,
                  font=('Arial', 12), relief='flat', bd=0, cursor='hand2',
                  command=self.close).pack(side='right', padx=10)
        if self._on_hide:
            tk.Button(hdr, text='⊟', bg=C_BRAND, fg=C_WHITE,
                      activebackground=C_BRAND2, activeforeground=C_WHITE,
                      font=('Arial', 12), relief='flat', bd=0, cursor='hand2',
                      command=self._on_hide).pack(side='right', padx=2)
        tk.Button(hdr, text='🌐', bg=C_BRAND, fg=C_WHITE,
                  activebackground=C_BRAND2, activeforeground=C_WHITE,
                  font=('Arial', 11), relief='flat', bd=0, cursor='hand2',
                  command=lambda: __import__('webbrowser').open(AGENT_UI_URL)
                  ).pack(side='right', padx=2)

        # Bind drag-to-move on every widget in the header
        for w in (hdr,) + tuple(hdr.winfo_children()):
            w.bind('<ButtonPress-1>',   self._hdr_press)
            w.bind('<B1-Motion>',       self._hdr_drag)

        # ── Input row — packed BOTTOM first ──
        tk.Frame(outer, bg=C_BORDER, height=1).pack(side='bottom', fill='x')

        bot = tk.Frame(outer, bg=C_PANEL)
        bot.pack(side='bottom', fill='x')

        self.inp = tk.Text(bot, height=3, wrap='word', relief='flat', bd=0,
                           bg='#f5f5f5', fg='#222', insertbackground='#222',
                           font=('Arial', 10), padx=10, pady=8)
        self.inp.pack(side='left', fill='x', expand=True, padx=(8, 0), pady=8)
        self.inp.bind('<Return>',       self._on_enter)
        self.inp.bind('<Shift-Return>', lambda e: None)

        self._btn = tk.Button(bot, text='Send', font=('Arial', 9, 'bold'),
                              bg=C_BRAND, fg=C_WHITE, relief='flat', bd=0,
                              activebackground=C_BRAND2, activeforeground=C_WHITE,
                              cursor='hand2', width=5, command=self._submit)
        self._btn.pack(side='right', padx=8, pady=8)

        # ── Resize grip — bottom-right corner ──
        grip = tk.Label(outer, text='⊿', bg=C_PANEL, fg='#aaa',
                        font=('Arial', 11), cursor='size_nw_se')
        grip.pack(side='bottom', anchor='e', padx=2, pady=0)
        grip.bind('<ButtonPress-1>',   self._grip_press)
        grip.bind('<B1-Motion>',       self._grip_drag)

        self.win.bind('<Escape>', lambda _: self.close())

        # ── Message area — fills remaining space ──
        mid = tk.Frame(outer, bg=C_PANEL)
        mid.pack(side='top', fill='both', expand=True)

        sb = tk.Scrollbar(mid, width=10)
        sb.pack(side='right', fill='y')

        self.txt = tk.Text(
            mid, wrap='word', state='disabled',
            bg=C_PANEL, relief='flat', bd=0,
            yscrollcommand=sb.set,
            font=('Consolas', 10),
            padx=10, pady=8, cursor='arrow',
            spacing1=2, spacing3=4,
        )
        sb.config(command=self.txt.yview)
        self.txt.pack(fill='both', expand=True)

        # Message tags
        self.txt.tag_configure('hint',
            justify='center', foreground=C_HINT,
            font=('Arial', 10), spacing1=16)
        self.txt.tag_configure('user',
            justify='right', foreground=C_USER_FG,
            background=C_USER_BG, font=('Arial', 10),
            lmargin1=55, lmargin2=55, rmargin=8,
            spacing1=4, spacing3=4)
        self.txt.tag_configure('agent',
            justify='left', foreground=C_AGNT_FG,
            background=C_AGNT_BG, font=('Consolas', 10),
            lmargin1=8, lmargin2=8, rmargin=55,
            spacing1=4, spacing3=4)
        self.txt.tag_configure('error',
            justify='left', foreground=C_ERR_FG,
            background=C_ERR_BG, font=('Arial', 10),
            lmargin1=8, lmargin2=8, rmargin=55,
            spacing1=4, spacing3=4)
        self.txt.tag_configure('dots',
            justify='left', foreground=C_BRAND,
            font=('Arial', 16), lmargin1=8,
            spacing1=4, spacing3=4)

        self._write('\nHow can I help you today?\n', 'hint')
        self._empty = True

    # ── Window move (drag header) ─────────────────────────────────────────────

    def _hdr_press(self, e):
        self._mx = e.x_root - self.win.winfo_x()
        self._my = e.y_root - self.win.winfo_y()

    def _hdr_drag(self, e):
        x = e.x_root - self._mx
        y = e.y_root - self._my
        self.win.geometry(f'+{x}+{y}')

    # ── Window resize (drag bottom-right grip) ────────────────────────────────

    def _grip_press(self, e):
        self._rw = self.win.winfo_width()
        self._rh = self.win.winfo_height()
        self._rx = e.x_root
        self._ry = e.y_root

    def _grip_drag(self, e):
        nw = max(280, self._rw + (e.x_root - self._rx))
        nh = max(300, self._rh + (e.y_root - self._ry))
        self.win.geometry(f'{nw}x{nh}')

    # ── Message helpers ───────────────────────────────────────────────────────

    def _write(self, text, tag):
        self.txt.config(state='normal')
        self.txt.insert('end', text + '\n', tag)
        self.txt.config(state='disabled')
        self.txt.see('end')

    def _clear_hint(self):
        if getattr(self, '_empty', False):
            self.txt.config(state='normal')
            self.txt.delete('1.0', 'end')
            self.txt.config(state='disabled')
            self._empty = False

    def _show_typing(self):
        self._status_text = 'working'
        self._dot_frame = 0
        self.txt.config(state='normal')
        self.txt.insert('end', self._status_text + '   \n', 'dots')
        self.txt.config(state='disabled')
        self.txt.see('end')
        self._tick_dots()

    def _render_status(self, suffix):
        ranges = self.txt.tag_ranges('dots')
        if ranges:
            self.txt.config(state='normal')
            self.txt.delete(ranges[-2], ranges[-1])
            self.txt.insert(str(ranges[-2]), self._status_text + suffix + '\n', 'dots')
            self.txt.config(state='disabled')
            self.txt.see('end')

    def _tick_dots(self):
        # Gentle animation shown only until the first real progress event.
        frames = ['.  ', '.. ', '...']
        self._dot_frame = (self._dot_frame + 1) % 3
        self._render_status(frames[self._dot_frame])
        self._dot_after = self.root.after(400, self._tick_dots)

    def _set_status(self, text):
        # A progress line arrived — stop the placeholder animation and show it.
        if self._dot_after:
            self.root.after_cancel(self._dot_after)
            self._dot_after = None
        self._status_text = text
        self._render_status('')

    def _stop_typing(self):
        if self._dot_after:
            self.root.after_cancel(self._dot_after)
            self._dot_after = None
        ranges = self.txt.tag_ranges('dots')
        if ranges:
            self.txt.config(state='normal')
            for i in range(len(ranges) - 1, -1, -2):
                self.txt.delete(ranges[i - 1], ranges[i])
            self.txt.config(state='disabled')

    # ── Input / submit ────────────────────────────────────────────────────────

    def _on_enter(self, event):
        if not (event.state & 0x1):
            self._submit()
            return 'break'

    def auto_send(self, text):
        """Programmatically send a message (used by hotkeys)."""
        if self._busy:
            return
        self.inp.delete('1.0', 'end')
        self.inp.insert('1.0', text)
        self._submit()

    def _submit(self):
        text = self.inp.get('1.0', 'end').strip()
        if not text or self._busy:
            return
        self._busy = True
        self._btn.config(state='disabled')
        self.inp.delete('1.0', 'end')
        self._clear_hint()
        self._write(text, 'user')
        self._show_typing()
        threading.Thread(target=self._bg_call, args=(text,), daemon=True).start()

    def _bg_call(self, text):
        try:
            stream_to_agent(
                text,
                on_progress=lambda t: self.root.after(0, self._on_progress, t),
                on_final=lambda t: self.root.after(0, self._on_reply, t, None),
            )
        except Exception as e:
            self.root.after(0, self._on_reply, None, str(e))

    def _on_progress(self, text):
        self._set_status(text)

    def _on_reply(self, reply, err):
        self._stop_typing()
        self._write('⚠ ' + err if err else (reply or '(empty response)'),
                    'error' if err else 'agent')
        self._busy = False
        self._btn.config(state='normal')
        self.inp.focus_set()

    # ── Open / close — pop up just above the trigger button ──────────────────

    def toggle(self, btn_x, btn_y):
        self.close() if self._open else self.open(btn_x, btn_y)

    def open(self, btn_x, btn_y):
        if self._open:
            return
        self._open = True

        sw, sh = _screen_w(), _screen_h()

        # Position: sit just above the trigger button, nudge left if near edge
        px = max(MARGIN, min(btn_x + SIZE // 2 - PANEL_W // 2,
                             sw - PANEL_W - MARGIN))
        py = btn_y - PANEL_H - MARGIN

        # If trigger is near the top, open below it instead
        if py < MARGIN:
            py = btn_y + SIZE + MARGIN

        self.win.geometry(f'{PANEL_W}x{PANEL_H}+{px}+{py}')
        self.win.deiconify()
        self.win.lift()
        self.root.after(80, self.inp.focus_set)

    def close(self):
        if not self._open:
            return
        self._open = False
        self.win.withdraw()


# =============================================================================
# FLOATING TRIGGER BUTTON
# =============================================================================
class FloatingIcon:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-transparentcolor', TRANSPARENT)
        self._visible = False
        self.root.configure(bg=TRANSPARENT)

        sw, sh = _screen_w(), _screen_h()
        self._x = sw - SIZE - MARGIN
        self._y = sh - SIZE - MARGIN * 2
        self.root.geometry(f'{SIZE}x{SIZE}+-{SIZE*10}+-{SIZE*10}')

        cv = tk.Canvas(self.root, width=SIZE, height=SIZE,
                       bg=TRANSPARENT, highlightthickness=0)
        cv.pack()

        r, c = SIZE // 2 - 3, SIZE // 2
        cv.create_oval(c-r, c-r, c+r, c+r, fill=C_BRAND, outline='')
        cv.create_text(c, c, text='SAP', fill=C_WHITE, font=('Arial', 11, 'bold'))

        self._ox = self._oy = self._sx = self._sy = 0
        self._moved = False

        cv.bind('<ButtonPress-1>',   self._press)
        cv.bind('<B1-Motion>',       self._drag)
        cv.bind('<ButtonRelease-1>', self._release)
        cv.bind('<Enter>', lambda _: self.root.config(cursor='hand2'))
        cv.bind('<Leave>', lambda _: self.root.config(cursor=''))
        cv.bind('<ButtonPress-3>',   self._right_click_menu)

        self.popup = ChatPopup(self.root, on_hide=lambda: self._hotkey_toggle())

        if STARTUP_DESTINATION:
            threading.Thread(target=self._silent_switch, daemon=True).start()

        self._start_hotkey(self.root, self._hotkey_toggle, self._hotkey_switch_d4h)

        self.root.mainloop()

    def _silent_switch(self):
        """Silently switch to STARTUP_DESTINATION at launch — no UI message shown."""
        try:
            stream_to_agent(
                f'switch destination to {STARTUP_DESTINATION}',
                on_progress=lambda _: None,
                on_final=lambda _: None,
            )
        except Exception:
            pass

    def _right_click_menu(self, e):
        m = tk.Toplevel(self.root)
        m.overrideredirect(True)
        m.attributes('-topmost', True)

        def _dismiss(ev=None):
            try: m.destroy()
            except Exception: pass

        fr = tk.Frame(m, bg='white', bd=1, relief='solid')
        fr.pack()

        btn_cfg = dict(relief='flat', bg='white', activebackground='#e8e8e8',
                       anchor='w', padx=14, pady=5, font=('Arial', 10),
                       cursor='hand2', bd=0)

        if self.popup._open:
            def _do_close():
                _dismiss(); self.popup.close()
            tk.Button(fr, text='Close chat', command=_do_close, **btn_cfg).pack(fill='x')
        else:
            def _do_open():
                _dismiss(); self.popup.open(*self._btn_pos())
            tk.Button(fr, text='Open chat', command=_do_open, **btn_cfg).pack(fill='x')

        tk.Frame(fr, bg='#dddddd', height=1).pack(fill='x')

        def _do_quit():
            _dismiss(); self.root.destroy(); import os; os._exit(0)
        tk.Button(fr, text='Quit', command=_do_quit,
                  **{**btn_cfg, 'fg': '#cc0000', 'activeforeground': '#cc0000'}).pack(fill='x')

        sw, sh = _screen_w(), _screen_h()
        mx = max(4, min(e.x_root - 60, sw - 160))
        my = e.y_root - 84
        m.geometry(f'+{mx}+{my}')
        m.focus_set()
        m.bind('<Escape>', _dismiss)

    def _btn_pos(self):
        return self.root.winfo_x(), self.root.winfo_y()

    def _hotkey_toggle(self):
        if self._visible:
            self._visible = False
            self.root.geometry(f'{SIZE}x{SIZE}+-{SIZE*10}+-{SIZE*10}')
            if self.popup._open:
                self.popup.close()
        else:
            self._visible = True
            self.root.geometry(f'{SIZE}x{SIZE}+{self._x}+{self._y}')

    def _hotkey_switch_d4h(self):
        bx, by = self._btn_pos()
        if not self.popup._open:
            self.popup.open(bx, by)
        self.root.after(120, lambda: self.popup.auto_send('switch destination to D4H-200'))

    def _press(self, e):
        self._ox = e.x_root - self.root.winfo_x()
        self._oy = e.y_root - self.root.winfo_y()
        self._sx, self._sy = e.x_root, e.y_root
        self._moved = False

    def _drag(self, e):
        if abs(e.x_root - self._sx) > 4 or abs(e.y_root - self._sy) > 4:
            self._moved = True
        if self._moved:
            x = max(0, min(e.x_root - self._ox, _screen_w() - SIZE))
            y = max(0, min(e.y_root - self._oy, _screen_h() - SIZE))
            self.root.geometry(f'+{x}+{y}')

    def _release(self, e):
        if not self._moved:
            bx, by = self._btn_pos()
            self.popup.toggle(bx, by)

    @staticmethod
    def _start_hotkey(root, on_toggle, on_d4h):
        import threading, time
        def _thread():
            ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, MOD_CTRL | MOD_ALT | MOD_NOREPEAT, VK_W)
            ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID_D4H, MOD_CTRL | MOD_ALT | MOD_NOREPEAT, VK_J)
            msg = ctypes.wintypes.MSG()
            _last = [0.0, 0.0]
            while True:
                r = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_HOTKEY:
                    now = time.time()
                    if msg.wParam == HOTKEY_ID and now - _last[0] > 0.5:
                        _last[0] = now
                        root.after(0, on_toggle)
                    elif msg.wParam == HOTKEY_ID_D4H and now - _last[1] > 0.5:
                        _last[1] = now
                        root.after(0, on_d4h)

        threading.Thread(target=_thread, daemon=True).start()


if __name__ == '__main__':
    FloatingIcon()
