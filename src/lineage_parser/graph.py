"""Core lineage graph data model shared by all parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeKind(str, Enum):
    TABLE = "table"
    COLUMN = "column"
    FILE = "file"
    COMPONENT = "component"


@dataclass(frozen=True)
class Node:
    """A single addressable entity in the lineage graph (table, column, file, etc.)."""

    id: str
    kind: NodeKind
    label: str

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind.value, "label": self.label}


@dataclass(frozen=True)
class Edge:
    """A directed edge meaning `source` flows into / produces `target`."""

    source: str
    target: str
    relation: str = "flows_to"
    detail: str | None = None

    def to_dict(self) -> dict:
        d = {"source": self.source, "target": self.target, "relation": self.relation}
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class LineageGraph:
    """A directed graph of lineage edges, always stored in source->target orientation.

    Direction for presentation (source->target vs target->source) is applied only
    at render/export time via `oriented_edges`, so the internal representation
    never has to be rebuilt when the caller flips direction.
    """

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node_id: str, kind: NodeKind, label: str | None = None) -> Node:
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(id=node_id, kind=kind, label=label or node_id)
        return self.nodes[node_id]

    def add_edge(self, source: str, target: str, relation: str = "flows_to", detail: str | None = None) -> None:
        edge = Edge(source=source, target=target, relation=relation, detail=detail)
        if edge not in self.edges:
            self.edges.append(edge)

    def merge(self, other: "LineageGraph") -> None:
        self.nodes.update(other.nodes)
        for e in other.edges:
            if e not in self.edges:
                self.edges.append(e)

    def oriented_edges(self, direction: str) -> list[Edge]:
        """Return edges in the requested presentation direction.

        `direction` is 'source_to_target' (default, no-op) or 'target_to_source'
        (reverses each edge so the graph reads target -> source).
        """
        if direction == "source_to_target":
            return list(self.edges)
        if direction == "target_to_source":
            return [Edge(source=e.target, target=e.source, relation=self._reverse_relation(e.relation), detail=e.detail) for e in self.edges]
        raise ValueError(f"Unknown direction: {direction!r}. Expected 'source_to_target' or 'target_to_source'.")

    @staticmethod
    def _reverse_relation(relation: str) -> str:
        return {
            "flows_to": "derived_from",
            "derived_from": "flows_to",
        }.get(relation, relation)

    def to_dict(self, direction: str = "source_to_target") -> dict:
        return {
            "direction": direction,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.oriented_edges(direction)],
        }

    def is_empty(self) -> bool:
        return not self.edges

    def collapse_to_kind(self, kind: NodeKind) -> "LineageGraph":
        """Collapse a multi-hop graph down to direct reachability edges between
        nodes of the given kind (typically physical tables)."""
        return self.collapse_to_boundary(lambda n: n.kind == kind)

    def collapse_to_physical_columns(self) -> "LineageGraph":
        """Collapse a multi-hop column graph (e.g. Informatica chains that pass
        through transformation-instance columns) down to direct reachability
        edges between physical-table columns only, skipping over intermediate
        component/transformation column hops."""
        return self.collapse_to_boundary(lambda n: n.kind == NodeKind.COLUMN and n.id.startswith("table:"))

    def collapse_to_boundary(self, is_boundary) -> "LineageGraph":
        """Collapse a multi-hop graph (e.g. component/column chains from SSIS or
        Informatica mappings) down to direct reachability edges between nodes
        matching `is_boundary`, skipping over intermediate hops. Includes
        transitive edges (A->B->C implies A->C)."""
        adjacency: dict[str, list[str]] = {}
        for e in self.edges:
            adjacency.setdefault(e.source, []).append(e.target)

        boundary_nodes = [n for n in self.nodes.values() if is_boundary(n)]
        collapsed = LineageGraph()
        for n in boundary_nodes:
            collapsed.add_node(n.id, n.kind, n.label)

        for start in boundary_nodes:
            visited = {start.id}
            stack = list(adjacency.get(start.id, []))
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                node = self.nodes.get(cur)
                if node and is_boundary(node) and node.id != start.id:
                    collapsed.add_edge(start.id, node.id, relation="flows_to")
                stack.extend(adjacency.get(cur, []))

        return collapsed
