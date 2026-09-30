# Freebuff Support Ticket — Country verification fails on clean ZA residential connection

**Subject:** "We could not verify a direct connection" — verified-clean South African residential fibre, no VPN/proxy/relay anywhere

**Account:** (your paid account email here)

## What happens
- Freebuff Desktop (v0.0.154, Windows) shows **"Limited Access — verify country"**.
- Clicking verify (in-app and on freebuff.com in a browser) returns:
  *"We could not verify a direct connection. Open this page on your own phone or computer, outside any cloud PC, VPN, proxy or iCloud Private Relay, using home internet or mobile data."*
- The message persists even though this IS a home fibre line, verified clean by six independent services.

## Evidence that this connection is a direct SA residential line
| Check | Result |
|---|---|
| Public IPv4 | `102.32.94.58` — Johannesburg/Centurion/Midrand, Gauteng, **ZA** |
| ASN | **AS327782 Metro Fibre Networx (Pty) Ltd** — ipinfo classifies type **`isp`** (residential ISP, not hosting) |
| ip-api.com | `proxy: false`, `hosting: false`, `mobile: false` |
| ipinfo privacy | `vpn: false`, `proxy: false`, `tor: false`, `relay: false` |
| Scamalytics | **Low Risk** |
| ipquery.io | `is_vpn: false`, `is_tor: false`, `is_proxy: false` |
| IPv6 | `2c0f:f528:44:1a19::/64` (Metrofibre) — also geolocates ZA (ipwho.is) |
| System proxies | WinINET off, WinHTTP direct, no PAC, no env vars |
| VPN state | No VPN connections configured; the only TAP adapter (Phantom V9, disconnected) is now **disabled** |
| OS locale | en-ZA, timezone Africa/Johannesburg |

## Observations that may help your engineers
1. **REGRESSION SIGNAL (strongest lead):** the "Limited Access / verify country" badge **did not display before a recent Desktop update** (now v0.0.154). Same machine, same line, same account — the gate appeared with an update. Worth checking what changed in the verifier between the previous build and 0.0.154.
2. **IPv4-only test — NOT the IPv6 path:** with IPv6 fully disabled at the adapter binding (zero global v6 addresses on the machine, outbound provably IPv4-only to your 200-OK edge), the verifier result is **unchanged**. The v6 hypothesis is eliminated; the failure is stack-independent.
3. **AFRINIC range handling:** `102.32.0.0/15` is a legitimate AFRINIC Metrofibre allocation; some verification vendors have thinner coverage for African ranges and default to "unverifiable".
4. The **verify-country button itself never completes** — on the desktop app AND on freebuff.com in a browser. So the region gate can never be satisfied even for the limited-tier region list. This looks like a checker-side failure, not a policy answer.

## Request
- Please either (a) fix the verifier for AF/uncommon regions, (b) publish the current full-access country list, or (c) advise a manual verification path for paid accounts in ZA.
- Paid subscription is active on this account; per your docs, paid plans unlock the full catalog regardless of region.

*Evidence gathered 2026-09-30 on Windows 10/11, Freebuff Desktop v0.0.154.*
