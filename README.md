# OCR API — Field-Capture Receipt OCR

Local-first receipt OCR: a worker photographs a receipt on a phone, the pipeline
returns contract v1 JSON in seconds. `PLAN.md` holds the architecture,
`CONTRACT.md` the integrator contract, `PROJECT_BRIEF.md` the requirements.

## Tailscale — HTTPS on the tailnet

The app itself listens plain HTTP on `127.0.0.1:8090` (`APP_PORT`, see
`app/config.py`); TLS and its certificate are Tailscale's job. Start the stack
first (`python run.py`) — `tailscale serve` only proxies, it never launches the app.

```powershell
.\scripts\tailscale_serve.ps1              # enable HTTPS for the app port
.\scripts\tailscale_serve.ps1 -Status      # what tailscale serves right now
.\scripts\tailscale_serve.ps1 -Rollback    # take HTTPS back down
```

| | |
| --- | --- |
| Port | `8090` — the app port (`-AppPort` to override, `-HttpsPort` for the tailnet-side port, default `443`) |
| Cert path | `data\certs\` — the certificate and key the script exports with `tailscale cert`; `data/` is gitignored and the key is a secret, so never commit it |
| Rollback | `tailscale serve --https=443 off` (what `-Rollback` runs); the files under `data\certs\` stay on disk — deleting them is the operator's call |

Tailscale issues and renews the certificate for this machine's own
`<host>.<tailnet>.ts.net` name, so `run.py` needs no TLS flags and uvicorn keeps
listening on loopback.

### No public internet (v1 rule)

The tailnet is the only ingress (`PROJECT_BRIEF.md` §8): no public-internet
exposure in v1. Concretely — never run `tailscale funnel`, never forward a port on
the router, never point public DNS at this host. `funnel` is the one command that
would publish receipt images (personal data: names, card last-4) and the API to the
whole internet, which is why the script uses `serve` and never `funnel`. If
integrators or workers ever turn out to be external, a public HTTPS front-end is a
separate product decision — TLS, hardening and data policy included.

### Enrolling a worker's phone

1. Install Tailscale on the phone (App Store / Google Play) and sign in with the
   account that owns this tailnet.
2. Approve the new device in the Tailscale admin console if the tailnet requires
   device approval; the phone then appears next to the server in the machine list.
3. Keep the phone's Tailscale connected — on mobile data as well as Wi-Fi, the
   tunnel is the only route to the app.
4. Open `https://<tailnet-host>.ts.net/app` in the phone browser. A certificate
   error means HTTPS is not up yet: run `.\scripts\tailscale_serve.ps1 -Status`.
5. "Add to Home Screen" installs it as an app; the worker pastes their own API key
   (admin → Anahtarlar, one key per worker) once. Keys are shown a single time.
6. Revoke the key in the admin UI the day a phone is lost or a worker leaves —
   further calls answer 401 and the PWA shows its key-error state.
