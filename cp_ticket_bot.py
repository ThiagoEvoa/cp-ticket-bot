#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time as time_mod
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional

from playwright.sync_api import Error, Locator, Page, TimeoutError, sync_playwright


WEEKDAY_MAP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

WEEKDAY_NAME = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

# Fill these values directly in script.
# No env vars required when running via BotConfig.from_script_settings().
SCRIPT_SETTINGS = {
    "email": "example@mail.com",
    "password": "*********",
    "from_station": "Lisboa Oriente",
    "to_station": "Entroncamento",
    "travel_weekdays": "mon,tue",
    "departure_time": "17:39",
    "additional_info": "0000000000",
    "discount_name": "Rail Green Pass",
    "confirm_purchase": True,
    "headless": True,
    "log_steps": True,
    "use_saved_session": True,
    "session_state_path": ".cp_session_state.json",
    "ui_timeout_ms": 60000,
    "action_delay_ms": 120,
    "post_action_wait_ms": 250,
    "station_type_delay_ms": 75,
    "retry_interval_seconds": 10,
    "stop_retry_before_next_open_minutes": 10,
}


class ConfigError(ValueError):
    pass


class NoSeatsAvailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class BotConfig:
    email: str
    password: str
    from_station: str
    to_station: str
    travel_weekdays: set[int]
    departure_time: time
    additional_info: str
    discount_name: str
    confirm_purchase: bool
    headless: bool
    log_steps: bool
    use_saved_session: bool
    session_state_path: str
    ui_timeout_ms: int
    action_delay_ms: int
    post_action_wait_ms: int
    station_type_delay_ms: int
    retry_interval_seconds: int
    stop_retry_before_next_open_minutes: int

    @staticmethod
    def _parse_hhmm(name: str, raw: str) -> time:
        try:
            return datetime.strptime(raw.strip(), "%H:%M").time()
        except ValueError as exc:
            raise ConfigError(f"Invalid {name}. Expected HH:MM, got: {raw}") from exc

    @staticmethod
    def _parse_travel_weekdays(raw: str) -> set[int]:
        if not raw.strip():
            raise ConfigError("Missing required setting: travel_weekdays")
        result: set[int] = set()
        for chunk in raw.split(","):
            token = chunk.strip().lower()
            if token not in WEEKDAY_MAP:
                raise ConfigError(f"Invalid weekday in travel_weekdays: {chunk}")
            result.add(WEEKDAY_MAP[token])
        return result

    @staticmethod
    def _require_setting(settings: dict, name: str) -> str:
        value = settings.get(name)
        text = "" if value is None else str(value).strip()
        if not text:
            raise ConfigError(f"Missing required script setting: {name}")
        return text

    @staticmethod
    def _parse_bool_value(name: str, raw: object, default: bool) -> bool:
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        value = str(raw).strip().lower()
        if value in {"1", "true", "yes", "y", "on"}:
            return True
        if value in {"0", "false", "no", "n", "off"}:
            return False
        raise ConfigError(f"Invalid boolean for script setting '{name}': {raw}")

    @staticmethod
    def _parse_int_value(name: str, raw: object, default: int, minimum: int = 0) -> int:
        if raw is None or str(raw).strip() == "":
            return default
        try:
            value = int(str(raw).strip())
        except ValueError as exc:
            raise ConfigError(f"Invalid integer for script setting '{name}': {raw}") from exc
        if value < minimum:
            raise ConfigError(f"Script setting '{name}' must be >= {minimum}")
        return value

    @classmethod
    def _parse_weekdays_setting(cls, raw: object) -> set[int]:
        if isinstance(raw, (list, tuple, set)):
            value = ",".join(str(item) for item in raw)
        else:
            value = "" if raw is None else str(raw)
        if not value.strip():
            raise ConfigError("Missing required script setting: travel_weekdays")
        return cls._parse_travel_weekdays(value)

    @classmethod
    def from_script_settings(cls) -> "BotConfig":
        settings = SCRIPT_SETTINGS
        retry_seconds = cls._parse_int_value("retry_interval_seconds", settings.get("retry_interval_seconds"), 60, 1)

        return cls(
            email=cls._require_setting(settings, "email"),
            password=cls._require_setting(settings, "password"),
            from_station=cls._require_setting(settings, "from_station"),
            to_station=cls._require_setting(settings, "to_station"),
            travel_weekdays=cls._parse_weekdays_setting(settings.get("travel_weekdays")),
            departure_time=cls._parse_hhmm("departure_time", cls._require_setting(settings, "departure_time")),
            additional_info=cls._require_setting(settings, "additional_info"),
            discount_name=str(settings.get("discount_name", "Rail Green Pass")).strip() or "Rail Green Pass",
            confirm_purchase=cls._parse_bool_value("confirm_purchase", settings.get("confirm_purchase"), False),
            headless=cls._parse_bool_value("headless", settings.get("headless"), True),
            log_steps=cls._parse_bool_value("log_steps", settings.get("log_steps"), False),
            use_saved_session=cls._parse_bool_value("use_saved_session", settings.get("use_saved_session"), True),
            session_state_path=str(settings.get("session_state_path", ".cp_session_state.json")).strip()
            or ".cp_session_state.json",
            ui_timeout_ms=cls._parse_int_value("ui_timeout_ms", settings.get("ui_timeout_ms"), 60000, 5000),
            action_delay_ms=cls._parse_int_value("action_delay_ms", settings.get("action_delay_ms"), 0, 0),
            post_action_wait_ms=cls._parse_int_value(
                "post_action_wait_ms", settings.get("post_action_wait_ms"), 250, 0
            ),
            station_type_delay_ms=cls._parse_int_value(
                "station_type_delay_ms", settings.get("station_type_delay_ms"), 75, 0
            ),
            retry_interval_seconds=retry_seconds,
            stop_retry_before_next_open_minutes=cls._parse_int_value(
                "stop_retry_before_next_open_minutes", settings.get("stop_retry_before_next_open_minutes"), 10, 0
            ),
        )


@dataclass
class RuntimeState:
    last_station_field: Optional[str] = None  # "from" | "to"
    date_field_set: bool = False


@dataclass(frozen=True)
class ScheduleCandidate:
    travel_date: date
    travel_weekday: int
    opening_datetime: datetime

    @property
    def travel_date_str(self) -> str:
        return self.travel_date.strftime("%d/%m/%Y")


def flatten_selectors(selectors: Iterable[Iterable[str]]) -> str:
    return " ".join(item for chain in selectors for item in chain)


def now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def wait_for_settle(page: Page, cfg: BotConfig) -> None:
    if cfg.post_action_wait_ms > 0:
        page.wait_for_timeout(cfg.post_action_wait_ms)


def first_aria_label(selectors: list[list[str]]) -> Optional[str]:
    for chain in selectors:
        for item in chain:
            if not item.startswith("aria/"):
                continue
            label = item[5:]
            label = re.sub(r"\*\[.*$", "", label).strip()
            label = re.sub(r"\[role=.*$", "", label).strip()
            if label:
                return label
    return None


