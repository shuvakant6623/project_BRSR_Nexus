"use client";

import { useEffect, useMemo, useState } from "react";

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
  const [showDetail, setShowDetail] = useState(false);
  const color = TYPE_COLORS[node.entity_type] ?? "#94a3b8";
  return (
    <div style={{ marginLeft: depth === 0 ? 0 : "1.25rem" }}>
      <div className="entity-row" onClick={() => setOpen(!open)}>
        <span className="entity-dot" style={{ background: color }} />
        <strong>{node.name}</strong>
        <span className="entity-type">{node.entity_type.replace("_", " ")}</span>
        {!node.is_active && <span className="badge error">inactive</span>}
        <button
          className="entity-info-btn"
          title="Show details"
          onClick={(e) => { e.stopPropagation(); setShowDetail(!showDetail); }}
          style={{
            background: "transparent", border: "none", color: "var(--muted)",
            cursor: "pointer", fontSize: "0.82rem", padding: "0.1rem 0.4rem",
            borderRadius: 6, transition: "color 0.15s",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--sky)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--muted)")}
        >
          ⓘ
        </button>
        {node.children.length > 0 && (
          <span className="entity-caret">{open ? "▾" : "▸"} {node.children.length}</span>
        )}
      </div>
      {showDetail && (
        <div
          style={{
            marginLeft: "2rem", padding: "0.5rem 0.8rem", borderLeft: `2px solid ${color}`,
            marginBottom: "0.3rem", fontSize: "0.82rem", color: "var(--muted)",
            animation: "fadeUp 0.18s ease both",
          }}
        >
          <div><strong>ID:</strong> <span className="mono">{node.id.slice(0, 8)}…</span></div>
          <div><strong>Effective from:</strong> {node.effective_from}</div>
          {node.effective_to && <div><strong>Effective to:</strong> {node.effective_to}</div>}
          {node.reporting_boundary_notes && (
            <div><strong>Boundary:</strong> {node.reporting_boundary_notes}</div>
          )}
        </div>
      )}
      {open && node.children.map((c) => <TreeNode key={c.id} node={c} depth={depth + 1} />)}
    </div>
  );
}

export default function EntitiesPage() {
  const [entities, setEntities] = useState<EntityNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  useEffect(() => {
    listEntities(showInactive)
      .then(setEntities)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load entities"));
  }, [showInactive]);

  const stats = useMemo(() => {
    if (!entities) return null;
    const active = entities.filter((e) => e.is_active).length;
    const typeCounts: Record<string, number> = {};
    for (const e of entities) {
      typeCounts[e.entity_type] = (typeCounts[e.entity_type] ?? 0) + 1;
    }
    const roots = entities.filter((e) => !e.parent_id).length;
    return { total: entities.length, active, inactive: entities.length - active, roots, typeCounts };
  }, [entities]);

  if (error) return <main className="page"><div className="state error">Error: {error}</div></main>;
  if (entities === null) return <main className="page"><div className="state">Loading entities…</div></main>;
  if (entities.length === 0)
    return <main className="page"><div className="state">No entities visible in your scope.</div></main>;

  const tree = buildTree(entities);
  return (
    <main className="page">
      <h1 className="rise">Entity Hierarchy</h1>
      <p className="hint rise rise-d1">
        {entities.length} entit{entities.length === 1 ? "y" : "ies"} visible in your authorized
        scope. Writes are admin-only and fully audited.
      </p>

      {stats && (
        <div className="stat-row rise rise-d1">
          <div className="stat-card">
            <div className="stat-value">{stats.total}</div>
            <div className="stat-label">Total Entities</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.active}</div>
            <div className="stat-label">Active</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.roots}</div>
            <div className="stat-label">Root Nodes</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{Object.keys(stats.typeCounts).length}</div>
            <div className="stat-label">Entity Types</div>
          </div>
        </div>
      )}

      <div className="filter-row rise rise-d2">
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.84rem", color: "var(--muted)", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
            style={{ accentColor: "var(--accent)" }}
          />
          Show inactive entities
        </label>
      </div>

      <div className="legend-row rise rise-d2">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <span key={type} className="legend-item">
            <span className="legend-swatch" style={{ background: color }} />
            {type.replace("_", " ")}
            {stats?.typeCounts[type] ? ` (${stats.typeCounts[type]})` : ""}
          </span>
        ))}
      </div>

      <div className="entity-tree rise rise-d2">
        {tree.map((n) => (
          <TreeNode key={n.id} node={n} depth={0} />
        ))}
      </div>
    </main>
  );
}
