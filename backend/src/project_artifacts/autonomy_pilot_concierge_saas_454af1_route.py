# SPDX-License-Identifier: BSL-1.1

"""Generated executable project artifact route."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=['generated-project-artifacts'])

_ARTIFACT = {
  "slug": "autonomy-pilot-concierge-saas-454af1",
  "title": "Autonomy Pilot backend executable route",
  "summary": "Follow-up route template for the pilot project, generated after the initial artifact manifest.",
  "endpoints": [
    "/api/v1/projects/proj_from_proposal_prp_94078a1dabeb1e00",
    "/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1",
    "/api/v1/bounties?project_id=proj_from_proposal_prp_94078a1dabeb1e00"
  ],
  "kind": "backend_artifact"
}

_LINKS = {
  "artifact_path": "/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1",
  "artifact_summary_path": "/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1/summary",
  "portal_app_path": "/apps/autonomy-pilot-concierge-saas-454af1"
}

@router.get('/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1', include_in_schema=False)
def get_generated_project_artifact() -> dict[str, object]:
    data = dict(_ARTIFACT)
    data['links'] = dict(_LINKS)
    data['route_kind'] = 'template'
    return {'success': True, 'data': data}


@router.get('/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1/summary', include_in_schema=False)
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