def infer_step_target_name(step: dict) -> str:
    step_type = step.get("type", "unknown")
    selectors = step.get("selectors", [])
    selectors_blob = flatten_selectors(selectors).lower()

    if step_type == "setViewport":
        return "Browser viewport"
    if step_type == "navigate":
        return f"Navigation to {step.get('url', '')}"
    if "#username" in selectors_blob or "aria/email" in selectors_blob:
        return "Email field"
    if "#password" in selectors_blob or "aria/password" in selectors_blob:
        return "Password field"
    if is_station_text_input(step, "from"):
        return "From station field"
    if is_station_text_input(step, "to"):
        return "To station field"
    if is_station_option_click(step):
        return "Station suggestion list"
    if is_date_click(step):
        return "Travel date field"
    if should_handle_departure_selection(step):
        return "Departure option"
    if is_terms_checkbox_click(step):
        return "Terms and privacy checkbox"
    if is_discount_trigger_click(step):
        return "Discount dropdown"
    if is_discount_option_click(step):
        return "Discount option"
    if "additional information" in selectors_blob or "informação adicional" in selectors_blob:
        return "Additional information field"
    if is_final_confirm_click(step):
        return "Final payment confirmation"

    label = first_aria_label(selectors)
    if label:
        return label
    return "Generic flow step"


def step_summary(step: dict) -> str:
    step_type = step.get("type", "unknown")
    target = infer_step_target_name(step)
    summary = f"type={step_type} target={target}"
    if step_type == "change":
        selectors_blob = flatten_selectors(step.get("selectors", [])).lower()
        if (
            "password" in selectors_blob
            or "email" in selectors_blob
            or "from *[role=\"textbox\"]" in selectors_blob
            or "to *[role=\"textbox\"]" in selectors_blob
            or "additional information" in selectors_blob
            or "informação adicional" in selectors_blob
        ):
            summary += " value=<from script settings>"
        else:
            summary += f" value={step.get('value', '')}"
    return summary


def convert_selector(selector: str) -> str:
    if selector.startswith("xpath//"):
        return f"xpath={selector[len('xpath'):]}"
    if selector.startswith("pierce/"):
        return selector[len("pierce/") :]
    return selector


def resolve_locator(page: Page, selectors: list[list[str]], timeout_ms: int = 30000) -> Locator:
    converted: list[str] = []
    for chain in selectors:
        if not chain:
            continue
        converted.append(convert_selector(chain[0]))

    last_error: Optional[Exception] = None
    for selector in converted:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except (TimeoutError, Error) as exc:
            last_error = exc

    raise RuntimeError(f"No visible locator found for selectors={converted}") from last_error


def normalize_text(raw: str) -> str:
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()


def tokenize_text(raw: str) -> set[str]:
    normalized = normalize_text(raw)
    return {token for token in normalized.split() if token}


def read_visible_station_options(page: Page) -> list[str]:
    values = page.evaluate(
        """() => {
            const nodes = [
              ...document.querySelectorAll('[id*="react-autowhatever"] [id*="item-"]'),
              ...document.querySelectorAll('[role="listbox"] [role="option"]'),
              ...document.querySelectorAll('[id*="react-autowhatever"] div'),
            ];
            const texts = [];
            for (const node of nodes) {
              const text = (node.textContent || '').replace(/\\s+/g, ' ').trim();
              if (text && text.length > 1) texts.push(text);
            }
            return [...new Set(texts)];
        }"""
    )
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return []


def choose_station_option(station_name: str, options: list[str]) -> Optional[str]:
    target_norm = normalize_text(station_name)
    target_tokens = tokenize_text(station_name)
    if not target_tokens:
        return None

    exact: list[str] = []
    strong: list[str] = []
    for option in options:
        option_norm = normalize_text(option)
        option_tokens = tokenize_text(option)
        if option_norm == target_norm:
            exact.append(option)
            continue
        if target_tokens.issubset(option_tokens):
            strong.append(option)

    if exact:
        return sorted(exact, key=len)[0]
    if strong:
        return sorted(strong, key=len)[0]
    return None


def station_query_variants(station_name: str) -> list[str]:
    raw = station_name.strip()
    variants: list[str] = [raw]
    cleaned = re.sub(r"\s*-\s*", " ", raw)
    if cleaned != raw:
        variants.append(cleaned)

    lowered = normalize_text(cleaned)
    if lowered.startswith("lisboa "):
        variants.append(cleaned.split(" ", 1)[1].strip())

    tokens = [token for token in cleaned.split() if len(token) >= 4]
    if tokens:
        variants.append(tokens[-1])
        if len(tokens) >= 2:
            variants.append(" ".join(tokens[-2:]))

    unique: list[str] = []
    seen: set[str] = set()
    for item in variants:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item.strip())
    return unique


def type_station_query(locator: Locator, query: str, typing_delay_ms: int) -> None:
    locator.click()
    locator.press("Control+A")
    locator.press("Backspace")
    locator.type(query, delay=typing_delay_ms)


def wait_station_options(page: Page, timeout_seconds: int = 16) -> list[str]:
    deadline = time_mod.time() + timeout_seconds
    latest: list[str] = []
    while time_mod.time() < deadline:
        options = read_visible_station_options(page)
        if options:
            return options
        latest = options
        time_mod.sleep(0.35)
    return latest


def select_station(
    page: Page,
    station_input: Locator,
    station_name: str,
    field_name: str,
    log_steps: bool,
    typing_delay_ms: int,
) -> None:
    last_options: list[str] = []
    tried_queries: list[str] = []

    for query in station_query_variants(station_name):
        tried_queries.append(query)
        type_station_query(station_input, query, typing_delay_ms=typing_delay_ms)
        options = wait_station_options(page, timeout_seconds=8)
        if options:
            last_options = options
            if log_steps:
                print(f"[{now_ts()}] {field_name} query='{query}' options: {', '.join(options)}")

            selected = choose_station_option(station_name, options) or choose_station_option(query, options)
            if selected is None and len(options) == 1:
                option_tokens = tokenize_text(options[0])
                query_tokens = tokenize_text(query)
                if query_tokens and query_tokens.issubset(option_tokens):
                    selected = options[0]

            if selected:
                candidates = [
                    page.get_by_role("option", name=re.compile(re.escape(selected), re.IGNORECASE)).first,
                    page.locator("[id*='react-autowhatever'] [id*='item-']", has_text=selected).first,
                    page.locator("[id*='react-autowhatever'] div", has_text=selected).first,
                ]
                option_locator = first_visible_locator(candidates, timeout_ms=2500)
                if option_locator is not None:
                    robust_click(page, option_locator)
                    return
        elif log_steps:
            print(f"[{now_ts()}] {field_name} query='{query}' produced no autocomplete options")

    if last_options:
        raise RuntimeError(
            f"Could not map '{station_name}' to visible {field_name} options: {', '.join(last_options)}. "
            f"Tried queries: {', '.join(tried_queries)}"
        )
    raise RuntimeError(
        f"No {field_name} autocomplete options appeared for '{station_name}'. Tried queries: {', '.join(tried_queries)}"
    )


def set_date_field(page: Page, date_ddmmyyyy: str) -> None:
    date_input = resolve_input_by_kind(page, "date", selectors=[], timeout_ms=12000)
    date_input.click()
    date_input.fill(date_ddmmyyyy)
    date_input.press("Enter")


def time_to_minutes(hhmm: str) -> int:
    parsed = datetime.strptime(hhmm.strip(), "%H:%M")
    return parsed.hour * 60 + parsed.minute


