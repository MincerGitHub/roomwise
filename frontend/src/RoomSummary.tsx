import { Armchair, House, LockKeyhole } from 'lucide-react';
import type { Scene } from './types';
import './room-summary.css';

export default function RoomSummary({ scene }: { scene: Scene }) {
  const { width, depth } = scene.room;
  const locked = scene.items.filter(item => item.locked).length;
  const cards = [
    { icon: House, title: '房间面积', value: `${(width * depth).toFixed(1)} m²`, detail: `宽 ${width.toFixed(1)} 米 · 进深 ${depth.toFixed(1)} 米` },
    { icon: Armchair, title: '家具清单', value: `${scene.items.length} 件`, detail: '当前布局包含的家具总数' },
    { icon: LockKeyhole, title: '位置锁定', value: `${locked} 件`, detail: `其余 ${scene.items.length - locked} 件家具未锁定` },
  ];
  return <section className="room-summary" aria-label="房间概览">
    {cards.map(({ icon: Icon, title, value, detail }) => <article className="room-summary-card" key={title}>
      <Icon size={20} strokeWidth={1.6} aria-hidden="true" />
      <div><h3>{title}</h3><strong>{value}</strong><p>{detail}</p></div>
    </article>)}
  </section>;
}
