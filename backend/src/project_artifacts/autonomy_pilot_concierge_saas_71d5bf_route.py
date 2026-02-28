# SPDX-License-Identifier: BSL-1.1

"""Generated executable project artifact route."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=['generated-project-artifacts'])

_ARTIFACT = {
  "slug": "autonomy-pilot-concierge-saas-71d5bf",
  "title": "Autonomy Pilot: Concierge SaaS 71D5BF backend artifact",
  "summary": "Generated from the backend bounty deliverable. Captures the minimal API contract and operator-facing safety checks.",
  "endpoints": [
    "/api/v1/projects/proj_from_proposal_prp_4f01552188836881",
    "/api/v1/projects/proj_from_proposal_prp_4f01552188836881/capital",
    "/api/v1/projects/proj_from_proposal_prp_4f01552188836881/funding",
    "/api/v1/bounties?project_id=proj_from_proposal_prp_4f01552188836881",
    "/api/v1/discussions/threads?scope=project&project_id=proj_from_proposal_prp_4f01552188836881"
  ],
  "kind": "backend_artifact"
}
_LINKS = {
  "artifact_path": "/api/v1/project-artifacts/autonomy-pilot-concierge-saas-71d5bf",
  "artifact_summary_path": "/api/v1/project-artifacts/autonomy-pilot-concierge-saas-71d5bf/summary",
  "portal_app_path": "/apps/autonomy-pilot-concierge-saas-71d5bf"
}

@router.get('/api/v1/project-artifacts/autonomy-pilot-concierge-saas-71d5bf', include_in_schema=False)
def get_generated_project_artifact() -> dict[str, object]:
    data = dict(_ARTIFACT)
    data['links'] = dict(_LINKS)
    data['route_kind'] = 'template'
    return {'success': True, 'data': data}

@router.get('/api/v1/project-artifacts/autonomy-pilot-concierge-saas-71d5bf/summary', include_in_schema=False)
def get_generated_project_artifact_summary() -> dict[str, object]:
    return {
        'success': True,
        'data': {
            'slug': _ARTIFACT['slug'],
            'title': _ARTIFACT.get('title'),
            'summary': _ARTIFACT.get('summary'),
            'kind': _ARTIFACT.get('kind'),
            'status': 'ready',
            'endpoints': list(_ARTIFACT.get('endpoints') or []),
            'links': dict(_LINKS),
            'route_kind': 'summary_template',
        },
    }