def time_token_to_minutes(token: str) -> Optional[int]:
    raw = token.strip().upper().replace(".", "")
    try:
        if raw.endswith("AM") or raw.endswith("PM"):
            normalized = raw if " " in raw else f"{raw[:-2]} {raw[-2:]}"
            parsed = datetime.strptime(normalized, "%I:%M %p")
            return parsed.hour * 60 + parsed.minute
        parsed = datetime.strptime(raw, "%H:%M")
        return parsed.hour * 60 + parsed.minute
    except ValueError:
        return None


def first_time_from_label(label: str) -> Optional[int]:
    # Prefer first time token in label (usually departure time).
    token_pattern = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[APap][Mm])?\b")
    for token in token_pattern.findall(label):
        minutes = time_token_to_minutes(token)
        if minutes is not None:
            return minutes
    return None


def to_12h_variants(hhmm: str) -> list[str]:
    parsed = datetime.strptime(hhmm.strip(), "%H:%M")
    v1 = parsed.strftime("%I:%M %p").lstrip("0")  # 5:30 PM
    v2 = parsed.strftime("%I:%M%p").lstrip("0")   # 5:30PM
    v3 = parsed.strftime("%H:%M")                 # 17:30
    return [v1, v2, v3]


def choose_departure_by_time(page: Page, desired_hhmm: str) -> None:
    target = time_to_minutes(desired_hhmm)
    start = time_mod.time()
    timeout_seconds = 90
    candidate_indexes: list[int] = []
    candidate_labels: list[str] = []

    while time_mod.time() - start < timeout_seconds:
        buttons = page.get_by_role("button")
        total = buttons.count()
        candidate_indexes.clear()
        candidate_labels.clear()
        for idx in range(total):
            button = buttons.nth(idx)
            aria = (button.get_attribute("aria-label") or "").strip()
            text = ""
            try:
                text = (button.inner_text(timeout=300) or "").strip()
            except Error:
                pass
            combined = f"{aria} {text}".strip()
            if first_time_from_label(combined) is not None:
                candidate_indexes.append(idx)
                candidate_labels.append(combined)
        if candidate_indexes:
            break
        time_mod.sleep(1)

    if not candidate_indexes:
        raise RuntimeError("No departure option buttons with time labels became visible.")

    # Strict: only exact requested time (or equivalent 12h representation).
    for global_idx, label in zip(candidate_indexes, candidate_labels):
        dep_minutes = first_time_from_label(label)
        if dep_minutes is not None and dep_minutes == target:
            robust_click(page, page.get_by_role("button").nth(global_idx))
            return

    for variant in to_12h_variants(desired_hhmm):
        pattern = re.compile(rf"\b{re.escape(variant)}\b", re.IGNORECASE)
        for global_idx, label in zip(candidate_indexes, candidate_labels):
            if pattern.search(label):
                robust_click(page, page.get_by_role("button").nth(global_idx))
                return

    raise RuntimeError(
        f"Requested departure '{desired_hhmm}' not found. Visible options: {', '.join(candidate_labels)}"
    )


def force_remove_onetrust_overlay(page: Page) -> None:
    page.evaluate(
        """() => {
            const selectors = [
              '#onetrust-consent-sdk',
              '#onetrust-pc-sdk',
              '#onetrust-banner-sdk',
              '.onetrust-pc-dark-filter',
            ];
            for (const selector of selectors) {
              document.querySelectorAll(selector).forEach((node) => node.remove());
            }
        }"""
    )


def dismiss_onetrust_if_present(page: Page) -> None:
    buttons = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Aceitar todos')",
        "button:has-text('Aceitar')",
        ".onetrust-close-btn-handler",
    ]
    for selector in buttons:
        button = page.locator(selector).first
        try:
            button.wait_for(state="visible", timeout=700)
            button.click(timeout=2000)
            break
        except (TimeoutError, Error):
            continue

    overlay = page.locator(".onetrust-pc-dark-filter").first
    try:
        overlay.wait_for(state="hidden", timeout=2000)
    except (TimeoutError, Error):
        force_remove_onetrust_overlay(page)


def robust_click(page: Page, locator: Locator) -> None:
    try:
        locator.click()
        return
    except Error as exc:
        message = str(exc).lower()
        if "intercepts pointer events" in message or "onetrust" in message:
            dismiss_onetrust_if_present(page)
            locator.click()
            return
        raise


def first_visible_locator(candidates: list[Locator], timeout_ms: int) -> Optional[Locator]:
    for locator in candidates:
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except (TimeoutError, Error):
            continue
    return None


def click_first_visible_match(page: Page, locator: Locator, timeout_ms: int = 4000) -> bool:
    deadline = time_mod.time() + (timeout_ms / 1000)
    while time_mod.time() < deadline:
        try:
            count = min(locator.count(), 40)
        except Error:
            count = 0
        for index in range(count):
            candidate = locator.nth(index)
            try:
                candidate.wait_for(state="visible", timeout=250)
                robust_click(page, candidate)
                return True
            except (TimeoutError, Error):
                continue
        time_mod.sleep(0.15)
    return False


def read_input_metadata(locator: Locator) -> Optional[dict]:
    try:
        return locator.evaluate(
            """(el) => {
                const labels = [];
                if (el.labels) {
                  for (const lb of Array.from(el.labels)) {
                    labels.push((lb.textContent || '').trim());
                  }
                }
                const nearestLabel = el.closest('label');
                if (nearestLabel) labels.push((nearestLabel.textContent || '').trim());
                const attrs = [
                  el.tagName || '',
                  el.id || '',
                  el.getAttribute('name') || '',
                  el.getAttribute('type') || '',
                  el.getAttribute('role') || '',
                  el.getAttribute('aria-label') || '',
                  el.getAttribute('placeholder') || '',
                  el.getAttribute('aria-autocomplete') || '',
                  el.getAttribute('autocomplete') || '',
                  el.getAttribute('list') || '',
                  el.className || '',
                ].join(' ').toLowerCase();
                const disabled = !!el.disabled;
                const readOnly = !!el.readOnly;
                const hidden = !!el.hidden || (el.getAttribute('aria-hidden') === 'true');
                return {
                  attrs,
                  disabled,
                  readOnly,
                  hidden,
                  type: (el.getAttribute('type') || '').toLowerCase(),
                  labels: labels.join(' ').toLowerCase(),
                };
            }"""
        )
    except Error:
        return None


def is_editable_text_input(metadata: dict) -> bool:
    attrs = str(metadata.get("attrs", ""))
    disabled = bool(metadata.get("disabled", False))
    read_only = bool(metadata.get("readOnly", False))
    hidden = bool(metadata.get("hidden", False))
    input_type = str(metadata.get("type", ""))

    if disabled or read_only or hidden:
        return False

    if "input" not in attrs and "textarea" not in attrs:
        return False

    if input_type in {"hidden", "checkbox", "radio", "button", "submit"}:
        return False

    return True


def metadata_tokens(metadata: dict) -> set[str]:
    blob = f"{metadata.get('attrs', '')} {metadata.get('labels', '')}"
    return tokenize_text(blob)


