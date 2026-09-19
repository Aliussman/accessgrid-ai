import React, { useState } from 'react';
import { Play, RotateCcw, AlertTriangle, ShieldAlert, Sparkles, Navigation, Layers, Sliders } from 'lucide-react';

export default function ScenarioStudio({
  presets = {},
  roads = [],
  threshold = 15,
  onThresholdChange,
  onRunScenario,
  onReset,
  loading = false,
  activeScenario = null,
  showIsochrones,
  setShowIsochrones,
  showRiskiest,
  setShowRiskiest,
}) {
  const [scenarioType, setScenarioType] = useState('closure');
  const [selectedRoad, setSelectedRoad] = useState('');
  const [nlQuery, setNlQuery] = useState('');
  const [parsedIntent, setParsedIntent] = useState(null);

  const handleNlSubmit = async (e) => {
    e.preventDefault();
    if (!nlQuery.trim()) return;

    try {
      const res = await fetch('/api/nl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: nlQuery }),
      });
      const data = await res.json();
      setParsedIntent(data);

      if (data.action === 'close' && data.road) {
        onRunScenario({ scenario: 'closure', road: data.road });
      } else if (data.action === 'add_facility' && data.road) {
        onRunScenario({ scenario: 'facility', road: data.road });
      } else if (data.action === 'corridor' && data.road) {
        onRunScenario({ scenario: 'corridor', road: data.road });
      }
    } catch (err) {
      console.error('NL Parse error:', err);
    }
  };

  return (
    <div className="sidebar-panel glass-panel">
      {/* Studio Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: '1.05rem', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Sliders size={18} color="var(--accent-cyan)" />
          Scenario Studio
        </h3>
        {activeScenario && (
          <button onClick={onReset} className="btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }}>
            <RotateCcw size={13} /> Reset
          </button>
        )}
      </div>

      {/* Natural Language Query */}
      <form onSubmit={handleNlSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: '600' }}>
          Ask AccessGrid (Natural Language)
        </label>
        <div style={{ display: 'flex', gap: '6px' }}>
          <input
            type="text"
            className="chat-input"
            style={{ fontSize: '0.78rem', padding: '8px 10px' }}
            placeholder='e.g. "What if Dakshin Marg is closed?"'
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
          />
          <button type="submit" className="btn-primary" style={{ padding: '8px 12px' }}>
            <Sparkles size={14} />
          </button>
        </div>
        {parsedIntent && parsedIntent.road && (
          <span style={{ fontSize: '0.7rem', color: 'var(--accent-cyan)' }}>
            Parsed: <strong>{parsedIntent.action}</strong> on <strong>{parsedIntent.road}</strong>
          </span>
        )}
      </form>

      <hr style={{ borderColor: 'var(--border-subtle)' }} />

      {/* 1-Click Multi-Hazard Presets */}
      <div>
        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: '600', marginBottom: '8px', display: 'block' }}>
          🌊 Multi-Hazard Incident Presets
        </label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {Object.entries(presets).map(([key, p]) => (
            <div
              key={key}
              className={`preset-card ${activeScenario?.preset_id === key ? 'active' : ''}`}
              onClick={() => onRunScenario({ scenario: 'closure', preset_id: key })}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontWeight: '700', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>{p.icon}</span> {p.title}
                </span>
                <span className="badge badge-rose">{p.segments_count} segs</span>
              </div>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-dim)', lineHeight: '1.3', margin: 0 }}>
                {p.description}
              </p>
            </div>
          ))}
        </div>
      </div>

      <hr style={{ borderColor: 'var(--border-subtle)' }} />

      {/* Manual What-If Studio */}
      <div>
        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: '600', marginBottom: '8px', display: 'block' }}>
          Targeted Road Simulation
        </label>

        <div style={{ display: 'flex', gap: '4px', marginBottom: '10px' }}>
          {[
            { id: 'closure', label: 'Close Road', color: 'rose' },
            { id: 'corridor', label: 'Emergency Corridor', color: 'emerald' },
            { id: 'facility', label: 'Add Facility', color: 'purple' },
          ].map((type) => (
            <button
              key={type.id}
              onClick={() => setScenarioType(type.id)}
              style={{
                flex: 1,
                fontSize: '0.7rem',
                fontWeight: '600',
                padding: '6px 4px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid',
                borderColor: scenarioType === type.id ? 'var(--accent-cyan)' : 'var(--border-subtle)',
                background: scenarioType === type.id ? 'rgba(14, 165, 233, 0.15)' : 'transparent',
                color: scenarioType === type.id ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >
              {type.label}
            </button>
          ))}
        </div>

        <select
          className="chat-input"
          style={{ width: '100%', marginBottom: '10px', fontSize: '0.82rem' }}
          value={selectedRoad}
          onChange={(e) => setSelectedRoad(e.target.value)}
        >
          <option value="">Select a corridor...</option>
          {roads.map((r) => (
            <option key={r.name} value={r.name}>
              {r.name} ({r.segments} segments)
            </option>
          ))}
        </select>

        <button
          className="btn-primary"
          style={{ width: '100%' }}
          disabled={!selectedRoad || loading}
          onClick={() => onRunScenario({ scenario: scenarioType, road: selectedRoad })}
        >
          <Play size={15} /> Run Simulation
        </button>
      </div>

      <hr style={{ borderColor: 'var(--border-subtle)' }} />

      {/* Threshold Slider & Toggles */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: '600', marginBottom: '6px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Emergency Threshold</span>
            <span style={{ color: 'var(--accent-cyan)' }}>{threshold} Minutes</span>
          </div>
          <input
            type="range"
            min="5"
            max="30"
            step="1"
            value={threshold}
            onChange={(e) => onThresholdChange(Number(e.target.value))}
            style={{ width: '100%', accentColor: 'var(--accent-cyan)' }}
          />
        </div>

        {/* Map Layers Checkboxes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.75rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', color: 'var(--text-muted)' }}>
            <input
              type="checkbox"
              checked={showIsochrones}
              onChange={(e) => setShowIsochrones(e.target.checked)}
              style={{ accentColor: 'var(--accent-cyan)' }}
            />
            Show Isochrone Catchment Bands
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', color: 'var(--text-muted)' }}>
            <input
              type="checkbox"
              checked={showRiskiest}
              onChange={(e) => setShowRiskiest(e.target.checked)}
              style={{ accentColor: 'var(--accent-cyan)' }}
            />
            Show Riskiest Network Corridors
          </label>
        </div>
      </div>
    </div>
  );
}
