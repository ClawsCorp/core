import type { ProjectDetail } from "@/types";

export function DemoSurface({ project }: { project: ProjectDetail }) {
  return (
    <section style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 16 }}>
      <h2>{project.name} — Demo Product Surface</h2>
      <p>This is an example repository-coded surface mounted at /apps/{project.slug}.</p>
      <ul>
        <li>Custom hero content for a specific project slug.</li>
        <li>Feature bullet section for early SaaS packaging.</li>
        <li>Safe fallback to generic app landing when not registered.</li>
      </ul>
    </section>
  );
}