def metadata_matches_kind(metadata: dict, kind: str) -> bool:
    tokens = metadata_tokens(metadata)
    attrs = str(metadata.get("attrs", ""))
    input_type = str(metadata.get("type", ""))

    if kind == "email":
        return input_type == "email" or any(token in tokens for token in ("email", "username", "utilizador", "usuario"))

    if kind == "password":
        return input_type == "password" or "password" in tokens

    if kind == "date":
        return (
            input_type == "date"
            or any(token in tokens for token in ("date", "data", "ida", "departure"))
            or any(token in attrs for token in ("#ida", " ida ", "date", "calendar"))
        )

    if kind == "from_station":
        if any(token in tokens for token in ("date", "data", "ida", "volta", "password", "email", "discount", "desconto")):
            return False
        if any(token in tokens for token in ("from", "origin", "origem", "partida")):
            return True
        return " de " in f" {normalize_text(attrs)} "

    if kind == "to_station":
        if any(token in tokens for token in ("date", "data", "ida", "volta", "password", "email", "discount", "desconto")):
            return False
        return any(token in tokens for token in ("to", "destination", "destino", "chegada", "para"))

    if kind == "additional_info":
        if any(token in tokens for token in ("password", "email", "date", "data", "tax", "document", "numero", "número")):
            return False
        return any(token in tokens for token in ("additional", "information", "adicional", "informacao"))

    return False


def selector_locators(page: Page, selectors: list[list[str]]) -> list[Locator]:
    locators: list[Locator] = []
    for chain in selectors:
        if not chain:
            continue
        locators.append(page.locator(convert_selector(chain[0])))
    return locators


def resolve_input_by_kind(page: Page, kind: str, selectors: list[list[str]], timeout_ms: int = 12000) -> Locator:
    candidates = selector_locators(page, selectors)

    if kind == "email":
        candidates.extend(
            [
                page.locator("#username"),
                page.get_by_role("textbox", name=re.compile(r"(email|username|utilizador)", re.IGNORECASE)),
                page.locator("input[type='email'], input[name*='user' i], input[id*='user' i]"),
            ]
        )
    elif kind == "password":
        candidates.extend(
            [
                page.locator("#password"),
                page.locator("input[type='password']"),
                page.get_by_role("textbox", name=re.compile(r"password", re.IGNORECASE)),
            ]
        )
    elif kind == "from_station":
        candidates.extend(
            [
                page.get_by_role("textbox", name=re.compile(r"(from|origin|partida|\bde\b)", re.IGNORECASE)),
                page.locator(
                    "input[aria-label*='From' i], input[placeholder*='From' i], "
                    "input[aria-label*='Origin' i], input[placeholder*='Origin' i], "
                    "input[aria-label*='Partida' i], input[placeholder*='Partida' i], "
                    "input[aria-label='De'], input[placeholder='De']"
                ),
            ]
        )
    elif kind == "to_station":
        candidates.extend(
            [
                page.get_by_role("textbox", name=re.compile(r"(to|destination|chegada|para)", re.IGNORECASE)),
                page.locator(
                    "input[aria-label*='To' i], input[placeholder*='To' i], "
                    "input[aria-label*='Destination' i], input[placeholder*='Destination' i], "
                    "input[aria-label*='Chegada' i], input[placeholder*='Chegada' i], "
                    "input[aria-label='Para'], input[placeholder='Para']"
                ),
            ]
        )
    elif kind == "additional_info":
        candidates.extend(
            [
                page.locator(
                    "input[aria-label*='Additional information' i], "
                    "input[aria-label*='informacao adicional' i], "
                    "input[aria-label*='informação adicional' i], "
                    "input[placeholder*='Additional information' i], "
                    "input[placeholder*='informacao adicional' i], "
                    "input[placeholder*='informação adicional' i]"
                ),
                page.locator(
                    "xpath=(//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'additional information') "
                    "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'informacao adicional') "
                    "or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'informação adicional')]"
                    "/following::input[1])[1]"
                ),
            ]
        )
    elif kind == "date":
        candidates.extend(
            [
                page.locator("#ida"),
                page.get_by_role("textbox", name=re.compile(r"(date|data|ida|departure)", re.IGNORECASE)),
                page.locator("input[name*='date' i], input[id*='date' i], input[id*='ida' i]"),
            ]
        )

    deadline = time_mod.time() + (timeout_ms / 1000)
    while time_mod.time() < deadline:
        for group in candidates:
            try:
                count = min(group.count(), 16)
            except Error:
                count = 0
            for idx in range(count):
                locator = group.nth(idx)
                try:
                    locator.wait_for(state="visible", timeout=300)
                except (TimeoutError, Error):
                    continue
                metadata = read_input_metadata(locator)
                if not isinstance(metadata, dict):
                    continue
                if not is_editable_text_input(metadata):
                    continue
                if metadata_matches_kind(metadata, kind):
                    return locator
        time_mod.sleep(0.2)

    raise RuntimeError(f"Could not find validated input for kind '{kind}'.")


def resolve_editable_input_from_selectors(page: Page, selectors: list[list[str]], timeout_ms: int = 12000) -> Locator:
    candidates = selector_locators(page, selectors)
    deadline = time_mod.time() + (timeout_ms / 1000)
    while time_mod.time() < deadline:
        for group in candidates:
            try:
                count = min(group.count(), 16)
            except Error:
                count = 0
            for idx in range(count):
                locator = group.nth(idx)
                try:
                    locator.wait_for(state="visible", timeout=300)
                except (TimeoutError, Error):
                    continue
                metadata = read_input_metadata(locator)
                if not isinstance(metadata, dict):
                    continue
                if is_editable_text_input(metadata):
                    return locator
        time_mod.sleep(0.2)
    raise RuntimeError("Could not find editable input from provided selectors.")


def is_station_input_candidate(page: Page, locator: Locator, direction: str) -> bool:
    kind = "from_station" if direction == "from" else "to_station"
    metadata = read_input_metadata(locator)
    if not isinstance(metadata, dict):
        return False
    return is_editable_text_input(metadata) and metadata_matches_kind(metadata, kind)


def selector_station_hints(selectors: list[list[str]]) -> set[str]:
    hints: set[str] = set()
    joined = flatten_selectors(selectors).lower()
    for match in re.findall(r"r\d+", joined):
        hints.add(match)
    if ":r3:" in joined or "r3" in joined:
        hints.add("from")
    if ":r4:" in joined or "r4" in joined:
        hints.add("to")
    return hints


def is_plausible_station_fallback(metadata: dict, kind: str, selectors: list[list[str]]) -> bool:
    if not is_editable_text_input(metadata):
        return False
    tokens = metadata_tokens(metadata)
    attrs = str(metadata.get("attrs", ""))
    input_type = str(metadata.get("type", ""))
    blocked_tokens = {
        "date",
        "data",
        "ida",
        "volta",
        "password",
        "email",
        "discount",
        "desconto",
        "document",
        "tax",
        "nif",
    }
    if any(token in tokens for token in blocked_tokens):
        return False

    # If it already matches semantic kind, accept.
    if metadata_matches_kind(metadata, kind):
        return True

    # Prefer controls that look like autocomplete/search textboxes.
    has_autocomplete_signal = any(
        marker in attrs for marker in ("aria-autocomplete", "autocomplete", "react-autowhatever", "listbox")
    ) or input_type in {"text", "search", ""}
    if not has_autocomplete_signal:
        return False

    hints = selector_station_hints(selectors)
    if "from" in hints and kind == "from_station":
        return True
    if "to" in hints and kind == "to_station":
        return True
    if any(hint in attrs for hint in hints if hint.startswith("r")):
        return True

    return False


