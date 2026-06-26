import React from 'react';

interface LayerDef {
  id: string;
  label: string;
  visible: boolean;
  onToggle: () => void;
}

interface Props {
  layers: LayerDef[];
}

const HydrologyLayerToggle: React.FC<Props> = ({ layers = [] }) => (
  <div className="hydrology-layer-toggle space-y-1">
    {layers.map((l) => (
      <label key={l.id} className="flex items-center gap-2 text-xs cursor-pointer hover:bg-white/5 px-1 py-0.5 rounded">
        <input
          type="checkbox"
          checked={l.visible}
          onChange={l.onToggle}
          className="w-3.5 h-3.5"
        />
        <span className={l.visible ? 'text-nkz-text' : 'text-nkz-muted'}>{l.label}</span>
      </label>
    ))}
  </div>
);

export default HydrologyLayerToggle;
