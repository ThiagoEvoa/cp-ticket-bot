# CP Ticket Bot - Setup and Usage

`cp_ticket_bot.py` uses in-file config only. `.env` file and `CP_*` variables are not used.

## 1. Required files

Keep these files in same folder:

- `cp_ticket_bot.py`
- `login.json`
- `buy-ticket.json`
- `buy-ticket-fail.json`

## 2. Configure script

Open `cp_ticket_bot.py` and edit `SCRIPT_SETTINGS`.

```python
SCRIPT_SETTINGS = {
    "email": "you@example.com",
    "password": "your-password",
    "from_station": "Lisboa Santa Apolonia",
    "to_station": "Entroncamento",
    "travel_weekdays": "mon,tue",
    "departure_time": "17:30",
    "additional_info": "0000000000",
    "discount_name": "Rail Green Pass",
    "confirm_purchase": False,
    "headless": True,
    "log_steps": True,
    "use_saved_session": True,
    "session_state_path": ".cp_session_state.json",
    "ui_timeout_ms": 60000,
    "action_delay_ms": 120,
    "post_action_wait_ms": 250,
    "station_type_delay_ms": 75,
    "retry_interval_seconds": 10,
}
```

Settings details:

| Key | Type | Meaning |
|---|---|---|
| `email` | string | CP login email |
| `password` | string | CP login password |
| `from_station` | string | origin station |
| `to_station` | string | destination station |
| `travel_weekdays` | string or list | travel days (`mon,tue,...`) |
| `departure_time` | string | `HH:MM` 24h |
| `additional_info` | string | extra CP field value |
| `discount_name` | string | discount label to select |
| `confirm_purchase` | bool | `False` = stop before final confirm click |
| `headless` | bool | `True` = no browser UI |
| `log_steps` | bool | prints per-step logs |
| `use_saved_session` | bool | reuse saved auth session |
| `session_state_path` | string | session file path |
| `ui_timeout_ms` | int | Playwright timeout |
| `action_delay_ms` | int | delay between actions |
| `post_action_wait_ms` | int | settle wait after actions |
| `station_type_delay_ms` | int | typing delay for station autocomplete |
| `retry_interval_seconds` | int | retry delay after failure |

## 3. Scheduling behavior

CP rule handled by bot:

- For each `travel_weekdays` + `departure_time`, first attempt starts **1 day before** at same hour.
- Example: travel Tuesday `17:30` -> first buy attempt Monday `17:30`.
- If `buy-ticket.json` reports no seats, bot runs `buy-ticket-fail.json` to return to results, then retries every `retry_interval_seconds` until success.

## 4. Install

> `venv` below means Python virtual environment (dependency isolation), not `.env` config file.

### Raspberry Pi (Raspberry Pi OS / Debian-based Linux)

Run install steps once, from project directory:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

To start bot automatically after every reboot, create a systemd service. Replace `/home/pi/cp-ticket-bot` with project’s absolute path and `pi` with your Linux username:

```bash
sudo tee /etc/systemd/system/cp-ticket-bot.service >/dev/null <<'EOF'
[Unit]
Description=CP Ticket Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/cp-ticket-bot
ExecStart=/home/pi/cp-ticket-bot/.venv/bin/python /home/pi/cp-ticket-bot/cp_ticket_bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now cp-ticket-bot
```

Check status/logs and manage service:

```bash
sudo systemctl status cp-ticket-bot
sudo journalctl -u cp-ticket-bot -f
sudo systemctl restart cp-ticket-bot
sudo systemctl disable --now cp-ticket-bot
```

Keep credentials secure: `cp_ticket_bot.py` contains login details. Restrict access to project files (`chmod 700 /home/pi/cp-ticket-bot`; `chmod 600 /home/pi/cp-ticket-bot/cp_ticket_bot.py`).

### macOS

If needed, install Python 3 first:

```bash
brew install python
```

Then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

## 5. Run

```bash
python cp_ticket_bot.py
```

## 6. Safe first run

For dry-run, keep:

```python
"confirm_purchase": False
```

Flow will stop before final payment confirmation click.