def resolve_station_textbox(page: Page, direction: str, selectors: list[list[str]]) -> Locator:
    dismiss_onetrust_if_present(page)
    kind = "from_station" if direction == "from" else "to_station"
    try:
        return resolve_input_by_kind(page, kind, selectors, timeout_ms=16000)
    except RuntimeError as semantic_error:
        fallback = resolve_editable_input_from_selectors(page, selectors, timeout_ms=12000)
        metadata = read_input_metadata(fallback)
        if isinstance(metadata, dict) and is_plausible_station_fallback(metadata, kind, selectors):
            return fallback
        raise RuntimeError(
            f"Could not find validated input for kind '{kind}' and selector fallback was not a station field."
        ) from semantic_error


def is_terms_checkbox_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return (
        "online ticket office sales conditions" in selectors
        or "terms and privacy policy" in selectors
        or "#checkbox-" in selectors
    )


def click_terms_checkbox(page: Page, selectors: list[list[str]]) -> None:
    def ensure_checkbox_checked(checkbox: Locator) -> bool:
        try:
            if checkbox.is_checked():
                return True
        except Error:
            pass
        try:
            checkbox.check(force=True, timeout=5000)
            return True
        except Error:
            return False

    try:
        locator = resolve_locator(page, selectors, timeout_ms=8000)
        try:
            if ensure_checkbox_checked(locator):
                return
        except Error:
            pass

        robust_click(page, locator)
        checkbox_candidates_direct = [
            page.locator("#checkbox-\\:rb\\:").first,
            page.locator("input[type='checkbox'][aria-label*='termos' i]").first,
            page.locator("input[type='checkbox'][aria-label*='terms' i]").first,
        ]
        checkbox_direct = first_visible_locator(checkbox_candidates_direct, timeout_ms=1200)
        if checkbox_direct is not None and ensure_checkbox_checked(checkbox_direct):
            return
    except RuntimeError:
        dismiss_onetrust_if_present(page)

    checkbox_candidates = [
        page.get_by_role(
            "checkbox",
            name=re.compile(r"(sales conditions|terms|privacy|over 16|condi|privacidade|maior de 16)", re.IGNORECASE),
        ).first,
        page.locator("div.modal-footer input[type='checkbox']").first,
        page.locator("input[type='checkbox'][id^='checkbox-']").first,
    ]

    checkbox = first_visible_locator(checkbox_candidates, timeout_ms=6000)
    if checkbox is not None:
        if ensure_checkbox_checked(checkbox):
            return

    clickable_candidates = [
        page.locator("label[for^='checkbox-'] span.custom-checkbox").first,
        page.locator("input[type='checkbox'][id^='checkbox-'] + span.custom-checkbox").first,
        page.locator("div.modal-footer label span").first,
        page.locator("label span").first,
    ]
    clickable = first_visible_locator(clickable_candidates, timeout_ms=4000)
    if clickable is not None:
        robust_click(page, clickable)
        checkbox_after_click = first_visible_locator(checkbox_candidates, timeout_ms=1200)
        if checkbox_after_click is not None and ensure_checkbox_checked(checkbox_after_click):
            return

    raise RuntimeError("Could not find terms/conditions checkbox with fallback locators.")


def should_skip_date_picker_day_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", []))
    return "aria/Choose " in selectors and "react-datepicker__day" in selectors


