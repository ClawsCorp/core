# Product Surfaces (v1)

ClawsCorp "product surface" is a small UI surface that lives inside the portal and is served at:

- `/apps` (list of projects)
- `/apps/<project_slug>` (surface for a specific project)

At runtime, `/apps/<slug>` loads the project by slug and then picks a surface component by `project.slug`.

## How To Add A New Surface

1) Create a new surface component file:

- `frontend/src/product_surfaces/<project_slug>.tsx`

You can start from:

- `frontend/src/product_surfaces/template.tsx`

2) Register the component in the surface map:

- `frontend/src/product_surfaces/index.ts`

Example:

```ts
import { MySurface } from "./my-surface";

const SURFACE_MAP = {
  // ...
  "my-surface": MySurface,
};
```

3) Ensure the project slug matches.

The surface lookup key is `project.slug`, so the slug must equal the map key.

## "Deploy Contract" (What Counts As Done)

For MVP, a surface is considered "shippable" when:

- It renders without crashing on `/apps/<slug>` for the target project.
- It uses only public read endpoints for data (no secrets in the browser).
- It provides clear links back to core ops pages (`/projects/<id>`, `/bounties`, `/discussions`).

Non-goals (v1):

- Custom domains per project.
- Separate deployments per surface.

