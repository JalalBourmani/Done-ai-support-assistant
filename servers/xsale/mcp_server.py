import os
import re
import html as html_mod
import io
import time
import json
import requests
import urllib.parse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("XSALE CRM Server")

# Global session cache
_session = None
_user_id = None


def _get_env():
    """Reads XSALE credentials from environment variables."""
    base_url = os.getenv("XSALE_URL", "https://amendo.app.xsale.no")
    email = os.getenv("XSALE_EMAIL")
    password = os.getenv("XSALE_PASSWORD")
    if not email or not password:
        raise ValueError("XSALE_EMAIL and XSALE_PASSWORD environment variables must be set.")
    return base_url.rstrip("/"), email, password


def _get_session():
    """Establishes or retrieves the cached XSALE session."""
    global _session, _user_id
    if _session is not None:
        return _session

    base_url, email, password = _get_env()
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept-Language": "nb-NO,nb;q=0.6",
    })

    # Step 1: GET the login page to extract the CSRF token
    login_page = sess.get(f"{base_url}/user/login", timeout=15)
    login_page.raise_for_status()

    csrf_match = re.search(r'name=["\']_csrf_token["\']\s+value=["\']([^"\']+)["\']', login_page.text)
    if not csrf_match:
        csrf_match = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']_csrf_token["\']', login_page.text)
    if not csrf_match:
        raise RuntimeError("Could not extract CSRF token from XSALE login page.")

    csrf_token = csrf_match.group(1)

    # Step 2: POST login credentials
    login_data = {
        "_redirect_url": "/",
        "_csrf_token": csrf_token,
        "_email": email,
        "_password": password,
    }
    login_resp = sess.post(
        f"{base_url}/user/login",
        data=login_data,
        timeout=15,
        allow_redirects=True,
    )

    if login_resp.status_code != 200 or "/user/login" in login_resp.url:
        raise RuntimeError("XSALE login failed. Check XSALE_EMAIL and XSALE_PASSWORD.")

    # Step 3: Get logged-in user info to find our userId
    user_resp = sess.get(f"{base_url}/user/get_logged_user", timeout=15)
    if user_resp.status_code == 200:
        try:
            user_data = user_resp.json()
            u = user_data.get("user") or user_data.get("data") or {}
            if isinstance(u, dict):
                _user_id = u.get("id")
        except (json.JSONDecodeError, KeyError):
            pass

    _session = sess
    return _session


def _clear_session():
    """Clears the cached session."""
    global _session, _user_id
    _session = None
    _user_id = None


def _api_get(path, params=None, max_retries=2):
    """Makes an authenticated GET request to the XSALE API with retry logic."""
    base_url = _get_env()[0]
    for attempt in range(max_retries):
        try:
            sess = _get_session()
            url = f"{base_url}{path}"
            resp = sess.get(url, params=params, timeout=30)

            if resp.status_code in (401, 403) or "/user/login" in resp.url:
                _clear_session()
                continue

            resp.raise_for_status()
            res_json = resp.json()
            if isinstance(res_json, dict) and res_json.get("success") is False:
                _clear_session()
                continue
            return res_json

        except requests.exceptions.JSONDecodeError:
            _clear_session()
            continue
        except Exception as e:
            if attempt < max_retries - 1:
                _clear_session()
                continue
            raise

    raise RuntimeError("XSALE API request failed after retries.")


def _extract_list(result: dict, entity_key: str) -> tuple[list, int]:
    """Extracts list data from XSALE response using the entity-specific key.
    
    XSALE returns data under entity-specific keys, e.g.:
      /customercase/ -> result["customercase"]
      /account/case_type/ -> result["caseType"]
      /email/inbound/ -> result["inbound"]
    """
    data = result.get(entity_key) or result.get("data") or []
    total = result.get("totalCount") or result.get("total") or result.get("count") or len(data)
    return data, total


def _extract_entity(result: dict, entity_key: str) -> dict:
    """Extracts a single entity from XSALE responses."""
    data = result.get(entity_key) or result.get("data") or result
    if isinstance(data, list):
        return data[0] if data else {}
    return data if isinstance(data, dict) else {}


def _api_put(path, payload=None, params=None, max_retries=2):
    """PUT mot XSALE-API-et. Oppdatering, i motsetning til POST.

    Skillet er ikke kosmetisk: POST /customercase/<id> ignorerer id-en i stien
    og OPPRETTER en ny sak, med success:true og meldingen "Sak opprettet".
    Malt tre ganger på TESTKUNDE 21.09.2026 - tre saker ble til der jeg
    trodde jeg endret en status. Oppdatering krever PUT, og id-en må ligge i
    payloaden.

    Som _api_post returneres success=false til kalleren uten nytt forsok. Et
    gjentatt skriv er farligere enn en feilmelding.
    """
    base_url = _get_env()[0]
    last_error = None

    for attempt in range(max_retries):
        sess = _get_session()
        url = f"{base_url}{path}"
        try:
            resp = sess.put(url, json=payload, params=params, timeout=30)

            if resp.status_code in (401, 403) or "/user/login" in resp.url:
                _clear_session()
                last_error = f"not authenticated (HTTP {resp.status_code})"
                continue

            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                return {"success": False,
                        "message": "Non-JSON response from XSALE.",
                        "raw": resp.text[:500]}
        except requests.RequestException as exc:
            last_error = str(exc)
            break

    return {"success": False,
            "message": f"PUT {path} failed: {last_error}"}


# Feltene som må være med i en PUT for at ingenting skal blankes.
# Utelates priority, settes den til tom. Utelates customerId, svarer XSALE
# "Kunne ikke finne kunde". description står bevisst IKKE her.
CASE_UPDATE_FIELDS = ("id", "customerId", "subject", "typeKey", "priority",
                      "userId", "origin", "contactId", "notes",
                      "requestedById", "type")


def _bygg_status_payload(raa_sak, ny_status):
    """Payloaden som endrer status uten å blanke noe.

    Malt på sak 48638-48641 21.09.2026:
      {id, status}                     -> "Kunne ikke finne kunde"
      uten priority                    -> priority blankes
      uten customerId                  -> "Kunne ikke finne kunde"
      med disse feltene                -> bare status endres, 33 andre urørt

    description står bevisst utenfor. Den er ikke nødvendig, og å ekko den
    tilbake er den siste måten å overskrive HTML-en i saken på.
    """
    p = {}
    for felt in CASE_UPDATE_FIELDS:
        if felt in raa_sak:
            v = raa_sak[felt]
            if isinstance(v, dict):
                v = v.get("id")
            p[felt] = v
    p["status"] = str(ny_status)
    return p


def _bygg_epost_payload(case_id, emne, innhold_html, mottaker, cc=""):
    """Payloaden /email/send godtar.

    Feltnavnene er trådfeltene, ikke kolonnenavnene. Aktivitetsloggen viser
    body/receiver/sender fordi det er de LAGREDE navnene; API-et vil ha
    content og to. Og "to" må være en LISTE - som streng svarer XSALE
    "to should not be blank" selv om feltet er fylt ut.

    Avsender settes serverside (målt til support@plorea.com), så sender
    sendes ikke med.
    """
    p = {
        "model": "Customercase",
        "fk": int(case_id),
        "action": "email/send",
        "subject": str(emne),
        "content": innhold_html,
        "to": [str(mottaker)],
    }
    kopi = [a.strip() for a in re.split(r"[;,]", str(cc or "")) if a.strip()]
    if kopi:
        p["cc"] = kopi
    return p


def _raa_sak(case_id):
    """Saksposten slik den er lagret, uten clean_html."""
    return _extract_entity(_api_get("/customercase/%d" % int(case_id)),
                           "customercase")


def _api_get_optional(path, params=None):
    """Best-effort GET used for optional context enrichment."""
    try:
        return _api_get(path, params=params)
    except Exception:
        return None


def _build_filter(filters: list[dict]) -> str:
    return json.dumps(filters, separators=(",", ":"))


def _build_sort(sorts: list[dict]) -> str:
    return json.dumps(sorts, separators=(",", ":"))


def _format_cases(cases: list[dict]) -> list[dict]:
    """Extracts the most useful fields from raw case data for display."""
    formatted = []
    for case in cases:
        # XSALE uses "subject" for the case title
        customer = case.get("customer") or {}
        contact = case.get("contact") or {}
        user = case.get("user") or {}

        formatted.append({
            "id": case.get("id"),
            "serialNumber": case.get("serialNumber"),
            "subject": case.get("subject", ""),
            "description": (case.get("description") or "")[:500],
            "status": case.get("status", ""),
            "priority": case.get("priority", ""),
            "typeKey": case.get("typeKey", ""),
            "created": case.get("created", ""),
            "updated": case.get("updated", ""),
            "dueDate": case.get("dueDate", ""),
            "assignedUser": user.get("name", "") if isinstance(user, dict) else str(user),
            "customerName": customer.get("name", "") if isinstance(customer, dict) else str(customer),
            "contactName": contact.get("name", contact.get("fullName", "")) if isinstance(contact, dict) else str(contact),
            "contactEmail": contact.get("email", "") if isinstance(contact, dict) else "",
        })
    return formatted


def _api_post(path, payload=None, params=None, max_retries=2):
    """Makes an authenticated POST request to the XSALE API.

    XSALE does not require a CSRF token for API writes - the token is only used
    by the login form - so the session cookie is sufficient.

    Deliberately different from _api_get in one important way: a response with
    success=false is returned to the caller instead of triggering a retry. For a
    read, retrying a failed call is harmless. For a write it risks creating the
    same record twice, so a validation failure must be reported, never retried.
    Only a genuinely unauthenticated response re-authenticates and tries again.
    """
    base_url = _get_env()[0]
    last_error = None

    for attempt in range(max_retries):
        sess = _get_session()
        url = f"{base_url}{path}"
        try:
            resp = sess.post(url, json=payload, params=params, timeout=30)

            if resp.status_code in (401, 403) or "/user/login" in resp.url:
                _clear_session()
                last_error = f"not authenticated (HTTP {resp.status_code})"
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.JSONDecodeError:
            # Could mean the write succeeded but returned HTML. Do not retry.
            raise RuntimeError(
                f"XSALE returned a non-JSON response to POST {path}. "
                "The write may or may not have been applied - verify in XSALE "
                "before retrying."
            )
        except requests.exceptions.HTTPError as exc:
            body = ""
            try:
                body = exc.response.text[:400]
            except Exception:
                pass
            raise RuntimeError(f"XSALE rejected POST {path}: {exc}. Response: {body}")
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                _clear_session()
                continue
            raise

    raise RuntimeError(f"XSALE API POST to {path} failed: {last_error}")


# ──────────────────────────────────────────────
# MCP TOOLS
# ──────────────────────────────────────────────

@mcp.tool()
def list_my_cases(status: str = "ACTIVE", limit: int = 100) -> str:
    """
    Lists your own cases in XSALE CRM.
    
    Args:
        status: Filter by case status. Default: "ACTIVE". Options: "ACTIVE", "CLOSED", "ALL".
        limit: Maximum number of cases to return. Default: 100.
    """
    global _user_id
    if _user_id is None:
        _get_session()
    if _user_id is None:
        return json.dumps({"error": "Could not determine logged-in user ID."})

    filters = [{"property": "userId", "value": _user_id}]
    if status != "ALL":
        filters.append({"property": "status", "value": status})

    sorts = [
        {"property": "groupingStatus", "direction": "ASC"},
        {"property": "updated", "direction": "DESC"},
    ]

    params = {
        "page": 1,
        "start": 0,
        "limit": limit,
        "filter": _build_filter(filters),
        "sort": _build_sort(sorts),
        "group": json.dumps([{"property": "groupingStatus", "direction": "ASC"}]),
    }

    result = _api_get("/customercase/", params=params)
    cases, total = _extract_list(result, "customercase")

    formatted = _format_cases(cases)
    return json.dumps({"total": total, "showing": len(formatted), "cases": formatted}, indent=2, ensure_ascii=False)


@mcp.tool()
def list_unassigned_cases(limit: int = 100) -> str:
    """
    Lists unassigned (ufordelte) cases in XSALE CRM — cases with no assigned user.
    
    Args:
        limit: Maximum number of cases to return. Default: 100.
    """
    filters = [
        {"property": "userId", "value": 0},
        {"property": "status", "value": "ACTIVE"},
    ]

    params = {
        "page": 1,
        "start": 0,
        "limit": limit,
        "filter": _build_filter(filters),
        "sort": _build_sort([{"property": "updated", "direction": "DESC"}]),
    }

    result = _api_get("/customercase/", params=params)
    cases, total = _extract_list(result, "customercase")

    formatted = _format_cases(cases)
    return json.dumps({"total": total, "showing": len(formatted), "cases": formatted}, indent=2, ensure_ascii=False)


def clean_html(text: str) -> str:
    """Strips HTML tags and decodes HTML entities, preserving block structure with newlines."""
    import html
    if not text:
        return ""
    # Replace common block/break tags with newlines
    text = re.sub(r'<(div|p|br|h[1-6]|li)[^>]*>', '\n', text)
    # Strip all other HTML tags
    text = re.sub(r'<[^>]*>', '', text)
    # Decode HTML entities
    text = html.unescape(text)
    # Normalize whitespace and empty lines
    lines = [line.strip() for line in text.split('\n')]
    cleaned_lines = []
    for line in lines:
        if line:
            cleaned_lines.append(line)
        elif cleaned_lines and cleaned_lines[-1] != "":
            cleaned_lines.append("")
    return '\n'.join(cleaned_lines).strip()


def _truncate_text(value, max_length: int = 4000):
    if not isinstance(value, str):
        return value
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip() + " …[truncated]"


def _clean_value(value, max_length: int = 4000):
    if isinstance(value, str):
        return _truncate_text(clean_html(value), max_length)
    return value


def _name_from_person(person) -> str:
    if not person:
        return ""
    if isinstance(person, dict):
        if person.get("name"):
            return str(person.get("name"))
        if person.get("fullName"):
            return str(person.get("fullName"))
        parts = [
            str(person.get("firstname") or ""),
            str(person.get("middlename") or ""),
            str(person.get("lastname") or ""),
        ]
        return " ".join(part for part in parts if part).strip() or str(person.get("id") or "")
    return str(person)


def _model_variants(model_name: str) -> list[str]:
    base = (model_name or "").strip()
    variants = [base]
    lowered = base.lower()
    if lowered == "customercase":
        variants += ["Customercase", "customercase"]
    elif lowered == "customer":
        variants += ["Customer", "customer"]
    elif lowered == "order":
        variants += ["Order", "order"]
    else:
        variants += [base.capitalize(), lowered]

    result = []
    for variant in variants:
        if variant and variant not in result:
            result.append(variant)
    return result