def should_handle_departure_selection(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", []))
    return "aria/Select departure from" in selectors


def is_station_text_input(step: dict, direction: str) -> bool:
    selectors = flatten_selectors(step.get("selectors", []))
    if direction == "from":
        return "aria/From *[role=\"textbox\"]" in selectors
    return "aria/To *[role=\"textbox\"]" in selectors


def is_email_input_step(step: dict) -> bool:
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return "#username" in selectors or "aria/email" in selectors


def is_password_input_step(step: dict) -> bool:
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return "#password" in selectors or "aria/password" in selectors


def is_additional_info_input_step(step: dict) -> bool:
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return (
        "additional information" in selectors
        or "informacao adicional" in selectors
        or "informação adicional" in selectors
    )


def is_optional_passenger_form_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors_blob = flatten_selectors(step.get("selectors", [])).lower()
    if ":re:" not in selectors_blob:
        return False
    if "div:nth-of-type" not in selectors_blob and "xpath=" not in selectors_blob:
        return False
    if any(token in selectors_blob for token in ("button", "checkbox", "aria/", "proceed", "next", "confirm")):
        return False
    return True


def is_station_option_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", []))
    return "react-autowhatever" in selectors


def is_date_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", []))
    return "aria/Date" in selectors or "#ida" in selectors


def is_search_trips_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return "aria/search trips" in selectors or "search-info" in selectors


def is_final_confirm_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", []))
    return "aria/Confirm" in selectors


def is_proceed_to_purchase_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return "proceed to purchase" in selectors or "prosseguir para compra" in selectors


def is_discount_option_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return "rail green pass" in selectors or "select-option-" in selectors


def is_discount_trigger_click(step: dict) -> bool:
    if step.get("type") != "click":
        return False
    selectors = flatten_selectors(step.get("selectors", [])).lower()
    return "aria/discount *" in selectors or ("select-" in selectors and "/img" in selectors)


def filter_discount_trigger_selectors(selectors: list[list[str]]) -> list[list[str]]:
    safe: list[list[str]] = []
    for chain in selectors:
        if not chain:
            continue
        primary = chain[0].lower()
        if "aria/discount" in primary or "aria/desconto" in primary or "select-" in primary:
            safe.append(chain)
    return safe


def is_any_discount_option_visible(page: Page) -> bool:
    option_candidates = [
        page.locator("[id*='select-option-']").first,
        page.get_by_role("option").first,
        page.locator("[role='listbox'] [role='option']").first,
    ]
    return first_visible_locator(option_candidates, timeout_ms=1000) is not None


def wait_for_purchase_form_ready(page: Page) -> None:
    markers = [
        page.locator("input[aria-label*='Additional information' i]").first,
        page.locator("input[aria-label*='informacao adicional' i]").first,
        page.locator("input[aria-label*='informação adicional' i]").first,
        page.get_by_text(re.compile(r"(discount|desconto)", re.IGNORECASE)).first,
        page.get_by_role("button", name=re.compile(r"next|seguinte", re.IGNORECASE)).first,
    ]
    first_visible_locator(markers, timeout_ms=20000)


def click_discount_trigger(page: Page, selectors: list[list[str]]) -> None:
    wait_for_purchase_form_ready(page)

    safe_selectors = filter_discount_trigger_selectors(selectors)
    if safe_selectors:
        try:
            locator = resolve_locator(page, safe_selectors, timeout_ms=4000)
            robust_click(page, locator)
            return
        except RuntimeError:
            dismiss_onetrust_if_present(page)

    candidates = [
        page.get_by_role("combobox", name=re.compile(r"(discount|desconto)", re.IGNORECASE)).first,
        page.get_by_role("button", name=re.compile(r"(discount|desconto)", re.IGNORECASE)).first,
        page.locator("label:has-text('Discount') + div").first,
        page.locator("label:has-text('Desconto') + div").first,
        page.locator("xpath=(//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'discount') or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'desconto')]/following::*[self::div or self::button][1])[1]").first,
        page.locator("[role='combobox']").first,
        page.locator("[aria-haspopup='listbox']").first,
        page.locator("[aria-label*='Discount' i], [aria-label*='Desconto' i]").first,
        page.locator("xpath=(//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'discount') or contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'desconto')]/following::*[@role='combobox' or @aria-haspopup='listbox' or self::button][1])[1]").first,
        page.locator("[id^='select-']").first,
        page.locator("label:has-text('Discount')").first,
        page.locator("label:has-text('Desconto')").first,
    ]
    locator = first_visible_locator(candidates, timeout_ms=6000)
    if locator is not None:
        robust_click(page, locator)
        return

    # Some CP variants already show dropdown options without explicit trigger click.
    if is_any_discount_option_visible(page):
        return

    clicked_via_dom = page.evaluate(
        """() => {
            const textMatch = (el) => /discount|desconto/i.test((el?.textContent || '').trim());
            const roots = Array.from(document.querySelectorAll('[id], form, section, div'));
            for (const root of roots) {
              if (!textMatch(root)) continue;
              const target = root.querySelector('[role="combobox"], [aria-haspopup="listbox"], [id^="select-"], button');
              if (target) { target.click(); return true; }
            }
            return false;
        }"""
    )
    if clicked_via_dom:
        return

    if is_any_discount_option_visible(page):
        return

    if locator is None:
        raise RuntimeError("Could not find discount dropdown trigger with fallback locators.")


def read_visible_discount_options(page: Page) -> list[str]:
    values = page.evaluate(
        """() => {
            const nodes = [
              ...document.querySelectorAll('[role="option"]'),
              ...document.querySelectorAll('[id*="select-option-"]'),
              ...document.querySelectorAll('[id*="option-"]'),
              ...document.querySelectorAll('[role="listbox"] *'),
            ];
            const texts = [];
            for (const node of nodes) {
              const text = (node.textContent || '').replace(/\\s+/g, ' ').trim();
              if (text) texts.push(text);
            }
            return [...new Set(texts)];
        }"""
    )
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return []


def detect_no_seats_and_raise(page: Page) -> None:
    no_seat_message = first_visible_locator(
        [
            page.get_by_text(
                re.compile(
                    r"(no seats|no seat|sem lugares|lugares indispon[ií]veis|esgotad|sold out)",
                    re.IGNORECASE,
                )
            ).first,
        ],
        timeout_ms=800,
    )
    if no_seat_message is not None:
        raise NoSeatsAvailableError("No seats available for selected trip.")

    back_to_results = first_visible_locator(
        [
            page.get_by_role("button", name=re.compile(r"(back to results|voltar aos resultados)", re.IGNORECASE)).first,
            page.get_by_text(re.compile(r"(back to results|voltar aos resultados)", re.IGNORECASE)).first,
        ],
        timeout_ms=3500,
    )
    if back_to_results is not None:
        raise NoSeatsAvailableError("No seats available for selected trip (Back to results shown).")


def click_discount_option(page: Page, discount_name: str) -> None:
    labels = [discount_name]
    if discount_name.strip().lower() == "rail green pass":
        labels.append("Passe Ferroviario Verde")
        labels.append("Passe Ferroviário Verde")
        labels.append("Passe Verde")
        labels.append("Rail Green pass")

    def try_click_discount_by_label(timeout_ms: int) -> bool:
        for label in labels:
            exact_pattern = re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE)
            contains_pattern = re.compile(re.escape(label), re.IGNORECASE)
            if click_first_visible_match(page, page.get_by_role("option", name=exact_pattern), timeout_ms):
                return True
            if click_first_visible_match(
                page, page.locator("[id*='option-'], [role='listbox'] *", has_text=exact_pattern), timeout_ms
            ):
                return True
            if click_first_visible_match(page, page.get_by_text(exact_pattern), timeout_ms):
                return True
            if click_first_visible_match(page, page.get_by_text(contains_pattern), timeout_ms):
                return True
        return False

    options = read_visible_discount_options(page)
    if options:
        print(f"[{now_ts()}] Available discount options: {', '.join(options)}")

    if try_click_discount_by_label(timeout_ms=2500):
        return

    click_discount_trigger(page, [])
    options = read_visible_discount_options(page)
    if options:
        print(f"[{now_ts()}] Available discount options: {', '.join(options)}")
    if try_click_discount_by_label(timeout_ms=6000):
        return

    raise RuntimeError(f"Could not find discount option '{discount_name}'. Visible options: {', '.join(options)}")


def override_change_value(step: dict, cfg: BotConfig, state: RuntimeState) -> str:
    selectors = flatten_selectors(step.get("selectors", []))

    if is_email_input_step(step):
        return cfg.email
    if is_password_input_step(step):
        return cfg.password
    if is_station_text_input(step, "from"):
        state.last_station_field = "from"
        return cfg.from_station
    if is_station_text_input(step, "to"):
        state.last_station_field = "to"
        return cfg.to_station
    if is_additional_info_input_step(step) or "aria/Additional information *" in selectors:
        return cfg.additional_info

    return step.get("value", "")


