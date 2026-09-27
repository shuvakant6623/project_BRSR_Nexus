"use client";

import { useEffect, useState } from "react";

import { buildTree, EntityNode, EntityTreeNode, listEntities } from "@/features/entities/entities";

const TYPE_COLORS: Record<string, string> = {
  GROUP: "#10b981",
  SUBSIDIARY: "#38bdf8",
  BUSINESS_UNIT: "#a78bfa",
  PLANT: "#f59e0b",
  PROJECT: "#f472b6",
  DEPARTMENT: "#94a3b8",
};

function TreeNode({ node, depth }: { node: EntityTreeNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const color = TYPE_COLORS[node.entity_type] ?? "#94a3b8";
  return (
    <div style={{ marginLeft: depth === 0 ? 0 : "1.25rem" }}>
      <div className="entity-row" onClick={() => setOpen(!open)}>
        <span className="entity-dot" style={{ background: color }} />
        <strong>{node.name}</strong>
        <span className="entity-type">{node.entity_type.replace("_", " ")}</span>
        {!node.is_active && <span className="badge error">inactive</span>}
        {node.children.length > 0 && (
          <span className="entity-caret">{open ? "▾" : "▸"} {node.children.length}</span>
        )}
      </div>
      {open && node.children.map((c) => <TreeNode key={c.id} node={c} depth={depth + 1} />)}
    </div>
  );
}

export default function EntitiesPage() {
  const [entities, setEntities] = useState<EntityNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listEntities()
      .then(setEntities)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load entities"));
  }, []);

  if (error) return <main className="page"><div className="state error">Error: {error}</div></main>;
  if (entities === null) return <main className="page"><div className="state">Loading entities…</div></main>;
  if (entities.length === 0)
    return <main className="page"><div className="state">No entities visible in your scope.</div></main>;

  const tree = buildTree(entities);
  return (
    <main className="page">
      <h1>Entity Hierarchy</h1>
      <p className="hint">
        {entities.length} entit{entities.length === 1 ? "y" : "ies"} visible in your authorized
        scope. Writes are admin-only and fully audited.
      </p>
      <div className="entity-tree">
        {tree.map((n) => (
          <TreeNode key={n.id} node={n} depth={0} />
        ))}
      </div>
    </main>
  );
}
