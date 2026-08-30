const $ = (id) => document.getElementById(id);
    const fmt = (n, d=2) => n == null || Number.isNaN(n) ? "—" : Number(n).toLocaleString(undefined, {minimumFractionDigits:d, maximumFractionDigits:d});
    const money = (n) => n == null ? "—" : (n < 0 ? "-" : "") + "$" + fmt(Math.abs(n), 2);
    const signedMoney = (n) => {
      if (n == null || Number.isNaN(n)) return "—";
      if (Math.abs(n) < 0.0001) return "$0.00";
      return (n > 0 ? "+" : "-") + "$" + fmt(Math.abs(n), 2);
    };
    const clsPnl = (n) => n > 0.0001 ? "up" : n < -0.0001 ? "dn" : "flat";
    const pnlDir = (n) => n > 0.0001 ? "UP" : n < -0.0001 ? "DOWN" : "FLAT";
    const TOKEN_KEY = "scalper_dash_token";
    const LOG_HIDDEN_KEY = "scalper_log_hidden";
    const RULES_KEY = "scalper_rules_bullets";
    const ui = { filter: "all", sort: "name", tape: "all", selected: null, last: null, rulesEditing: false };

    function logHidden() {
      const v = localStorage.getItem(LOG_HIDDEN_KEY);
      if (v === null) return true; // default: quieter dashboard
      return v === "1";
    }
    function setLogHidden(hidden) {
      localStorage.setItem(LOG_HIDDEN_KEY, hidden ? "1" : "0");
      applyLogHidden();
    }
    function applyLogHidden() {
      const hide = logHidden();
      $("logBody").hidden = hide;
      $("tapeFilters").hidden = hide;
      $("btnLogToggle").textContent = hide ? "SHOW" : "HIDE";
    }

    function defaultRules(s) {
      const r = (s && s.rules) || {};
      return [
        (s && s.mode === "LIVE") ? "REAL MONEY. IOC limits hit Kalshi." : "PAPER. Same signals, no Kalshi orders.",
        r.size || "3–5% of bankroll (hard cap 10%)",
        r.edge || "≥4¢ and ≥5% net after fees",
        r.target || "+4–8¢ then out",
        r.dead || "out in ~35s if it does not move",
        r.orders || "limits only; never market both sides",
        r.chase || "no revenge / no chase after a missed tick",
      ];
    }
    function loadRules(s) {
      try {
        const raw = localStorage.getItem(RULES_KEY);
        if (raw) {
          const arr = JSON.parse(raw);
          if (Array.isArray(arr) && arr.length) return arr.map(String);
        }
      } catch (_) {}
      return defaultRules(s);
    }
    function saveRules(bullets) {
      localStorage.setItem(RULES_KEY, JSON.stringify(bullets));
    }
    function renderRulesList(bullets) {
      $("rulesList").innerHTML = bullets.map(b => `<li>${b.replace(/</g, "&lt;")}</li>`).join("");
    }
    function setRulesEditMode(on) {
      ui.rulesEditing = on;
      $("rulesList").hidden = on;
      $("rulesEdit").hidden = !on;
      $("btnRulesEdit").hidden = on;
      $("btnRulesSave").hidden = !on;
      $("btnRulesCancel").hidden = !on;
      $("btnRulesReset").hidden = on;
      if (on) {
        const bullets = loadRules(ui.last || {});
        $("rulesEdit").value = bullets.join("\n");
        $("rulesEdit").focus();
      }
    }

    function dashToken() {
      const header = ($("dashToken") && $("dashToken").value) || "";
      const modal = ($("modeToken") && $("modeToken").value) || "";
      return (header || modal || sessionStorage.getItem(TOKEN_KEY) || "").trim();
    }
    function saveToken(value) {
      const t = (value || "").trim();
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      if ($("dashToken") && t && !$("dashToken").value) $("dashToken").value = t;
    }
    function tokenHeaders(extra) {
      const h = Object.assign({"Content-Type": "application/json"}, extra || {});
      const t = dashToken();
      if (t) h["X-Scalper-Token"] = t;
      return h;
    }

    function clock(s) {
      if (s == null) return "—";
      const x = Math.max(0, s);
      const m = Math.floor(x / 60), ss = Math.floor(x % 60);
      return m + ":" + String(ss).padStart(2,"0");
    }
    function showCard(c) {
      const hot = c.signal && c.signal.kind && c.signal.kind !== "none";
      if (ui.filter === "edge") return hot;
      if (ui.filter === "in") return !!c.position;
      if (ui.filter === "muted") return !!c.muted;
      if (ui.filter === "watch") return !hot && !c.position && !c.muted;
      return true;
    }
    function sortCards(a, b) {
      if (ui.sort === "edge") return (b.signal?.edge || 0) - (a.signal?.edge || 0);
      if (ui.sort === "clock") return (a.seconds_left ?? 9e9) - (b.seconds_left ?? 9e9);
      if (ui.sort === "spread") return (a.spread ?? 9) - (b.spread ?? 9);
      return a.asset.localeCompare(b.asset);
    }
    function sw(on, asset) {
      return `<button type="button" class="sw ${on ? "on" : ""}" data-act="mute" data-asset="${asset}" aria-pressed="${on}">${on ? "ON" : "OFF"}</button>`;
    }
    function card(c) {
      const hot = c.signal && c.signal.kind && c.signal.kind !== "none";
      const inPos = !!c.position;
      const edge = (c.fair != null && c.mid != null) ? (c.fair - c.mid) : 0;
      const vs = c.spot_vs_strike_bps;
      const vsCls = vs > 2 ? "up" : vs < -2 ? "dn" : "flat";
      const pos = c.position
        ? `<div class="pos">IN ${c.position.side.toUpperCase()} ×${fmt(c.position.qty,0)} @ ${fmt(c.position.entry,2)}
           MTM ${fmt(c.position.mtm,3)}  held ${fmt(c.position.held_s,0)}s  tgt +${fmt(c.position.target,2)}</div>`
        : "";
      const sigCls = hot ? "sig edge" : "sig";
      const sigTxt = hot
        ? `${c.signal.kind} ${c.signal.side}  edge ${fmt(c.signal.edge,3)}  ${c.signal.reason}`
        : (c.skip || "watching");
      const cls = ["card", hot ? "hot" : "", inPos ? "in" : "", c.muted ? "off" : "", ui.selected === c.asset ? "sel" : ""]
        .filter(Boolean).join(" ");
      return `<article class="${cls}" data-asset="${c.asset}">
        <div class="row">
          <div class="asset">${c.asset}${c.muted ? " · OFF" : ""}</div>
          <div class="row" style="gap:8px">
            ${sw(!c.muted, c.asset)}
            <div class="clock">${clock(c.seconds_left)}</div>
          </div>
        </div>
        <div class="spot">${fmt(c.spot, c.spot >= 100 ? 2 : 6)}</div>
        <div class="sub">strike ${fmt(c.strike, c.strike >= 100 ? 2 : 6)}
          <span class="${vsCls}">${vs == null ? "" : (vs>=0?"+":"") + fmt(vs,1) + " bps"}</span>
          · ${c.ticker || ""}
          ${c.spread != null ? " · spr " + fmt(c.spread, 2) : ""}
        </div>
        <div class="quotes">
          <div class="q"><div class="k">BID / ASK</div><div class="v">${fmt(c.yes_bid,2)} / ${fmt(c.yes_ask,2)}</div></div>
          <div class="q"><div class="k">FAIR</div><div class="v">${fmt(c.fair,2)}</div></div>
          <div class="q"><div class="k">EDGE</div><div class="v ${clsPnl(edge)}">${edge>=0?"+":""}${fmt(edge,3)}</div></div>
        </div>
        <div class="depth"><span>bid sz ${fmt(c.yes_bid_size,0)}</span><span>ask sz ${fmt(c.yes_ask_size,0)}</span></div>
        <div class="${sigCls}">${sigTxt}</div>
        ${pos}
        ${inPos ? `<div class="acts"><button type="button" class="danger" data-act="flatten" data-asset="${c.asset}">FLATTEN</button></div>` : ""}
      </article>`;
    }
    function marketChip(c) {
      return `<div class="mkt ${c.muted ? "off" : "on"}">
        <span class="nm">${c.asset}</span>${sw(!c.muted, c.asset)}
      </div>`;
    }
    function levels(rows) {
      return rows.map(r => `
        <div class="lvl">
          <span>${fmt(r.px,2)}</span>
          <span>${fmt(r.sz,0)}</span>
        </div>`).join("") || `<div class="empty">no book</div>`;
    }
    function detailHTML(c) {
      const src = Object.entries(c.sources || {});
      const lock = c.locked_avg != null
        ? `locked ${fmt(c.locked_secs,0)}s @ ${fmt(c.locked_avg, c.locked_avg >= 100 ? 2 : 6)}`
        : "not in settlement minute";
      return `
        <div class="card">
          <h2>${c.asset} BOOK</h2>
          <div class="ladder">
            <div><div class="sub">YES BIDS</div>${levels(c.depth_bid || [])}</div>
            <div><div class="sub">YES ASKS</div>${levels(c.depth_ask || [])}</div>
          </div>
        </div>
        <div class="card">
          <h2>WHY</h2>
          <div class="sig ${c.signal && c.signal.kind !== "none" ? "edge" : ""}">${c.signal?.kind || "none"} ${c.signal?.side || ""} · ${c.signal?.reason || c.skip || "watching"}</div>
          <div class="sub" style="margin-top:6px">vol ${fmt(c.sigma_1m_bps,1)} bps/min · last ${fmt(c.last,2)} · vol ${fmt(c.volume,0)} · oi ${fmt(c.oi,0)}</div>
          <div class="sub">settlement ${lock}</div>
          ${c.error ? `<div class="sig" style="color:var(--no)">${c.error}</div>` : ""}
        </div>
        <div class="card">
          <h2>VENUES</h2>
          <div class="src">${src.length ? src.map(([k,v]) => `<span>${k} ${fmt(v, v>=100?2:6)}</span>`).join("") : `<span>waiting</span>`}</div>
          <div class="sub" style="margin-top:8px">spot ${fmt(c.spot, c.spot>=100?2:6)} vs strike ${fmt(c.strike, c.strike>=100?2:6)}
            ${c.spot_chg == null ? "" : " · " + (c.spot_chg>=0?"+":"") + fmt(c.spot_chg, c.spot>=100?2:4) + " / 8s"}</div>
          <div class="acts" style="margin-top:10px">
            ${sw(!c.muted, c.asset)}
            ${c.position ? `<button type="button" class="danger" data-act="flatten" data-asset="${c.asset}">FLATTEN</button>` : ""}
            <button type="button" data-act="clear">CLOSE</button>
          </div>
        </div>`;
    }
    async function act(op, extra) {
      const payload = Object.assign({op}, typeof extra === "string" ? {asset: extra} : (extra || {}));
      const r = await fetch("/api/action", {
        method: "POST",
        headers: tokenHeaders(),
        body: JSON.stringify(payload),
      });
      const j = await r.json().catch(() => ({ok:false, error:"bad response"}));
      if (r.status === 401) $("feed").textContent = "TOKEN REQUIRED";
      else if (!j.ok) $("feed").textContent = j.error || "ACTION FAILED";
      await tick();
      return j;
    }
    function openLiveModal(msg, needType) {
      $("modeModalMsg").textContent = msg;
      $("modeConfirm").value = "";
      $("modeConfirm").hidden = !needType;
      $("modeGo").hidden = !needType;
      $("modeToken").hidden = !needType;
      if (needType) $("modeToken").value = dashToken();
      $("modeModal").hidden = false;
      if (needType) $("modeConfirm").focus();
    }
    function closeLiveModal() { $("modeModal").hidden = true; }
    async function requestLive() {
      const s = ui.last || {};
      if (s.mode === "LIVE") return;
      if (!dashToken()) {
        openLiveModal("Dashboard is locked. Enter the SCALPER_DASHBOARD_TOKEN in the token box, then type LIVE.", true);
        $("dashToken").hidden = false;
        $("modeToken").focus();
        return;
      }
      if (!s.live_ready) {
        openLiveModal(s.live_error || "Kalshi keys missing. Set KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH.", false);
        return;
      }
      if (s.dashboard_locked === false) {
        openLiveModal(s.live_error || "Set SCALPER_DASHBOARD_TOKEN before LIVE so anyone who can reach :8787 cannot arm real orders.", false);
        return;
      }
      openLiveModal("This spends real Kalshi cash with IOC limits at the touch. Flatten first if anything is open. Type LIVE to arm real-money mode (starts paused).", true);
    }
    async function confirmLive() {
      const typed = ($("modeConfirm").value || "").trim();
      const tok = ($("modeToken").value || "").trim() || dashToken();
      if (tok) {
        saveToken(tok);
        $("dashToken").value = tok;
      }
      const j = await act("mode", {mode: "LIVE", confirm: typed});
      if (j && j.ok) closeLiveModal();
      else $("modeModalMsg").textContent = (j && j.error) || "could not go live";
    }
    function handleAct(btn) {
      const a = btn.dataset.act;
      if (a === "clear") { ui.selected = null; if (ui.last) render(ui.last); return; }
      if (a === "mute") {
        const card = ((ui.last && ui.last.cards) || []).find(c => c.asset === btn.dataset.asset);
        act(card && card.muted ? "unmute" : "mute", btn.dataset.asset);
        return;
      }
      act(a, btn.dataset.asset);
    }
    function selectAsset(asset) {
      if (!asset) return;
      ui.selected = ui.selected === asset ? null : asset;
      if (ui.last) render(ui.last);
    }
    function render(s) {
      ui.last = s;
      $("mode").textContent = s.mode === "LIVE" ? "LIVE $" : "PAPER";
      $("mode").className = "pill " + (s.mode === "LIVE" ? "real" : "live");
      $("lock").textContent = s.dashboard_locked ? "LOCKED" : "OPEN";
      $("lock").className = "pill " + (s.dashboard_locked ? "warn" : "live");
      $("dashToken").hidden = !s.dashboard_locked;
      $("btnPaper").className = s.mode !== "LIVE" ? "yes on" : "";
      $("btnLive").className = s.mode === "LIVE" ? "danger on" : "danger";
      $("feed").textContent = s.ws_ok ? "WS" : "REST";
      $("armed").textContent = s.paused ? "PAUSED" : "ARMED";
      $("armed").className = "pill " + (s.paused ? "warn" : "live");
      const loose = !!s.temp_loose;
      $("loosePill").hidden = !loose;
      if (loose) {
        const base = s.temp_loose_baseline;
        const lim = s.temp_loose_loss != null ? s.temp_loose_loss : 1;
        $("loosePill").textContent = "LOOSE −$" + fmt(lim, 0);
        $("loosePill").className = "pill warn";
        $("loosePill").title = base != null
          ? `Auto-reverts after $${fmt(lim, 2)} equity drawdown from $${fmt(base, 2)}`
          : "Temporary loose entry gates";
      }
      $("btnPause").textContent = s.paused ? "RESUME" : "PAUSE";
      $("btnPause").className = s.paused ? "yes" : "warn";
      $("tuneSigma").textContent = fmt(s.min_spot_move_sigma != null ? s.min_spot_move_sigma : 0.55, 2);
      $("tuneEdge").textContent = fmt(s.min_net_edge != null ? s.min_net_edge : 0.04, 3);
      const fs = s.factory_sigma != null ? s.factory_sigma : 0.55;
      const fe = s.factory_edge != null ? s.factory_edge : 0.04;
      const drifted = Math.abs((s.min_spot_move_sigma || fs) - fs) > 1e-9
        || Math.abs((s.min_net_edge || fe) - fe) > 1e-9;
      $("btnTuneReset").className = drifted ? "warn" : "";
      $("eq").textContent = money(s.equity);
      $("cash").textContent = money(s.cash);
      const pnlCls = clsPnl(s.realized);
      $("pnlBox").className = pnlCls;
      $("pnlDir").textContent = pnlDir(s.realized);
      $("pnl").textContent = signedMoney(s.realized);
      $("fees").textContent = money(s.fees_paid);
      $("open").textContent = s.open;
      $("tick").textContent = s.tick;
      $("up").textContent = clock(s.uptime_s);
      const st = s.stats || {};
      $("wl").textContent = `${st.wins || 0}/${st.losses || 0}`;
      $("wl").className = (st.wins || 0) === (st.losses || 0) ? "flat" : (st.wins > st.losses ? "up" : "dn");
      const all = (s.cards || []).slice().sort((a,b) => a.asset.localeCompare(b.asset));
      $("markets").innerHTML = all.map(marketChip).join("");
      const cards = all.filter(showCard).sort(sortCards);
      $("cards").innerHTML = cards.map(card).join("") || `<div class="empty">no markets match this filter</div>`;
      const sel = all.find(c => c.asset === ui.selected);
      const d = $("detail");
      if (sel) { d.hidden = false; d.innerHTML = detailHTML(sel); }
      else { d.hidden = true; d.innerHTML = ""; }
      const tape = (s.log || []).filter(l => ui.tape === "all" || l.level === ui.tape).slice(0, 30);
      if (!logHidden()) {
        $("log").innerHTML = tape.map(l => {
          const t = new Date(l.ts * 1000).toISOString().slice(11,19);
          const asset = l.asset || "";
          return `<div class="${l.level||""}${asset ? " click" : ""}" data-pick="${asset}">${t}  ${l.msg}</div>`;
        }).join("");
      }
      $("fills").innerHTML = (s.trades || []).slice(0, 20).map(t =>
        `<tr class="click${ui.selected===t.asset?" sel":""}" data-pick="${t.asset}">
          <td>${t.asset}</td><td>${t.side}</td><td>${fmt(t.qty,0)}</td>
          <td>${fmt(t.entry,2)}</td><td>${fmt(t.exit,2)}</td>
          <td>${fmt(t.hold_s,0)}s</td>
          <td class="${clsPnl(t.pnl)}">${signedMoney(t.pnl)}</td>
          <td>${t.reason_out || ""}</td>
        </tr>`
      ).join("") || `<tr><td colspan="8" class="flat">no fills yet</td></tr>`;
      if (!ui.rulesEditing) renderRulesList(loadRules(s));
    }
    async function tick() {
      try {
        const r = await fetch("/api/state", {cache:"no-store", headers: tokenHeaders()});
        const s = await r.json();
        if (r.status === 401) {
          $("feed").textContent = "TOKEN";
          $("lock").textContent = "LOCKED";
          $("lock").className = "pill warn";
          $("dashToken").hidden = false;
          return;
        }
        render(s);
      } catch (e) {
        $("feed").textContent = "OFFLINE";
      }
    }
    $("markets").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      if (btn && $("markets").contains(btn)) { handleAct(btn); return; }
      const chip = e.target.closest(".mkt");
      if (chip && chip.querySelector("[data-asset]")) selectAsset(chip.querySelector("[data-asset]").dataset.asset);
    });
    $("cards").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      if (btn && $("cards").contains(btn)) { handleAct(btn); return; }
      const art = e.target.closest("article.card");
      if (art) selectAsset(art.dataset.asset);
    });
    $("detail").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      if (btn && $("detail").contains(btn)) handleAct(btn);
    });
    $("log").addEventListener("click", (e) => {
      const el = e.target.closest("[data-pick]");
      if (el) selectAsset(el.dataset.pick);
    });
    $("fills").addEventListener("click", (e) => {
      const el = e.target.closest("[data-pick]");
      if (el) selectAsset(el.dataset.pick);
    });
    $("btnPause").addEventListener("click", () => {
      const paused = !!(ui.last && ui.last.paused);
      act(paused ? "resume" : "pause");
    });
    $("btnAllOn").addEventListener("click", () => act("unmute_all"));
    $("btnAllOff").addEventListener("click", () => act("mute_all"));
    $("tuneBar").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tune]");
      if (!btn) return;
      act("tune", {field: btn.dataset.tune, dir: Number(btn.dataset.dir)});
    });
    $("btnTuneReset").addEventListener("click", () => act("tune", {field: "reset"}));
    $("btnPaper").addEventListener("click", () => {
      if (ui.last && ui.last.mode === "PAPER") return;
      act("mode", {mode: "PAPER"});
    });
    $("btnLive").addEventListener("click", requestLive);
    $("modeCancel").addEventListener("click", closeLiveModal);
    $("dashToken").value = sessionStorage.getItem(TOKEN_KEY) || "";
    $("dashToken").addEventListener("change", () => { saveToken($("dashToken").value); tick(); });
    $("dashToken").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { saveToken($("dashToken").value); tick(); }
    });
    $("modeGo").addEventListener("click", confirmLive);
    $("modeConfirm").addEventListener("keydown", (e) => {
      if (e.key === "Enter") confirmLive();
      if (e.key === "Escape") closeLiveModal();
    });
    $("modeModal").addEventListener("click", (e) => {
      if (e.target === $("modeModal")) closeLiveModal();
    });
    document.querySelectorAll("[data-filter]").forEach(btn => {
      btn.addEventListener("click", () => {
        ui.filter = btn.dataset.filter;
        document.querySelectorAll("[data-filter]").forEach(b => b.classList.toggle("active", b === btn));
        if (ui.last) render(ui.last);
      });
    });
    document.querySelectorAll("[data-sort]").forEach(btn => {
      btn.addEventListener("click", () => {
        ui.sort = btn.dataset.sort;
        document.querySelectorAll("[data-sort]").forEach(b => b.classList.toggle("active", b === btn));
        if (ui.last) render(ui.last);
      });
    });
    document.querySelectorAll("[data-tape]").forEach(btn => {
      btn.addEventListener("click", () => {
        ui.tape = btn.dataset.tape;
        document.querySelectorAll("[data-tape]").forEach(b => b.classList.toggle("active", b === btn));
        if (ui.last) render(ui.last);
      });
    });
    $("btnLogToggle").addEventListener("click", () => setLogHidden(!logHidden()));
    $("btnRulesEdit").addEventListener("click", () => setRulesEditMode(true));
    $("btnRulesCancel").addEventListener("click", () => setRulesEditMode(false));
    $("btnRulesSave").addEventListener("click", () => {
      const bullets = ($("rulesEdit").value || "").split("\n").map(x => x.trim()).filter(Boolean);
      saveRules(bullets.length ? bullets : defaultRules(ui.last || {}));
      setRulesEditMode(false);
      renderRulesList(loadRules(ui.last || {}));
    });
    $("btnRulesReset").addEventListener("click", () => {
      localStorage.removeItem(RULES_KEY);
      setRulesEditMode(false);
      renderRulesList(defaultRules(ui.last || {}));
    });
    applyLogHidden();
    document.addEventListener("keydown", (e) => {
      if (e.target && ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
      const cards = (ui.last && ui.last.cards) || [];
      if (e.key >= "1" && e.key <= "7") {
        const c = cards[Number(e.key) - 1];
        if (c) { ui.selected = c.asset; render(ui.last); }
      } else if (e.key === "Escape") {
        if (!$("modeModal").hidden) { closeLiveModal(); return; }
        ui.selected = null; if (ui.last) render(ui.last);
      } else if (e.key === "p" || e.key === "P") {
        act(ui.last && ui.last.paused ? "resume" : "pause");
      } else if ((e.key === "m" || e.key === "M") && ui.selected) {
        const c = cards.find(x => x.asset === ui.selected);
        act(c && c.muted ? "unmute" : "mute", ui.selected);
      } else if ((e.key === "f" || e.key === "F") && ui.selected) {
        act("flatten", ui.selected);
      }
    });
    tick();
    setInterval(tick, 1000);
