# CP Ticket Bot - Setup and Usage

`cp_ticket_bot.py` uses in-file config only. `.env` file and `CP_*` variables are not used.

## 1. Required files

Keep these files in same folder:

- `cp_ticket_bot.py`
- `CP-Login.json`
- `CP-ticket.json`

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
- If flow fails (including no seats), bot retries every `retry_interval_seconds` until success.

## 4. Install

> `venv` below means Python virtual environment (dependency isolation), not `.env` config file.

### Raspberry Pi (Raspberry Pi OS / Debian-based Linux)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

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
