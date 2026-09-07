"""
Minimal admin review page — no separate frontend project, no build step.
Served directly by FastAPI as a single HTML+JS page. This exists purely to
replace manually calling /drivers/pending and /drivers/{id}/verify via
curl/Postman with something an admin can actually click through.

ASSUMPTION FLAGGED: this sends the admin credential as an `X-Admin-Key`
header on every request. I don't have app/core/deps.py, so I don't know
exactly how require_admin reads the credential (header name, query param,
or something else). If this doesn't authenticate, that's almost certainly
why — check deps.py and adjust ADMIN_HEADER_NAME below and the fetch calls
to match.

Not linked from anywhere in the app on purpose — reachable only by typing
the URL directly (http://<backend>:8001/admin). That's a thin line of
protection at best; the real gate is still the admin key itself. Don't
expose this on a public Cloud Run URL without also putting real auth
(e.g. HTTP Basic at a reverse proxy) in front of it.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["admin-ui"])

ADMIN_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>itrola Ride — Driver Review</title>
<style>
  body { font-family: -apple-system, Arial, sans-serif; background: #f7f3e8; margin: 0; padding: 24px; color: #1b1b1b; }
  h1 { color: #EC1E7D; font-size: 22px; }
  .key-bar { display: flex; gap: 8px; margin-bottom: 24px; }
  .key-bar input { flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 8px; font-size: 14px; }
  .key-bar button { padding: 10px 16px; border: none; border-radius: 8px; background: #00AEEF; color: white; font-weight: 600; cursor: pointer; }
  .card { background: white; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
  .card h3 { margin: 0 0 8px 0; }
  .field { font-size: 14px; color: #444; margin: 4px 0; }
  .field b { color: #111; }
  .photos { display: flex; gap: 12px; margin: 12px 0; }
  .photos img { width: 140px; height: 140px; object-fit: cover; border-radius: 8px; border: 1px solid #ddd; }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  .approve { background: #1b8a3a; color: white; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; }
  .reject { background: #c0392b; color: white; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; }
  .empty { color: #888; font-style: italic; }
  .error { color: #c0392b; font-weight: 600; }
</style>
</head>
<body>
  <h1>Pending Driver Applications</h1>
  <div class="key-bar">
    <input id="adminKey" type="password" placeholder="Admin key" />
    <button onclick="loadPending()">Load</button>
  </div>
  <div id="status"></div>
  <div id="list"></div>

<script>
const ADMIN_HEADER_NAME = 'X-Admin-Key'; // ASSUMPTION — confirm against deps.py

function getKey() {
  return document.getElementById('adminKey').value.trim();
}

async function loadPending() {
  const key = getKey();
  const status = document.getElementById('status');
  const list = document.getElementById('list');
  status.innerHTML = 'Loading…';
  list.innerHTML = '';
  try {
    const res = await fetch('/drivers/pending', {
      headers: { [ADMIN_HEADER_NAME]: key }
    });
    if (!res.ok) {
      status.innerHTML = `<span class="error">Request failed (${res.status}). Check the admin key, or the header name assumption noted in admin_ui.py.</span>`;
      return;
    }
    const drivers = await res.json();
    status.innerHTML = '';
    if (drivers.length === 0) {
      list.innerHTML = '<p class="empty">No pending applications.</p>';
      return;
    }
    list.innerHTML = drivers.map(renderCard).join('');
  } catch (err) {
    status.innerHTML = `<span class="error">${err.message}</span>`;
  }
}

function renderCard(d) {
  const vehicle = d.vehicle || {};
  return `
    <div class="card" id="card-${d.id}">
      <h3>${d.name || '(no name)'}</h3>
      <div class="field"><b>Phone:</b> ${d.phone}</div>
      <div class="field"><b>Ghana Card:</b> ${d.ghana_card_number || '—'}</div>
      <div class="field"><b>License:</b> ${d.license_number || '—'} (expires ${d.license_expiry ? d.license_expiry.slice(0,10) : '—'})</div>
      <div class="field"><b>Vehicle plate:</b> ${vehicle.plate_number || '—'}</div>
      <div class="photos">
        ${d.profile_photo_url ? `<img src="${d.profile_photo_url}" alt="Driver photo">` : ''}
        ${vehicle.photo_url ? `<img src="${vehicle.photo_url}" alt="Vehicle photo">` : ''}
      </div>
      <div class="actions">
        <button class="approve" onclick="act('${d.id}', 'verify')">Approve</button>
        <button class="reject" onclick="act('${d.id}', 'reject')">Reject</button>
      </div>
    </div>
  `;
}

async function act(driverId, action) {
  const key = getKey();
  try {
    const res = await fetch(`/drivers/${driverId}/${action}`, {
      method: 'POST',
      headers: { [ADMIN_HEADER_NAME]: key }
    });
    if (!res.ok) {
      alert(`Failed (${res.status}). Check the admin key.`);
      return;
    }
    document.getElementById(`card-${driverId}`).remove();
  } catch (err) {
    alert(err.message);
  }
}
</script>
</body>
</html>
"""


@router.get("/admin", response_class=HTMLResponse)
def admin_page():
    return ADMIN_PAGE_HTML
