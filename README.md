# itrola Ride — MVP Backend

Backend for **itrola Ride** (rider app) and **itrola Drive** (driver app),
part of the itrola true image "Software & Hardware Solutions" pillar.

FastAPI backend implementing:
- Phone + OTP auth (rider and driver)
- Driver onboarding + manual admin verification
- Vehicle registration
- Live driver location updates
- Trip request → nearest-driver matching (PostGIS) → lifecycle (matched → in_progress → completed)
- Fare estimation (placeholder flat-rate formula — replace with Google Distance Matrix for accuracy)

## Setup

1. **Start Postgres+PostGIS locally:**
   ```
   docker compose up -d
   ```

2. **Install dependencies:**
   ```
   python -m venv venv
   source venv/bin/activate   # On Windows Git Bash: source venv/Scripts/activate
   pip install -r requirements.txt
   ```

3. **Set environment variables** (or create a `.env` and load it):
   ```
   DATABASE_URL=postgresql://taxi_user:taxi_pass@localhost:5432/taxi_ghana
   JWT_SECRET=some-long-random-string
   ADMIN_API_KEY=some-other-long-random-string
   PAYSTACK_SECRET_KEY=sk_test_your_paystack_test_key
   ```

4. **Run the API:**
   ```
   uvicorn app.main:app --reload
   ```

5. Visit `http://localhost:8000/docs` for interactive Swagger UI — test every endpoint from there before building the mobile apps.

## Auth model (implemented and tested)

- **Riders/drivers**: phone + OTP → JWT bearer token (`Authorization: Bearer <token>`)
- **Admin actions** (currently just driver verification): static key via `X-Admin-Key` header, checked against `ADMIN_API_KEY` env var. Simple by design for MVP — a rotating key is enough until you build a real admin panel.
- **Ownership checks**: a driver can only update their own vehicle/location/availability; a rider can only request trips as themselves (rider_id comes from the JWT, never from client input); only the trip's rider or assigned driver can view or cancel it.

All of the above was smoke-tested: unauthorized requests correctly return 403, cross-account access attempts are blocked, and the full authorized flow (onboard → verify → location → available → request → match → start → complete) works end to end.

## Endpoint overview

| Endpoint | Purpose |
|---|---|
| `POST /auth/request-otp` | Send OTP to phone |
| `POST /auth/verify-otp` | Verify OTP, get JWT |
| `POST /drivers/onboard` | Driver signs up (status=pending) |
| `POST /drivers/{id}/vehicle` | Add vehicle to driver profile |
| `POST /drivers/{id}/verify` | Admin approves driver (build admin auth before production) |
| `POST /drivers/{id}/location` | Driver app pings live GPS location |
| `POST /drivers/{id}/availability` | Toggle online/offline |
| `POST /trips/request` | Rider requests trip, triggers matching |
| `POST /trips/{id}/start` | Driver starts trip |
| `POST /trips/{id}/complete` | Driver completes trip |
| `POST /trips/{id}/cancel` | Cancel trip |
| `GET /trips/{id}` | Poll trip status (or replace with WebSocket push) |

## Payments (MoMo via Paystack)

- `POST /trips/{trip_id}/pay` — rider (own trip only, must be `completed` status) submits their MoMo number + network (`mtn`, `vodafone`, `airteltigo`). Calls Paystack's mobile money charge API, which triggers an approval prompt on the rider's phone.
- `POST /webhooks/paystack` — Paystack calls this when the charge settles. Signature is verified via HMAC-SHA512 against `PAYSTACK_SECRET_KEY`; on `charge.success` the trip's `payment_status` flips to `paid`, on `charge.failed` to `failed`.
- Add `PAYSTACK_SECRET_KEY=sk_test_...` (or `sk_live_...`) to your env vars. Get this from your Paystack dashboard.
- In Paystack's dashboard, set your webhook URL to `https://<your-deployed-domain>/webhooks/paystack`.

**Testing status**: the full payment flow has now been tested end-to-end with real Paystack test-mode keys. A live trip was created (request → matched → start → complete), then `/trips/{trip_id}/pay` was called with a test MoMo number — Paystack returned `paystack_status: "success"` with a real transaction reference (`mdbz5g7thpwyobl`), confirming the outbound `/charge` call, auth headers, and response parsing all work correctly against the live API. `payment_status` correctly stays `pending` until the webhook fires (expected, since sandbox test mode has no real phone to approve the MoMo prompt on). Webhook signature verification and trip-status update logic were separately tested with simulated Paystack payloads — wrong signatures are correctly rejected (401), correct signatures correctly update the trip to `paid`.

## What's stubbed / needs real implementation before production

- **OTP delivery**: currently just prints to console. Wire up Hubtel SMS or Arkesel API in `app/core/security.py`.
- **OTP storage**: in-memory dict, resets on restart and won't work across multiple server instances — move to Redis.
- **Live location push to rider**: currently the rider app would need to poll `GET /trips/{id}` — swap for WebSocket or Firebase Realtime DB for smooth live tracking on the map.
- **Fare calc**: flat straight-line-distance formula — replace with Google Distance Matrix API for real road distance/ETA.
- **Admin system**: currently a single shared static key — fine for one person (you) managing verifications, but build a real admin user/role system before you have a team.
- **Paystack `/charge` call**: implemented and live-tested successfully with real test-mode keys (see Payments section above). Still needs: live webhook delivery testing (requires a public URL Paystack can actually reach, e.g. after Cloud Run deploy) to confirm the full pending → paid transition happens automatically outside of simulated payloads.

## Suggested next steps

1. Get this running locally, test the full flow in `/docs`: onboard driver → verify (with admin key) → set location → set available → rider requests trip → matched → start → complete → pay.
2. ~~Test the Paystack `/charge` call live~~ — done, verified working. Next: test live webhook delivery once deployed to a public URL.
3. Build the driver and rider app screens against these endpoints (React Native).
4. Deploy to Cloud Run (you've done this before with ChurnSpy — same pattern, root route is already included here to avoid the startup-probe 404 loop issue). Suggested Cloud Run service name: `itrola-ride-api`.
