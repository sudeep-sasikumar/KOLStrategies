# KOL Strategies

Studies the memecoin strategies that well-known traders (KOLs) describe. For each one it collects data
on every token the strategy would have shown, follows what happened next, and looks for patterns. The
results are on a dashboard with one tab per strategy.

**Telegram signals are off.** The bot only sends a start-up notice. Signals are built from patterns
the collected data shows: hundreds of settled hits per column. No rule is guessed in advance.

Strategies so far:

| Tab | Source | What is tested |
|---|---|---|
| Daumen - New Filters | [YouTube, 12 Nov 2026](https://www.youtube.com/watch?v=qONQbEUQx9Y) · [notes](docs/strategies/daumen-filters.md) | His Terminal (Padre) board filters for the New, Soon and Migrated columns |
| Daumen - Old Filters | [YouTube, 7 Oct 2026](https://www.youtube.com/watch?v=KBgcOGWEARY) · [notes](docs/strategies/daumen-old-filters.md) | His earlier filters. New requires a social. Soon allows up to 24 min and adds an insiders limit. Migrated has the same values as the new filters |

---

## 1. What it does

1. **Sees every new pump.fun token** the moment it is created, and every migration (PumpPortal websocket).
2. **Follows each token for 24 hours.** It reads market cap, volume and buys/sells from DexScreener: every 20 s
   for the first 25 minutes, then every minute above $20K, every 10 minutes above $7K, and at 1 h / 6 h / 24 h.
3. **Looks on-chain only when a column is interested.** If a token passes a column's cheap filters (age, market
   cap, volume), or reaches $10K early, it reads from the Solana RPC: holders, dev holding %, sniper holding %,
   transaction count and the fee estimate.
4. **Evaluates every strategy column on every update.** A token that passes all of a column's filters is a
   **hit**. Each hit records a snapshot of the token at that moment, then its peak and its market cap 5 m, 1 h,
   6 h and 24 h later. For tokens that never pass, the collector stores the closest they came: which filters
   failed.
5. **The dashboard turns this into answers.**
   - How often each column's hits went 2x / 5x / 10x, became runners or migrated.
   - **Runners caught vs missed.** A runner is a token whose market cap reaches $100K within 24 h. For each
     missed runner, the dashboard shows which filters it failed.
   - **Which filter costs runners.** It counts the tokens that failed only one filter: how many that filter
     removed, and how many of those became runners. This tests Daumen's stated goal: less noise, no missed runners.
   - **Winners vs the rest.** Median holders, dev %, snipers %, fees, volume and so on at the moment of the hit,
     plus results by trading session.

### How far to trust each filter

Terminal (Padre) computes some values its own way. The dashboard labels each filter:

- **exact**: read directly. Mayhem mode and the dev wallet come from the pump.fun creation event. Market cap and
  volume come from DexScreener. Holders and dev % are on-chain balances (pool and bonding-curve accounts excluded).
- **approx**: our reading of the definition.
  - **Snipers:** wallets other than the dev that bought in the creation slot or the next 2 slots (~1.2 s).
  - **Keywords:** name and symbol are matched against the readable phrases ("FREE ENTRY", "READ OR"). The
    censored or blurred parts in the videos can't be matched.
  - **Insiders (old filters):** wallets other than the dev that bought in the creation slot itself, i.e.
    bundled with the launch. Terminal's exact definition isn't public.
  - **At least one social (old filters):** an X, Telegram or website link in the token's metadata.
    - pump.fun now adds an automatic "coin community" link to most tokens: 25 of 30 sampled had one, but only
      10 of 30 had a real link.
    - That community link is recorded but not counted as a social, so the filter is stricter than
      "99% have one".
    - The dashboard compares winners on both.
- **estimate**: **Total fees (SOL)**. This is what traders paid to land their transactions: network fee,
  priority fee and Jito tips. Terminal uses it to separate real activity from cheap bot volume. It adds two parts:
  - the exact cost of every transaction in the first 3 slots;
  - the average cost of sampled later transactions × the rest of the transaction count.

  pump.fun's own 1.25% trading fee is **not** included; it is stored separately (`fees_trade_sol`). Padre
  doesn't publish its formula. Compare a few tokens with Terminal and we'll calibrate.

### Data sources (all free)

| Source | Used for | Limits |
|---|---|---|
| PumpPortal websocket | creations (name, symbol, dev, mayhem flag, bonding curve), migrations | free; per-token trade streams need a funded API key, so they are not used |
| DexScreener `/tokens/v1` | market cap, volume, buys/sells, socials | 300 req/min (we use ≤ 200) |
| Solana RPC | holders, dev %, snipers, transaction count, fees | public RPC ~4 req/s; set `SOLANA_RPC_URL` for a private one |
| Binance / Coinbase / Kraken | SOL/USD | |
| IPFS metadata (4everland, ipfs.io, Pinata gateways) | socials the creator linked; read for every new non-Mayhem token | |

pump.fun's own APIs are behind Cloudflare bot protection, so they are not used.

---

## 2. Deploying on the Hostinger VPS

The image is built by GitHub Actions on every push to `main` and published as
`ghcr.io/sudeep-sasikumar/kolstrategies:latest`. The VPS only pulls it.

1. In hPanel open the VPS, then **Docker Manager → Compose → Compose from URL**, and paste:
   ```
   https://raw.githubusercontent.com/sudeep-sasikumar/KOLStrategies/main/docker-compose.yaml
   ```
2. Name the project `kol-strategies`.
3. Add the environment variables:
   - `DASHBOARD_PASSWORD`: **required**. Pick a long one; without it the dashboard stays off.
   - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: optional, start-up notice only. The bot is send-only, so you
     can reuse the bot of another app.
   - `SOLANA_RPC_URL`: optional, see below.
4. Deploy. The dashboard is at **https://srv1479428.hstgr.cloud/kol/**, on the same hostname and certificate as
   the other apps, through the Traefik that is already running.

**Updating:** push to `main` and wait for the GitHub Action to finish, then press **Redeploy** in Docker Manager.
The database lives in the `kol_data` volume and survives redeploys. If `docker-compose.yaml` itself changes,
paste the new file into the project's compose editor, because Hostinger keeps its own copy.

**If the image can't be pulled** ("denied" / "unauthorized"), the GitHub package is private. On GitHub, open
your profile, then **Packages → kolstrategies → Package settings → Change visibility → Public**.

**If the on-chain audits fail** (the Overview tab shows RPC errors or "failed" audits), the public Solana RPC may
be rate-limiting the VPS. Create a free RPC key (e.g. Helius), set
`SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY` in Docker Manager, and redeploy.

## 3. Running on this PC

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m kol
```

Open http://localhost:8030. No password is needed on localhost. Data goes to `data\kol.sqlite`.
Tests: `.venv\Scripts\python.exe -m pytest -q`.

## 4. Adding a strategy

1. Put the source notes in `docs/strategies/`.
2. Describe its columns and filters in a new module under `kol/strategies/`, using `daumen.py` as the model:
   - a column's `stage` is `new`, `bonding` or `migrated`;
   - each filter names the token feature it reads and its operator;
   - mark a filter `audit=True` when it needs on-chain data.
3. Add it to `STRATEGIES` in `kol/strategies/__init__.py`.

The dashboard tab, hit tracking and missed-runner analysis come automatically. If a strategy needs a feature the
collector doesn't compute yet, add it to `features()` in `kol/strategies/base.py` and fill it in the collector.

## 5. Files

| Path | What |
|---|---|
| `kol/collector.py` | follows tokens, schedules look-ups, evaluates strategies, records hits/outcomes |
| `kol/sources/` | PumpPortal, DexScreener, Solana RPC, SOL price, metadata |
| `kol/strategies/` | strategy definitions (one file each) |
| `kol/analysis.py` | dashboard numbers (hit rates, recall, missed runners, filter impact, feature comparison) |
| `kol/web.py`, `kol/static/` | dashboard |
| `kol/telegram.py` | Telegram (start-up notice only; `SIGNALS_ENABLED = False`) |
| `kol/config.py` | environment settings and collector tuning |
