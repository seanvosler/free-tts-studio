# Setting up a stable URL with Cloudflare

These steps turn your `trycloudflare.com` ephemeral URL into a stable
hostname like `voice.yourdomain.com`.

## Prerequisites

- A domain managed by Cloudflare (you've got one)
- `cloudflared` installed (`winget install --id Cloudflare.cloudflared`)
- A `config.yml` file (copy `tunnel-config.yml` from this folder and edit
  your domain)

## Step-by-step

### 1. Log in to Cloudflare

Open a terminal **as your normal user** (not admin) and run:

```
cloudflared tunnel login
```

A browser window opens. Pick the domain you want to use. After approval,
cloudflared writes a `cert.pem` file to `C:\Users\me\.cloudflared\`.

### 2. Create the named tunnel

```
cloudflared tunnel create tts-bridge
```

This creates `C:\Users\me\.cloudflared\tts-bridge.json` — a credentials
file that cloudflared uses to authenticate as this tunnel. **Treat this
file as a secret** (it grants access to your Cloudflare account for this
tunnel). It's already in `.gitignore`.

### 3. Write the config

Edit `tunnel-config.yml`, replace `voice.yourdomain.com` with your
subdomain, and save it to `C:\Users\me\.cloudflared\config.yml`:

```yaml
tunnel: tts-bridge
credentials-file: C:\Users\me\.cloudflared\tts-bridge.json

ingress:
  - hostname: voice.yourdomain.com      # <-- your real subdomain
    service: http://localhost:7861
    originRequest:
      noTLSVerify: true
  - service: http_status:404
```

Or use the helper:

```
powershell -ExecutionPolicy Bypass -File .\setup-tunnel.ps1
```

It will interactively walk you through steps 3–4.

### 4. Add the DNS route

```
cloudflared tunnel route dns tts-bridge voice.yourdomain.com
```

This creates a CNAME record in your Cloudflare DNS pointing
`voice.yourdomain.com` → `<tunnel-id>.cfargotunnel.com`. DNS propagation
usually takes <60s.

### 5. Run the tunnel

```
cloudflared tunnel run tts-bridge
```

Now `https://voice.yourdomain.com` resolves to your local bridge.

### 6. Hand it off to the orchestrator

`start-all.bat` (and `install-autostart.ps1`) already detect when a
named tunnel config exists and use it. Just make sure `%USERPROFILE%\
.cloudflared\tts-bridge.json` is in place — `start-all.bat` looks for
that file.

## Verifying

After step 5:

```
curl https://voice.yourdomain.com/healthz
```

should return `{"ok": true, "engine": "up"}`.

## Troubleshooting

| Symptom                                  | Likely cause                                       |
|------------------------------------------|----------------------------------------------------|
| `tunnel credentials not found`           | Step 2 didn't finish; re-run `tunnel create`.     |
| `connection refused` from cloudflared    | Bridge isn't running on 7861; check `start-all`. |
| 521 / 522 / 524 from Cloudflare         | DNS propagation; wait 1–2 min and retry.          |
| Quick-tunnel URL keeps changing          | You're still using `--url`, not the named tunnel. |
| `cannot find tunnel`                     | Wrong tunnel name; check `config.yml` matches.    |

## Removing the tunnel

```
cloudflared tunnel delete tts-bridge
cloudflared tunnel route dns delete tts-bridge voice.yourdomain.com
```
