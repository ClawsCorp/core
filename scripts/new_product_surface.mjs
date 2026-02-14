#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const surfacesDir = path.join(repoRoot, "frontend", "src", "product_surfaces");
const surfaceFile = path.join(surfacesDir, `${slug}.tsx`);

if (!fs.existsSync(surfacesDir)) {
  throw new Error(`missing directory: ${surfacesDir}`);
}

if (fs.existsSync(surfaceFile)) {
  throw new Error(`surface already exists: ${surfaceFile}`);
}

const componentName = `${toPascalCase(slug)}Surface`;

const surfaceSource = `import { TemplateSurface } from "./template";
import type { ProjectDetail } from "@/types";

export function ${componentName}({ project }: { project: ProjectDetail }) {
  return <TemplateSurface project={project} />;
}
`;

fs.writeFileSync(surfaceFile, surfaceSource, "utf8");

// Keep registry mapping fully automated (no manual edits).
const genScript = path.join(repoRoot, "scripts", "gen_product_surface_registry.mjs");
const proc = spawnSync("node", [genScript], { cwd: repoRoot, encoding: "utf8" });
if (proc.status !== 0) {
  throw new Error(`registry generator failed: ${proc.stderr || proc.stdout}`);
}

process.stdout.write(
  JSON.stringify(
    {
      ok: true,
      slug,
      file: path.relative(repoRoot, surfaceFile),
      component: componentName,
    },
    null,
    2
  ) + "\n"
);
