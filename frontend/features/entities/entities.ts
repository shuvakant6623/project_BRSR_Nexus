import { api } from "@/lib/api";

export interface EntityNode {
  id: string;
  parent_id: string | null;
  entity_type: string;
  name: string;
  is_active: boolean;
  effective_from: string;
  effective_to: string | null;
  reporting_boundary_notes: string | null;
}

export function listEntities(includeInactive = false): Promise<EntityNode[]> {
  return api<EntityNode[]>(`/api/v1/entities${includeInactive ? "?include_inactive=true" : ""}`);
}

export type EntityTreeNode = EntityNode & { children: EntityTreeNode[] };

export function buildTree(entities: EntityNode[]): EntityTreeNode[] {
  const byParent = new Map<string | null, EntityNode[]>();
  for (const e of entities) {
    const list = byParent.get(e.parent_id) ?? [];
    list.push(e);
    byParent.set(e.parent_id, list);
  }
  const attach = (node: EntityNode): EntityTreeNode => ({
    ...node,
    children: (byParent.get(node.id) ?? []).map(attach),
  });
  return (byParent.get(null) ?? []).map(attach);
}