def _dedupe_by_id(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        item_id = item.get("id") if isinstance(item, dict) else None
        key = item_id if item_id is not None else json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _raa_epost(email_id):
    """En e-postpost slik den er lagret, uten clean_html."""
    try:
        return _extract_entity(_api_get("/email/%d" % int(email_id)), "email")
    except Exception:
        return {}


def _raa_relasjoner(case_id, limit=50):
    """Relasjonene på en sak slik de er LAGRET, uten clean_html.

    _format_relation vasker note-feltet, så den kan ikke brukes til å
    verifisere at et skriv landet. Her hentes rader rått.

    Merk at XSALE ignorerer tekstfiltre, så fk filtreres lokalt.
    """
    ut = []
    try:
        filt = json.dumps([{"property": "model", "value": "customercase"},
                           {"property": "fk", "value": int(case_id)}])
        r = _api_get("/relation/", {"filter": filt, "limit": limit,
                                    "sort": json.dumps(
                                        [{"property": "id",
                                          "direction": "DESC"}])})
        rader, _ = _extract_list(r, "relation")
        for rel in rader:
            if str(rel.get("fk")) == str(case_id):
                ut.append(rel)
    except Exception:
        pass
    return ut


def _format_relation(relation: dict) -> dict:
    file_info = relation.get("docarchivefile") or {}
    created_by = relation.get("createdBy") or relation.get("author") or {}
    return {
        "id": relation.get("id"),
        "type": relation.get("type"),
        "subtype": relation.get("subtype"),
        "created": relation.get("created"),
        "author": _name_from_person(created_by),
        "note": _clean_value(relation.get("note", "")),
        "status": relation.get("status"),
        "attachment": {
            "id": file_info.get("id"),
            "title": file_info.get("title") or file_info.get("name"),
            "url": file_info.get("url") or file_info.get("name"),
            "type": file_info.get("type"),
            "internal": file_info.get("internal"),
        } if isinstance(file_info, dict) and file_info else None,
    }


def _get_relations_for_model(model_name: str, fk: int, limit: int = 250) -> list[dict]:
    relations = []
    for variant in _model_variants(model_name):
        filt = [{"property": "model", "value": variant}, {"property": "fk", "value": fk}]
        params = {
            "page": 1,
            "start": 0,
            "limit": limit,
            "filter": _build_filter(filt),
            "sort": _build_sort([{"property": "created", "direction": "ASC"}]),
        }
        res = _api_get_optional("/relation/", params=params)
        if not res:
            continue
        items, _ = _extract_list(res, "relation")
        relations.extend(item for item in items if isinstance(item, dict))

    formatted = [_format_relation(item) for item in _dedupe_by_id(relations)]
    formatted.sort(key=lambda item: item.get("created") or "")
    return formatted


def _parse_email_headers(headers: str) -> dict:
    parsed = {}
    if not headers:
        return parsed
    for key in ("Subject", "To", "From", "Cc", "Bcc", "Reply-To"):
        match = re.search(rf"^{re.escape(key)}:\s*(.+)$", headers, flags=re.MULTILINE | re.IGNORECASE)
        if match:
            parsed[key.lower().replace("-", "_")] = match.group(1).strip()
    return parsed


def _find_email_refs(activity: dict) -> list[dict]:
    refs = []
    ref = activity.get("modelReference")
    if isinstance(ref, dict):
        refs.append(ref)
    for change in activity.get("changelog") or []:
        ref = change.get("modelReference") if isinstance(change, dict) else None
        if isinstance(ref, dict):
            refs.append(ref)
    return refs


def _extract_email_info(activity: dict) -> dict | None:
    is_emailish = (
        activity.get("model") == "email"
        or "email" in str(activity.get("route") or "").lower()
        or activity.get("isEmailed") == 1
    )
    if not is_emailish:
        return None

    info = {
        "subject": "",
        "sender": "",
        "receiver": "",
        "cc": "",
        "bcc": "",
        "reply_to": "",
        "headers": "",
        "body": "",
        "attachments": None,
    }

    for ref in _find_email_refs(activity):
        headers = ref.get("headers") or ""
        if headers and not info["headers"]:
            info["headers"] = _truncate_text(headers, 3000)
            parsed_headers = _parse_email_headers(headers)
            for key, value in parsed_headers.items():
                if key in info and not info[key]:
                    info[key] = value
                elif key == "from" and not info["sender"]:
                    info["sender"] = value
                elif key == "to" and not info["receiver"]:
                    info["receiver"] = value

        field_map = {
            "subject": ("subject",),
            "sender": ("sender", "from", "fromEmail"),
            "receiver": ("receiver", "to", "toEmail"),
            "cc": ("cc",),
            "bcc": ("bcc",),
            "reply_to": ("replyTo", "reply_to"),
            # "description" og "notes" er BEVISST utelatt. De traff sakens egen
            # beskrivelse, slik at hver aktivitet fikk samme kropp - den
            # opprinnelige innkommende e-posten. Funnet 21.08.2026.
            "body": ("body", "html", "content", "message", "text"),
            "attachments": ("attachments",),
        }
        for target, keys in field_map.items():
            if info.get(target):
                continue
            for key in keys:
                value = ref.get(key)
                if value:
                    info[target] = _clean_value(value) if isinstance(value, str) else value
                    break

    for change in activity.get("changelog") or []:
        if not isinstance(change, dict):
            continue
        field = str(change.get("fieldName") or "")
        value = change.get("newValue")
        if not value:
            continue
        normalized = field.lower()
        if normalized in ("subject", "sender", "receiver", "cc", "bcc", "headers", "attachments"):
            target = "reply_to" if normalized == "reply-to" else normalized
            if target in info and not info[target]:
                info[target] = _clean_value(value) if isinstance(value, str) else value
        elif normalized in ("body", "html", "content", "message", "text", "description") and not info["body"]:
            info["body"] = _clean_value(value)

    return {key: value for key, value in info.items() if value}


def _summarize_model_reference(ref: dict) -> dict:
    if not isinstance(ref, dict):
        return {}

    keys = [
        "id", "serialNumber", "uuid", "name", "subject", "status", "typeKey", "priority",
        "email", "phone", "mobile", "externalReference", "orderDate", "deliveryDate",
        "orderTotalWoVat", "vatTotal", "orderTotal", "orderInPriceTotal", "paymentTerms",
        "paymentCurrency", "created", "updated", "customerId", "contactId", "userId",
        "comment", "note", "notes", "description",
    ]
    summary = {}
    for key in keys:
        if key in ref and ref.get(key) not in (None, ""):
            summary[key] = _clean_value(ref.get(key), 2500)

    for nested_key in ("customer", "contact", "user", "createdBy", "updatedBy"):
        nested = ref.get(nested_key)
        if isinstance(nested, dict):
            summary[nested_key] = {
                key: _clean_value(nested.get(key), 800)
                for key in ("id", "serialNumber", "name", "fullName", "firstname", "lastname", "email", "phone", "mobile", "status")
                if nested.get(key) not in (None, "")
            }

    return summary


def _format_activity(activity: dict) -> dict:
    changes = []
    for change in activity.get("changelog") or []:
        if not isinstance(change, dict):
            continue
        grouped = change.get("groupedDiff") or []
        if grouped:
            for diff in grouped:
                if isinstance(diff, dict):
                    changes.append({
                        "field": diff.get("fieldName"),
                        "old": _clean_value(diff.get("oldValue"), 1200),
                        "new": _clean_value(diff.get("newValue"), 1200),
                    })
        else:
            changes.append({
                "field": change.get("fieldName"),
                "old": _clean_value(change.get("oldValue"), 1200),
                "new": _clean_value(change.get("newValue"), 1200),
            })

    formatted = {
        "id": activity.get("id"),
        "model": activity.get("model"),
        "fk": activity.get("fk"),
        "action": activity.get("action"),
        "route": activity.get("route"),
        "isEmailed": activity.get("isEmailed"),
        "created": activity.get("created"),
        "author": _name_from_person(activity.get("createdBy")),
        "email": _extract_email_info(activity),
        "reference": _summarize_model_reference(activity.get("modelReference") or {}),
        "changes": changes[:80],
    }
    return formatted


def _activity_matches_model(activity: dict, model_name: str, fk: int) -> bool:
    variants = {variant.lower() for variant in _model_variants(model_name)}
    fk_str = str(fk)

    if str(activity.get("model") or "").lower() in variants and str(activity.get("fk") or "") == fk_str:
        return True

    route = str(activity.get("route") or "").lower()
    if model_name.lower() == "order" and f"/order/{fk_str}" in route:
        return True

    ref = activity.get("modelReference")
    if isinstance(ref, dict) and str(ref.get("id") or "") == fk_str:
        ref_model = str(ref.get("model") or activity.get("model") or "").lower()
        if not ref_model or ref_model in variants:
            return True

    for change in activity.get("changelog") or []:
        if not isinstance(change, dict):
            continue
        if str(change.get("model") or "").lower() in variants and str(change.get("fk") or "") == fk_str:
            return True
        ref = change.get("modelReference")
        if isinstance(ref, dict) and str(ref.get("id") or "") == fk_str:
            ref_model = str(ref.get("model") or change.get("model") or "").lower()
            if not ref_model or ref_model in variants:
                return True

    return False


def _get_activities_for_model(model_name: str, fk: int, limit: int = 200) -> list[dict]:
    activities = []
    filter_sets = []
    for variant in _model_variants(model_name):
        filter_sets.append([{"property": "model", "value": variant}, {"property": "fk", "value": fk}])
        filter_sets.append([{"property": "relModel", "value": variant}, {"property": "relFk", "value": fk}])

    for filt in filter_sets:
        params = {
            "page": 1,
            "start": 0,
            "limit": limit,
            "filter": _build_filter(filt),
            "sort": _build_sort([{"property": "created", "direction": "ASC"}]),
        }
        res = _api_get_optional("/activity/", params=params)
        if not res:
            continue
        items, _ = _extract_list(res, "activity")
        activities.extend(item for item in items if isinstance(item, dict))

    matched = [
        item for item in _dedupe_by_id(activities)
        if _activity_matches_model(item, model_name, fk)
    ]
    formatted = [_format_activity(item) for item in matched]
    formatted.sort(key=lambda item: item.get("created") or "")
    return formatted


def _customer_summary(customer: dict) -> dict:
    if not isinstance(customer, dict):
        return {}
    keys = [
        "id", "serialNumber", "isCompany", "name", "firstname", "middlename", "lastname",
        "email", "phone", "mobile", "status", "note", "orgNr", "orgnr", "organizationNumber",
        "vatNumber", "paymentTerms", "paymentCurrency", "invoiceEmail", "invoiceType",
        "generalCustomerDiscount", "externalId", "created", "updated",
    ]
    summary = {
        key: _clean_value(customer.get(key), 2000)
        for key in keys
        if customer.get(key) not in (None, "")
    }
    for address_key in ("addressBilling", "addressShipping", "addressVisiting"):
        address = customer.get(address_key)
        if isinstance(address, dict):
            summary[address_key] = {
                key: _clean_value(address.get(key), 1000)
                for key in ("name", "address", "zip", "city", "country")
                if address.get(key) not in (None, "")
            }
    contacts = customer.get("contacts")
    if isinstance(contacts, list):
        summary["contacts"] = [
            {
                key: _clean_value(contact.get(key), 1000)
                for key in ("id", "isMain", "firstname", "middlename", "lastname", "email", "phone", "mobile", "status")
                if isinstance(contact, dict) and contact.get(key) not in (None, "")
            }
            for contact in contacts
            if isinstance(contact, dict)
        ]
    return summary


def _order_summary(order: dict) -> dict:
    if not isinstance(order, dict):
        return {}
    keys = [
        "id", "serialNumber", "status", "externalReference", "orderDate", "deliveryDate",
        "offerStarts", "offerEnds", "orderTotalWoVat", "vatTotal", "orderTotal",
        "orderInPriceTotal", "paymentTerms", "paymentCurrency", "subscriptionsEnabled",
        "comment", "note", "created", "updated", "customerId", "contactId", "userId",
    ]
    summary = {
        key: _clean_value(order.get(key), 2500)
        for key in keys
        if order.get(key) not in (None, "")
    }
    for nested_key in ("customer", "contact", "user"):
        nested = order.get(nested_key)
        if isinstance(nested, dict):
            summary[nested_key] = {
                key: _clean_value(nested.get(key), 1000)
                for key in ("id", "serialNumber", "name", "firstname", "lastname", "email", "phone", "mobile", "status")
                if nested.get(key) not in (None, "")
            }
    return summary


def _get_customer_raw(customer_id: int) -> dict:
    for path in (f"/customer/{customer_id}", f"/customers/{customer_id}"):
        res = _api_get_optional(path)
        if res:
            customer = _extract_entity(res, "customer")
            if customer.get("id") or customer.get("serialNumber"):
                return customer

    for prop in ("id", "serialNumber"):
        params = {
            "page": 1,
            "start": 0,
            "limit": 5,
            "filter": _build_filter([{"property": prop, "value": customer_id}]),
        }
        res = _api_get_optional("/customer/", params=params)
        if res:
            customers, _ = _extract_list(res, "customer")
            if customers:
                return customers[0]
    return {}


def _get_order_raw(order_id: int) -> dict:
    status_values = [
        "ORDER_NEW",
        "ORDER_PENDING",
        "ORDER_PROCESSING",
        "ORDER_COMPLETED",
        "ORDER_INVOICED",
        "ORDER_INVOICING",
    ]

    # The UI usually shows the visible order serialNumber, while /order/{id}
    # expects an internal DB id. Prefer serialNumber lookup to avoid returning
    # an unrelated order when the visible number also exists as an internal id.
    params = {
        "page": 1,
        "start": 0,
        "limit": 10,
        "filter": _build_filter([{"property": "serialNumber", "value": order_id}]),
    }
    res = _api_get_optional("/order/", params=params)
    if res:
        orders, _ = _extract_list(res, "order")
        for order in orders:
            if isinstance(order, dict) and str(order.get("serialNumber") or "") == str(order_id):
                return order

    # Some XSALE list filters are permissive/ignored. Scan a bounded newest-first
    # slice before falling back to /order/{internal_id}.
    start = 0
    limit = 250
    for page in range(1, 21):
        params = {
            "page": page,
            "start": start,
            "limit": limit,
            "filter": _build_filter([
                {"property": "entitiesToReturn", "value": ["customer", "contact"]},
                {"property": "status", "value": status_values},
            ]),
            "sort": _build_sort([{"property": "orderDate", "direction": "DESC"}]),
        }
        res = _api_get_optional("/order/", params=params)
        if not res:
            break
        orders, _ = _extract_list(res, "order")
        if not orders:
            break
        for order in orders:
            if isinstance(order, dict) and str(order.get("serialNumber") or "") == str(order_id):
                return order
        start += limit

    params = {
        "page": 1,
        "start": 0,
        "limit": 10,
        "filter": _build_filter([{"property": "id", "value": order_id}]),
    }
    res = _api_get_optional("/order/", params=params)
    if res:
        orders, _ = _extract_list(res, "order")
        for order in orders:
            if isinstance(order, dict) and str(order.get("id") or "") == str(order_id):
                return order

    for path in (f"/order/{order_id}", f"/orders/{order_id}"):
        res = _api_get_optional(path)
        if res:
            order = _extract_entity(res, "order")
            if str(order.get("id") or "") == str(order_id):
                return order
    return {}


def _get_orders_for_customer(customer_id: int, limit: int = 100) -> list[dict]:
    resolved_customer = _get_customer_raw(customer_id)
    ids_to_try = [customer_id]
    if resolved_customer.get("id") and resolved_customer.get("id") not in ids_to_try:
        ids_to_try.append(resolved_customer.get("id"))

    orders = []
    status_values = [
        "ORDER_NEW",
        "ORDER_PENDING",
        "ORDER_PROCESSING",
        "ORDER_COMPLETED",
        "ORDER_INVOICED",
        "ORDER_INVOICING",
    ]
    for candidate_id in ids_to_try:
        filters = [
            {"property": "entitiesToReturn", "value": ["customer", "contact"]},
            {"property": "customerId", "value": candidate_id},
            {"property": "status", "value": status_values},
        ]
        params = {
            "page": 1,
            "start": 0,
            "limit": limit,
            "filter": _build_filter(filters),
            "sort": _build_sort([{"property": "orderDate", "direction": "DESC"}]),
        }
        res = _api_get_optional("/order/", params=params)
        if not res:
            continue
        items, _ = _extract_list(res, "order")
        orders.extend(item for item in items if isinstance(item, dict))

    return _dedupe_by_id(orders)


def _case_summary(case: dict) -> dict:
    return {
        "id": case.get("id"),
        "serialNumber": case.get("serialNumber"),
        "subject": case.get("subject"),
        "status": case.get("status"),
        "priority": case.get("priority"),
        "typeKey": case.get("typeKey"),
        "created": case.get("created"),
        "updated": case.get("updated"),
        "dueDate": case.get("dueDate"),
        "customerId": case.get("customerId"),
        "customer": _customer_summary(case.get("customer") or {}),
        "contactId": case.get("contactId"),
        "assignedUser": _name_from_person(case.get("user")),
        "description": _clean_value(case.get("description", ""), 6000),
        "notes": _clean_value(case.get("notes", ""), 3000),
    }


def _get_case_data_by_serial(serial_number: int) -> dict:
    try:
        return json.loads(get_case_by_serial(serial_number))
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_case_details(case_id: int) -> str:
    """
    Gets the full details of a specific case by its ID, including all comments and attachments.
    
    Args:
        case_id: The numeric ID of the case to retrieve.
    """
    result = _api_get(f"/customercase/{case_id}")
    data = result.get("customercase") or result.get("data")
    if data:
        if isinstance(data, list):
            data = data[0] if data else {}
            
        try:
            filt = [{"property": "model", "value": "Customercase"}, {"property": "fk", "value": case_id}]
            filt_str = json.dumps(filt, separators=(",", ":"))
            sorts = [{"property": "created", "direction": "ASC"}]
            sorts_str = json.dumps(sorts, separators=(",", ":"))
            
            relations_res = _api_get("/relation/", params={"filter": filt_str, "sort": sorts_str})
            relations = relations_res.get("relation") or relations_res.get("data") or []
            
            # Sort chronologically by created timestamp
            relations = list(relations)
            relations.sort(key=lambda x: x.get("created") or "")
            
            formatted_relations = []
            for r in relations:
                cleaned_note = clean_html(r.get("note", ""))
                created_by = r.get("createdBy") or {}
                author_name = created_by.get("name", "") if isinstance(created_by, dict) else str(created_by)
                
                formatted_relations.append({
                    "id": r.get("id"),
                    "type": r.get("type"),
                    "subtype": r.get("subtype"),
                    "created": r.get("created"),
                    "author": author_name,
                    "note": cleaned_note,
                    "docarchivefile": r.get("docarchivefile"),
                    "status": r.get("status")
                })
                
            data["relation"] = formatted_relations
            
            # Construct a structured timeline
            timeline = []
            
            # 1. Case creation event
            case_created = data.get("created")
            case_author = (data.get("createdBy") or {}).get("name", "") if isinstance(data.get("createdBy"), dict) else str(data.get("createdBy"))
            case_desc = clean_html(data.get("description", ""))
            if not case_desc:
                case_desc = "(Skriv beskrivelse her)"
                
            timeline.append({
                "timestamp": case_created,
                "author": case_author,
                "type": "CREATION",
                "content": case_desc
            })
            
            # 2. Add relations
            for r in formatted_relations:
                content = r["note"]
                if r["type"] == "ATTACHMENT" and r["docarchivefile"]:
                    file_info = r["docarchivefile"]
                    filename = file_info.get("title") or file_info.get("name") or "Unnamed file"
                    content = f"[Vedlegg: {filename}] {content}".strip()
                    
                timeline.append({
                    "timestamp": r["created"],
                    "author": r["author"],
                    "type": r["type"],
                    "content": content
                })
                
            data["timeline"] = timeline
            
        except Exception as e:
            data["relation_error"] = str(e)
            
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)



