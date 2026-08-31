const TOKEN_KEY = "scalper_dash_token";
const $ = (id) => document.getElementById(id);

function readStoredToken() {
  try {
    const local = (localStorage.getItem(TOKEN_KEY) || "").trim();
    if (local) return local;
  } catch (_) {}
  try {
    return (sessionStorage.getItem(TOKEN_KEY) || "").trim();
  } catch (_) {
    return "";
  }
}
function saveToken(value) {
  const t = (value || "").trim();
  if (!t) return;
  try { localStorage.setItem(TOKEN_KEY, t); } catch (_) {}
  try { sessionStorage.setItem(TOKEN_KEY, t); } catch (_) {}
}
function captureUrlToken() {
  try {
    const u = new URL(window.location.href);
    const t = (u.searchParams.get("token") || "").trim();
    if (!t) return;
    saveToken(t);
    u.searchParams.delete("token");
    const qs = u.searchParams.toString();
    history.replaceState({}, "", u.pathname + (qs ? "?" + qs : "") + u.hash);
  } catch (_) {}
}
function tokenHeaders() {
  const h = {};
  const t = (($("unlockToken") && $("unlockToken").value) || readStoredToken()).trim();
  if (t) h["X-Scalper-Token"] = t;
  return h;
}
function money(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const x = Number(n);
  return (x < 0 ? "-" : "") + "$" + Math.abs(x).toFixed(2);
}
function signedMoney(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const x = Number(n);
  if (Math.abs(x) < 0.0001) return "$0.00";
  return (x > 0 ? "+" : "-") + "$" + Math.abs(x).toFixed(2);
}
function showUnlock(msg) {
  $("unlockGate").hidden = false;
  if (msg) $("unlockMsg").textContent = msg;
}
function hideUnlock() {
  $("unlockGate").hidden = true;
}
function deskSrc() {
  const host = location.hostname || "127.0.0.1";
  const proto = location.protocol === "https:" ? "https:" : "http:";
  return proto + "//" + host + ":8000/";
}
let startTried = false;
function render(c) {
  if (!c || !c.present) {
    $("campaignMeta").textContent = (c && c.error) || "Campaign file not on this Pi yet.";
    $("campaignStats").innerHTML = "";
    $("campaignLog").textContent = "";
  } else {
    const halted = c.halted ? "HALTED · " : "";
    $("campaignMeta").textContent = halted + "book " + money(c.bankroll) + " · realized " + signedMoney(c.realized);
    $("campaignStats").innerHTML =
      `<div>OPEN <b>${(c.open_tickets || []).length}</b></div>` +
      `<div>RESTS <b>${(c.rests || []).length}</b></div>` +
      `<div>MAKER <b>${c.maker_auto ? "ON" : "OFF"}</b></div>`;
    $("campaignLog").innerHTML = (c.log || []).slice(0, 8).map((x) => {
      const msg = typeof x === "string" ? x : (x && (x.msg || x.message)) || JSON.stringify(x);
      return `<div>${String(msg).replace(/</g, "&lt;")}</div>`;
    }).join("");
  }
  const up = !!(c && c.desk_up);
  const iframe = $("desk");
  const hint = $("deskHint");
  const status = $("statusLine");
  const startBtn = $("btnStart");
  if (startBtn) startBtn.hidden = !!up;
  if (up) {
    iframe.hidden = false;
    if (!iframe.src) iframe.src = deskSrc();
    hint.textContent = "KALSHI15 desk is up. This is not SCALPER.";
    status.textContent = "KALSHI15 running. Campaign / post-only — not the IOC scalp.";
    status.className = "status";
  } else {
    iframe.hidden = true;
    iframe.removeAttribute("src");
    hint.textContent = (c && c.error) || "Desk is down. Tap Start KALSHI15, or on the Pi: python3 run_kalshi15.py";
    status.textContent = (c && c.error) || "KALSHI15 desk is not running yet.";
    status.className = "status down";
  }
}
async function startDesk() {
  const startBtn = $("btnStart");
  if (startBtn) {
    startBtn.disabled = true;
    startBtn.textContent = "Starting…";
  }
  $("statusLine").textContent = "Starting KALSHI15…";
  $("statusLine").className = "status";
  try {
    const headers = Object.assign({"Content-Type": "application/json"}, tokenHeaders());
    const r = await fetch("/api/kalshi15", {
      method: "POST",
      headers,
      body: JSON.stringify({op: "start"}),
    });
    if (r.status === 401) {
      showUnlock("Unlock first, then tap Start.");
      return;
    }
    const c = await r.json();
    render(c);
    if (!c.ok && c.error) {
      $("statusLine").textContent = c.error;
      $("statusLine").className = "status down";
    }
  } catch (_) {
    $("statusLine").textContent = "Could not start. On the Pi: python3 run_kalshi15.py";
    $("statusLine").className = "status down";
  } finally {
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.textContent = "Start KALSHI15";
    }
  }
}
async function tick() {
  try {
    const r = await fetch("/api/campaign", { cache: "no-store", headers: tokenHeaders() });
    if (r.status === 401) {
      showUnlock(readStoredToken()
        ? "Wrong token. That is not the Kalshi Key ID. Use SCALPER_DASHBOARD_TOKEN from the Pi .env."
        : "Unlock with the board password from the Pi .env — not the Kalshi Key ID.");
      return;
    }
    hideUnlock();
    const c = await r.json();
    render(c);
    if (!startTried && !c.desk_up) {
      startTried = true;
      startDesk();
    }
  } catch (_) {
    $("statusLine").textContent = "Phone cannot reach the board.";
    $("statusLine").className = "status down";
  }
}
function submitUnlock() {
  const t = (($("unlockToken") && $("unlockToken").value) || "").trim();
  if (t) saveToken(t);
  tick();
}
captureUrlToken();
if ($("btnUnlock")) $("btnUnlock").addEventListener("click", submitUnlock);
if ($("unlockToken")) {
  $("unlockToken").value = readStoredToken();
  $("unlockToken").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitUnlock();
  });
}
if ($("btnStart")) $("btnStart").addEventListener("click", startDesk);
if (!readStoredToken()) showUnlock();
tick();
setInterval(tick, 4000);
