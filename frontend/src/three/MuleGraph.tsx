import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph from "react-force-graph-3d";
import type {
  ForceGraphMethods,
  NodeObject,
  LinkObject,
} from "react-force-graph-3d";
import type { Schema } from "../api/client";
import { riskColor } from "../lib/display";

type Node = Schema["Node"];
type Edge = Schema["Link"];
export default function MuleGraph({
  nodes,
  links,
  highlight,
  choose,
}: {
  nodes: Node[];
  links: Edge[];
  highlight: Set<number>;
  choose: (id: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    graph =
      useRef<ForceGraphMethods<NodeObject<Node>, LinkObject<Node, Edge>>>();
  const [width, setWidth] = useState(500);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const obs = new ResizeObserver((es) => {
      const r = es[0];
      if (r) setWidth(Math.floor(r.contentRect.width));
    });
    obs.observe(el);
    return () => {
      obs.disconnect();
    };
  }, []);
  const data = useMemo(
    () => ({
      nodes: nodes.map((n) => ({ ...n, id: n.account_id })),
      links: links.map((l) => ({ ...l, source: l.src, target: l.dst })),
    }),
    [nodes, links],
  );
  const last = Math.max(...links.map((l) => l.ts), 0);
  return (
    <div className="graph" ref={host}>
      <button
        className="overlay"
        onClick={() => graph.current?.zoomToFit(450, 30)}
      >
        Reset camera
      </button>
      <ForceGraph<Node, Edge>
        ref={graph}
        width={width}
        height={410}
        graphData={data}
        backgroundColor="#101b1d"
        showNavInfo={false}
        cooldownTicks={65}
        nodeVal={(n) => 1 + Math.log1p(n.volume) / 3}
        nodeColor={(n) => riskColor(n.probability)}
        nodeLabel={(n) => "Account " + String(n.account_id)}
        linkWidth={(l) => (highlight.has(l.txn_id) ? 2 : 0)}
        linkColor={(l) => (highlight.has(l.txn_id) ? "#ffd56a" : "#62887f")}
        linkOpacity={0.45}
        linkDirectionalParticles={(l) =>
          Math.min(5, Math.max(1, Math.ceil(Math.log10(l.amount + 1))))
        }
        linkDirectionalParticleSpeed={(l) =>
          0.001 + 0.005 / (1 + (last - l.ts) / 86400)
        }
        linkDirectionalParticleWidth={1.1}
        onNodeClick={(n) => {
          choose(n.account_id);
          if (n.x !== undefined && n.y !== undefined && n.z !== undefined) {
            const d = Math.hypot(n.x, n.y, n.z) || 1;
            graph.current?.cameraPosition(
              {
                x: n.x * (1 + 65 / d),
                y: n.y * (1 + 65 / d),
                z: n.z * (1 + 65 / d),
              },
              { x: n.x, y: n.y, z: n.z },
              650,
            );
          }
        }}
      />
    </div>
  );
}