def run_flow_from_json(
    page: Page,
    flow_path: Path,
    cfg: BotConfig,
    state: RuntimeState,
    travel_date: str,
    start_index: int = 0,
    end_index: Optional[int] = None,
    preloaded_steps: Optional[list[dict]] = None,
    detect_no_seats: bool = True,
) -> None:
    if preloaded_steps is None:
        raw = json.loads(flow_path.read_text(encoding="utf-8"))
        steps = raw.get("steps", [])
    else:
        steps = preloaded_steps

    upper_bound = len(steps) if end_index is None else min(end_index, len(steps))
    if start_index < 0 or start_index > upper_bound:
        raise RuntimeError(f"Invalid step range [{start_index}, {upper_bound}) for {flow_path.name}")

    for real_index in range(start_index, upper_bound):
        step = steps[real_index]
        index = real_index + 1
        step_type = step.get("type")
        selectors = step.get("selectors", [])
        if cfg.log_steps:
            print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} start {step_summary(step)}")

        try:
            if should_skip_date_picker_day_click(step):
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} skip date-picker day")
                continue

            if should_handle_departure_selection(step):
                choose_departure_by_time(page, cfg.departure_time.strftime("%H:%M"))
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok departure selected")
                continue

            if is_final_confirm_click(step) and not cfg.confirm_purchase:
                print("confirm_purchase=False -> stopping before final payment confirmation.")
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} stop before final confirm")
                return

            if step_type == "setViewport":
                width = int(step.get("width", 1158))
                height = int(step.get("height", 1000))
                page.set_viewport_size({"width": width, "height": height})
                wait_for_settle(page, cfg)
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok viewport set")
                continue

            if step_type == "navigate":
                page.goto(step["url"], wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=min(cfg.ui_timeout_ms, 15000))
                except TimeoutError:
                    pass
                dismiss_onetrust_if_present(page)
                wait_for_settle(page, cfg)
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok navigated")
                continue

            if step_type == "change":
                if is_station_text_input(step, "from"):
                    locator = resolve_station_textbox(page, "from", selectors)
                elif is_station_text_input(step, "to"):
                    locator = resolve_station_textbox(page, "to", selectors)
                elif is_email_input_step(step):
                    locator = resolve_input_by_kind(page, "email", selectors, timeout_ms=12000)
                elif is_password_input_step(step):
                    locator = resolve_input_by_kind(page, "password", selectors, timeout_ms=12000)
                elif is_additional_info_input_step(step):
                    locator = resolve_input_by_kind(page, "additional_info", selectors, timeout_ms=12000)
                else:
                    locator = resolve_editable_input_from_selectors(page, selectors, timeout_ms=12000)
                value = override_change_value(step, cfg, state)
                if is_station_text_input(step, "from"):
                    select_station(
                        page,
                        locator,
                        cfg.from_station,
                        "From station",
                        cfg.log_steps,
                        cfg.station_type_delay_ms,
                    )
                elif is_station_text_input(step, "to"):
                    select_station(
                        page,
                        locator,
                        cfg.to_station,
                        "To station",
                        cfg.log_steps,
                        cfg.station_type_delay_ms,
                    )
                else:
                    locator.fill(value)
                wait_for_settle(page, cfg)
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok value changed")
                continue

            if step_type == "click":
                if is_search_trips_click(step) and not state.date_field_set:
                    set_date_field(page, travel_date)
                    state.date_field_set = True

                if is_station_option_click(step):
                    if cfg.log_steps:
                        print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} skip station option click")
                    continue

                if is_discount_trigger_click(step):
                    click_discount_trigger(page, selectors)
                    if cfg.log_steps:
                        print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok discount opened")
                    continue

                if is_discount_option_click(step):
                    click_discount_option(page, cfg.discount_name)
                    if cfg.log_steps:
                        print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok discount selected")
                    continue

                if is_terms_checkbox_click(step):
                    click_terms_checkbox(page, selectors)
                    if cfg.log_steps:
                        print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok terms checked")
                    continue

                if is_additional_info_input_step(step):
                    locator = resolve_input_by_kind(page, "additional_info", selectors, timeout_ms=16000)
                    robust_click(page, locator)
                    wait_for_settle(page, cfg)
                    if cfg.log_steps:
                        print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok additional info focused")
                    continue

                if is_optional_passenger_form_click(step):
                    try:
                        locator = resolve_locator(page, selectors, timeout_ms=3500)
                        robust_click(page, locator)
                        if cfg.log_steps:
                            print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok optional form click")
                    except RuntimeError:
                        if cfg.log_steps:
                            print(
                                f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} "
                                "skip optional dynamic form click"
                            )
                    wait_for_settle(page, cfg)
                    continue

                if is_station_text_input(step, "from"):
                    locator = resolve_station_textbox(page, "from", selectors)
                elif is_station_text_input(step, "to"):
                    locator = resolve_station_textbox(page, "to", selectors)
                else:
                    locator = resolve_locator(page, selectors)
                robust_click(page, locator)

                if is_date_click(step):
                    set_date_field(page, travel_date)
                    state.date_field_set = True
                if is_proceed_to_purchase_click(step) and detect_no_seats:
                    detect_no_seats_and_raise(page)
                wait_for_settle(page, cfg)
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok clicked")
                continue

            if step_type == "keyDown":
                page.keyboard.down(step["key"])
                wait_for_settle(page, cfg)
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok keyDown")
                continue

            if step_type == "keyUp":
                page.keyboard.up(step["key"])
                wait_for_settle(page, cfg)
                if cfg.log_steps:
                    print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} ok keyUp")
                continue

            raise RuntimeError(f"Unsupported step type '{step_type}' in {flow_path.name}")
        except NoSeatsAvailableError:
            if cfg.log_steps:
                print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} fail: no seats available")
            raise
        except Exception as exc:
            if cfg.log_steps:
                print(f"[{now_ts()}] [{flow_path.name}] step {index}/{len(steps)} fail: {exc}")
            raise RuntimeError(f"Step {index}/{len(steps)} failed in {flow_path.name}: {exc}") from exc


def find_no_seat_retry_window(steps: list[dict]) -> Optional[tuple[int, int]]:
    select_idx: Optional[int] = None
    for idx, step in enumerate(steps):
        if should_handle_departure_selection(step):
            select_idx = idx
            break
    if select_idx is None:
        return None

    for idx in range(select_idx + 1, len(steps)):
        if is_proceed_to_purchase_click(steps[idx]):
            return select_idx, idx
    return None


def resolve_session_state_path(flow_root: Path, configured_path: str) -> Path:
    path = Path(configured_path).expanduser()
    if path.is_absolute():
        return path
    return flow_root / path


def is_session_authenticated(page: Page) -> bool:
    page.goto("https://www.cp.pt/en/mycp", wait_until="domcontentloaded")
    dismiss_onetrust_if_present(page)
    current_url = page.url.lower()
    if "login.cp.pt" in current_url:
        return False

    username = page.locator("#username").first
    login_button = page.locator("#kc-login").first
    try:
        if username.is_visible() or login_button.is_visible():
            return False
    except Error:
        pass
    return True


def run_purchase(
    login_flow: Path,
    ticket_flow: Path,
    failure_flow: Path,
    cfg: BotConfig,
    travel_date: str,
) -> None:
    state = RuntimeState()
    session_state_file = resolve_session_state_path(ticket_flow.parent, cfg.session_state_path)
    ticket_raw = json.loads(ticket_flow.read_text(encoding="utf-8"))
    ticket_steps = ticket_raw.get("steps", [])
    failure_raw = json.loads(failure_flow.read_text(encoding="utf-8"))
    failure_steps = failure_raw.get("steps", [])
    retry_window = find_no_seat_retry_window(ticket_steps)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=cfg.headless, slow_mo=cfg.action_delay_ms)
        if cfg.use_saved_session and session_state_file.exists():
            context = browser.new_context(storage_state=str(session_state_file))
            if cfg.log_steps:
                print(f"[{now_ts()}] Loaded saved session from {session_state_file}")
        else:
            context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(cfg.ui_timeout_ms)
        page.set_default_navigation_timeout(cfg.ui_timeout_ms)

        logged_in = False
        if cfg.use_saved_session and session_state_file.exists():
            try:
                logged_in = is_session_authenticated(page)
            except Exception as exc:
                if cfg.log_steps:
                    print(f"[{now_ts()}] Saved session check failed, will login again: {exc}")
                logged_in = False

        if not logged_in:
            run_flow_from_json(page, login_flow, cfg, state, travel_date)
            if cfg.use_saved_session:
                session_state_file.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(session_state_file))
                if cfg.log_steps:
                    print(f"[{now_ts()}] Saved authenticated session to {session_state_file}")
        elif cfg.log_steps:
            print(f"[{now_ts()}] Session valid, skipping login flow.")

        if retry_window is None:
            run_flow_from_json(page, ticket_flow, cfg, state, travel_date, preloaded_steps=ticket_steps)
        else:
            select_idx, proceed_idx = retry_window
            first_pass = True
            while True:
                segment_start = 0 if first_pass else select_idx
                segment_end = proceed_idx + 1
                try:
                    run_flow_from_json(
                        page,
                        ticket_flow,
                        cfg,
                        state,
                        travel_date,
                        start_index=segment_start,
                        end_index=segment_end,
                        preloaded_steps=ticket_steps,
                    )
                    break
                except NoSeatsAvailableError:
                    first_pass = False
                    if failure_steps:
                        # Recorded failure flow returns CP to search results. Skip its stale
                        # final navigation URL; next attempt supplies current SCRIPT_SETTINGS data.
                        failure_end = len(failure_steps)
                        if failure_steps[-1].get("type") == "navigate":
                            failure_end -= 1
                        try:
                            run_flow_from_json(
                                page,
                                failure_flow,
                                cfg,
                                state,
                                travel_date,
                                end_index=failure_end,
                                preloaded_steps=failure_steps,
                                detect_no_seats=False,
                            )
                        except Exception as recovery_error:
                            if cfg.log_steps:
                                print(f"[{now_ts()}] Failure flow recovery skipped: {recovery_error}")
                    print(
                        f"[{now_ts()}] No seats available for {travel_date}. "
                        f"Retrying from results in {cfg.retry_interval_seconds}s."
                    )
                    page.wait_for_timeout(cfg.retry_interval_seconds * 1000)

            if proceed_idx + 1 < len(ticket_steps):
                run_flow_from_json(
                    page,
                    ticket_flow,
                    cfg,
                    state,
                    travel_date,
                    start_index=proceed_idx + 1,
                    preloaded_steps=ticket_steps,
                )

        context.close()
        browser.close()


