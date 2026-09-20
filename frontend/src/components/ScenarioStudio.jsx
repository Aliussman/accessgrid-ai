import React, { useState } from 'react';
import { Play, RotateCcw, AlertTriangle, ShieldAlert, Sparkles, Navigation, Layers, Sliders } from 'lucide-react';

export default function ScenarioStudio({
  presets = {},
  roads = [],
  threshold = 15,
  onThresholdChange,
  destCategory = 'all',
  onDestCategoryChange,
  showAltRoute = true,
  setShowAltRoute,
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
  const [isNlLoading, setIsNlLoading] = useState(false);

  const handleNlSubmit = async (e, directQuery = null) => {
    if (e) e.preventDefault();
    const queryToRun = (directQuery || nlQuery).trim();
    if (!queryToRun) return;

    setIsNlLoading(true);
    try {
      const res = await fetch('/api/nl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: queryToRun }),
      });
      const data = await res.json();
      setParsedIntent(data);

      if (data.action === 'preset' && data.preset_id) {
        onRunScenario({ scenario: 'closure', preset_id: data.preset_id });
      } else if (data.action === 'close' && data.road) {
        onRunScenario({ scenario: 'closure', road: data.road });
      } else if ((data.action === 'add_facility' || data.action === 'facility') && data.road) {
        onRunScenario({ scenario: 'facility', road: data.road });
      } else if (data.action === 'corridor' && data.road) {
        onRunScenario({ scenario: 'corridor', road: data.road });
      } else if (data.action === 'reopen' || data.action === 'coverage') {
        onReset();
      }
    } catch (err) {
      console.error('NL Parse error:', err);
    } finally {
      setIsNlLoading(false);
    }
  };

  const handleChipClick = (suggestion) => {
    setNlQuery(suggestion);
    handleNlSubmit(null, suggestion);
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

      {/* Destination Layer Category Switcher */}
      <div>
        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: '600', marginBottom: '6px', display: 'block' }}>
          📍 Destination Facility Layers
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px' }}>
          {[
            { id: 'all', label: '🌐 All POIs', badge: '50' },
            { id: 'hospital', label: '🏥 Hospitals', badge: '21' },
            { id: 'school', label: '🏫 Schools', badge: '15' },
            { id: 'market', label: '🛒 Markets', badge: '14' },
          ].map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => onDestCategoryChange && onDestCategoryChange(cat.id)}
              style={{
                fontSize: '0.72rem',
                fontWeight: '600',
                padding: '6px 8px',
                borderRadius: '6px',
                border: '1px solid',
                borderColor: destCategory === cat.id ? 'var(--accent-cyan)' : 'var(--border-subtle)',
                background: destCategory === cat.id ? 'rgba(6, 182, 212, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                color: destCategory === cat.id ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                transition: 'all 0.15s ease',
              }}
            >
              <span>{cat.label}</span>
              <span style={{ fontSize: '0.65rem', opacity: 0.7 }}>{cat.badge}</span>
            </button>
          ))}
        </div>
      </div>

      <hr style={{ borderColor: 'var(--border-subtle)' }} />

      {/* Natural Language Query */}
      <form onSubmit={(e) => handleNlSubmit(e)} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: '600' }}>
            Ask AccessGrid (Natural Language)
          </label>
          {isNlLoading && (
            <span style={{ fontSize: '0.68rem', color: 'var(--accent-cyan)' }}>Processing...</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <input
            type="text"
            className="chat-input"
            style={{ fontSize: '0.78rem', padding: '8px 10px' }}
            placeholder='e.g. "What if Dakshin Marg is closed?"'
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            disabled={isNlLoading}
          />
          <button
            type="submit"
            className="btn-primary"
            style={{ padding: '8px 12px', minWidth: '40px' }}
            disabled={isNlLoading || !nlQuery.trim()}
          >
            <Sparkles size={14} className={isNlLoading ? 'animate-spin' : ''} />
          </button>
        </div>

        {/* Quick Suggestion Chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '2px' }}>
          {[
            'Dakshin Marg closure',
            'Monsoon flood',
            'Route to DPS School',
            'Bypass to Sector 17 Market',
            'VIP lockdown',
          ].map((chip) => (
            <button
              key={chip}
              type="button"
              onClick={() => handleChipClick(chip)}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '12px',
                padding: '2px 8px',
                fontSize: '0.66rem',
                color: 'var(--text-dim)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--accent-cyan)')}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
            >
              {chip}
            </button>
          ))}
        </div>

        {/* Parsed Feedback Display */}
        {parsedIntent && (
          <div style={{
            fontSize: '0.7rem',
            padding: '4px 8px',
            borderRadius: '4px',
            background: parsedIntent.action === 'help' ? 'rgba(244, 63, 94, 0.1)' : 'rgba(6, 182, 212, 0.1)',
            border: `1px solid ${parsedIntent.action === 'help' ? 'rgba(244, 63, 94, 0.2)' : 'rgba(6, 182, 212, 0.2)'}`,
            color: parsedIntent.action === 'help' ? 'var(--accent-rose)' : 'var(--accent-cyan)',
            marginTop: '2px',
          }}>
            {parsedIntent.action === 'preset' && (
              <span>⚡ Running preset: <strong>{parsedIntent.scenario_title || parsedIntent.preset_id}</strong></span>
            )}
            {parsedIntent.action === 'close' && parsedIntent.road && (
              <span>🚫 Simulating closure: <strong>{parsedIntent.road}</strong></span>
            )}
            {(parsedIntent.action === 'facility' || parsedIntent.action === 'add_facility') && parsedIntent.road && (
              <span>🏥 Siting mobile triage: <strong>{parsedIntent.road}</strong></span>
            )}
            {parsedIntent.action === 'corridor' && parsedIntent.road && (
              <span>🟢 Activating green wave: <strong>{parsedIntent.road}</strong></span>
            )}
            {(parsedIntent.action === 'reopen' || parsedIntent.action === 'coverage') && (
              <span>🔄 Reset to baseline coverage</span>
            )}
            {parsedIntent.action === 'help' && (
              <span>ℹ️ {parsedIntent.message || 'Please specify a road name or disaster preset.'}</span>
            )}
          </div>
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
              checked={showAltRoute}
              onChange={(e) => setShowAltRoute && setShowAltRoute(e.target.checked)}
              style={{ accentColor: 'var(--accent-emerald)' }}
            />
            Show Alternative Detour Routes
          </label>
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
