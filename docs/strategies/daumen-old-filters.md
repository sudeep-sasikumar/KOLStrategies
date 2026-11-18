# Strategy: Daumen Old Filters

- **Source:** "2026 Memecoin Trading Tutorial (New Updates!)", https://www.youtube.com/watch?v=KBgcOGWEARY (channel: Daumen, published 7 Oct 2026, length 23:17)
- **Platform used in video:** Terminal (trade.padre.gg, linked in the video description). Solana memecoins.
- **Board layout:** three columns, each with its own filter set: **New**, **Soon**, **Migrated**.
- **Scope:** The video gives column filters, a tracked-wallet setup, and discretionary rules for judging tokens and entries. It gives no exit, take-profit, stop-loss or position-sizing rules.

Values below come from what he says and from the filter panel shown on screen. Where a value is visible on screen but not spoken, it is marked *(on screen)*.

---

## 1. Column filters

### Column 1: New

| Section | Filter | Value |
|---|---|---|
| Protocols | All protocols | **Selected** |
| Protocols | Mayhem mode | **Hide** |
| Audit | (none) | No audit filters *(on screen)* |
| $ Metrics | Market cap | **Max $30,000** (no minimum) |
| Socials | At least one social | **On** |
| Keywords | Exclude keywords | `FREE ENTRY, ███ FREE` *(on screen; part of the text is blurred in the video; not discussed)* |

**His reasons:**
- **Mayhem mode hidden:** he says it is "a tricky mode on Pump". The token buys and sells for you, so you are effectively PvPing the token, like an on-chain casino. There's no point buying these coins.
- **At least one social:** his personal preference. A social link includes web links or tweets. Without a single social link, it is very hard to understand what the token is about. He says 99% of tokens have at least one. This applies only to the New column.

### Column 2: Soon

| Section | Filter | Value |
|---|---|---|
| Protocols | Mayhem mode | **Hide** |
| Audit | Token age (mins) | **Max 24** |
| Audit | Insiders holdings | **Max 25%** |
| Audit | Dev holding | **Max 25%** |
| Audit | Snipers holdings | **Max 25%** |
| $ Metrics | Volume | **Min $4,000** |
| $ Metrics | Market cap | **Min $6,000** |
| $ Metrics | Total fees (SOL) | **Min 0.05** |
| Socials | (none) | No social filter |
| Keywords | Exclude keywords | *(empty, on screen)* |

**His reasons:**
- **Token age max 24 min:** to keep the middle column clean.
- **Insiders, dev and snipers max 25%:** he says this removes a few coins, not many.
- **Volume and market cap:** adjusted to current conditions. Some volume, and a market cap that isn't 3K or 4K, give a higher chance the coin is organic.
- **Total fees min 0.05 SOL:** trading on the coin has generated at least that much in fees. Poor bundles don't generate much in fees because the bundlers don't want to lose money. An organic token should have generated a minimum amount of fees. He sometimes changes it to 0.2 but is comfortable with 0.05.
- **No socials filter:** good gems sometimes appear here without socials. When tracked wallets buy one, he can ask them why, or click the X search button for information. If a coin reaches this column at around 30K with no socials, "sometimes it is something", so he pastes the contract address into X to check.

### Column 3: Migrated

| Section | Filter | Value |
|---|---|---|
| Protocols | Mayhem mode | **Hide** |
| Audit | Snipers holdings | **Max 25%** |
| $ Metrics | Market cap | **Min $6,000** |
| $ Metrics | Total fees (SOL) | **Min 6** |
| Socials | (none) | No social filter |
| Keywords | Exclude keywords | *(empty, on screen)* |

He says there are no other restrictions on this column.

---

## 2. Working the Soon column

- He says the Soon column is very important and is where he makes most of his money, because he likes tokens in this range. He says that if you trench low caps, the Migrated column will be the one you use least.
- After he researches a token in Soon and decides he doesn't like it, he hides it (the "Hide token" button, or press **H**). This keeps the column clean, so he can see at a glance whether the few remaining tokens are good and doesn't miss any.

