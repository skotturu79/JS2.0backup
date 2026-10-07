/*!
 * joule-chat-widget.js  –  Embeddable SAP Warehouse Assistant chat panel
 * No external dependencies · No build step · Single-file drop-in
 *
 * ============================================================
 * USAGE
 * ============================================================
 *
 *   <script src="joule-chat-widget.js"></script>
 *   <script>
 *     initJouleWidget({
 *
 *       // Plug your A2A / Joule endpoint here.
 *       // BLOCKING (message/send) — returns the final answer only:
 *       onSendMessage: async function (message) {
 *         var res = await fetch('https://your-agent.cfapps.eu10.hana.ondemand.com/', {
 *           method: 'POST',
 *           headers: {
 *             'Content-Type': 'application/json',
 *             'Authorization': 'Bearer ' + getAccessToken()
 *           },
 *           body: JSON.stringify({
 *             jsonrpc: '2.0',
 *             id: crypto.randomUUID(),
 *             method: 'tasks/send',
 *             params: {
 *               message: {
 *                 role: 'user',
 *                 parts: [{ type: 'text', text: message }]
 *               }
 *             }
 *           })
 *         });
 *         if (!res.ok) throw new Error('HTTP ' + res.status);
 *         var data = await res.json();
 *         // A2A response: result.artifacts[0].parts[].text
 *         var parts = (data.result && data.result.artifacts &&
 *                      data.result.artifacts[0] && data.result.artifacts[0].parts) || [];
 *         return parts.filter(function (p) { return p.type === 'text'; })
 *                     .map(function (p) { return p.text; }).join('\n') || '(no response)';
 *       },
 *
 *       // STREAMING (message/stream, SSE) — the 2nd arg onProgress(text) streams
 *       // live step/tool progress into the typing bubble; resolve to the final answer:
 *       //
 *       //   onSendMessage: async function (message, onProgress) {
 *       //     var ctx = window._jcwCtx;                       // keep thread across turns
 *       //     var msg = { messageId: crypto.randomUUID(), role: 'user',
 *       //                 parts: [{ type: 'text', text: message }] };
 *       //     if (ctx) msg.contextId = ctx;
 *       //     var res = await fetch(AGENT_URL, {
 *       //       method: 'POST',
 *       //       headers: { 'Content-Type': 'application/json',
 *       //                  'Accept': 'text/event-stream',
 *       //                  'Authorization': 'Bearer ' + getAccessToken() },
 *       //       body: JSON.stringify({ jsonrpc: '2.0', id: '1',
 *       //                              method: 'message/stream',
 *       //                              params: { message: msg } })
 *       //     });
 *       //     if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);
 *       //     var reader = res.body.getReader(), dec = new TextDecoder();
 *       //     var buf = '', finalText = null;
 *       //     function dispatch(payload) {
 *       //       var evt; try { evt = JSON.parse(payload); } catch (e) { return; }
 *       //       var r = evt.result || {};
 *       //       if (r.contextId && !window._jcwCtx) window._jcwCtx = r.contextId;
 *       //       var partsText = function (ps) {
 *       //         return (ps || []).filter(function (p){ return p.kind==='text'||p.type==='text'; })
 *       //                          .map(function (p){ return p.text; }).join('\n').trim(); };
 *       //       if (r.kind === 'status-update') {
 *       //         var s = r.status || {}, t = partsText((s.message||{}).parts);
 *       //         if (s.state === 'input-required' && t) finalText = t;
 *       //         else if (t) onProgress(t);                 // 🔧 step progress
 *       //       } else if (r.kind === 'artifact-update') {
 *       //         var a = partsText((r.artifact||{}).parts); if (a) finalText = a;
 *       //       }
 *       //     }
 *       //     for (;;) {
 *       //       var chunk = await reader.read(); if (chunk.done) break;
 *       //       buf += dec.decode(chunk.value, { stream: true });
 *       //       var parts = buf.split('\n\n'); buf = parts.pop();
 *       //       parts.forEach(function (block) {
 *       //         var data = block.split('\n')
 *       //           .filter(function (l){ return l.indexOf('data:') === 0; })
 *       //           .map(function (l){ return l.slice(5).trim(); }).join('\n');
 *       //         if (data) dispatch(data);
 *       //       });
 *       //     }
 *       //     return finalText || '(no response)';
 *       //   },
 *
 *       // Optional (all have sensible defaults):
 *       logoUrl:  '/assets/sap-logo.svg',           // omit to use the built-in SAP placeholder SVG
 *       position: 'bottom-right',                    // 'bottom-right' | 'bottom-left'
 *       shortcut: { ctrlKey: true, shiftKey: true, altKey: false, key: 'j' }  // Ctrl+Shift+J
 *     });
 *   </script>
 *
 * ============================================================
 */

