# Mafia Telegram Bot (MVP)

Python MVP for managing a Mafia game in Telegram groups.

## Features (MVP)

- Lobby flow: `/run` then `/play`
- Start game and assign roles privately: `/startgame`
- Phases: `NIGHT -> DAY_DISCUSSION -> DAY_VOTE`
- Night private actions: `/kill @user`, `/save @user`, `/check @user`
- Group vote: `/vote @user`
- Win conditions for mafia/citizens

## Setup

1. Create bot with [@BotFather](https://t.me/BotFather)
2. Copy `.env.example` to `.env` and set `BOT_TOKEN`
3. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Run:

```bash
python -m bot.main
```

## Commands

- `/start` - bot intro
- `/help` - help
- `/run` - create game lobby, or advance phase
- `/play` - join game
- `/players` - list players
- `/startgame` - host starts game
- `/status` - game status
- `/vote @username` - vote during vote phase
- `/endgame` - host ends game

### Notes

- Every player should send `/start` to bot in private chat before `/startgame`
- This version stores state in memory (no database yet)