---

## 3. Tracked wallets and tweets

- **Wallet tracker:** he imports his own wallet list (a Google Doc linked in the video description) into Terminal's tracked-wallet manager.
- **Minimum buy shown: $40.** This removes noise from people "pinging" charts with small buys.
- **Tweet plays:** he does not buy them and doesn't use Terminal's X tracker. When a viral tweet comes out, many versions of the token get deployed on different launchpads and pairings. You are unlikely to be first, so you end up buying on top of people who sell on you and rotate. (He keeps the J7 Twitter tracker open on a second screen.)

---

## 4. Token types and fee checks

### Launchpads
- **Pump.fun** and **Stonk** are the two main launchpads. Some launchpads use Pump's infrastructure and appear as Pump.

### Pump tokens paired with another token (for example, SpaceX stock)
- **Good:** the token shows the yellow **holder-rewards** icon with a percentage (for example 0.1% or 0.3%). This means holders receive the rewards.
- **Bad:** the token is paired but has no yellow holder-rewards icon. Only the dev receives the rewards.

### Pure memes on Pump (paired only with SOL)
- **Good:** the token shows the yellow holder-rewards icon, so holders receive the fees.
- **Bad:** no holder-rewards icon, so the dev keeps the fees. In his example of two identical coins, the one without the icon was "bad because the dev himself is getting the fees". He says this holds 99% of the time, with rare exceptions.

### Fee-distribution tokens (green pie-chart icon)
- Fees go to a wallet or a GitHub account instead of to holders. This is acceptable when the launchpad's model needs the fees. Examples:
  - **Agency pad (AI agent / AI influencer launchpad, built on Pump):** fees fund the agent's content generation. No holder rewards are needed.
  - **Charity coins (pink heart icon):** fees go to the named charity.
  - **OTC (computer logo, built on Pump):** fees are used to buy the paired stocks and give them back to holders.

### Stonk tokens
- They are paired with a stock (for example SpaceX) and charge a tax on every transaction (for example 3%). Holders receive the tax as the paired stock.

---

## 5. Spotting bundles (do not buy)

- Use the **1-second** chart timeframe.
- **Main red flag:** the chart goes straight up to about 20K–30K with no tracked-wallet buys (no emojis from your own tracked wallets and no "K bubbles", which are Terminal's own tracked traders). He says "nothing goes like that" with no tracked wallets, so it is 100% a bundle and you will lose if you buy.
- **Holder red flags:** all wallets are fresh (green leaf icon), all come from the same trading bot, and the holders are snipers.
- **Less obvious bundles:** he points to signs that look more organic. These are a mix of trading platforms among the top wallets, some FOMO wallets that bought at different market caps (for example 7K and 3K), and varied position sizes (50 SOL, 50 SOL, 5 SOL). He still treats a token as a bundle if it went up with no tracked wallets, and would not buy it.
- **Fake support pattern:** a tracked dev launches and gets sniped up to 26K. The dev keeps selling into tracked-wallet buys, the bundlers pay for DEX ("Dex paid") to make it look legitimate, and the coin goes from 14K to 42K with no pings. He calls this run-up fake; the bundle sells and the coin dies.
- **Action on a rug:** blacklist the dev so their future tokens don't appear.

---

## 6. Entry rules

- **Early (first buyer, or very early such as around 7K market cap):** it's fine to take the risk if he likes the coin.
- **Higher (for example, buying at 20K):** he does not buy with "no confluence, no bids before". He assumes someone faster has already seen the coin, and if they didn't buy, it usually isn't good. When he buys higher, he wants some confluence.
- **Up-only charts without information:** he wouldn't buy. When a strong tracked trader buys such a coin, he calls it a very risky gamble that he does not recommend for a normal trader.

---

## 7. Wallets

- Use **one wallet** until you know what you're doing. More wallets means more you can lose.
- Start with trading, not deving. Trading teaches you whether a coin is good. With deving you also lose on fees.
