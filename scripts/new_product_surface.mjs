#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

function usage() {
  process.stderr.write(
    "usage: node scripts/new_product_surface.mjs --slug <project-slug>\n"
  );
}

function parseArgs(argv) {
  const args = { slug: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--slug") {
      args.slug = argv[++i] ?? null;
    } else if (a === "-h" || a === "--help") {
      usage();
      process.exit(0);
    } else {
      usage();
      process.exit(2);
    }
  }
  if (!args.slug) {
    usage();
    process.exit(2);
  }
  return args;
}

function toPascalCase(slug) {
  return slug
    .split(/[^a-z0-9]+/g)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join("");
}

function assertValidSlug(slug) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    throw new Error("invalid slug: use lowercase letters, digits, and dashes only");
  }
  if (slug.length > 64) {
    throw new Error("invalid slug: must be <= 64 chars");
  }
}

const { slug } = parseArgs(process.argv);
assertValidSlug(slug);

const repoRoot = process.cwd();
const surfacesDir = path.join(repoRoot, "frontend", "src", "product_surfaces");
const surfaceFile = path.join(surfacesDir, `${slug}.tsx`);
const indexFile = path.join(surfacesDir, "index.ts");

if (!fs.existsSync(surfacesDir)) {
  throw new Error(`missing directory: ${surfacesDir}`);
}

if (fs.existsSync(surfaceFile)) {
  throw new Error(`surface already exists: ${surfaceFile}`);
}

if (!fs.existsSync(indexFile)) {
  throw new Error(`missing file: ${indexFile}`);
}

const componentName = `${toPascalCase(slug)}Surface`;

const surfaceSource = `import { TemplateSurface } from "./template";
import type { ProjectDetail } from "@/types";

export function ${componentName}({ project }: { project: ProjectDetail }) {
  return <TemplateSurface project={project} />;
}
`;

fs.writeFileSync(surfaceFile, surfaceSource, "utf8");

let indexSource = fs.readFileSync(indexFile, "utf8");

if (indexSource.includes(`from "./${slug}"`)) {
  throw new Error(`index.ts already imports ./${slug}`);
}
if (indexSource.includes(`"${slug}"`)) {
  throw new Error(`index.ts already contains slug key "${slug}"`);
}

// Insert import after the last local surface import (or after DemoSurface import).
const importNeedle = 'import { DemoSurface } from "./demo";';
if (!indexSource.includes(importNeedle)) {
  throw new Error("unsupported index.ts format: missing DemoSurface import");
}
indexSource = indexSource.replace(
  importNeedle,
  `${importNeedle}\nimport { ${componentName} } from "./${slug}";`
);

// Insert map entry.
const mapNeedle = "const SURFACE_MAP: Record<string, ProductSurfaceComponent> = {\n  demo: DemoSurface,\n};";
if (!indexSource.includes(mapNeedle)) {
  throw new Error("unsupported index.ts format: SURFACE_MAP block not found");
}
indexSource = indexSource.replace(
  mapNeedle,
  `const SURFACE_MAP: Record<string, ProductSurfaceComponent> = {\n  demo: DemoSurface,\n  \"${slug}\": ${componentName},\n};`
);

fs.writeFileSync(indexFile, indexSource, "utf8");

process.stdout.write(
  JSON.stringify(
    {
      ok: true,
      slug,
      file: path.relative(repoRoot, surfaceFile),
      index: path.relative(repoRoot, indexFile),
      component: componentName,
    },
    null,
    2
  ) + "\n"
);

