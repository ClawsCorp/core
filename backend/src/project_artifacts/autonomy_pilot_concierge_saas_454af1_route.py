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

@router.get('/api/v1/project-artifacts/autonomy-pilot-concierge-saas-454af1', include_in_schema=False)
def get_generated_project_artifact() -> dict[str, object]:
    data = dict(_ARTIFACT)
    data['route_kind'] = 'template'
    return {'success': True, 'data': data}
