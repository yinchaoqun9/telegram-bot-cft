# Pet Pantry — User Manual

**What this is:** a Telegram bot that helps you track pet food, litter, and meds. No spreadsheet required.

**How you talk to it**
- **Add new items** → send a **voice note** (this is the main way to log stock).
- **Open / used, fixes, commands** → voice **or** plain text both work.

**Languages**
- You may **speak or type** Chinese or English anytime — what you say is **saved as spoken** (brands, flavors, **and categories** like `lickable` / `猫条` stay in that language).
- **System replies** (menus, buttons, errors, digests) follow your personal setting: default **English**. Switch with `/language` (per person — household partners can each choose differently; this does **not** rewrite old inventory text).

---

## 1. Set up in Telegram

You only need the **Telegram** app (phone or desktop). No extra account for Pet Pantry.

### Step A — Install Telegram (if you don’t have it)

1. On your phone: install **Telegram** from the App Store (iPhone) or Google Play (Android).  
   On computer: download from [https://desktop.telegram.org](https://desktop.telegram.org) or use [https://web.telegram.org](https://web.telegram.org) in a browser.
2. Open Telegram and sign in with your phone number (usual Telegram login / SMS code).

### Step B — Find the Pet Pantry bot

1. In Telegram, tap the **search** icon (magnifying glass) at the top.
2. Type the bot username (exact spelling):

   ```text
   @cpg_tracker_bot
   ```

   Or open this link on a device with Telegram installed:

   [https://t.me/cpg_tracker_bot](https://t.me/cpg_tracker_bot)

3. Tap the bot in the results (it should show a **bot** badge, not a regular person).
4. Tap **Start** at the bottom  
   — or type `/start` and send it.

You should get a short welcome / help message. That means you’re connected.

> If search finds nothing: check the spelling, or ask whoever invited you for the latest bot link / `@username`.

### Step C — Turn on notifications (recommended)

1. Open the chat with the bot.
2. Tap the bot’s **name** at the top → open the profile / info screen.
3. Make sure **notifications** are not muted (no 🔕), so you get daily reminders and replies.

You do **not** need to “add as contact” or join a group. Use the bot in a **private 1:1 chat**.

### Step D — Send your first voice note

**On phone**

1. Open the chat with `@cpg_tracker_bot`.
2. Hold the **microphone** icon next to the message box (don’t just tap once — hold).
3. Speak, then release. The voice bubble should appear in the chat.
4. Wait a few seconds for the bot’s reply (Saved / confirmation).

**On Telegram Desktop / Web**

1. Click the **microphone** (or use the voice-message control if shown).  
   If you only see a paperclip / attach menu, look for **Record voice message**.
2. Speak, send, wait for the reply.

If the mic is missing: in phone settings, allow Telegram access to the **microphone**.

### Step E — Optional: web dashboard

1. In the bot chat, send `/dashboard` (or `/help` and tap the link).
2. Open this exact page (lowercase path):  
   `https://telegram-bot-cft-production.up.railway.app/dashboard`  
   (`/Dashboard` with a capital D will show Not Found.)
3. In the browser, click **Log in with Telegram** and approve.

You’ll see the same pantry as in the bot. Inventory is tied to your Telegram account.

---

## 2. Add items (voice)

Hold the mic and speak naturally. You don’t need a fixed script.

### English examples

> “Two cans of Fancy Feast chicken, best by June first 2026.”

> “Three bags of Orijen dog food.”

> “I got a big bag of cat litter.”

> “Half a bottle of Apoquel sixteen milligrams.”

### 中文例子

> “Fancy Feast 鸡肉两罐，保质期 2026 年 6 月 1 号。”

> “丸味冻干还剩三袋。”

> “买了猫砂一大袋。”

> “还有半瓶甲状腺药。”

### Tips

- Mention **brand**, **flavor/type**, **how many**, and **best-by date** when you know them. Skipping a field is fine.
- One voice note can include **several** products.
- Meds: say the drug name (and strength if you know it). The bot files them as medication.
- Brands can be Chinese or English (丸味, Ziwi, Royal Canin, …).

After saving, you’ll usually see buttons:

| Button | What it does |
|--------|----------------|
| **Fix** | Correct brand, quantity, or category |
| **Open −1** | You just opened a sealed unit |
| **Delete** | Remove that row |

---

## 3. Open vs Used (important)

Think of sealed packs on the shelf vs something already opened in the fridge.

| Action | Meaning |
|--------|---------|
| **Open** | You opened one sealed unit. Sealed count goes down by 1; the bot tracks that open portion. |
| **Used** | You finished / used something. If there’s an open portion, that gets cleared first (sealed count stays the same). If nothing is open, sealed count goes down by 1. |

You can have **more than one** open portion of the same product at once (e.g. two cans open).

### Say it by voice or text

**English**

- “Opened Ziwi beef”
- “Used the freeze dried”  
- “Finish 9 Lives tuna” / “finished the can” (same as Used)
- “Finished Tiki Cat”

**中文**

- “开了 Ziwi 牛肉”
- “用了冻干”
- “吃完了罐头”

If several items match, the bot asks you to pick one.

### Or use commands / buttons

- `/open <id>` — open that item  
- `/used <id>` — use / finish that item  
- Or tap **Open** / **Used** on the daily message or dashboard  

(`id` appears under items in digests, or use the buttons so you don’t need to copy it.)

---

## 4. See your pantry / “what today?”

**Browse everything (in Telegram):**

```text
/list
```

(or `/pantry`)

You’ll see up to **12** items (open portions first, then **soonest best-by**), each line showing the expiry date, with **Open** / **Used** buttons (date on the button too so same brand/flavor lots stay distinct). If you have more, use the web dashboard for the full list.

**Short suggestion for today:**

```text
/today
```

Up to **3** suggestions (open portions first, then soonest best-by). Tap Open or Used under each line.

The daily morning message:

- If something is **near expiry** → expiry list.  
- If nothing is near expiry → **today’s picks**.

---

## 5. Fix a mistake

After a save, tap **Fix**, then send one short line, for example:

- a **number** → changes quantity  
- a **category** (`罐头` / wet food / `冻干` / litter / meds …) → changes type  
- otherwise → treated as a **brand** correction  

Or:

```text
/fix <item_id>
```

then send the correction.

The bot remembers your brand corrections for next time.

---

## 6. Share the pantry with a partner

Free for **2 people**.

| Command | What it does |
|---------|----------------|
| `/household` | Create a shared pantry (or show your invite code) |
| `/join CODE` | Partner joins with your code |
| `/leave` | Leave the shared pantry |
| `/notify on` | Get a ping when the other person logs / opens / uses something |
| `/notify off` | Turn those pings off |

**Always on for both of you:** the daily expiry / today’s-picks message.  
**Optional:** live “partner just changed something” alerts (`/notify`).

---

## 7. Web dashboard

1. Open the dashboard link from `/help`.  
2. Log in with **Telegram Login**.  
3. You’ll only see **your** pantry (or the shared household pantry).

On the page you can:

- See what’s low or soon to expire / past open-shelf window  
- Tap **Open −1** or **Used**  
- Switch language with the **中文 / EN** toggle at the top  

Cans / soup pouches: the dashboard treats an **opened** portion as needing attention after about **3 days** (a soft reminder, not medical advice).

---

## 8. Quick command list

Type these in the bot chat (same commands on phone or desktop):

| Command | Purpose |
|---------|---------|
| `/start` or `/help` | How to use (+ dashboard link when the host has set one) |
| `/dashboard` | Get the web dashboard link |
| `/language` | Switch English / 中文 (saved for you only) |
| `/list` or `/pantry` | Show pantry (up to 12) with Open/Used buttons |
| `/today` | Suggest up to 3 things to use today |
| `/open <id>` | Mark opened |
| `/used <id>` | Mark used / finished |
| `/fix <id>` | Then send a correction (brand / number / category) |
| `/cancel` | Cancel an in-progress **Fix** |
| `/household` | Show invite code, or create a shared pantry |
| `/join CODE` | Join partner’s pantry |
| `/leave` | Leave shared pantry |
| `/notify on` / `/notify off` | Partner change alerts |

You can also say open/used in normal words (see §3) without a command.  
There is **no** “type a shopping list as plain text to add stock” — use a **voice note** to add items.

---

## 9. What Pet Pantry does *not* do

- It does **not** order or buy food for you.  
- It does **not** replace a vet for medication advice.  
- Expiry and “days after opening” are **reminders**, not guarantees.

---

## 10. Troubleshooting (simple)

| Problem | Try this |
|---------|----------|
| Bot didn’t understand the voice | Speak a bit slower; say brand + count + date; or type the same thing. |
| Wrong brand saved | Tap **Fix** and send the correct brand. |
| “Couldn’t match” on open/used | The bot still shows the **closest pantry items** with Open/Used buttons — tap the right one. Or use `/today` / the dashboard. |
| Partner doesn’t see updates | They need `/join` with your code; both should have messaged the bot at least once. |
| No daily message | Make sure you’ve talked to the bot before (so it knows your chat). Ask whoever runs the bot if the daily reminder job is on. |

---

## Example day

1. Morning: bot suggests three things → you tap **Open** on a can.  
2. Evening: you say **“Used Ziwi beef”** → that open portion is cleared.  
3. Weekend: you voice-log a Costco litter bag and two meds.  
4. Partner joins with `/join` and also gets the daily digest.

Welcome to Pet Pantry — less guessing what’s left in the cupboard.
