# Friend Forest 🌳

A cozy, private CRM for friendships. Every person you know becomes a pixel tree —
friends cluster into groves, close friendships grow tall, drifting ones ask for
water. Walk it like a farming game. Remember everyone, forever.

**Everything runs in your browser.** Your contacts and messages are parsed
locally, stored in your browser's localStorage, and never touch a server.

## Try it

Open `index.html` (or host the folder anywhere static — GitHub Pages works):

```bash
python3 -m http.server 8000
# then open http://localhost:8000
```

With no data planted yet you'll land in the onboarding; `forest.html` on its own
shows a demo forest with synthetic villagers.

## Growing your own forest

The onboarding (`onboard.html`) accepts any mix of:

| Source | How | What it adds |
|---|---|---|
| ✍️ By hand | type friends in one at a time | names, groups, cities, notes |
| 📇 Contacts CSV | Google Contacts / Apple Contacts export | names, jobs, birthdays |
| 💼 LinkedIn | `Connections.csv` from your data export | companies, positions |
| 💬 Messages (Mac) | `python3 helper/extract_messages.py` | who you actually talk to — message counts and dates only, never content |
| 🤖 Claude (optional) | paste **your own** Anthropic API key | short written profiles for your ~30 closest people |

Groups and companies become groves; message volume becomes tree size; long
silences turn trees autumn and mark them "needs watering."

The Claude step calls the Anthropic API directly from your browser with your
key — there is no middleman server. Skip it and everything still works.

## In the forest

- **Search** — one bar that both finds friends by name and answers questions
  like "who do I know in climbing?" or "who should I reach out to?"
- **Roam** — walk the forest as a farmer (WASD), water trees, talk to villagers
- **Filters** — group by circles, city, or hobbies; highlight friendship ties
- Click any tree for their profile and timeline; add their pixel person to
  stroll the forest

## Your data

- Lives in `localStorage` under the key `ff-data` (plus small UI prefs)
- Delete it any time: DevTools → Application → Local Storage, or
  `localStorage.removeItem("ff-data")`
- Re-run the onboarding whenever you like — forests love compost

## Repo layout

```
index.html                  routes to your forest or the onboarding
onboard.html                data import + optional Claude enrichment
forest.html                 the forest itself (demo data baked in)
helper/extract_messages.py  Mac iMessage summary helper (offline, counts only)
```

## License

MIT — see [LICENSE](LICENSE).
