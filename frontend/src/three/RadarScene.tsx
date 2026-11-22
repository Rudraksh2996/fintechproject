import { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import type { Mesh, Group } from "three";
import type { Schema } from "../api/client";

function Sweep() {
  const ref = useRef<Group>(null);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += dt * 0.55;
  });
  return (
    <group ref={ref}>
      <mesh position={[2.5, 0, 0]}>
        <boxGeometry args={[5, 0.012, 0.023]} />
        <meshBasicMaterial color="#8fe4c9" />
      </mesh>
    </group>
  );
}
function Point({
  alert,
  angle,
  pulsing,
  choose,
}: {
  alert: Schema["AlertView"];
  angle: number;
  pulsing: boolean;
  choose: () => void;
}) {
  const [hover, setHover] = useState(false),
    ref = useRef<Mesh>(null);
  useFrame(({ clock }) => {
    ref.current?.scale.setScalar(
      pulsing ? 1.3 + 0.35 * Math.sin(clock.elapsedTime * 5) : 1,
    );
  });
  const r = 1 + Number(alert.conviction_score) * 0.041;
  return (
    <group
      position={[
        Math.cos(angle) * r,
        0.17 + Number(alert.conviction_score) / 240,
        Math.sin(angle) * r,
      ]}
    >
      <mesh
        ref={ref}
        onClick={(e) => {
          e.stopPropagation();
          choose();
        }}
        onPointerOver={() => {
          setHover(true);
        }}
        onPointerOut={() => {
          setHover(false);
        }}
      >
        <sphereGeometry
          args={[
            0.045 + Math.log10(1 + Number(alert.total_value_usd)) * 0.019,
            12,
            12,
          ]}
        />
        <meshBasicMaterial
          color={
            hover
              ? "#fff"
              : `hsl(164,58%,${String(Math.min(85, 30 + alert.n_insiders * 8))}%)`
          }
        />
      </mesh>
      {hover && (
        <Html center distanceFactor={9}>
          <span className="tooltip">
            {alert.ticker} · {alert.conviction_score}
          </span>
        </Html>
      )}
    </group>
  );
}
export default function RadarScene({
  alerts,
  choose,
  pulse,
}: {
  alerts: Schema["AlertView"][];
  choose: (id: number) => void;
  pulse: number | null;
}) {
  const days = useMemo(
      () => alerts.map((a) => Date.parse(a.alert_filing_date)),
      [alerts],
    ),
    min = Math.min(...days),
    span = Math.max(1, Math.max(...days) - min);
  return (
    <Canvas
      camera={{ position: [0, 8, 5], fov: 57 }}
      fallback={<p>WebGL unavailable. Select an issuer from the alert feed.</p>}
    >
      <OrbitControls enablePan={false} minDistance={4} maxDistance={16} />
      <group rotation={[-Math.PI / 2, 0, 0]}>
        {[1, 2, 3, 4, 5].map((r) => (
          <mesh key={r}>
            <ringGeometry args={[r, r + 0.013, 128]} />
            <meshBasicMaterial color="#31514b" />
          </mesh>
        ))}
      </group>
      <gridHelper args={[10, 10, "#35534d", "#20302e"]} />
      <Sweep />
      {alerts.map((a, i) => (
        <Point
          key={a.id}
          alert={a}
          angle={(((days[i] ?? min) - min) / span) * Math.PI * 1.92}
          pulsing={pulse === a.id}
          choose={() => {
            choose(a.id);
          }}
        />
      ))}
    </Canvas>
  );
}
