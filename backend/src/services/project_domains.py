from __future__ import annotations

import re
from datetime import datetime, timezone

import dns.resolver
from sqlalchemy.orm import Session

from src.models.project_domain import ProjectDomain, ProjectDomainStatus

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def normalize_domain(value: str) -> str:
    d = (value or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.rstrip(".")
    if not _DOMAIN_RE.fullmatch(d):
        raise ValueError("invalid_domain")
    return d


def verification_txt_name(domain: str) -> str:
    # Put TXT under a stable name so users don't need to expose token at root.
    return f"_clawscorp.{domain}"


def resolve_txt_values(name: str) -> list[str]:
    answers = dns.resolver.resolve(name, "TXT")
    out: list[str] = []
    for rdata in answers:
        # dnspython TXT records may be split into chunks.
        parts = getattr(rdata, "strings", None)
        if parts:
            for part in parts:
                try:
                    out.append(part.decode("utf-8"))
                except Exception:
                    continue
        else:
            try:
                out.append(str(rdata).strip('"'))
            except Exception:
                continue
    return out


def verify_domain(db: Session, *, row: ProjectDomain) -> bool:
    now = datetime.now(timezone.utc)
    name = verification_txt_name(row.domain)
    ok = False
    error: str | None = None
    try:
        values = resolve_txt_values(name)
        ok = row.dns_txt_token in values
        if not ok:
            error = "token_not_found"
    except Exception as exc:
        ok = False
        error = f"dns_error:{exc.__class__.__name__}"

    row.last_checked_at = now
    row.last_check_error = None if ok else error
    if ok:
        row.status = ProjectDomainStatus.verified
        row.verified_at = now
    else:
        row.status = ProjectDomainStatus.pending
    db.add(row)
    return ok
