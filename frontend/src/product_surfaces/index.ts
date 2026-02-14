import type { ProductSurfaceComponent } from "./registry.gen";
import { SURFACE_MAP } from "./registry.gen";

export function getSurface(slug: string): ProductSurfaceComponent | null {
  return SURFACE_MAP[slug] ?? null;
}