(function (global) {
  'use strict';

  /* ------------------------------------------------------------------
   * Internal constants
   * ------------------------------------------------------------------ */
  var P = 'jcw';   // CSS class / id prefix — scopes all widget styles

  var DEFAULTS = {
    position: 'bottom-right',
    shortcut: { ctrlKey: true, shiftKey: true, altKey: false, key: 'j' },
    // Inline SAP-blue placeholder SVG so the widget works with zero config
    logoUrl: 'data:image/svg+xml,' + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">' +
      '<rect width="44" height="44" rx="8" fill="#0070F2"/>' +
      '<text x="22" y="30" text-anchor="middle" fill="#fff" ' +
      'font-family="Arial,Helvetica,sans-serif" font-size="15" ' +
      'font-weight="700" letter-spacing="0.5">SAP</text>' +
      '</svg>'
    )
  };


  /* ============================================================
   * SECTION 1 — FLOATING TRIGGER BUTTON (draggable)
   * ============================================================ */

  function buildTriggerButton(logoUrl, position) {
    var btn = document.createElement('button');
    btn.id  = P + '-trigger';
    btn.className = P + '-trigger ' + P + '-pos-' + position;
    btn.setAttribute('role', 'button');
    btn.setAttribute('tabindex', '0');
    btn.setAttribute('aria-label', 'Open SAP assistant');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('title', 'Open SAP assistant — drag to reposition');

    var img = document.createElement('img');
    img.src = logoUrl;
    img.alt = '';
    img.setAttribute('aria-hidden', 'true');
    img.width  = 32;
    img.height = 32;

    btn.appendChild(img);
    return btn;
  }

  // Attach mouse + touch drag behaviour.
  // Distinguishes click (≤ 4 px movement) from drag (> 4 px).
  // Keeps the button fully within the viewport. Returns a teardown fn.
  function makeDraggable(btn) {
    var DRAG_THRESHOLD = 4;   // px — movement below this is treated as a click
    var dragging  = false;
    var didDrag   = false;
    var startX, startY, origLeft, origTop;

    function getPos() {
      var r = btn.getBoundingClientRect();
      return { left: r.left, top: r.top };
    }

    function applyPos(left, top) {
      // Clamp to viewport
      var maxLeft = window.innerWidth  - btn.offsetWidth;
      var maxTop  = window.innerHeight - btn.offsetHeight;
      left = Math.max(0, Math.min(left, maxLeft));
      top  = Math.max(0, Math.min(top,  maxTop));

      // Switch from corner-class positioning to explicit coordinates
      btn.classList.remove(P + '-pos-bottom-right', P + '-pos-bottom-left');
      btn.style.left   = left + 'px';
      btn.style.top    = top  + 'px';
      btn.style.right  = 'auto';
      btn.style.bottom = 'auto';
    }

    function onMouseDown(e) {
      if (e.button !== 0) return;   // left button only
      dragging = true;
      didDrag  = false;
      var pos  = getPos();
      startX   = e.clientX;
      startY   = e.clientY;
      origLeft = pos.left;
      origTop  = pos.top;
      btn.style.cursor = 'grabbing';
      e.preventDefault();
    }

    function onMouseMove(e) {
      if (!dragging) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      if (!didDrag && Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) didDrag = true;
      if (didDrag) applyPos(origLeft + dx, origTop + dy);
    }

    function onMouseUp(e) {
      if (!dragging) return;
      dragging = false;
      btn.style.cursor = '';
      // Suppress the click event that fires after a drag
      if (didDrag) {
        e.stopImmediatePropagation();
        // One-shot capture listener to swallow the synthetic click
        btn.addEventListener('click', function absorb(ev) {
          ev.stopImmediatePropagation();
          btn.removeEventListener('click', absorb, true);
        }, true);
      }
    }

    // Touch equivalents
    function onTouchStart(e) {
      var t = e.touches[0];
      dragging = true;
      didDrag  = false;
      var pos  = getPos();
      startX   = t.clientX;
      startY   = t.clientY;
      origLeft = pos.left;
      origTop  = pos.top;
    }

    function onTouchMove(e) {
      if (!dragging) return;
      var t  = e.touches[0];
      var dx = t.clientX - startX;
      var dy = t.clientY - startY;
      if (!didDrag && Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) didDrag = true;
      if (didDrag) {
        e.preventDefault();   // stop page scroll while dragging the button
        applyPos(origLeft + dx, origTop + dy);
      }
    }

    function onTouchEnd() {
      dragging = false;
    }

    btn.addEventListener('mousedown',  onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup',   onMouseUp);
    btn.addEventListener('touchstart', onTouchStart, { passive: true });
    btn.addEventListener('touchmove',  onTouchMove,  { passive: false });
    btn.addEventListener('touchend',   onTouchEnd);

    return function teardown() {
      btn.removeEventListener('mousedown',  onMouseDown);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup',   onMouseUp);
      btn.removeEventListener('touchstart', onTouchStart);
      btn.removeEventListener('touchmove',  onTouchMove);
      btn.removeEventListener('touchend',   onTouchEnd);
    };
  }


  /* ============================================================
   * SECTION 3 — SLIDE-OUT CHAT PANEL (shell + header)
   * ============================================================ */

  function buildPanel(logoUrl) {
    // Outer panel — fixed, slides in from the right edge
    var panel = document.createElement('div');
    panel.id        = P + '-panel';
    panel.className = P + '-panel';
    panel.setAttribute('role', 'complementary');
    panel.setAttribute('aria-label', 'SAP Warehouse Assistant');
    panel.setAttribute('aria-hidden', 'true');

    // Header: logo + title + close button
    var header = document.createElement('div');
    header.className = P + '-header';

    var headerLogo = document.createElement('img');
    headerLogo.src = logoUrl;
    headerLogo.alt = '';
    headerLogo.setAttribute('aria-hidden', 'true');
    headerLogo.className = P + '-header-logo';
    headerLogo.width  = 24;
    headerLogo.height = 24;

    var headerTitle = document.createElement('span');
    headerTitle.className   = P + '-header-title';
    headerTitle.textContent = 'SAP Warehouse Assistant';

    var closeBtn = document.createElement('button');
    closeBtn.className = P + '-close-btn';
    closeBtn.setAttribute('aria-label', 'Close assistant');
    closeBtn.setAttribute('title', 'Close (Esc)');
    closeBtn.textContent = '✕';   // ✕

    header.appendChild(headerLogo);
    header.appendChild(headerTitle);
    header.appendChild(closeBtn);

    // Message list (SECTION 4 content)
    var msgList = document.createElement('div');
    msgList.className = P + '-msg-list';
    msgList.setAttribute('role', 'log');
    msgList.setAttribute('aria-live', 'polite');
    msgList.setAttribute('aria-label', 'Conversation');

    var emptyState = document.createElement('p');
    emptyState.className   = P + '-empty-state';
    emptyState.textContent = 'How can I help you today?';
    msgList.appendChild(emptyState);

    // Input row (SECTION 4 content)
    var inputRow = document.createElement('div');
    inputRow.className = P + '-input-row';

    var textarea = document.createElement('textarea');
    textarea.className   = P + '-input';
    textarea.placeholder = 'Ask about stock, deliveries, tasks…';
    textarea.rows        = 1;
    textarea.setAttribute('aria-label', 'Type a message. Enter to send, Shift+Enter for new line.');

    var sendBtn = document.createElement('button');
    sendBtn.className = P + '-send-btn';
    sendBtn.setAttribute('aria-label', 'Send message');
    // Paper-plane send icon (Heroicons outline)
    sendBtn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" width="18" height="18" aria-hidden="true">' +
      '<line x1="22" y1="2" x2="11" y2="13"/>' +
      '<polygon points="22 2 15 22 11 13 2 9 22 2"/>' +
      '</svg>';

    inputRow.appendChild(textarea);
    inputRow.appendChild(sendBtn);

    panel.appendChild(header);
    panel.appendChild(msgList);
    panel.appendChild(inputRow);

    return {
      panel:      panel,
      closeBtn:   closeBtn,
      msgList:    msgList,
      emptyState: emptyState,
      textarea:   textarea,
      sendBtn:    sendBtn
    };
  }


  /* ============================================================
   * SECTION 4 — CHAT UI helpers
   * ============================================================ */

  function hideEmptyState(emptyState) {
    if (emptyState && emptyState.parentNode) {
      emptyState.style.display = 'none';
    }
  }

  // Append a chat bubble; role is 'user' | 'agent'
  function appendMessage(msgList, emptyState, text, role) {
    hideEmptyState(emptyState);
    var bubble = document.createElement('div');
    bubble.className = P + '-msg ' + P + '-msg--' + role;
    bubble.innerText = text;    // innerText: XSS-safe and preserves whitespace (good for tables)
    msgList.appendChild(bubble);
    msgList.scrollTop = msgList.scrollHeight;
    return bubble;
  }

  // Show an inline error bubble (never throws, never breaks the panel)
  function appendErrorBubble(msgList, emptyState, errorText) {
    hideEmptyState(emptyState);
    var bubble = document.createElement('div');
    bubble.className = P + '-msg ' + P + '-msg--error';
    bubble.innerText = '⚠ ' + errorText;   // ⚠ ...
    msgList.appendChild(bubble);
    msgList.scrollTop = msgList.scrollHeight;
  }

  // Show animated three-dot typing / loading indicator
  function showTypingIndicator(msgList) {
    var indicator = document.createElement('div');
    indicator.className = P + '-msg ' + P + '-msg--agent ' + P + '-typing';
    indicator.setAttribute('aria-label', 'Agent is responding…');
    indicator.innerHTML =
      '<span class="' + P + '-dot" aria-hidden="true"></span>' +
      '<span class="' + P + '-dot" aria-hidden="true"></span>' +
      '<span class="' + P + '-dot" aria-hidden="true"></span>';
    msgList.appendChild(indicator);
    msgList.scrollTop = msgList.scrollHeight;
    return indicator;
  }

  // Convert the dots indicator into a live progress/status line (e.g. "🔧 …").
  // Called on each intermediate streaming update via the onProgress callback.
  function setIndicatorText(indicator, text) {
    indicator.classList.remove(P + '-typing');
    indicator.classList.add(P + '-progress');
    indicator.innerHTML = '';               // drop the dot <span>s
    indicator.textContent = text;
  }

  // Grow textarea with content, capped at 120 px
  function autoResizeTextarea(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }


  /* ============================================================
   * SECTION 5 — AGENT INTEGRATION HOOK
   * ============================================================ */

  // Calls onSendMessage, shows typing indicator, appends reply or error bubble.
  // onSendMessage receives (message, onProgress): call onProgress(text) to stream
  // intermediate step/tool progress into the indicator (optional — handlers that
  // ignore the 2nd arg keep working). onDone() fires when the op settles.
  function callAgent(onSendMessage, message, msgList, emptyState, onDone) {
    var indicator = showTypingIndicator(msgList);

    function onProgress(text) {
      if (text == null || !indicator.parentNode) return;
      setIndicatorText(indicator, String(text));
      msgList.scrollTop = msgList.scrollHeight;
    }

    Promise.resolve()
      .then(function () { return onSendMessage(message, onProgress); })
      .then(function (reply) {
        indicator.remove();
        appendMessage(
          msgList, emptyState,
          reply != null ? String(reply) : '(empty response)',
          'agent'
        );
      })
      .catch(function (err) {
        indicator.remove();
        var msg = (err && err.message) ? err.message : String(err);
        appendErrorBubble(msgList, emptyState, 'Agent error: ' + msg);
      })
      .then(function () {
        if (typeof onDone === 'function') onDone();
      });
  }

  // Demo stub shown when no onSendMessage is provided
  function demoAgentHandler(message) {
    return Promise.resolve(
      'Widget is in demo mode.\n' +
      'Pass an `onSendMessage` async function to connect to your Joule / A2A agent.\n\n' +
      'Your message: "' + message + '"'
    );
  }


  /* ============================================================
   * SECTION 2 — CONFIGURABLE KEYBOARD SHORTCUT (helpers)
   * ============================================================ */

  function shortcutMatches(event, shortcut) {
    return (
      !!event.ctrlKey  === !!shortcut.ctrlKey  &&
      !!event.shiftKey === !!shortcut.shiftKey &&
      !!event.altKey   === !!shortcut.altKey   &&
      event.key.toLowerCase() === shortcut.key.toLowerCase()
    );
  }

  // Returns true when the given element is a native text-entry target
  function isEditableElement(el) {
    if (!el) return false;
    var tag = el.tagName ? el.tagName.toLowerCase() : '';
    return tag === 'input' || tag === 'textarea' || !!el.isContentEditable;
  }


  /* ============================================================
   * CSS — injected into <head> once; all rules scoped under
   * #jcw-trigger / #jcw-panel / .jcw-* — nothing leaks into host page
   * ============================================================ */

  function injectStyles() {
    if (document.getElementById(P + '-style')) return;
    var style = document.createElement('style');
    style.id = P + '-style';
    style.textContent = widgetCSS();
    (document.head || document.documentElement).appendChild(style);
  }

  /* eslint-disable */
  function widgetCSS() {
    return (
      // Scoped reset — only affects widget elements
      '#' + P + '-trigger, #' + P + '-panel, #' + P + '-panel * {' +
        'box-sizing:border-box;' +
        'font-family:"72","72full",Arial,Helvetica,sans-serif;' +
      '}' +

      /* ---- SECTION 1: Trigger button ---- */
      '#' + P + '-trigger {' +
        'position:fixed;' +
        'width:52px;height:52px;' +
        'border-radius:50%;border:none;' +
        'background:#0070F2;' +
        'cursor:grab;' +
        'display:flex;align-items:center;justify-content:center;' +
        'box-shadow:0 4px 16px rgba(0,0,0,.25);' +
        'z-index:999998;' +
        'padding:0;' +
        'transition:transform .15s ease, box-shadow .15s ease;' +
        'user-select:none;' +
      '}' +
      '#' + P + '-trigger:hover {' +
        'transform:scale(1.08);' +
        'box-shadow:0 6px 20px rgba(0,0,0,.32);' +
      '}' +
      // Visible focus ring (WCAG 2.4.7)
      '#' + P + '-trigger:focus-visible {' +
        'outline:3px solid #0070F2;outline-offset:4px;' +
      '}' +
      '.' + P + '-pos-bottom-right { bottom:24px; right:24px; }' +
      '.' + P + '-pos-bottom-left  { bottom:24px; left:24px;  }' +
      '#' + P + '-trigger img { pointer-events:none; border-radius:6px; }' +

      /* ---- SECTION 3: Slide-out panel ---- */
      '#' + P + '-panel {' +
        'position:fixed;top:0;right:0;' +
        'width:380px;height:100vh;' +
        'background:#fff;' +
        'box-shadow:-4px 0 24px rgba(0,0,0,.15);' +
        'display:flex;flex-direction:column;' +
        'z-index:999999;' +
        // Closed state: slide out to the right; visibility:hidden removes from tab order
        'transform:translateX(100%);' +
        'visibility:hidden;' +
        'transition:transform .27s cubic-bezier(.4,0,.2,1), visibility 0s linear .27s;' +
      '}' +
      '#' + P + '-panel.open {' +
        'transform:translateX(0);' +
        'visibility:visible;' +
        'transition:transform .27s cubic-bezier(.4,0,.2,1), visibility 0s linear 0s;' +
      '}' +

      // Header
      '.' + P + '-header {' +
        'display:flex;align-items:center;gap:10px;' +
        'padding:14px 16px;' +
        'background:#0070F2;color:#fff;' +
        'flex-shrink:0;' +
      '}' +
      '.' + P + '-header-logo { border-radius:4px; flex-shrink:0; }' +
      '.' + P + '-header-title {' +
        'flex:1;font-size:14px;font-weight:600;' +
        'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;' +
      '}' +
      '.' + P + '-close-btn {' +
        'background:none;border:none;color:#fff;cursor:pointer;' +
        'font-size:16px;padding:4px 8px;border-radius:4px;' +
        'line-height:1;flex-shrink:0;' +
      '}' +
      '.' + P + '-close-btn:hover { background:rgba(255,255,255,.2); }' +
      '.' + P + '-close-btn:focus-visible { outline:2px solid #fff; outline-offset:2px; }' +

      /* ---- SECTION 4: Message list ---- */
      '.' + P + '-msg-list {' +
        'flex:1;overflow-y:auto;' +
        'padding:16px;' +
        'display:flex;flex-direction:column;gap:10px;' +
        'scroll-behavior:smooth;' +
      '}' +
      '.' + P + '-empty-state {' +
        'margin:auto;text-align:center;' +
        'color:#8c8c8c;font-size:14px;padding:32px 16px 12px;' +
      '}' +
      '.' + P + '-quick-actions {' +
        'display:flex;flex-wrap:wrap;gap:6px;justify-content:center;' +
        'padding:0 16px 16px;' +
      '}' +
      '.' + P + '-quick-chip {' +
        'background:#f0f4ff;color:#0070F2;' +
        'border:1px solid #cce0ff;border-radius:16px;' +
        'padding:6px 12px;font-size:12px;cursor:pointer;' +
        'white-space:nowrap;transition:background .15s,border-color .15s;' +
        'font-family:inherit;line-height:1.3;' +
      '}' +
      '.' + P + '-quick-chip:hover { background:#ddeeff;border-color:#99c5ff; }' +
      '.' + P + '-quick-chip:active { background:#cce0ff; }' +

      // Bubble base
      '.' + P + '-msg {' +
        'max-width:82%;' +
        'padding:9px 13px;border-radius:12px;' +
        'font-size:13px;line-height:1.5;' +
        'word-break:break-word;' +
        // pre-wrap preserves whitespace in agent markdown tables/code blocks
        'white-space:pre-wrap;' +
      '}' +
      // User bubble — right-aligned
      '.' + P + '-msg--user {' +
        'align-self:flex-end;' +
        'background:#0070F2;color:#fff;' +
        'border-bottom-right-radius:4px;' +
      '}' +
      // Agent bubble — left-aligned, monospace so markdown tables render cleanly
      '.' + P + '-msg--agent {' +
        'align-self:flex-start;' +
        'background:#f0f4ff;color:#1a1a1a;' +
        'border-bottom-left-radius:4px;' +
        'font-family:Consolas,"Courier New",monospace;font-size:12px;' +
      '}' +
      // Error bubble — left-aligned, red tint
      '.' + P + '-msg--error {' +
        'align-self:flex-start;' +
        'background:#fff0f0;color:#c00;' +
        'border:1px solid #f5c6cb;' +
        'border-bottom-left-radius:4px;' +
      '}' +

      /* ---- SECTION 4: Typing indicator ---- */
      '.' + P + '-typing {' +
        'display:flex;align-items:center;gap:5px;padding:10px 14px;' +
      '}' +
      '.' + P + '-dot {' +
        'width:7px;height:7px;border-radius:50%;background:#0070F2;' +
        'animation:' + P + 'Bounce 1.2s ease-in-out infinite;' +
      '}' +
      '.' + P + '-dot:nth-child(2) { animation-delay:.2s; }' +
      '.' + P + '-dot:nth-child(3) { animation-delay:.4s; }' +
      '@keyframes ' + P + 'Bounce {' +
        '0%,60%,100% { transform:translateY(0);   opacity:.4; }' +
        '30%          { transform:translateY(-5px); opacity:1;  }' +
      '}' +
      // Live progress/status line (replaces the dots on each streaming update)
      '.' + P + '-progress {' +
        'align-self:flex-start;' +
        'background:#f0f4ff;color:#0070F2;' +
        'font-style:italic;' +
        'border-bottom-left-radius:4px;' +
      '}' +

      /* ---- SECTION 4: Input row ---- */
      '.' + P + '-input-row {' +
        'display:flex;align-items:flex-end;gap:8px;' +
        'padding:12px 14px;' +
        'border-top:1px solid #e5e5e5;background:#fff;' +
        'flex-shrink:0;' +
      '}' +
      '.' + P + '-input {' +
        'flex:1;resize:none;' +
        'border:1px solid #ccc;border-radius:8px;' +
        'padding:8px 12px;font-size:13px;line-height:1.4;' +
        'outline:none;max-height:120px;overflow-y:auto;min-height:36px;' +
        'font-family:inherit;' +
      '}' +
      '.' + P + '-input:focus {' +
        'border-color:#0070F2;box-shadow:0 0 0 2px rgba(0,112,242,.2);' +
      '}' +
      '.' + P + '-input:disabled { background:#f5f5f5; }' +
      '.' + P + '-send-btn {' +
        'width:36px;height:36px;border-radius:8px;border:none;' +
        'background:#0070F2;color:#fff;cursor:pointer;' +
        'display:flex;align-items:center;justify-content:center;' +
        'flex-shrink:0;transition:background .15s;' +
      '}' +
      '.' + P + '-send-btn:hover    { background:#0057c2; }' +
      '.' + P + '-send-btn:focus-visible { outline:2px solid #0070F2; outline-offset:2px; }' +
      '.' + P + '-send-btn:disabled { background:#b3b3b3; cursor:not-allowed; }' +

      // Responsive: full-width on very narrow viewports
      '@media(max-width:420px) { #' + P + '-panel { width:100vw; } }'
    );
  }
  /* eslint-enable */


  /* ============================================================
   * SECTION 6 — PUBLIC API
   * ============================================================ */

  /**
   * initJouleWidget(config)
   *
   * @param {object} config
   * @param {function} config.onSendMessage  async (message: string) => string
   * @param {string}   [config.logoUrl]      URL of logo image; defaults to inline SAP SVG
   * @param {string}   [config.position]     'bottom-right' (default) | 'bottom-left'
   * @param {object}   [config.shortcut]     { ctrlKey, shiftKey, altKey, key }
   *                                         Default: Ctrl+Shift+J
   * @param {Array}    [config.quickActions] Array of {label, message} chips shown in empty state
   */
  function initJouleWidget(config) {
    var cfg = config || {};

    // Merge config with defaults
    var logoUrl  = cfg.logoUrl  || DEFAULTS.logoUrl;
    var position = cfg.position === 'bottom-left' ? 'bottom-left' : DEFAULTS.position;

    var sc = cfg.shortcut || {};
    var shortcut = {
      ctrlKey:  sc.ctrlKey  !== undefined ? !!sc.ctrlKey  : DEFAULTS.shortcut.ctrlKey,
      shiftKey: sc.shiftKey !== undefined ? !!sc.shiftKey : DEFAULTS.shortcut.shiftKey,
      altKey:   sc.altKey   !== undefined ? !!sc.altKey   : DEFAULTS.shortcut.altKey,
      key:      sc.key      !== undefined ? sc.key        : DEFAULTS.shortcut.key
    };

    var onSendMessage = typeof cfg.onSendMessage === 'function'
      ? cfg.onSendMessage
      : demoAgentHandler;

    // Guard against double-init
    if (document.getElementById(P + '-trigger')) {
      console.warn('[JouleWidget] Already initialised. Call jcwDestroy() before re-initialising.');
      return;
    }

    // Inject CSS and build DOM nodes
    injectStyles();
    var triggerBtn = buildTriggerButton(logoUrl, position);
    var ui         = buildPanel(logoUrl);
    document.body.appendChild(triggerBtn);
    document.body.appendChild(ui.panel);

    // Quick-action chips — shown in empty state, hidden after first send
    var chipsContainer = null;
    var quickActions = Array.isArray(cfg.quickActions) ? cfg.quickActions : [];
    if (quickActions.length) {
      chipsContainer = document.createElement('div');
      chipsContainer.className = P + '-quick-actions';
      quickActions.forEach(function (qa) {
        var chip = document.createElement('button');
        chip.className   = P + '-quick-chip';
        chip.textContent = qa.label || '';
        chip.type        = 'button';
        chip.addEventListener('click', function () {
          ui.textarea.value = qa.message || '';
          autoResizeTextarea(ui.textarea);
          submitMessage();
        });
        chipsContainer.appendChild(chip);
      });
      ui.msgList.appendChild(chipsContainer);
    }

    // Make trigger draggable; store teardown so jcwDestroy can clean up
    var _dragTeardown = makeDraggable(triggerBtn);

    // Widget state
    var isOpen    = false;
    var isWaiting = false;

    /* ------ Open / Close ---------------------------------------- */

    function openPanel() {
      isOpen = true;
      ui.panel.classList.add('open');
      ui.panel.setAttribute('aria-hidden', 'false');
      triggerBtn.setAttribute('aria-expanded', 'true');
      // Shift focus after CSS transition completes (270 ms)
      setTimeout(function () { ui.textarea.focus(); }, 290);
    }

    function closePanel() {
      isOpen = false;
      ui.panel.classList.remove('open');
      ui.panel.setAttribute('aria-hidden', 'true');
      triggerBtn.setAttribute('aria-expanded', 'false');
      // Return focus to trigger button (WCAG 2.4.3)
      triggerBtn.focus();
    }

    /* ------ SECTION 1: Trigger button events -------------------- */

    triggerBtn.addEventListener('click', function () {
      isOpen ? closePanel() : openPanel();
    });

    // Enter / Space keyboard activation (button already handles click for Space,
    // but explicit handler makes Enter behaviour explicit for all browsers)
    triggerBtn.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        isOpen ? closePanel() : openPanel();
      }
    });

    /* ------ SECTION 3: Close button + focus trap ---------------- */

    ui.closeBtn.addEventListener('click', closePanel);

    // Simple focus trap: Tab wraps around inside the open panel
    ui.panel.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab') return;
      var focusable = Array.from(
        ui.panel.querySelectorAll(
          'button:not([disabled]), textarea:not([disabled]),' +
          ' [tabindex]:not([tabindex="-1"])'
        )
      );
      if (!focusable.length) return;
      var first = focusable[0];
      var last  = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    /* ------ SECTION 2: Global keyboard shortcut + Escape -------- */

    function onGlobalKeyDown(e) {
      // Escape closes the panel when open
      if (e.key === 'Escape' && isOpen) {
        closePanel();
        return;
      }

      if (!shortcutMatches(e, shortcut)) return;

      var active  = document.activeElement;
      var inPanel = ui.panel.contains(active);

      // Do NOT intercept if the shortcut key is pressed inside a foreign editable element
      // (protects native undo/typing in the host page). Exception: the widget's own input.
      if (!inPanel && isEditableElement(active)) return;

      e.preventDefault();
      isOpen ? closePanel() : openPanel();
    }

    document.addEventListener('keydown', onGlobalKeyDown);

    /* ------ SECTION 4: Textarea auto-resize + send on Enter ----- */

    ui.textarea.addEventListener('input', function () {
      autoResizeTextarea(ui.textarea);
    });

    ui.textarea.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();   // Shift+Enter inserts a newline; plain Enter sends
        submitMessage();
      }
    });

    ui.sendBtn.addEventListener('click', submitMessage);

    /* ------ SECTION 5: Message submit flow ---------------------- */

    function submitMessage() {
      var text = ui.textarea.value.trim();
      if (!text || isWaiting) return;

      if (chipsContainer) { chipsContainer.style.display = 'none'; }

      // Lock UI while waiting for the agent
      isWaiting = true;
      ui.sendBtn.disabled  = true;
      ui.textarea.disabled = true;
      ui.textarea.value    = '';
      ui.textarea.style.height = 'auto';

      appendMessage(ui.msgList, ui.emptyState, text, 'user');

      callAgent(onSendMessage, text, ui.msgList, ui.emptyState, function () {
        // Re-enable UI when agent response arrives (success or error)
        isWaiting = false;
        ui.sendBtn.disabled  = false;
        ui.textarea.disabled = false;
        ui.textarea.focus();
      });
    }
  }

  /* ------------------------------------------------------------------
   * Teardown helper — removes all widget DOM and event listeners.
   * Call before re-initialising with different config.
   * ------------------------------------------------------------------ */
  function jcwDestroy() {
    var trigger = document.getElementById(P + '-trigger');
    var panel   = document.getElementById(P + '-panel');
    if (trigger) trigger.remove();
    if (panel)   panel.remove();
    if (typeof global._jcwKeyHandler === 'function') {
      document.removeEventListener('keydown', global._jcwKeyHandler);
      global._jcwKeyHandler = null;
    }
    if (typeof global._jcwDragTeardown === 'function') {
      global._jcwDragTeardown();
      global._jcwDragTeardown = null;
    }
  }

  // Expose public API
  global.initJouleWidget = initJouleWidget;
  global.jcwDestroy      = jcwDestroy;

}(typeof window !== 'undefined' ? window : this));