@mcp.tool()
def get_case_by_serial(serial_number: int) -> str:
    """
    Finds and retrieves the full details of a specific case by its serialNumber (e.g. 43255).
    Performs a client-side paginated scan internally if needed.
    
    Args:
        serial_number: The numeric serial number of the case to retrieve.
    """
    _mark_case_read(serial_number)
    global _user_id
    if _user_id is None:
        _get_session()

    target_serial = str(serial_number)

    # Super fast path: filter directly by serialNumber in the API request
    try:
        filters = [{"property": "serialNumber", "value": int(serial_number)}]
        params = {
            "page": 1,
            "start": 0,
            "limit": 10,
            "filter": _build_filter(filters),
        }
        result = _api_get("/customercase/", params=params)
        cases, _ = _extract_list(result, "customercase")
        for case in cases:
            if str(case.get("serialNumber")) == target_serial:
                case_id = case.get("id")
                return get_case_details(case_id)
    except Exception:
        pass

    # Fast path: cases assigned to the logged-in user. Some older assigned cases
    # show up here but are missed by the global newest-first scan below.
    if _user_id is not None:
        for status_filter in ("ACTIVE", "ALL"):
            filters = [{"property": "userId", "value": _user_id}]
            if status_filter != "ALL":
                filters.append({"property": "status", "value": status_filter})

            params = {
                "page": 1,
                "start": 0,
                "limit": 1000,
                "filter": _build_filter(filters),
                "sort": _build_sort([{"property": "updated", "direction": "DESC"}]),
            }
            result = _api_get("/customercase/", params=params)
            cases, _ = _extract_list(result, "customercase")
            for case in cases:
                if str(case.get("serialNumber")) == target_serial:
                    case_id = case.get("id")
                    return get_case_details(case_id)

    # Global search across every case, regardless of assigned user.
    #
    # Two XSALE API quirks make the obvious approaches fail silently:
    #   * A filter on serialNumber is IGNORED. The API answers with the
    #     unfiltered result set and an unchanged total, so the "super fast path"
    #     above only ever succeeds by coincidence.
    #   * A filter of status="ALL" matches NOTHING. "ALL" is not a real status
    #     value, so the previous implementation paginated through 100 empty
    #     pages and then reported "not found" for every case it did not own.
    #     Omitting the status filter searches all statuses, which is the intent.
    #
    # Sorting by serialNumber IS honoured, and descending it is strictly
    # monotonic across pages. That lets us binary search rather than scan, so a
    # lookup costs ~log2(pages) requests instead of a capped linear walk.
    limit = 100
    sorts = [{"property": "serialNumber", "direction": "DESC"}]

    def _fetch_page(page_number):
        params = {
            "page": page_number,
            "start": (page_number - 1) * limit,
            "limit": limit,
            "sort": _build_sort(sorts),
        }
        result = _api_get("/customercase/", params=params)
        return _extract_list(result, "customercase")

    def _match(page_cases):
        for case in page_cases:
            if str(case.get("serialNumber")) == target_serial:
                return case.get("id")
        return None

    try:
        target_int = int(serial_number)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid serialNumber: {serial_number!r}"}, indent=2)

    cases, total = _fetch_page(1)
    if not cases:
        return json.dumps({"error": "Case list request returned no cases."}, indent=2)

    case_id = _match(cases)
    if case_id:
        return get_case_details(case_id)

    last_page = max(1, (int(total or 0) + limit - 1) // limit)
    low, high = 1, last_page

    # Serial numbers are densely packed, so interpolate the likely page from how
    # far the target sits below the highest serial instead of probing the middle.
    # This usually lands on the right page immediately. Each request costs real
    # seconds against this API, so it is worth the arithmetic. Binary search
    # takes over from the second probe onwards, which keeps it correct even if
    # the numbering has large gaps.
    page_serials = [int(c.get("serialNumber") or 0) for c in cases]
    guess = 1 + (max(page_serials) - target_int) // limit
    next_probe = min(max(guess, low), high)

    while low <= high:
        if next_probe is not None:
            mid = next_probe
            next_probe = None
        else:
            mid = (low + high) // 2
        page_cases, _ = _fetch_page(mid)
        if not page_cases:
            high = mid - 1
            continue

        case_id = _match(page_cases)
        if case_id:
            return get_case_details(case_id)

        serials = [int(c.get("serialNumber") or 0) for c in page_cases]
        if min(serials) > target_int:
            low = mid + 1
        elif max(serials) < target_int:
            high = mid - 1
        else:
            # The serial falls inside this page's range but is not present,
            # so it does not exist at all. No point continuing.
            break

    return json.dumps({"error": f"Case with serialNumber {serial_number} not found."}, indent=2)


@mcp.tool()
def get_case_communications(serial_number: int, include_activities: bool = True) -> str:
    """
    Gets communication/history for a case by serial number.

    This combines the normal XSALE relation timeline with the activity log,
    which is where sent e-mail metadata/body often appears.

    Args:
        serial_number: The visible XSALE case number, e.g. 42152.
        include_activities: Include activity log enrichment. Default True.
    """
    _mark_case_read(serial_number)
    case = _get_case_data_by_serial(serial_number)
    if case.get("error"):
        return json.dumps(case, indent=2, ensure_ascii=False)

    case_id = case.get("id")
    relations = case.get("relation") or []
    formatted_relations = []
    for relation in relations:
        if isinstance(relation, dict):
            formatted_relations.append({
                "id": relation.get("id"),
                "type": relation.get("type"),
                "subtype": relation.get("subtype"),
                "created": relation.get("created"),
                "author": relation.get("author"),
                "note": relation.get("note"),
                "status": relation.get("status"),
                "attachment": relation.get("docarchivefile") or relation.get("attachment"),
            })

    if case_id:
        extra_relations = _get_relations_for_model("Customercase", int(case_id))
        formatted_relations = _dedupe_by_id(formatted_relations + extra_relations)

    activities = _get_activities_for_model("Customercase", int(case_id)) if include_activities and case_id else []

    return json.dumps({
        "case": _case_summary(case),
        "replyTo": case.get("replyTo"),
        "relations": formatted_relations,
        "activities": activities,
        "timeline": case.get("timeline") or [],
    }, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def get_customer_details(customer_id: int) -> str:
    """
    Gets customer-card details from XSALE.

    The input can normally be the internal customer ID from a case. The tool
    also attempts serialNumber lookup when possible.

    Args:
        customer_id: XSALE customer ID or visible customer serial number.
    """
    customer = _get_customer_raw(customer_id)
    if not customer:
        return json.dumps({"error": f"Customer {customer_id} not found."}, indent=2, ensure_ascii=False)

    internal_id = customer.get("id") or customer_id
    relations = _get_relations_for_model("Customer", int(internal_id)) if internal_id else []
    activities = _get_activities_for_model("Customer", int(internal_id)) if internal_id else []

    return json.dumps({
        "customer": _customer_summary(customer),
        "relations": relations,
        "activities": activities,
        "rawCustomer": customer,
    }, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def get_customer_timeline(customer_id: int) -> str:
    """
    Gets notes, comments, call log/activity and communication history for a customer card.

    Args:
        customer_id: XSALE customer ID or visible customer serial number.
    """
    customer = _get_customer_raw(customer_id)
    if not customer:
        return json.dumps({"error": f"Customer {customer_id} not found."}, indent=2, ensure_ascii=False)

    internal_id = customer.get("id") or customer_id
    relations = _get_relations_for_model("Customer", int(internal_id)) if internal_id else []
    activities = _get_activities_for_model("Customer", int(internal_id)) if internal_id else []

    return json.dumps({
        "customer": _customer_summary(customer),
        "relations": relations,
        "activities": activities,
    }, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def get_customer_orders(customer_id: int, limit: int = 100) -> str:
    """
    Lists orders connected to a customer.

    Args:
        customer_id: XSALE customer ID or visible customer serial number.
        limit: Maximum orders to return. Default 100.
    """
    customer = _get_customer_raw(customer_id)
    orders = _get_orders_for_customer(customer_id, limit=limit)

    return json.dumps({
        "customer": _customer_summary(customer) if customer else {"input": customer_id},
        "total": len(orders),
        "orders": [_order_summary(order) for order in orders],
    }, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def get_order_details(order_id: int, include_activities: bool = True) -> str:
    """
    Gets order details, order lines/raw order data, relation history and activity log.

    The input can be the internal order ID or the visible order number when the
    API can resolve it.

    Args:
        order_id: XSALE internal order ID or visible order serial number.
        include_activities: Include activity log enrichment. Default True.
    """
    order = _get_order_raw(order_id)
    if not order:
        return json.dumps({"error": f"Order {order_id} not found."}, indent=2, ensure_ascii=False)

    internal_id = order.get("id") or order_id
    relations = _get_relations_for_model("Order", int(internal_id)) if internal_id else []
    activities = _get_activities_for_model("Order", int(internal_id)) if include_activities and internal_id else []

    return json.dumps({
        "order": _order_summary(order),
        "relations": relations,
        "activities": activities,
        "rawOrder": order,
    }, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def get_installation_context(serial_number: int) -> str:
    """
    Gets a production/installations context bundle for one XSALE case.

    Includes case summary, customer card, customer orders, case communications
    and likely related order details. Read-only.

    Args:
        serial_number: The visible XSALE case number, e.g. 42152.
    """
    _mark_case_read(serial_number)
    case = _get_case_data_by_serial(serial_number)
    if case.get("error"):
        return json.dumps(case, indent=2, ensure_ascii=False)

    customer_id = case.get("customerId")
    customer = _get_customer_raw(int(customer_id)) if customer_id else {}
    orders = _get_orders_for_customer(int(customer_id), limit=100) if customer_id else []

    relation_order_ids = set()
    for relation in case.get("relation") or []:
        if not isinstance(relation, dict):
            continue
        file_info = relation.get("docarchivefile") or {}
        url_parts = [
            str(file_info.get("url") or ""),
            str(file_info.get("name") or ""),
            str(file_info.get("title") or ""),
        ] if isinstance(file_info, dict) else []
        for value in url_parts:
            for match in re.findall(r"/order/(\d+)", value):
                relation_order_ids.add(int(match))

    likely_orders = []
    known_ids = set()
    for order in orders:
        order_id = order.get("id")
        serial = order.get("serialNumber")
        if order_id in relation_order_ids or str(serial or "") in str(case.get("description") or ""):
            likely_orders.append(order)
            if order_id:
                known_ids.add(order_id)

    for order_id in relation_order_ids:
        if order_id in known_ids:
            continue
        order = _get_order_raw(order_id)
        if order:
            likely_orders.append(order)

    case_activities = _get_activities_for_model("Customercase", int(case.get("id"))) if case.get("id") else []
    customer_relations = _get_relations_for_model("Customer", int(customer.get("id"))) if customer.get("id") else []
    customer_activities = _get_activities_for_model("Customer", int(customer.get("id"))) if customer.get("id") else []

    return json.dumps({
        "case": _case_summary(case),
        "replyTo": case.get("replyTo"),
        "customer": _customer_summary(customer) if customer else None,
        "customerRelations": customer_relations,
        "customerActivities": customer_activities,
        "caseRelations": case.get("relation") or [],
        "caseActivities": case_activities,
        "customerOrders": [_order_summary(order) for order in orders],
        "likelyRelatedOrders": [
            {
                "summary": _order_summary(order),
                "rawOrder": order,
                "relations": _get_relations_for_model("Order", int(order.get("id"))) if order.get("id") else [],
            }
            for order in _dedupe_by_id(likely_orders)
        ],
    }, indent=2, ensure_ascii=False, default=str)






# --- Autonominivaa ---------------------------------------------------------
#
# Fire nivåer, ikke en av/på-bryter. Begrunnelsen er empirisk: i uke 38/2026
# ville tre av mine egne utkast vært feil om de gikk ut automatisk.
#
#   Lille Lov  - "synken har feilet siden midten av august". Feil. Loggen forer
#                bare feil, så fravær av feil var ikke suksess.
#   Hany Metry - "BAX-prosedyren finnes ikke dokumentert". Feil. Den laa i
#                Confluence, oppdatert to uker for.
#   Sak 48404  - omfanget var et underanslag presentert som et funn.
#
# Monsteret er ikke at agenten er uforsiktig, men at den var SIKKER OG FEIL.
# Interne kommentarer er reversible og trygge; en e-post til en regnskapsforer
# er ikke. Derfor skiller nivåene på hvor langt ut handlingen rekker.
#
# Lukking har sitt eget minefelt: sak 38306 ble lukket med "migrert til ny
# platform" mens fem av seks meldte punkter var uverifiserte. Kunden hadde da
# vært misfornøyd i et år.

AUTONOMY_LEVELS = ("les", "kommenter", "svar", "full")
AUTONOMY_DESC = {
    "les": "bare lesing - alle skrivinger avvises",
    "kommenter": "interne kommentarer; kundesvar og lukking krever godkjenning",
    "svar": "interne kommentarer og kundesvar; lukking krever godkjenning",
    "full": "også lukking - helautonomt",
}
DEFAULT_AUTONOMY = "les"
MAX_AUTONOMOUS_ACTIONS = 20

AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "autonomy_audit.log")

_autonomy = None
_actions_done = 0
_cases_read = set()


def autonomy():
    global _autonomy
    if _autonomy is None:
        v = (os.getenv("XSALE_AUTONOMY") or DEFAULT_AUTONOMY).strip().lower()
        _autonomy = v if v in AUTONOMY_LEVELS else DEFAULT_AUTONOMY
    return _autonomy


def _audit(handling, serial, detaljer):
    """Skriver hver skrivehandling til logg. Grunnlaget for mandagsrapporten.

    En helgekjoring skal ikke bare ha handtert saker - den skal kunne gjøre
    rede for hva som ble gjort, hvorfor, og hva den lot være å røre.
    """
    try:
        with io.open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tid": time.strftime("%Y-%m-%d %H:%M:%S"),
                "nivaa": autonomy(),
                "handling": handling,
                "sak": serial,
                "detaljer": detaljer,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _mark_case_read(serial):
    """Kalles av leseverktøyene. Grunnlaget for sperren mot å skrive blindt."""
    try:
        _cases_read.add(int(serial))
    except (TypeError, ValueError):
        pass


def _krev_nivaa(handling, kreves, serial):
    """None hvis handlingen er tillatt, ellers en forklarende feiltekst."""
    na = autonomy()
    if AUTONOMY_LEVELS.index(na) < AUTONOMY_LEVELS.index(kreves):
        _audit(handling + ":AVVIST", serial, "nivå %s < %s" % (na, kreves))
        return json.dumps({
            "utfort": False,
            "arsak": "autonominivaa",
            "handling": handling,
            "naavaerende_nivaa": na,
            "kreves": kreves,
            "forklaring": (
                "Nivået er '%s' (%s). Handlingen '%s' krever '%s'. Brukeren kan "
                "heve nivået med set_autonomy('%s'), eller godkjenne denne "
                "ene handlingen manuelt."
                % (na, AUTONOMY_DESC[na], handling, kreves, kreves)),
        }, indent=2, ensure_ascii=False)

    if _actions_done >= MAX_AUTONOMOUS_ACTIONS:
        _audit(handling + ":TAK", serial, "%d handlinger" % _actions_done)
        return json.dumps({
            "utfort": False,
            "arsak": "handlingstak",
            "forklaring": (
                "Taket på %d skrivehandlinger per kjøring er nådd. Det er en "
                "sperre mot at en løkke spiser køen. Start en ny kjøring, "
                "eller hev MAX_AUTONOMOUS_ACTIONS bevisst."
                % MAX_AUTONOMOUS_ACTIONS),
        }, indent=2, ensure_ascii=False)

    if serial is not None and int(serial) not in _cases_read:
        _audit(handling + ":ULEST", serial, "saken er ikke lest i kjoringen")
        return json.dumps({
            "utfort": False,
            "arsak": "saken er ikke lest",
            "forklaring": (
                "Sak %s er ikke hentet i denne kjøringen. Les den med "
                "get_case_by_serial eller get_case_communications først. Å "
                "skrive til en sak man ikke har lest er nettopp hvordan sak "
                "38306 ble lukket med fem uverifiserte punkter." % serial),
        }, indent=2, ensure_ascii=False)
    return None


@mcp.tool()
def get_autonomy() -> str:
    """Viser gjeldende autonominivå og hva det tillater."""
    return json.dumps({
        "nivaa": autonomy(),
        "betyr": AUTONOMY_DESC[autonomy()],
        "nivaaer": AUTONOMY_DESC,
        "handlinger_utfort_denne_kjoringen": _actions_done,
        "tak_per_kjoring": MAX_AUTONOMOUS_ACTIONS,
        "saker_lest_denne_kjoringen": sorted(_cases_read),
        "revisjonslogg": AUDIT_LOG,
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def set_autonomy(level: str, begrunnelse: str = "") -> str:
    """Setter autonominivå. SKAL bare kalles når brukeren ber om det.

    Nivaaene, fra minst til mest inngripende:
      les       - bare lesing
      kommenter - interne kommentarer
      svar      - også svar til kunde
      full      - også lukking av saker

    Args:
        level: Ett av nivåene over.
        begrunnelse: Kort grunn, f.eks. "helgevakt 21.-22.09". Loggfores.
    """
    global _autonomy
    v = str(level or "").strip().lower()
    if v not in AUTONOMY_LEVELS:
        return json.dumps({
            "endret": False,
            "error": "Ukjent nivå %r. Gyldige: %s"
                     % (level, ", ".join(AUTONOMY_LEVELS)),
        }, indent=2, ensure_ascii=False)
    forrige = autonomy()
    _autonomy = v
    _audit("set_autonomy", None, "%s -> %s (%s)" % (forrige, v, begrunnelse))
    return json.dumps({
        "endret": True,
        "fra": forrige,
        "til": v,
        "betyr": AUTONOMY_DESC[v],
        "begrunnelse": begrunnelse,
        "merknad": ("Nivået gjelder bare denne kjøringen. Sett "
                    "XSALE_AUTONOMY i config.env for å gjøre det varig."),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def autonomy_report() -> str:
    """Rapport over skrivehandlinger fra revisjonsloggen.

    Ment som mandagsrapporten etter en helgekjoring: hva ble gjort, hva ble
    avvist, og hvorfor.
    """
    if not os.path.exists(AUDIT_LOG):
        return json.dumps({"linjer": 0,
                           "merknad": "Ingen skrivehandlinger er loggfort."},
                          indent=2, ensure_ascii=False)
    rader = []
    with io.open(AUDIT_LOG, encoding="utf-8") as fh:
        for ln in fh:
            try:
                rader.append(json.loads(ln))
            except Exception:
                pass
    utfort = [r for r in rader if ":" not in r.get("handling", "")]
    avvist = [r for r in rader if ":" in r.get("handling", "")]
    return json.dumps({
        "totalt_loggfort": len(rader),
        "utfort": len(utfort),
        "avvist": len(avvist),
        "siste_50": rader[-50:],
    }, indent=2, ensure_ascii=False)


# --- Kunderegister -------------------------------------------------------
#
# XSALEs API respekterer id-filtre (customerId, userId) og IGNORERER tekst-
# filtre - stille. Maalt 21.09.2026: query/name/serialNumber mot /customer/ og
# query/subject/serialNumber mot /customercase/ returnerer alle hele tabellen,
# som om filteret var tomt. Det er derfor search_cases aldri har virket: den ba
# om et filtrert sett, fikk 45 632 rader, filtrerte de første 50 klientsiden og
# falt så tilbake til bare innlogget brukers egne saker.
#
# Losningen er et lokalt navn -> customerId-register, bygget ved paginering.
# Deretter er customerId-filteret bade raskt og komplett: 10 saker på 2,6 s.

CUSTOMER_INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "customer_index.json")
_customer_index = None


def _load_customer_index():
    """(kunder, metadata) eller (None, feiltekst)."""
    global _customer_index
    if _customer_index is not None:
        return _customer_index, None
    if not os.path.exists(CUSTOMER_INDEX_PATH):
        return None, ("Kunderegisteret mangler (%s). Bygg det med "
                      "rebuild_customer_index()." % CUSTOMER_INDEX_PATH)
    try:
        with io.open(CUSTOMER_INDEX_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:
        return None, "Kunderegisteret kunne ikke leses: %s" % e
    _customer_index = d
    return d, None


def _ordmengde(s):
    return {o for o in re.split(r"[^\wæøåÆØÅ]+", str(s or "").casefold()) if o}


def _match_kunder(behov, kunder, maks=12):
    """Kunder som matcher soketeksten.

    Tre nivåer, i rekkefolge: eksakt navn, delstreng, og ordmengde. Det siste
    fordi kundenavn i XSALE varierer i form - "MRM AS" mot "Ming Restaurant" -
    og eksakt navnematch derfor bommer oftere enn den treffer.
    """
    b = str(behov or "").strip().casefold()
    if not b:
        return []
    bo = _ordmengde(b)

    eksakt, delstreng, ordvis = [], [], []
    for c in kunder:
        navn = str(c.get("navn") or "").casefold()
        felt = " ".join([navn, str(c.get("epost") or "").casefold(),
                         str(c.get("orgnr") or ""), str(c.get("serial") or "")])
        if navn == b:
            eksakt.append(c)
        elif b in felt:
            delstreng.append(c)
        elif bo and bo <= _ordmengde(felt):
            ordvis.append(c)
    return (eksakt + delstreng + ordvis)[:int(maks or 12)]


def _cases_for_customer(customer_id, status="ALL", limit=100):
    filters = [{"property": "customerId", "value": int(customer_id)}]
    if status and status != "ALL":
        filters.append({"property": "status", "value": status})
    r = _api_get("/customercase/", params={
        "page": 1, "start": 0, "limit": limit,
        "filter": _build_filter(filters),
        "sort": _build_sort([{"property": "updated", "direction": "DESC"}])})
    saker, tot = _extract_list(r, "customercase")
    return saker, tot


@mcp.tool()
def find_customer(query: str, limit: int = 12) -> str:
    """Finner en kunde på navn, e-post, org.nr eller kundenummer.

    Bruker det lokale kunderegisteret, fordi XSALEs egne tekstfiltre ikke
    virker. Returnerer kandidater med customerId, som er den eneste nøkkelen
    saksfiltrene respekterer.

    Args:
        query: Navn, e-post, organisasjonsnummer eller kundenummer.
        limit: Maks antall kandidater.
    """
    d, feil = _load_customer_index()
    if feil:
        return json.dumps({"error": feil}, indent=2, ensure_ascii=False)
    treff = _match_kunder(query, d.get("kunder") or [], maks=limit)
    return json.dumps({
        "query": query,
        "registeret_bygget": d.get("bygget"),
        "kunder_i_registeret": d.get("antall_i_registeret"),
        "antall_treff": len(treff),
        "treff": treff,
        "merknad": ("Ingen treff i registeret. Det betyr at ingen kunde har "
                    "denne teksten i navn, e-post, org.nr eller kundenummer - "
                    "ikke at saken ikke finnes. Er registeret gammelt, bygg "
                    "det på nytt med rebuild_customer_index()."
                    if not treff else None),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def rebuild_customer_index() -> str:
    """Bygger kunderegisteret på nytt ved å paginere gjennom /customer/.

    Tar rundt 25 sekunder for ca. 15 600 kunder. Kjor den når en ny kunde
    ikke finnes i find_customer.
    """
    global _customer_index
    SIDE = 1000
    alle, sett, side, forrige_forste, totalt = {}, set(), 0, None, None
    while side < 60:
        r = _api_get("/customer/", params={
            "page": side + 1, "start": side * SIDE, "limit": SIDE,
            "sort": _build_sort([{"property": "id", "direction": "ASC"}])})
        rader, tot = _extract_list(r, "customer")
        if totalt is None:
            totalt = tot
        if not rader:
            break
        # Et start-parameter som ignoreres ville gitt identiske sider og et
        # register med 1000 kunder som ser komplett ut. Stopp hoyt i stedet.
        if rader[0].get("id") == forrige_forste:
            return json.dumps({
                "built": False,
                "error": ("Pagineringen flytter seg ikke - side %d starter på "
                          "samme kunde som forrige. Registeret ville blitt "
                          "ufullstendig, så ingenting er lagret." % (side + 1)),
            }, indent=2, ensure_ascii=False)
        forrige_forste = rader[0].get("id")
        for c in rader:
            cid = c.get("id")
            if cid is None or cid in sett:
                continue
            sett.add(cid)
            alle[str(cid)] = {
                "id": cid, "serial": c.get("serialNumber"),
                "navn": c.get("name") or "", "epost": c.get("email") or "",
                # Feltet heter orgno i XSALE. organizationNumber og
                # orgNumber finnes ikke, så registeret lagret tom streng og
                # org.nr-sok falt gjennom til en 53-sekunders skanning.
                "orgnr": c.get("orgno") or "",
                "status": c.get("status") or "",
            }
        if len(rader) < SIDE:
            break
        side += 1

    d = {
        "bygget": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "totalt_meldt_av_xsale": totalt,
        "antall_i_registeret": len(alle),
        "dekning_prosent": round(len(alle) / float(totalt or 1) * 100, 1),
        "kunder": list(alle.values()),
    }
    with io.open(CUSTOMER_INDEX_PATH, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    _customer_index = d
    return json.dumps({k: v for k, v in d.items() if k != "kunder"},
                      indent=2, ensure_ascii=False)


@mcp.tool()
def search_cases(query: str, status: str = "ALL", limit: int = 50) -> str:
    """Finner saker på kundenavn, saksnummer, e-post eller org.nr.

    XSALEs egne tekstfiltre virker ikke (målt 21.09.2026: query, subject og
    serialNumber returnerer alle hele saksmengden). Soket går derfor i tre
    trinn, og rapporterer alltid hvilket som ble brukt:

      1. Ser teksten ut som et saksnummer -> hent saken direkte.
      2. Slaa opp kunden i det lokale registeret -> hent sakene via
         customerId, som er et filter XSALE faktisk respekterer. Komplett.
      3. Fritekst uten kundetreff -> avgrenset skanning av de sist oppdaterte
         sakene, med eksplisitt rapport om hvor mye som ble gjennomsokt.

    Et tomt svar sier ALLTID hva som ble sokt og hvor langt. Et "0 treff" som
    kan forveksles med et faktum er verre enn en feilmelding - det var nettopp
    slik den gamle versjonen meldte at en kunde med ti saker ikke fantes.

    Args:
        query: Kundenavn, saksnummer, e-post eller organisasjonsnummer.
        status: "ACTIVE", "CLOSED" eller "ALL" (standard).
        limit: Maks antall saker.
    """
    q = str(query or "").strip()
    if not q:
        return json.dumps({"error": "query er paakrevd."}, indent=2)

    # --- 1. saksnummer ---------------------------------------------------
    if re.fullmatch(r"\d{4,6}", q):
        sak = json.loads(get_case_by_serial(int(q)))
        if "error" not in sak:
            return json.dumps({
                "metode": "saksnummer",
                "query": q,
                "total": 1,
                "cases": _format_cases([sak]),
            }, indent=2, ensure_ascii=False)

    # --- 2. via kunderegisteret ------------------------------------------
    d, reg_feil = _load_customer_index()
    kandidater = _match_kunder(q, (d or {}).get("kunder") or []) if d else []

    if len(kandidater) == 1:
        k = kandidater[0]
        saker, tot = _cases_for_customer(k["id"], status=status, limit=limit)
        return json.dumps({
            "metode": "kunderegister -> customerId",
            "query": q,
            "kunde": k,
            "status_filter": status,
            "total": tot,
            "komplett": True,
            "cases": _format_cases(saker),
        }, indent=2, ensure_ascii=False)

    if len(kandidater) > 1:
        return json.dumps({
            "metode": "kunderegister",
            "query": q,
            "total": 0,
            "flere_kunder_matchet": kandidater,
            "merknad": ("Flere kunder matcher. Kall search_cases på nytt med "
                        "et mer presist navn, eller bruk customerId-en "
                        "direkte via list_cases_for_customer."),
        }, indent=2, ensure_ascii=False)

    # --- 3. avgrenset fritekstskanning -----------------------------------
    needle = q.casefold()

    def haystack(case):
        kunde = case.get("customer") or {}
        kontakt = case.get("contact") or {}
        return " ".join([
            str(case.get("serialNumber") or ""),
            case.get("subject") or "", case.get("description") or "",
            kunde.get("name", "") if isinstance(kunde, dict) else "",
            kontakt.get("name", "") if isinstance(kontakt, dict) else "",
            kontakt.get("email", "") if isinstance(kontakt, dict) else "",
        ]).casefold()

    SIDE, MAKS_SIDER = 1000, 3
    sett, skannet, totalt_meldt = [], 0, None
    for side in range(MAKS_SIDER):
        filtre = []
        if status and status != "ALL":
            filtre.append({"property": "status", "value": status})
        r = _api_get("/customercase/", params={
            "page": side + 1, "start": side * SIDE, "limit": SIDE,
            "filter": _build_filter(filtre) if filtre else _build_filter([]),
            "sort": _build_sort([{"property": "updated", "direction": "DESC"}])})
        rader, tot = _extract_list(r, "customercase")
        if totalt_meldt is None:
            totalt_meldt = tot
        if not rader:
            break
        skannet += len(rader)
        sett += [c for c in rader if needle in haystack(c)]
        if len(sett) >= limit or len(rader) < SIDE:
            break

    svar = {
        "metode": "avgrenset fritekstskanning",
        "query": q,
        "status_filter": status,
        "skannet_saker": skannet,
        "totalt_i_xsale": totalt_meldt,
        "komplett": skannet >= (totalt_meldt or 0),
        "total": len(sett[:limit]),
        "cases": _format_cases(sett[:limit]),
    }
    if reg_feil:
        svar["register_advarsel"] = reg_feil
    if not sett:
        svar["merknad"] = (
            "0 TREFF - men bare %s av %s saker ble gjennomsøkt, sortert på "
            "sist oppdatert. Dette er IKKE bevis for at saken ikke finnes. "
            "Kjenner du kunden, bruk find_customer og deretter "
            "list_cases_for_customer - den veien er komplett."
            % (skannet, totalt_meldt))
    return json.dumps(svar, indent=2, ensure_ascii=False)


@mcp.tool()
def list_cases_for_customer(customer_id: int, status: str = "ALL",
                            limit: int = 100) -> str:
    """Alle saker på en kunde. Komplett, via customerId.

    Dette er den eneste søke-veien i XSALE som er bade rask og fullstendig,
    fordi customerId er et filter API-et faktisk respekterer. Bruk
    find_customer for å finne id-en.

    Args:
        customer_id: XSALE-kundens interne id (ikke kundenummeret).
        status: "ACTIVE", "CLOSED" eller "ALL" (standard).
        limit: Maks antall saker.
    """
    saker, tot = _cases_for_customer(customer_id, status=status, limit=limit)
    navn = {(c.get("customer") or {}).get("name") for c in saker}
    return json.dumps({
        "customer_id": customer_id,
        "kundenavn": sorted(n for n in navn if n),
        "status_filter": status,
        "total": tot,
        "komplett": True,
        "cases": _format_cases(saker),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def list_case_types() -> str:
    """Lists all available case types in XSALE CRM."""
    result = _api_get("/account/case_type/", params={
        "page": 1,
        "start": 0,
        "limit": 999999,
        "sort": _build_sort([{"property": "sort", "direction": "ASC"}]),
    })
    types, _ = _extract_list(result, "caseType")
    return json.dumps(types, indent=2, ensure_ascii=False)


@mcp.tool()
def list_inbound_emails(limit: int = 50) -> str:
    """
    Lists recent inbound emails received in XSALE.
    
    Args:
        limit: Maximum number of emails to return. Default: 50.
    """
    params = {
        "page": 1,
        "start": 0,
        "limit": limit,
        "sort": _build_sort([{"property": "created", "direction": "DESC"}]),
        "filter": _build_filter([
            {"property": "mailboxes", "value": ""},
            {"property": "mailType", "value": ""},
        ]),
    }
    result = _api_get("/email/inbound/", params=params)
    emails, total = _extract_list(result, "inbound")

    formatted = []
    for email in emails:
        formatted.append({
            "id": email.get("id"),
            "from": email.get("fromEmail", email.get("from", "")),
            "subject": email.get("subject", ""),
            "created": email.get("created", ""),
            "status": email.get("status", ""),
            "customerName": email.get("customerName", ""),
        })

    return json.dumps({"total": total, "showing": len(formatted), "emails": formatted}, indent=2, ensure_ascii=False)


@mcp.tool()
def get_logged_user() -> str:
    """Gets information about the currently logged-in XSALE user."""
    result = _api_get("/user/get_logged_user")
    data = result.get("user") or result.get("data") or {}
    if isinstance(data, dict) and data.get("id"):
        return json.dumps({
            "id": data.get("id"),
            "name": data.get("name", data.get("fullName", "")),
            "fullName": data.get("fullName", ""),
            "email": data.get("email"),
            "role": data.get("role", data.get("roleName", "")),
        }, indent=2, ensure_ascii=False)
    return json.dumps(result, indent=2, ensure_ascii=False)


def _text_signature(s) -> str:
    """Tekstinnholdet i et HTML-felt, normalisert for sammenligning.

    Brukes til å verifisere at en skrevet kommentar faktisk ligger på saken.
    Vi sender HTML og XSALE normaliserer den videre, så rå strengsammenligning
    treffer aldri. Ved å fjerne tagger, dekode entiteter og kollapse mellomrom
    sammenligner vi det mennesket ser.
    """
    t = re.sub(r"<[^>]+>", " ", str(s or ""))
    t = html_mod.unescape(t)
    t = t.replace("\u00a0", " ")
    t = re.sub(r"\s+", " ", t)
    # Taggen gir et mellomrom der XSALE kanskje ikke har ett: "<b>Jalal</b>,"
    # blir "Jalal ,". Skilletegn limes derfor tilbake mot ordet foran.
    t = re.sub(r"\s+([,.;:!?%)\]])", r"\g<1>", t)
    t = re.sub(r"([(\[])\s+", r"\g<1>", t)
    return t.strip().casefold()


# Ord som bare finnes fordi noen har skrevet norsk uten ae, oe og å.
# Listen er bevisst kort og entydig: ingen av dem er engelske ord, og ingen
# av dem er riktige norske ord. "lost" og "mate" står med vilje IKKE her -
# de er vanlige engelske ord og ville gitt falske treff.
TRANSLITTERERT_NORSK = {
    "uroert": "urørt", "urort": "urørt", "utfort": "utført",
    "utfores": "utføres", "sporsmal": "spørsmål", "arsak": "årsak",
    "arsaken": "årsaken", "maned": "måned", "maneden": "måneden",
    "overforing": "overføring", "overfort": "overført",
    "dagsoppgjor": "dagsoppgjør", "oppgjor": "oppgjør",
    "gjor": "gjør", "gjore": "gjøre", "kjop": "kjøp", "kjope": "kjøpe",
    "kjoper": "kjøper", "lopende": "løpende", "forsok": "forsøk",
    "forsoke": "forsøke", "vaere": "være", "paa": "på", "naa": "nå",
    "maa": "må", "blabar": "blåbær", "apen": "åpen", "apne": "åpne",
    "apnet": "åpnet", "forst": "først", "ogsa": "også", "ogsaa": "også",
    "formalet": "formålet", "formal": "formål", "pamindelse": "påminnelse",
    "paminnelse": "påminnelse", "tilbakeforing": "tilbakeføring",
    "lost": None, "loste": "løste", "innforing": "innføring",
    "godtgjorelse": "godtgjørelse", "sporre": "spørre", "sporres": "spørres",
    "storrelse": "størrelse", "okning": "økning", "okt": "økt",
    "arsrapport": "årsrapport", "arsoppgjor": "årsoppgjør",
    "manedlig": "månedlig", "onsker": "ønsker", "onsket": "ønsket",
    "nodvendig": "nødvendig", "mulighet": None, "lonn": "lønn",
    "soke": "søke", "sokes": "søkes", "begrunnelse": None,
    # Forledd daekkes ikke av suffiksregelen, saa de vanligste
    # regnskapsordene staar eksplisitt.
    "arsberetning": "årsberetning", "arsberetningen": "årsberetningen",
    "arsregnskap": "årsregnskap", "arsregnskapet": "årsregnskapet",
    "paminnelser": "påminnelser", "palopte": "påløpte",
    "pavirker": "påvirker", "pakrevd": "påkrevd",
}
# Noen oppforinger over er None fordi de ER riktige ord - de står der bare
# for at listen ikke skal vokse feil vei senere. De filtreres bort her.
TRANSLITTERERT_NORSK = {k: v for k, v in TRANSLITTERERT_NORSK.items() if v}

# Suffikser for sammensatte ord. "skriveverktoy" fanges ikke av en
# hele-ord-liste, og sammensetning er normen i norsk fagsjargong. Hvert
# suffiks er entydig: ingen engelske ord ender slik.
TRANSLITTERERT_SUFFIKS = {
    "verktoy": "verktøy", "oppgjor": "oppgjør", "sporsmal": "spørsmål",
    "arsak": "årsak", "maned": "måned", "belop": "beløp",
    "gebyr": None, "loype": "løype", "tilgjengelig": None,
    "innstilling": None, "overforing": "overføring", "gjennomforing":
    "gjennomføring", "utforing": "utføring", "storrelse": "størrelse",
    "lonn": "lønn", "okning": "økning", "onske": "ønske",
    "nivaa": "nivå", "nivaaet": "nivået", "nivaaer": "nivåer",
}
TRANSLITTERERT_SUFFIKS = {k: v for k, v in TRANSLITTERERT_SUFFIKS.items() if v}


# Smaaord som finnes i all norsk prosa og ikke trenger ae, oe eller å.
# Brukes til å kjenne igjen norsk tekst som mistenkelig mangler dem helt.
_NORSKE_SMAAORD = ("og", "er", "ikke", "som", "det", "til", "med", "har",
                   "kan", "den", "at", "vi", "de", "et", "en", "av", "om")


def _finn_transliterert_norsk(tekst):
    """Ord som ser ut som norsk skrevet uten ae, oe og å.

    Returnerer (funn, mistenkelig_uten_tegn) der funn er en liste av
    (feilstavet, riktig) og det andre er True når teksten ser norsk ut og
    ikke har ett enkelt aeoea i seg.
    """
    raa = _text_signature(tekst)
    ord_ = re.findall(r"[a-zæøå]+", raa)
    funn = []
    sett = set()
    for o in ord_:
        if o in sett:
            continue
        if o in TRANSLITTERERT_NORSK:
            sett.add(o)
            funn.append((o, TRANSLITTERERT_NORSK[o]))
            continue
        for suff, riktig in TRANSLITTERERT_SUFFIKS.items():
            # Bare sammensetninger: selve ordet står i hovedlisten.
            if o.endswith(suff) and len(o) > len(suff):
                sett.add(o)
                funn.append((o, o[:-len(suff)] + riktig))
                break

    har_tegn = any(c in raa for c in "æøå")
    norske = sum(1 for o in set(ord_) if o in _NORSKE_SMAAORD)
    mistenkelig = ((not har_tegn) and norske >= 4
                   and (len(raa) >= 200 or bool(funn)))
    return funn, mistenkelig


def _norskvarsel(tekst):
    """Advarselsobjekt, eller None når teksten ser greit ut."""
    funn, mistenkelig = _finn_transliterert_norsk(tekst)
    if not funn and not mistenkelig:
        return None
    ut = {}
    if funn:
        ut["feilstavede_ord"] = ["%s -> %s" % (a, b) for a, b in funn]
    if mistenkelig:
        ut["ingen_aeoeaa"] = (
            "Teksten ser norsk ut og inneholder ikke ett enkelt ae, oe eller "
            "aa. Det er nesten alltid transliterering.")
    ut["forklaring"] = (
        "XSALE lagrer æ, ø og å byte-identisk - målt på 558 og 457 tegn "
        "21.09.2026. Det er ingen grunn til å transliterere. Skriv norsk "
        "med riktige tegn.")
    return ut


def _to_xsale_html(text, raw_html=False):
    """Gjor ren tekst klar for XSALE sine note- og description-felter.

    Feltene lagres og rendres som HTML. Et vanlig linjeskift kollapser derfor
    til et mellomrom, og et notat skrevet med avsnitt vises som en eneste
    sammenhengende blokk i grensesnittet. Escaper teksten og gjør linjeskift
    til <br>, slik at notatet leses slik det ble skrevet.

    raw_html=True sender teksten urørt, for de gangene formatering er onsket.
    """
    if raw_html:
        return text
    return _markdown_to_xsale_html(text)


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _inline(s: str) -> str:
    """Escaper teksten og oversetter **fet** og `kode`.

    Bevisst smalt utvalg. Enkel stjerne som kursiv er utelatt, fordi «5 * 3»
    og «a*b» da ville blitt formatert ved et uhell. Fet og kode er det jeg
    faktisk bruker, og begge har entydige avgrensere.
    """
    s = _esc(s)
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(?=\S)(.+?)(?<=\S)`", r"<code>\1</code>", s)
    # markdown-lenke [tekst](url) -> klikkbar, men bare http(s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               r'<a href="\2">\1</a>', s)
    return s


def _markdown_to_xsale_html(text) -> str:
    """Oversetter markdown til den HTML-en XSALE faktisk rendrer.

    XSALE lagrer note- og description-felter som HTML. Den gamle versjonen
    escapet alt og gjorde bare linjeskift til <br>, og da ble et strukturert
    notat staaende som ren tekst: «**fet**» viste stjernene, en punktliste
    viste bindestreker, og en tabell ble en vegg av roer. Det er den «rare
    formateringen» kunden så i en paapensak.

    Stotter det jeg faktisk skriver: overskrifter, fet, kode, lenker,
    punktlister, nummererte lister, tabeller og skillelinjer. Alt annet
    escapes og beholder linjeskiftene sine.
    """
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    linjer = s.split("\n")
    ut = []
    i, n = 0, len(linjer)

    def er_tabellrad(l):
        return l.strip().startswith("|") and l.strip().endswith("|")

    def celler(l):
        return [c.strip() for c in l.strip().strip("|").split("|")]

    while i < n:
        l = linjer[i]
        strippet = l.strip()

        # tom linje -> avsnittsskille
        if not strippet:
            if ut and not ut[-1].endswith(("</ul>", "</ol>", "</table>",
                                           "<hr>", "<br><br>")):
                ut.append("<br>")
            i += 1
            continue

        # skillelinje
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", strippet):
            ut.append("<hr>")
            i += 1
            continue

        # overskrift -> fet linje. XSALE-notatfeltet er smalt, så <h2> blir
        # unodig stort; fet + linjeskift leser bedre i praksis.
        m = re.match(r"^(#{1,6})\s+(.*)$", strippet)
        if m:
            ut.append("<b>%s</b><br>" % _inline(m.group(2)))
            i += 1
            continue

        # tabell: minst en rad, og neste linje er en skillerad
        if er_tabellrad(l) and i + 1 < n and re.fullmatch(
                r"\|[\s:|-]+\|", linjer[i + 1].strip()):
            hode = celler(l)
            i += 2
            rader = []
            while i < n and er_tabellrad(linjer[i]):
                rader.append(celler(linjer[i]))
                i += 1
            t = ['<table border="1" cellpadding="4" cellspacing="0">']
            t.append("<tr>%s</tr>" % "".join(
                "<th align=\"left\">%s</th>" % _inline(c) for c in hode))
            for r in rader:
                t.append("<tr>%s</tr>" % "".join(
                    "<td>%s</td>" % _inline(c) for c in r))
            t.append("</table>")
            ut.append("".join(t))
            continue

        # punktliste
        if re.match(r"^[-*]\s+\S", strippet):
            punkter = []
            while i < n and re.match(r"^[-*]\s+\S", linjer[i].strip()):
                punkter.append(re.sub(r"^[-*]\s+", "", linjer[i].strip()))
                i += 1
            ut.append("<ul>%s</ul>" % "".join(
                "<li>%s</li>" % _inline(p) for p in punkter))
            continue

        # nummerert liste
        if re.match(r"^\d+[.)]\s+\S", strippet):
            punkter = []
            while i < n and re.match(r"^\d+[.)]\s+\S", linjer[i].strip()):
                punkter.append(re.sub(r"^\d+[.)]\s+", "", linjer[i].strip()))
                i += 1
            ut.append("<ol>%s</ol>" % "".join(
                "<li>%s</li>" % _inline(p) for p in punkter))
            continue

        # vanlig tekstlinje
        ut.append(_inline(l) + "<br>")
        i += 1

    html = "".join(ut)

    # Luft etter blokkelementer. Uten dette klistrer neste avsnitt seg til
    # tabellen eller lista - og naar XSALE vasker taggene for
    # tidslinjevisningen smelter ordene sammen: «hardt mellomromFeltet
    # orgno». Maalt paa sak 48638 og paa e-posten slik Outlook viser den.
    html = re.sub(r"(</ul>|</ol>|</table>|<hr>)(?!<br>|$)",
                  r"\g<1><br>", html)

    html = re.sub(r"(<br>){3,}", "<br><br>", html)
    return re.sub(r"(<br>)+$", "", html)

EMAIL_ENTITY_KEYS = {"mailer", "headers", "bcc", "cc", "action"}


def _looks_like_email_entity(ref) -> bool:
    """Skiller en e-postentitet fra saken eller en relasjon.

    Aktivitetens changelog inneholder modelReference-objekter av flere slag.
    E-postene kjennes igjen pa at de har flere av mailer/headers/bcc/cc/action.
    """
    if not isinstance(ref, dict):
        return False
    return len(EMAIL_ENTITY_KEYS & set(ref.keys())) >= 3


def _header_field(headers, name):
    if not headers:
        return ""
    m = re.search(rf"^{re.escape(name)}:\s*(.+)$", str(headers), re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _get_email_by_id(email_id):
    """Henter en e-post i sin helhet.

    Aktivitetslista avkutter body og headers til 200 tegn. Enkeltoppslaget gir
    hele innholdet. Merk at /email/ MED FILTER ignorerer filteret og returnerer
    en tilfeldig e-post - bruk alltid /email/{id}.
    """
    try:
        result = _api_get(f"/email/{int(email_id)}")
    except Exception:
        return None
    entity = _extract_entity(result, "email")
    if not entity and isinstance(result, dict):
        entity = result.get("email") or result
    return entity if isinstance(entity, dict) else None


@mcp.tool()
def get_case_emails(serial_number: int, include_bodies: bool = True) -> str:
    """
    Gets the actual e-mails on a case, including what WE sent to the customer.

    The relation timeline stores outbound e-mails with an empty note, so the
    text of our own replies is invisible in get_case_details and
    get_case_communications. This tool finds the e-mail entities in the
    activity log and reads each one in full.

    Direction is taken from the activity route: "/email/send" is a reply we
    sent to the customer. Everything else is an inbound message or an internal
    notification copy.

    LIMIT: the activity log has a retention window. Cases older than roughly a
    couple of months return no activities at all, and then no e-mails can be
    recovered. The response says so explicitly rather than looking empty.

    Args:
        serial_number: The case serial number, e.g. 47126.
        include_bodies: Read each e-mail in full. Costs one request per e-mail.
            False returns only sender, receiver, subject and direction.
    """
    _mark_case_read(serial_number)
    case = json.loads(get_case_by_serial(serial_number))
    if case.get("error"):
        return json.dumps(case, indent=2, ensure_ascii=False)
    case_id = case.get("id")
    if not case_id:
        return json.dumps({"error": f"Case {serial_number} has no internal id."}, indent=2)

    try:
        raw = _api_get("/activity/", params={
            "page": 1, "start": 0, "limit": 200,
            "filter": _build_filter([{"property": "model", "value": "Customercase"},
                                     {"property": "fk", "value": int(case_id)}]),
            "sort": _build_sort([{"property": "created", "direction": "ASC"}]),
        })
        activities, _total = _extract_list(raw, "activity")
    except Exception as e:
        return json.dumps({
            "serialNumber": serial_number,
            "error": f"Could not read the activity log: {e}",
        }, indent=2, ensure_ascii=False)

    emails = []
    seen = set()
    for activity in activities:
        route = str(activity.get("route") or "")
        refs = []
        for change in activity.get("changelog") or []:
            if isinstance(change, dict):
                refs.append(change.get("modelReference"))
        refs.append(activity.get("modelReference"))

        for ref in refs:
            if not _looks_like_email_entity(ref):
                continue
            email_id = ref.get("id")
            if not email_id or email_id in seen:
                continue
            seen.add(email_id)

            full = _get_email_by_id(email_id) if include_bodies else None
            source = full or ref
            headers = source.get("headers") or ref.get("headers") or ""

            entry = {
                "id": email_id,
                "sent_at": activity.get("created") or source.get("created"),
                "direction": "outbound" if route == "/email/send" else "inbound_or_notice",
                "route": route,
                "sender": source.get("sender") or _header_field(headers, "From"),
                "receiver": source.get("receiver") or _header_field(headers, "To"),
                "subject": source.get("subject") or _header_field(headers, "Subject"),
            }
            for field in ("cc", "bcc"):
                if source.get(field):
                    entry[field] = source[field]
            if include_bodies:
                entry["body"] = clean_html(source.get("body") or "")
                entry["body_truncated_by_api"] = full is None
            emails.append(entry)

    emails.sort(key=lambda e: str(e.get("sent_at") or ""))
    outbound = [e for e in emails if e["direction"] == "outbound"]

    return json.dumps({
        "serialNumber": serial_number,
        "case_id": case_id,
        "subject": case.get("subject"),
        "activities_found": len(activities),
        "emails_found": len(emails),
        "outbound_found": len(outbound),
        "note": (
            "No activities on this case. The activity log has a retention "
            "window, so e-mails on older cases cannot be recovered this way."
            if not activities else
            "Outbound entries are replies we sent. The rest are inbound "
            "messages or internal notification copies of them."
        ),
        "emails": emails,
    }, indent=2, ensure_ascii=False, default=str)


# ──────────────────────────────────────────────
# WRITE TOOLS
#
# Everything above this point is read-only. These two tools change data in
# XSALE, and they act as the logged-in user, so that user's name appears as the
# author. They are deliberately narrow: creating a case and adding an internal
# comment. Closing, reopening, deleting, changing status and sending email are
# NOT implemented - CLAUDE.md requires an explicit instruction for those, and
# the field values involved have not been verified against the API.
#
# The unattended Auto-XSALE job cannot reach these tools: run-auto-xsale.ps1
# passes an explicit --allowedTools whitelist containing only read tools.
# ──────────────────────────────────────────────


@mcp.tool()
def create_case(
    customer_id: int,
    subject: str,
    description: str,
    contact_id: int = 0,
    type_key: str = "KEY_2",
    priority: str = "NORMAL",
    status: str = "NEW",
    origin: str = "PHONE",
    user_id: int = 0,
    raw_html: bool = False,
) -> str:
    """
    Creates a new case in XSALE. WRITES DATA - only use when explicitly asked to.

    The case is created as the logged-in user, so that user is recorded as author
    and owner unless user_id says otherwise. After creating, the case is read back
    from XSALE and returned, so the caller can verify what actually landed.

    Args:
        customer_id: XSALE internal customer id (not the customer number).
        subject: Case subject line.
        description: Case description body.
        contact_id: Optional contact id on the customer.
        type_key: Case type key. Default "KEY_2" (SUPPORT). See list_case_types().
        priority: "LOW", "NORMAL" or "HIGH". Default "NORMAL".
        status: Initial status. Default "NEW".
        origin: How the case arrived, e.g. "PHONE" or "EMAIL". Default "PHONE".
        user_id: Owner. Defaults to the logged-in user.
        raw_html: XSALE stores the description as HTML, so plain newlines
            collapse and a multi-line description renders as one solid block.
            By default the text is escaped and line breaks become <br>. Pass
            True only to send markup through untouched.
    """
    global _user_id

    if not str(subject).strip():
        return json.dumps({"error": "subject is required."}, indent=2)
    if not str(description).strip():
        return json.dumps({"error": "description is required."}, indent=2)
    if not customer_id:
        return json.dumps({"error": "customer_id is required."}, indent=2)

    if _user_id is None:
        _get_session()
    owner = user_id or _user_id
    if not owner:
        return json.dumps(
            {"error": "Could not determine the logged-in user id."}, indent=2)

    payload = {
        "customerId": int(customer_id),
        "subject": subject,
        "description": _to_xsale_html(description, raw_html),
        "typeKey": type_key,
        "priority": priority,
        "status": status,
        "userId": str(owner),
    }
    if contact_id:
        payload["contactId"] = int(contact_id)
    if origin:
        payload["origin"] = origin

    result = _api_post("/customercase/", payload=payload)

    if isinstance(result, dict) and result.get("success") is False:
        return json.dumps({
            "created": False,
            "error": "XSALE rejected the case.",
            "message": result.get("message"),
            "errors": result.get("errors"),
            "sent_payload": payload,
        }, indent=2, ensure_ascii=False)

    created = _extract_entity(result, "customercase")
    case_id = created.get("id")

    # XSALE does not return serialNumber in the create response, only the
    # internal id. Read the case back to get it - callers need the serial
    # number, since that is what everyone refers to a case by.
    verified = None
    if case_id:
        try:
            verified = json.loads(get_case_details(int(case_id)))
        except Exception:
            verified = None

    serial = (verified or {}).get("serialNumber") or created.get("serialNumber")

    return json.dumps({
        "created": True,
        "case_id": case_id,
        "serialNumber": serial,
        "subject": (verified or created).get("subject"),
        "status": (verified or created).get("status"),
        "priority": (verified or created).get("priority"),
        "typeKey": (verified or created).get("typeKey"),
        "owner": ((verified or created).get("user") or {}).get("fullName"),
        "customer": ((verified or created).get("customer") or {}).get("name"),
        "sent_payload": payload,
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def add_case_comment(serial_number: int, note: str, raw_html: bool = False) -> str:
    """
    Adds an internal comment to an XSALE case. WRITES DATA - only use when
    explicitly asked to.

    The comment is stored as an INTERNAL relation, which is what the XSALE UI
    creates for "Add internal comment". It is recorded as written by the
    logged-in user.

    Only internal comments are supported. A customer-visible comment uses a
    different relation type whose value has not been verified against the API,
    and guessing it could put the wrong text in front of a customer.

    Args:
        serial_number: The case serial number, e.g. 46700.
        note: The comment text.
        raw_html: XSALE stores the note as HTML, so plain newlines collapse and
            a multi-line note renders as one solid block. By default the text is
            escaped and line breaks become <br>. Pass True only to send markup
            through untouched.
    """
    if not str(note).strip():
        return json.dumps({"error": "note is required."}, indent=2)

    nekt = _krev_nivaa("add_case_comment", "kommenter", serial_number)
    if nekt:
        return nekt

    case = json.loads(get_case_by_serial(serial_number))
    if "error" in case:
        return json.dumps({
            "added": False,
            "error": f"Could not find case {serial_number}: {case['error']}",
        }, indent=2, ensure_ascii=False)

    case_id = case.get("id")
    if not case_id:
        return json.dumps({
            "added": False,
            "error": f"Case {serial_number} has no internal id.",
        }, indent=2)

    payload = {
        "model": "customercase",
        "fk": int(case_id),
        "relModel": "",
        "type": "INTERNAL",
        "subtype": "",
        "note": _to_xsale_html(note, raw_html),
        "status": "ACTIVE",
    }

    result = _api_post("/relation/0", payload=payload,
                       params={"saveAsInternal": "true"})

    if isinstance(result, dict) and result.get("success") is False:
        return json.dumps({
            "added": False,
            "error": "XSALE rejected the comment.",
            "message": result.get("message"),
            "errors": result.get("errors"),
            "sent_payload": payload,
        }, indent=2, ensure_ascii=False)

    # Read the case back and confirm the note is actually on it.
    #
    # The comparison has to be on text content, not on the raw strings: we send
    # HTML (the note is converted before the POST) and XSALE may normalise it
    # further. Comparing the stored HTML against the original plain text never
    # matched, so verified_on_case was reported false on comments that had in
    # fact landed — a false alarm that made a successful write look failed.
    landed = False
    author = None
    # Les relasjonen RAATT. get_case_details kjorer note gjennom clean_html,
    # som stripper taggene og limer tabellcellene sammen, så en
    # sammenligning mot den meldte false på kommentarer som la helt riktig.
    # Malt pa kastesak 48638 21.09.2026.
    sendt = payload["note"]
    forventet = _text_signature(sendt)
    for rel in _raa_relasjoner(case_id):
        if rel.get("type") != "INTERNAL":
            continue
        lagret = rel.get("note") or ""
        if lagret == sendt or _text_signature(lagret) == forventet:
            landed = True
            author = _name_from_person(rel.get("createdBy")
                                       or rel.get("author") or {})
            break

    global _actions_done
    _actions_done += 1
    varsel = _norskvarsel(note)
    _audit("add_case_comment", serial_number,
           "verifisert=%s, %d tegn%s"
           % (landed, len(str(note)),
              ", TRANSLITTERERT NORSK" if varsel else ""))

    return json.dumps({
        "added": True,
        "verified_on_case": landed,
        "sprakadvarsel": varsel,
        "serialNumber": serial_number,
        "case_id": case_id,
        "author": author,
        "note": note,
    }, indent=2, ensure_ascii=False)


# --- Svar til kunde og statusendring --------------------------------------
#
# Rutene og feltnavnene under er LEST UT av XSALE sin egen aktivitetslogg
# (/activity/, feltet route og changelog.groupedDiff), ikke gjettet. Malt
# 21.09.2026 pa 626 aktiviteter:
#
#   POST /email/send                       35 treff, model=Customercase
#   POST /customercase/<id>?sendEmail=false  statusendring, felt "status"
#
# Merk sendEmail=false: grensesnittet sender den eksplisitt. Uten den kan en
# statusendring varsle kunden pa e-post.

CASE_STATUSES = ("NEW", "ASSIGNED", "FEEDBACK", "ON_HOLD", "COMPLETED")
CLOSED_STATUS = "COMPLETED"


def _ser_ut_som_messageid(adresse):
    """True for Message-ID-er som regexen forveksler med e-postadresser.

    Malt på sak 48578 og 47910: inboundEmail inneholder headere, og en
    Message-ID har samme form som en adresse. Kjennetegnene er en lang
    heksadesimal lokaldel, eller et maskingenerert Exchange-domene.
    """
    a = str(adresse or "").lower()
    if "@" not in a:
        return True
    lokal, _, domene = a.partition("@")
    if len(lokal) >= 24 and re.fullmatch(r"[0-9a-f]+", lokal):
        return True
    if re.search(r"\.prod\.(outlook|exchangelabs)\.com$", domene):
        return True
    if re.fullmatch(r"[a-z]{2,4}\d?pr\d+mb\d+\..*", domene):
        return True
    return False


# Domenene vaare. En adresse herfra er oss, ikke en kunde, og skal aldri
# kunne bli mottaker av et kundesvar.
#
# amendo.no staar med fordi det er det gamle merkenavnet og fortsatt i bruk i
# eldre saker. Den innloggede brukerens eget domene legges til dynamisk, saa
# listen foelger med om firmaet bytter domene igjen.
EGNE_DOMENER = {"plorea.com", "amendo.no", "done.ai"}

# Lokaldeler som er funksjonspostkasser, ikke personer.
FUNKSJONSADRESSER = {"support", "noreply", "no-reply", "postmaster",
                     "mailer-daemon", "bounce"}


_egne_domener_cache = None


def _egne_domener():
    """Domenene som er oss. Caches - dette kalles per adresse.

    Forste versjon slo opp get_logged_user() hver gang, altsaa ett
    nettverkskall per kandidatadresse i en loekke. Maalt 22.09.2026: fem
    saker tok over sju minutter i stedet for sekunder.
    """
    global _egne_domener_cache
    if _egne_domener_cache is None:
        d = set(EGNE_DOMENER)
        try:
            egen = (json.loads(get_logged_user()) or {}).get("email") or ""
            if "@" in egen:
                d.add(egen.split("@", 1)[1].strip().lower())
        except Exception:
            pass
        _egne_domener_cache = d
    return _egne_domener_cache


def _er_egen_adresse(adresse):
    """True for adresser som er OSS, ikke kunden.

    Malt 22.09.2026: uten denne ble support@plorea.com valgt som mottaker paa
    sak 48638, og meldt som «siste innkommende» paa tre andre saker - fordi
    interne varselkopier av vaar egen utgaaende post klassifiseres som
    innkommende.
    """
    a = str(adresse or "").strip().lower()
    if "@" not in a:
        return False
    lokal, _, domene = a.partition("@")
    if domene in _egne_domener():
        return True
    if lokal in FUNKSJONSADRESSER:
        return True
    return False


# Mottakerkilder i fallende prioritet. Jalals regel 22.09.2026:
# kontaktpersonen er den autoritative mottakeren, og kundekortet er reserven
# for saker uten kontakt-e-post.
#
# Bekreftet paa sak 48661, der kontaktpersonen og kundekortet har ULIKE
# domener (albatrossfitness.no mot albatrossenter.no) og kollegaen sendte til
# kontaktpersonens adresse.
MOTTAKER_PRIORITET = (
    "kontaktperson",
    "siste innkommende",
    "e-post paa saken",
    "kundekortet",
    "kundekortets fakturaadresse",
)


def _case_kontakt(detalj):
    """Kontaktpersonen som er knyttet til saken, eller None.

    Saken peker med contactId inn i kundens kontaktliste. Er contactId null,
    er det ingen kontakt paa saken selv om kunden har flere registrert.
    """
    kid = detalj.get("contactId")
    if not kid:
        return None
    for c in ((detalj.get("customer") or {}).get("contacts") or []):
        if str(c.get("id")) == str(kid):
            return c
    return None


def _case_epostadresser(serial_number, case_id=None):
    """Adressene som hoerer til saken, med kilde, i fallende prioritet.

    Rekkefoelgen staar i MOTTAKER_PRIORITET og er uttalt med vilje - den laa
    tidligere implisitt i hvilken kilde som ble lest foerst.

    En sak som kom inn per telefon og mangler kontakt-e-post har bare
    kundekortet. 48423 og 48556 er slike.
    """
    kilder = {}

    def legg_til(verdi, kilde):
        for bit in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", str(verdi or "")):
            a = bit.strip().lower()
            # Vaare egne inbound-adresser er ruting, ikke mottakere.
            if ".inbound.xsale.no" in a:
                continue
            if _ser_ut_som_messageid(a):
                continue
            # Egne adresser beholdes for aa kunne gjenkjennes av sperren, men
            # merkes «oss» - en kilde som ikke staar i MOTTAKER_PRIORITET og
            # derfor aldri velges som mottaker.
            merke = "oss" if _er_egen_adresse(a) else kilde
            if a not in kilder:
                kilder[a] = merke
            elif kilder[a] == "oss" and merke != "oss":
                kilder[a] = merke

    detalj = {}
    try:
        detalj = json.loads(get_case_details(int(case_id))) if case_id else {}
    except Exception:
        detalj = {}

    # 1. Kontaktpersonen paa saken - hoyeste prioritet.
    kontakt = _case_kontakt(detalj)
    if kontakt:
        legg_til(kontakt.get("email"), "kontaktperson")

    # 2. Den som sist skrev inn. Man svarer i en traad til avsenderen.
    try:
        poster = (json.loads(get_case_emails(serial_number)) or {}).get(
            "emails", []) or []
    except Exception:
        poster = []
    # Bare EKSTERNE avsendere. Interne varselkopier av vaar egen utgaaende
    # post kommer tilbake som «inbound_or_notice», og uten dette filteret ble
    # support@plorea.com meldt som «den som sist skrev inn».
    innkommende = [e for e in poster
                   if str(e.get("direction") or "") != "outbound"
                   and not _er_egen_adresse(e.get("sender"))]
    for e in reversed(innkommende):
        legg_til(e.get("sender"), "siste innkommende")

    # 3. Resten av korrespondansen.
    for e in poster:
        legg_til(e.get("sender"), "e-post paa saken")
        legg_til(e.get("receiver"), "e-post paa saken")

    # 4. Kundekortet - reserven naar kontakten mangler e-post.
    kunde = detalj.get("customer") or {}
    legg_til(kunde.get("email"), "kundekortet")
    legg_til(kunde.get("invoiceEmail"), "kundekortets fakturaadresse")

    # 5. Ruting, lavest. Tas med for aa kunne gjenkjenne adressen, ikke for
    #    aa sende til den.
    legg_til(detalj.get("replyTo"), "saken sitt replyTo")
    legg_til(detalj.get("inboundEmail"), "saken sin inboundEmail")

    return kilder


def _anbefalt_mottaker(serial_number, case_id=None):
    """Hvem et svar boer gaa til, og hva som taler mot.

    Returnerer (adresse, kilde, konflikt). Konflikt er satt naar den siste
    som skrev inn er en ANNEN enn kontaktpersonen - da velger ikke koden
    stille, den sier fra. I delegert modus er det grunn til aa la saken staa.
    """
    kilder = _case_epostadresser(serial_number, case_id)
    if not kilder:
        return None, None, "saken har ingen e-postadresse i det hele tatt"

    valgt = kilde = None
    for p in MOTTAKER_PRIORITET:
        for a, k in kilder.items():
            if k == p:
                valgt, kilde = a, k
                break
        if valgt:
            break
    if not valgt:
        # Bare ruteadresser igjen. De skal ikke brukes som mottaker.
        return None, None, ("bare ruteadresser paa saken (replyTo/inbound), "
                            "ingen reell mottaker")

    konflikt = None
    sisteinn = [a for a, k in kilder.items() if k == "siste innkommende"]
    if kilde == "kontaktperson" and sisteinn and valgt not in sisteinn:
        konflikt = ("kontaktpersonen er %s, men den som sist skrev inn er %s. "
                    "Avgjor hvem svaret skal til foer du sender."
                    % (valgt, ", ".join(sisteinn)))
    return valgt, kilde, konflikt

@mcp.tool()
def edit_case_comment(serial_number: int, comment_id: int, note: str,
                      raw_html: bool = False, dry_run: bool = True) -> str:
    """
    Corrects an existing internal comment in place. Requires level 'kommenter'.

    Verified on case 48638 21.09.2026: PUT /relation/<id> rewrites the comment
    without creating a new one - the relation count stayed at 7 before and
    after. Use this to fix a typo rather than stacking a correction comment on
    top of it.

    Comment ids come from get_case_details (the relation list).

    Args:
        serial_number: Case serial number, for the read gate and the audit log.
        comment_id: The relation id of the comment to rewrite.
        note: The new text. Markdown is converted, as in add_case_comment.
        raw_html: Pass True to send markup through untouched.
        dry_run: True (default) returns the payload without writing.
    """
    if not str(note).strip():
        return json.dumps({"changed": False, "error": "note is required."},
                          indent=2)

    case = json.loads(get_case_by_serial(serial_number))
    if "error" in case:
        return json.dumps({"changed": False,
                           "error": "Could not find case %s: %s"
                                    % (serial_number, case["error"])},
                          indent=2, ensure_ascii=False)
    case_id = case.get("id")

    gammel = None
    for rel in _raa_relasjoner(case_id):
        if str(rel.get("id")) == str(comment_id):
            gammel = rel
            break
    if gammel is None:
        return json.dumps({
            "changed": False,
            "error": "Comment %s was not found on case %s."
                     % (comment_id, serial_number),
            "kommentarer_paa_saken": [r.get("id")
                                      for r in _raa_relasjoner(case_id)],
        }, indent=2, ensure_ascii=False)

    ny_html = _to_xsale_html(note, True) if raw_html \
        else _markdown_to_xsale_html(note)
    payload = {
        "id": int(comment_id),
        "model": "customercase",
        "fk": int(case_id),
        "type": gammel.get("type") or "INTERNAL",
        "subtype": gammel.get("subtype") or "",
        "note": ny_html,
        "status": gammel.get("status") or "ACTIVE",
    }

    if dry_run:
        return json.dumps({
            "changed": False,
            "dry_run": True,
            "metode": "PUT",
            "route": "/relation/%d" % int(comment_id),
            "gammel_note": gammel.get("note"),
            "ny_note": ny_html,
            "sprakadvarsel": _norskvarsel(note),
        }, indent=2, ensure_ascii=False)

    nekt = _krev_nivaa("edit_case_comment", "kommenter", serial_number)
    if nekt:
        return nekt

    for_antall = len(_raa_relasjoner(case_id))
    result = _api_put("/relation/%d" % int(comment_id), payload=payload,
                      params={"saveAsInternal": "true"})
    if isinstance(result, dict) and result.get("success") is False:
        _audit("edit_case_comment:AVVIST_AV_XSALE", serial_number,
               result.get("message"))
        return json.dumps({
            "changed": False,
            "error": "XSALE rejected the edit.",
            "message": result.get("message"),
            "sent_payload": payload,
        }, indent=2, ensure_ascii=False)

    # Les tilbake rått, og sjekk at det ikke ble laget en ny relasjon.
    etter = _raa_relasjoner(case_id)
    landed = False
    for rel in etter:
        if str(rel.get("id")) == str(comment_id):
            landed = (rel.get("note") or "") == ny_html
            break

    global _actions_done
    _actions_done += 1
    varsel = _norskvarsel(note)
    _audit("edit_case_comment", serial_number,
           "kommentar %s, verifisert=%s%s"
           % (comment_id, landed,
              ", TRANSLITTERERT NORSK" if varsel else ""))

    return json.dumps({
        "changed": landed,
        "comment_id": comment_id,
        "serialNumber": serial_number,
        "antall_kommentarer_for": for_antall,
        "antall_kommentarer_etter": len(etter),
        "ny_kommentar_laget": len(etter) != for_antall,
        "sprakadvarsel": varsel,
        "merknad": ("" if landed else
                    "Kommentaren leses ikke tilbake som forventet. "
                    "Kontroller i XSALE."),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def reply_to_customer(serial_number: int, body: str, receiver: str = "",
                      subject: str = "", cc: str = "",
                      sender: str = "", dry_run: bool = True,
                      allow_new_recipient: bool = False,
                      tillat_ascii_norsk: bool = False) -> str:
    """
    Sends an e-mail reply to the customer on an XSALE case. SENDS REAL MAIL.

    Requires autonomy level 'svar' or higher. dry_run defaults to True: the
    exact payload is returned and nothing is sent, so the text and the
    recipient can be checked before anything leaves the building.

    receiver may be left empty, and then it is derived. The rule is Jalal's,
    22.09.2026: the contact person's e-mail is the authoritative recipient,
    and the customer card is the fallback when the contact has none. Verified
    on case 48661, where the two hold DIFFERENT domains
    (albatrossfitness.no vs albatrossenter.no) and the colleague who answered
    sent to the contact person.

    Priority is in MOTTAKER_PRIORITET and is explicit on purpose - it used to
    sit implicitly in whichever source happened to be read first.

    Our own addresses can never be chosen. They stay in the candidate list so
    the guard still recognises them, but under the source "oss". Without that,
    support@plorea.com was picked as the recipient on case 48638, and was
    reported as "the last one who wrote in" on three other cases - XSALE
    returns internal notification copies of our own outbound mail as inbound.

    When the last EXTERNAL sender differs from the contact person, nothing is
    sent. The conflict is reported instead, because the code should not pick
    between two plausible recipients on its own. In delegated mode that is a
    reason to leave the case alone.

    An address that is passed explicitly must still belong to the case, unless
    allow_new_recipient=True. The response names the source in mottaker_kilde
    and says whether it was derived - read both before sending.

    The customer card is reached through the case's own record, not through a
    customer search. XSALE's /customer/ filter has silently returned the wrong
    customer, and an address from there would not be trustworthy.

    Args:
        serial_number: Case serial number, e.g. 48423.
        body: The reply. Markdown is converted to the HTML XSALE renders.
        receiver: Recipient address. Leave empty to derive it by the rule
            above. When given, it is checked against the addresses that
            belong to the case.
        subject: Defaults to "Sv: <case subject> [Sak <serial>]".
        cc: Optional copy recipients.
        sender: Defaults to the logged-in user's address.
        dry_run: True (default) returns the payload without sending.
        allow_new_recipient: Set True to mail an address not on the case.
        tillat_ascii_norsk: Norwegian written without æ, ø and å is refused,
            because it reads as unprofessional to the customer and XSALE
            stores the characters byte-identically anyway. Set True only when
            the text is deliberately English or ASCII.
    """
    if not str(body).strip():
        return json.dumps({"sent": False, "error": "body is required."},
                          indent=2)
    mottaker = str(receiver or "").strip().lower()
    utledet = False

    case = json.loads(get_case_by_serial(serial_number))
    if "error" in case:
        return json.dumps({"sent": False,
                           "error": "Could not find case %s: %s"
                                    % (serial_number, case["error"])},
                          indent=2, ensure_ascii=False)
    case_id = case.get("id")
    if not case_id:
        return json.dumps({"sent": False,
                           "error": "Case %s has no internal id."
                                    % serial_number}, indent=2)

    # Utled mottakeren naar den ikke er oppgitt. I delegert modus finnes det
    # ingen som kan oppgi den, saa regelen maa staa i koden: kontaktpersonen
    # foerst, kundekortet som reserve. Jalals regel 22.09.2026, bekreftet paa
    # sak 48661 der de to adressene har ulike domener.
    if not mottaker:
        anbefalt, anbefalt_kilde, anbefalt_konflikt = _anbefalt_mottaker(
            serial_number, case_id)
        if not anbefalt:
            return json.dumps({
                "sent": False,
                "arsak": "ingen mottaker kunne utledes",
                "forklaring": anbefalt_konflikt,
                "adresser_paa_saken": _case_epostadresser(serial_number,
                                                          case_id),
            }, indent=2, ensure_ascii=False)
        if anbefalt_konflikt:
            return json.dumps({
                "sent": False,
                "arsak": "uklar mottaker",
                "forklaring": anbefalt_konflikt,
                "kontaktperson": anbefalt,
                "adresser_paa_saken": _case_epostadresser(serial_number,
                                                          case_id),
                "merknad": ("Oppgi receiver eksplisitt naar du har avgjort. "
                            "I delegert modus er dette grunn til aa la saken "
                            "staa."),
            }, indent=2, ensure_ascii=False)
        mottaker, utledet = anbefalt, True

    if "@" not in mottaker:
        return json.dumps({"sent": False,
                           "error": "receiver must be an e-mail address."},
                          indent=2)

    kjente = _case_epostadresser(serial_number, case_id)
    if mottaker not in kjente and not allow_new_recipient:
        return json.dumps({
            "sent": False,
            "arsak": "mottaker ikke funnet i saken",
            "receiver": mottaker,
            "adresser_paa_saken": kjente,
            "ingen_epost_paa_saken": not kjente,
            "forklaring": (
                "Adressen hører ikke til sak %s. Kjente adresser er "
                "listet med kilde. Er saken meldt per telefon finnes ingen, "
                "og da må adressen hentes fra kundekortet og sendes med "
                "allow_new_recipient=True." % serial_number),
        }, indent=2, ensure_ascii=False)

    # En kunde som mottar "Formalet er a bekrefte" ser en useriøs avsender.
    # XSALE lagrer æøå byte-identisk - målt på 558 og 457 tegn 21.09.2026 -
    # så transliterering er aldri nødvendig, bare en vane. Internt gir det en
    # advarsel; til kunde blir det stoppet.
    varsel = _norskvarsel(body)
    if varsel and not tillat_ascii_norsk:
        return json.dumps({
            "sent": False,
            "arsak": "transliterert norsk",
            "sprakadvarsel": varsel,
            "forklaring": (
                "Teksten ser ut som norsk skrevet uten æ, ø og å. Skriv den om "
                "med riktige tegn. Er teksten engelsk eller bevisst ASCII, "
                "send med tillat_ascii_norsk=True."),
        }, indent=2, ensure_ascii=False)

    avsender = str(sender or "").strip()
    if not avsender:
        try:
            avsender = (json.loads(get_logged_user()) or {}).get("email") or ""
        except Exception:
            avsender = ""
    if "@" not in avsender:
        return json.dumps({
            "sent": False,
            "error": ("Could not determine the sender address. Pass sender= "
                      "explicitly."),
        }, indent=2)

    emne = str(subject or "").strip()
    if not emne:
        emne = "Sv: %s [Sak %s]" % (case.get("subject") or "", serial_number)

    # Feltnavnene her er trådfeltene, ikke kolonnenavnene i basen.
    # Aktivitetsloggen viser body/receiver/sender fordi det er det LAGREDE
    # navnet; API-et vil ha content og to. Og "to" må være en liste - som
    # streng svarer XSALE "to should not be blank" selv om feltet er fylt ut.
    # Malt på kastesak 48638 21.09.2026.
    payload = _bygg_epost_payload(case_id, emne,
                                  _markdown_to_xsale_html(body),
                                  mottaker, cc)

    if dry_run:
        return json.dumps({
            "sent": False,
            "dry_run": True,
            "sprakadvarsel": _norskvarsel(body),
            "route": "/email/send",
            "payload": payload,
            "avsender_settes_av_xsale": True,
            # mottaker_kilde er den eneste sannhetskilden om mottakeren.
            # Her sto ogsaa mottaker_bekreftet_paa_saken, som var
            # `mottaker in kjente` - men den meldte true ogsaa naar kilden var
            # kundekortet, og mottaker_kilde sier strengt mer: den navngir
            # kilden, eller "ikke paa saken". To felt som kan sprike er verre
            # enn ett. Fjernet 21.09.2026; den hadde ingen konsumenter.
            "mottaker_kilde": kjente.get(mottaker) or "ikke på saken",
            "mottaker_utledet": utledet,
            "merknad": ("Ingenting er sendt. Kall pa nytt med dry_run=False "
                        "for a sende."),
        }, indent=2, ensure_ascii=False)

    nekt = _krev_nivaa("reply_to_customer", "svar", serial_number)
    if nekt:
        return nekt

    result = _api_post("/email/send", payload=payload)
    if isinstance(result, dict) and result.get("success") is False:
        _audit("reply_to_customer:AVVIST_AV_XSALE", serial_number,
               result.get("message"))
        return json.dumps({
            "sent": False,
            "error": "XSALE rejected the e-mail.",
            "message": result.get("message"),
            "errors": result.get("errors"),
            "sent_payload": payload,
        }, indent=2, ensure_ascii=False)

    # Les saken tilbake og bekreft at e-posten faktisk ligger der.
    # Hent e-posten RAATT. get_case_emails kjorer kroppen gjennom clean_html
    # - målt til 522 mot 1002 tegn på e-post 12771211 - og vaskeren limer
    # tabellcellene sammen, så signaturene kan ikke sammenlignes.
    landed, epost_id = False, None
    sendt = payload["content"]
    forventet = _text_signature(sendt)
    try:
        for e in (json.loads(get_case_emails(serial_number)) or {}).get(
                "emails", []) or []:
            if str(e.get("direction") or "") != "outbound":
                continue
            raa = _raa_epost(e.get("id"))
            lagret = raa.get("body") or ""
            if lagret == sendt or _text_signature(lagret) == forventet:
                landed, epost_id = True, e.get("id")
                break
    except Exception:
        pass

    global _actions_done
    _actions_done += 1
    _audit("reply_to_customer", serial_number,
           "til=%s, verifisert=%s, %d tegn" % (mottaker, landed, len(body)))

    return json.dumps({
        "sent": True,
        "verified_on_case": landed,
        "email_id": epost_id,
        "serialNumber": serial_number,
        "case_id": case_id,
        "receiver": mottaker,
        "mottaker_kilde": _case_epostadresser(serial_number, case_id).get(
            mottaker) or "ikke paa saken",
        "mottaker_utledet": utledet,
        "sender": avsender,
        "subject": emne,
        "merknad": ("verified_on_case=false betyr at e-posten ikke ble "
                    "gjenfunnet på saken enda, ikke sikkert at den feilet. "
                    "Kontroller i XSALE." if not landed else ""),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def set_case_status(serial_number: int, status: str, comment: str = "",
                    dry_run: bool = True, notify_customer: bool = False) -> str:
    """
    Changes the status of an XSALE case. WRITES DATA.

    Requires autonomy level 'full'. dry_run defaults to True.

    Valid statuses, measured on 2000 live cases: NEW, ASSIGNED, FEEDBACK,
    ON_HOLD, COMPLETED. Closing a case means COMPLETED.

    Uses PUT, not POST. POST /customercase/<id> ignores the id in the path and
    creates a NEW case, answering success:true with "Sak opprettet" - measured
    three times on TESTKUNDE. The id has to travel in the payload.

    Eleven fields ride along besides status. Omitting priority blanks it;
    omitting customerId gets "Kunne ikke finne kunde". description is
    deliberately not sent - it is unnecessary, and echoing it back is the one
    remaining way to overwrite the case HTML with a cleaned value.

    After writing, every field is read back and compared. Only status may have
    changed; anything else is reported as damage.

    Args:
        serial_number: Case serial number.
        status: One of NEW, ASSIGNED, FEEDBACK, ON_HOLD, COMPLETED.
        comment: Optional internal comment written before the change, so the
            case records why.
        dry_run: True (default) returns the payload without writing.
        notify_customer: False (default) sends ?sendEmail=false, which is what
            the XSALE UI does.

            True sends ?sendEmail=true, and as far as we can measure it does
            NOTHING on a status change. Tested on case 48638 22.09.2026:
            no e-mail record on the case (four before and after), no email
            entity in the activity log, and nothing in the requester's inbox
            - and the requester was also the watcher, so the most likely
            recipient of any notification.

            Do not read `isEmailed` in the activity log as evidence either
            way. It is 1 on all 249 activities checked, regardless of route.

            The parameter is kept because the route accepts it and XSALE may
            use it for other transitions, but do not rely on it to inform a
            customer. Send an actual reply with reply_to_customer instead.
    """
    st = str(status or "").strip().upper()
    if st not in CASE_STATUSES:
        return json.dumps({
            "changed": False,
            "error": "Unknown status %r. Valid: %s"
                     % (status, ", ".join(CASE_STATUSES)),
        }, indent=2, ensure_ascii=False)

    case = json.loads(get_case_by_serial(serial_number))
    if "error" in case:
        return json.dumps({"changed": False,
                           "error": "Could not find case %s: %s"
                                    % (serial_number, case["error"])},
                          indent=2, ensure_ascii=False)
    case_id = case.get("id")
    if not case_id:
        return json.dumps({"changed": False,
                           "error": "Case %s has no internal id."
                                    % serial_number}, indent=2)

    forut = _raa_sak(case_id)
    if not forut:
        return json.dumps({"changed": False,
                           "error": "Could not read case %s raw."
                                    % serial_number}, indent=2)
    fra = forut.get("status")

    # En PUT som setter status til det den allerede er, endrer ingenting og
    # ser like vellykket ut som en ekte endring. close_case pa en sak som alt
    # var COMPLETED gjorde nettopp det - malt 21.09.2026 pa kastesak 48638,
    # der torrkjoringen meldte COMPLETED -> COMPLETED uten a si fra.
    # Kontrollen ligger foran dry_run med vilje: den som torrkjorer skal faa
    # vite at kallet ikke ville endret noe.
    if fra == st:
        har_kommentar = bool(str(comment or "").strip())
        if not dry_run:
            _audit("set_case_status:UENDRET", serial_number,
                   "sto allerede i %s" % st)
        return json.dumps({
            "changed": False,
            "allerede_i_status": True,
            "fra_status": fra,
            "til_status": st,
            "serialNumber": serial_number,
            "case_id": int(case_id),
            "kommentar_skrevet": False,
            "merknad": (
                "Saken står allerede i %s. Ingen PUT er sendt. %s"
                % (st, "Kommentaren er ikke skrevet - bruk add_case_comment "
                       "hvis den likevel skal inn." if har_kommentar
                       else "Ingen kommentar var oppgitt.")),
        }, indent=2, ensure_ascii=False)

    payload = _bygg_status_payload(forut, st)
    payload["id"] = int(case_id)
    params = {"sendEmail": "true" if notify_customer else "false"}

    if dry_run:
        return json.dumps({
            "changed": False,
            "dry_run": True,
            "metode": "PUT",
            "route": "/customercase/%d" % int(case_id),
            "params": params,
            "payload": payload,
            "fra_status": fra,
            "til_status": st,
            "merknad": ("Ingenting er endret. Kall pa nytt med dry_run=False."),
        }, indent=2, ensure_ascii=False)

    nekt = _krev_nivaa("set_case_status", "full", serial_number)
    if nekt:
        return nekt

    if str(comment or "").strip():
        add_case_comment(serial_number, comment)

    result = _api_put("/customercase/%d" % int(case_id),
                      payload=payload, params=params)
    if isinstance(result, dict) and result.get("success") is False:
        _audit("set_case_status:AVVIST_AV_XSALE", serial_number,
               result.get("message"))
        return json.dumps({
            "changed": False,
            "error": "XSALE rejected the status change.",
            "message": result.get("message"),
            "errors": result.get("errors"),
            "sent_payload": payload,
        }, indent=2, ensure_ascii=False)

    # Les hele posten tilbake. "success" alene er ikke bevis - POST svarte
    # success:true på noe helt annet enn det jeg ba om.
    etter = _raa_sak(case_id) or {}
    hopp = ("updated", "updatedBy", "updatedByExternalContact",
            "updatedByExternalCustomer", "updatedByExternalFk",
            "updatedByExternalModel")
    endret = sorted(k for k in set(forut) | set(etter)
                    if k not in hopp and forut.get(k) != etter.get(k))
    uventet = [k for k in endret if k != "status"]
    blanket = [k for k in uventet
               if forut.get(k) not in (None, "", [], {})
               and etter.get(k) in (None, "", [], {})]

    global _actions_done
    _actions_done += 1
    _audit("set_case_status", serial_number,
           "%s -> %s, lest tilbake %s, uventet %s"
           % (fra, st, etter.get("status"), uventet or "ingen"))

    ok = etter.get("status") == st and not uventet
    return json.dumps({
        "changed": ok,
        "fra_status": fra,
        "til_status": st,
        "lest_tilbake": etter.get("status"),
        "serialNumber": serial_number,
        "case_id": case_id,
        "endrede_felt": endret,
        "uventet_endret": uventet,
        "blankede_felt": blanket,
        "notify_customer": notify_customer,
        "merknad": ("" if ok else
                    "Kontroller saken i XSALE. Status leses som %r, og disse "
                    "feltene endret seg uventet: %s"
                    % (etter.get("status"), uventet or "ingen")),
    }, indent=2, ensure_ascii=False)



@mcp.tool()
def close_case(serial_number: int, comment: str = "",
               dry_run: bool = True) -> str:
    """
    Closes an XSALE case by setting status COMPLETED. Requires level 'full'.

    A thin wrapper over set_case_status. dry_run defaults to True.

    A case that is already COMPLETED is reported back untouched. No PUT is
    sent, because setting the status to what it already is changes nothing
    while looking exactly like a real change. Any comment is then NOT written
    either, and the response says so.

    Case 38306 was closed with "migrated to the new platform" while five of
    six reported points were unverified, and the customer stayed unhappy for
    a year. Write what was actually verified in the comment.

    Args:
        serial_number: Case serial number.
        comment: Internal comment explaining the resolution. Strongly advised.
        dry_run: True (default) returns the payload without writing.
    """
    svar = set_case_status(serial_number, CLOSED_STATUS, comment=comment,
                           dry_run=dry_run, notify_customer=False)
    try:
        d = json.loads(svar)
    except Exception:
        return svar
    if not d.get("allerede_i_status"):
        return svar

    # Samme tilstand, men «allerede lukket» er det den som lukker skal lese.
    d["allerede_lukket"] = True
    d["merknad"] = d.get("merknad", "").replace(
        "Saken står allerede i %s." % CLOSED_STATUS,
        "Saken er allerede lukket (%s)." % CLOSED_STATUS, 1)
    return json.dumps(d, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
