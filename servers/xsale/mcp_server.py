import os
import re
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





@mcp.tool()
def search_cases(query: str, status: str = "ACTIVE", limit: int = 50) -> str:
    """
    Searches for cases matching a text query (searches in subject, description, customer name).
    
    Args:
        query: The search text.
        status: Filter by status. Default: "ACTIVE". Options: "ACTIVE", "CLOSED", "ALL".
        limit: Maximum number of results. Default: 50.
    """
    filters = [{"property": "query", "value": query}]
    if status != "ALL":
        filters.append({"property": "status", "value": status})

    params = {
        "page": 1,
        "start": 0,
        "limit": limit,
        "filter": _build_filter(filters),
        "sort": _build_sort([{"property": "updated", "direction": "DESC"}]),
    }

    needle = query.casefold()

    def haystack(case: dict) -> str:
        customer = case.get("customer") or {}
        contact = case.get("contact") or {}
        parts = [
            str(case.get("serialNumber") or ""),
            case.get("subject") or "",
            case.get("description") or "",
            customer.get("name", "") if isinstance(customer, dict) else str(customer),
            contact.get("name", "") if isinstance(contact, dict) else str(contact),
            contact.get("email", "") if isinstance(contact, dict) else "",
        ]
        return " ".join(parts).casefold()

    result = _api_get("/customercase/", params=params)
    cases, total = _extract_list(result, "customercase")
    matched_cases = [case for case in cases if needle in haystack(case)]
    if matched_cases:
        cases = matched_cases[:limit]
        total = len(matched_cases)

    # XSALE's query filter can miss cases that are still returned by the
    # assigned-user list, or return a broad unfiltered result set. Fall back to
    # a small client-side search there when the server result has no match.
    if not matched_cases:
        global _user_id
        if _user_id is None:
            _get_session()
        if _user_id is not None:
            fallback_filters = [{"property": "userId", "value": _user_id}]
            if status != "ALL":
                fallback_filters.append({"property": "status", "value": status})
            fallback_params = {
                "page": 1,
                "start": 0,
                "limit": 1000,
                "filter": _build_filter(fallback_filters),
                "sort": _build_sort([{"property": "updated", "direction": "DESC"}]),
            }
            fallback = _api_get("/customercase/", params=fallback_params)
            fallback_cases, _ = _extract_list(fallback, "customercase")
            cases = [case for case in fallback_cases if needle in haystack(case)][:limit]
            total = len(cases)

    formatted = _format_cases(cases)
    return json.dumps({"total": total, "query": query, "cases": formatted}, indent=2, ensure_ascii=False)


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


def _to_xsale_html(text, raw_html=False):
    """Gjor ren tekst klar for XSALE sine note- og description-felter.

    Feltene lagres og rendres som HTML. Et vanlig linjeskift kollapser derfor
    til et mellomrom, og et notat skrevet med avsnitt vises som en eneste
    sammenhengende blokk i grensesnittet. Escaper teksten og gjor linjeskift
    til <br>, slik at notatet leses slik det ble skrevet.

    raw_html=True sender teksten urort, for de gangene formatering er onsket.
    """
    if raw_html:
        return text
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.replace("\n", "<br>")

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
# XSALE, and they act as the logged-in user, so that user's own name appears as
# the author. They are deliberately narrow: creating a case and adding an internal
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
    landed = False
    author = None
    try:
        fresh = json.loads(get_case_details(int(case_id)))
        for rel in fresh.get("relation", []) or []:
            if rel.get("type") == "INTERNAL" and (rel.get("note") or "").strip() == note.strip():
                landed = True
                author = rel.get("author")
                break
    except Exception:
        pass

    return json.dumps({
        "added": True,
        "verified_on_case": landed,
        "serialNumber": serial_number,
        "case_id": case_id,
        "author": author,
        "note": note,
    }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
