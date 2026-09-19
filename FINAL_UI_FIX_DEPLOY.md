# FINAL UI FIX + HARDEN + DEPLOY — single combined prompt
**Give this whole file to your build agent as one message. Execute the phases in order, top to bottom. Do not skip ahead to a later phase until the current one's verification step passes. This supersedes any earlier partial prompts about the Chainlit UI — those only added `ui/chainlit_app.py` and left everything else missing, which is the actual bug.**

---

## PHASE 1 — Add every missing file + kill the default screen + lock theme + hide reasoning

Right now only `ui/chainlit_app.py` exists. Everything below was already generated in an earlier turn but never actually written to the repo — that gap, not a new bug, is why the UI shows stock Chainlit's oversized logo/"Readme" screen and a half-applied theme.

### 1. Add every missing file, unchanged from what was already generated:
- `.chainlit/config.toml`
- `public/style.css`
- `public/custom.js`
- `public/logo.svg`
- `public/empty_state.svg`
- `public/icons/package.svg`, `public/icons/shield-check.svg`, `public/icons/lock.svg`
- `ui/ui_helpers.py`

`chainlit_app.py` already imports from `ui.ui_helpers` — if the app has been running without crashing despite that file being absent, double-check it genuinely isn't there yet before assuming this step is done.

### 2. Kill the default oversized logo + "Readme" empty-state screen
- In `.chainlit/config.toml`, set `show_readme_as_default = false`.
- Replace/create `public/chainlit.md` with a single short branded welcome line — this is what shows instead, if anything does.
- Confirm `public/logo.svg` is picked up as the small header logo via `custom.js` (already wired), not also used as Chainlit's giant centered empty-state watermark. If it still appears oversized after step 1, add `public/logo.png` at a small fixed size (e.g. 64×64) — Chainlit auto-detects that filename for its own logo slot, separate from your custom header.

### 3. Lock to ONE theme for the demo
- In `config.toml`, keep only the `[UI.theme.dark]` block correctly filled in.
- Hide/disable the theme toggle button in `custom.js` (simple `display: none` on its selector) so nobody can switch into the half-broken light mode before it's been separately verified. One consistent theme is safer for a demo than two, one of which is currently broken.

### 4. Hide the internal reasoning trail from customers by default
- Wrap the entire "🧠 How Delegate resolved this" / Analyzer-Router-Executor-Reviewer step block in `chainlit_app.py` behind:
  ```python
  if os.getenv("SHOW_REASONING_TO_CUSTOMER", "false").lower() == "true":
  ```
- When off: customers see only the transient "checking your order…" message and the final humanized reply + policy footer — nothing else. No raw ticket IDs, no `audit_trail`, no tool names, no `json.dumps(...)` output.
- Staff-profile messages (escalation cards) are allowed to keep showing ticket IDs/reasons — that's internal by design, not a leak.
- Set `SHOW_REASONING_TO_CUSTOMER=true` only in your own demo environment's env vars — never in what you'd eventually call real production.

### Phase 1 verification — do this once before moving on
- Restart: `chainlit run ui/chainlit_app.py -w`, hard refresh the browser.
- Confirm: no giant faded logo, no "Readme" link, header bar visible and pinned, login screen themed consistently, composer background matches the rest of the page, customer chat shows only replies (no JSON) unless the flag is explicitly on.
- If any of these still fail, stop and report exactly what's still broken — do not proceed to Phase 2 on a partial fix.

---

## PHASE 2 — Production hardening (errors, secrets, logging)

- Wrap every `create_ticket`/`resolve_ticket`/`get_ticket` call in `api_client.py` with try/except → on failure, return a generic customer-safe message ("We're having trouble right now, please try again") — never let a raw exception/traceback reach the Chainlit frontend.
- Confirm no `print()`/`logger.info()` anywhere logs full customer PII (email, raw ticket text) at a level that ends up in a public log stream on Render's free-tier logs.
- Replace the hardcoded `demo123` password path with an explicit `DEMO_MODE=true` flag — when `false`, `auth_callback` should require real per-user credentials (or at minimum a per-customer random password from seed data), so "demo123 for everyone" isn't sitting in a real deployment by accident.
- Confirm `CHAINLIT_AUTH_SECRET` is a real generated secret in Render's env vars, not the fallback dev value in the code.
- Confirm `CORS_ORIGINS` on the backend includes only your real deployed frontend URL, nothing wildcard, before going live.

**Verification:** force an API failure (stop the backend temporarily) → confirm the customer sees a polite fallback message, not a stack trace.

---

## PHASE 3 — Final polish (small, high-impact only — skip if time-constrained)

- Add a light "Delegate is thinking…" loading state on the parent pipeline step itself (if this Chainlit version supports a step-level spinner) so the transient message can be dropped entirely.
- Confirm dark theme passes a basic contrast check on the header trust pill and status pills (browser devtools' accessibility contrast checker).
- Replace `public/logo.svg` placeholder with your real wordmark/logo if you have one, before any judge-facing deploy.

**Verification:** full click-through as both Customer and Staff, on a narrow mobile viewport.

If you're short on time, this entire phase is safe to skip — nothing here is load-bearing for the demo working correctly.

---

## PHASE 4 — Deploy (Render)

1. Commit all files from Phases 1–3 to your repo (`config.toml`, `public/*`, `ui/ui_helpers.py`, updated `chainlit_app.py`).
2. In Render dashboard, for both `delegate-api` and `delegate-ui` services: set every var from `.env.example`/your real `.env` with real values. Use an Environment Group for shared vars (`DATABASE_URL`, `GROQ_API_KEY`, `N8N_WEBHOOK_SECRET`) so they're not duplicated across services.
3. Set `SHOW_REASONING_TO_CUSTOMER=true` and `DEMO_MODE=true` only on this deployed instance — this is your demo config, not real production. Note this explicitly in `docs/deploy.md` so it's not mistaken for a production-ready default later.
4. Update the backend's `CORS_ORIGINS` to include the deployed Chainlit URL.
5. Redeploy, wait for both services to build, then run your connection-verification script (if one exists, e.g. `scripts/verify_connections.py`) pointed at the deployed backend URL.
6. Warm both URLs yourself (visit them once) 2–3 minutes before any live demo — Render's free tier cold-starts.
7. Do one full click-through on the **live** URL: customer login → refund message → reply (no reasoning leak) → staff login → approve an escalated ticket → confirm email fires via n8n for real.

---

## Report format

After each phase, report: what was done, the exact verification result (pass/fail with specifics), and anything that didn't match this spec. Do not mark a phase complete if its verification step didn't fully pass — flag it and move to fixing that specific gap before continuing.
