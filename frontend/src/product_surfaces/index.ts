import type { ComponentType } from "react";

import type { ProjectDetail } from "@/types";

import { DemoSurface } from "./demo";

export type ProductSurfaceComponent = ComponentType<{ project: ProjectDetail }>;

const SURFACE_MAP: Record<string, ProductSurfaceComponent> = {
  demo: DemoSurface,
};

export function getSurface(slug: string): ProductSurfaceComponent | null {
  return SURFACE_MAP[slug] ?? null;
}
