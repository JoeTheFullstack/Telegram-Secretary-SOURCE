# Telegram-Secretary (MVP slice: register a customer)

One flow end-to-end through all layers:
Telegram -> router -> session -> LLM extraction -> validation -> service -> repository -> SQLite (+ audit log).

No third-party dependencies (Python 3.8+ stdlib only).

## Try it without Telegram
    python -m app.cli --user 1 --owner --offline     # step-by-step questions, no LLM
    python -m app.cli --user 1 --owner               # uses config/config.json LLM
    python -m app.cli --user 2                       # a "customer": denied
Type a button number to press a button.

## Run tests
    python -m unittest discover -s tests -t .

## Run the real bot
1. Copy `config/config.example.json` to `config/config.json` and fill token, LLM key, owner Telegram id
   (send `/myid` to the bot to learn your id; if Telegram is blocked set `telegram_proxy`, e.g. `http://127.0.0.1:10809`).
2. `python -m app.main`

LLM: the example config uses local Ollama (`http://localhost:11434/v1`, any api_key, a model from `ollama list`).
Cloud APIs also work: change base_url / api_key / model.

The LLM only *suggests*. Budget, property type, region and the name next to the phone number are re-read from the
text by plain code (`app/domain/parsing.py`) and override the model, so a small local model cannot corrupt them.
If the LLM is down or times out, the bot still fills these fields from the text.

## Commands
- `/newcustomer` or `مشتری جدید ...` : register a customer (staff/manager/owner)
- `/cancel`, `/myid`, `/help`
- `/setrole <telegram_id> <staff|manager|customer>` : owner only

## Layers
adapters (Telegram, LLM) -> core (router, sessions, permissions, flow) -> services -> repositories -> infra (SQLite, migrations).
domain = data shapes + business rules. The LLM only suggests JSON; code validates and decides.