def next_travel_date_for_weekday(
    now: datetime, travel_weekday: int, departure_time: time, blocked_dates: set[date]
) -> date:
    days_ahead = (travel_weekday - now.weekday()) % 7
    candidate = now.date() + timedelta(days=days_ahead)

    if candidate == now.date() and now.time() > departure_time:
        candidate += timedelta(days=7)

    while candidate in blocked_dates:
        candidate += timedelta(days=7)

    return candidate


def opening_datetime_for_travel(travel_day: date, departure_time: time) -> datetime:
    travel_datetime = datetime.combine(travel_day, departure_time)
    return travel_datetime - timedelta(days=1)


def build_candidates(now: datetime, cfg: BotConfig, blocked_dates: set[date]) -> list[ScheduleCandidate]:
    candidates: list[ScheduleCandidate] = []
    for weekday in sorted(cfg.travel_weekdays):
        travel_day = next_travel_date_for_weekday(now, weekday, cfg.departure_time, blocked_dates)
        candidates.append(
            ScheduleCandidate(
                travel_date=travel_day,
                travel_weekday=weekday,
                opening_datetime=opening_datetime_for_travel(travel_day, cfg.departure_time),
            )
        )
    return candidates


def next_opening_excluding_date(now: datetime, cfg: BotConfig, blocked_dates: set[date], exclude_date: date) -> Optional[ScheduleCandidate]:
    augmented_blocked = set(blocked_dates)
    augmented_blocked.add(exclude_date)
    candidates = build_candidates(now, cfg, augmented_blocked)
    future = [item for item in candidates if item.opening_datetime > now]
    if not future:
        return None
    return min(future, key=lambda item: item.opening_datetime)


def sleep_until(target: datetime) -> None:
    while True:
        now = datetime.now()
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        time_mod.sleep(min(remaining, 30))


def run_with_retry(
    login_flow: Path,
    ticket_flow: Path,
    failure_flow: Path,
    cfg: BotConfig,
    travel_date: str,
    handover_at: Optional[datetime] = None,
    next_opening_at: Optional[datetime] = None,
) -> bool:
    def should_handover() -> bool:
        return handover_at is not None and datetime.now() >= handover_at

    def handover_log() -> None:
        next_window = (
            next_opening_at.isoformat(timespec="seconds")
            if next_opening_at is not None
            else "upcoming schedule window"
        )
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            f"Stopping attempts for travel date {travel_date} to preserve next window at {next_window}."
        )

    attempt = 1
    while True:
        if should_handover():
            handover_log()
            return False

        try:
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] Attempt {attempt} started "
                f"for travel date {travel_date}."
            )
            run_purchase(login_flow, ticket_flow, failure_flow, cfg, travel_date)
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] Purchase flow succeeded "
                f"for travel date {travel_date}."
            )
            return True
        except Exception as exc:
            if should_handover():
                handover_log()
                return False

            sleep_seconds = float(cfg.retry_interval_seconds)
            if handover_at is not None:
                remaining = (handover_at - datetime.now()).total_seconds()
                if remaining <= 0:
                    handover_log()
                    return False
                sleep_seconds = min(sleep_seconds, remaining)

            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] Attempt {attempt} failed for "
                f"travel date {travel_date}: {exc}. Retrying in {sleep_seconds:.0f}s."
            )
            attempt += 1
            time_mod.sleep(sleep_seconds)


def main() -> int:
    root = Path(__file__).resolve().parent
    login_flow = root / "login.json"
    ticket_flow = root / "buy-ticket.json"
    failure_flow = root / "buy-ticket-fail.json"

    if not login_flow.exists():
        raise FileNotFoundError(f"Missing flow file: {login_flow}")
    if not ticket_flow.exists():
        raise FileNotFoundError(f"Missing flow file: {ticket_flow}")
    if not failure_flow.exists():
        raise FileNotFoundError(f"Missing flow file: {failure_flow}")

    cfg = BotConfig.from_script_settings()
    settled_dates: set[date] = set()

    while True:
        now = datetime.now()
        candidates = build_candidates(now, cfg, settled_dates)
        due = [item for item in candidates if item.opening_datetime <= now]

        if due:
            due.sort(key=lambda item: item.opening_datetime)
            for item in due:
                now_for_item = datetime.now()
                next_candidate = next_opening_excluding_date(now_for_item, cfg, settled_dates, item.travel_date)
                handover_at = None
                if next_candidate is not None:
                    handover_at = next_candidate.opening_datetime - timedelta(
                        minutes=cfg.stop_retry_before_next_open_minutes
                    )

                print(
                    f"[{now_for_item.isoformat(timespec='seconds')}] "
                    f"Travel day {WEEKDAY_NAME[item.travel_weekday]} ({item.travel_date_str}) is open for purchase. "
                    f"Starting attempts now."
                )
                success = run_with_retry(
                    login_flow,
                    ticket_flow,
                    failure_flow,
                    cfg,
                    item.travel_date_str,
                    handover_at=handover_at,
                    next_opening_at=next_candidate.opening_datetime if next_candidate is not None else None,
                )
                if not success:
                    print(
                        f"[{datetime.now().isoformat(timespec='seconds')}] "
                        f"Travel date {item.travel_date_str} not purchased before handover cutoff. Moving to next window."
                    )
                settled_dates.add(item.travel_date)

            cutoff = datetime.now().date() - timedelta(days=14)
            settled_dates = {value for value in settled_dates if value >= cutoff}
            continue

        next_item = min(candidates, key=lambda item: item.opening_datetime)
        print(
            f"[{now.isoformat(timespec='seconds')}] Next run for travel day "
            f"{WEEKDAY_NAME[next_item.travel_weekday]} ({next_item.travel_date_str}) at "
            f"{next_item.opening_datetime.isoformat(timespec='seconds')}."
        )
        sleep_until(next_item.opening_datetime)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfigError as config_error:
        print(f"Configuration error: {config_error}")
        raise SystemExit(2)
