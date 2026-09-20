import React, { useState } from 'react';
import {
  Play,
  RotateCcw,
  Sparkles,
  Sliders,
  Scissors,
  MapPin,
  ChevronDown,
  ChevronUp,
  Layers,
  Zap,
  Flame,
  ShieldAlert,
  Search,
} from 'lucide-react';

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
  nodeClosureMode = false,
  setNodeClosureMode,
  pointA = null,
  pointB = null,
  nodeClosureResolved = null,
  isResolvingNodes = false,
  onClearNodeClosure,
  onRunNodeClosure,
}) {
  // Main Studio Mode: 'presets' | 'custom' | 'nl'
  const [studioTab, setStudioTab] = useState('presets');

  // Custom Blockade Sub-mode: 'map' | 'road'
  const [customSubMode, setCustomSubMode] = useState('map');
  const [selectedRoad, setSelectedRoad] = useState('');
  const [scenarioType, setScenarioType] = useState('closure');

  // Natural Language
  const [nlQuery, setNlQuery] = useState('');
  const [parsedIntent, setParsedIntent] = useState(null);
  const [isNlLoading, setIsNlLoading] = useState(false);

  // Settings Collapsible
  const [showSettings, setShowSettings] = useState(false);

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
    <div className="sidebar-panel glass-panel" style={{ gap: '12px' }}>
      {/* 1. Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Zap size={16} color="var(--accent-cyan)" />
          Scenario Studio
        </h3>
        {activeScenario && (
          <button onClick={onReset} className="btn-secondary" style={{ padding: '4px 10px', fontSize: '0.72rem' }}>
            <RotateCcw size={12} /> Clear Disruption
          </button>
        )}
      </div>

      {/* 2. Destination Category Selector (Compact Pills) */}
      <div>
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: '600', marginBottom: '4px' }}>
          Destination Layer:
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '4px' }}>
          {[
            { id: 'all', label: 'All', icon: '🌐' },
            { id: 'hospital', label: 'Hospitals', icon: '🏥' },
            { id: 'school', label: 'Schools', icon: '🏫' },
            { id: 'market', label: 'Markets', icon: '🛒' },
          ].map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => onDestCategoryChange && onDestCategoryChange(cat.id)}
              style={{
                fontSize: '0.68rem',
                fontWeight: '600',
                padding: '5px 2px',
                borderRadius: '6px',
                border: '1px solid',
                borderColor: destCategory === cat.id ? 'var(--accent-cyan)' : 'var(--border-subtle)',
                background: destCategory === cat.id ? 'rgba(6, 182, 212, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                color: destCategory === cat.id ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
                textAlign: 'center',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s ease',
              }}
            >
              <span>{cat.icon} {cat.label}</span>
            </button>
          ))}
        </div>
      </div>

      <hr style={{ borderColor: 'var(--border-subtle)', margin: '2px 0' }} />

      {/* 3. Primary Mode Tabs */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr 1fr',
        gap: '4px',
        background: 'rgba(0, 0, 0, 0.25)',
        padding: '3px',
        borderRadius: '8px',
      }}>
        {[
          { id: 'presets', label: '🌊 Presets' },
          { id: 'custom', label: '✂️ Custom Cut' },
          { id: 'nl', label: '💬 Ask AI' },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setStudioTab(tab.id);
              if (tab.id === 'custom') {
                setNodeClosureMode(true);
              } else if (nodeClosureMode) {
                setNodeClosureMode(false);
              }
            }}
            style={{
              fontSize: '0.72rem',
              fontWeight: '700',
              padding: '6px 4px',
              borderRadius: '6px',
              border: 'none',
              background: studioTab === tab.id ? 'var(--accent-cyan)' : 'transparent',
              color: studioTab === tab.id ? '#070a13' : 'var(--text-dim)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB 1: 🌊 1-Click Multi-Hazard Presets */}
      {studioTab === 'presets' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            Simulate realistic disaster & emergency events with one click:
          </div>
          {Object.entries(presets).map(([key, p]) => (
            <div
              key={key}
              className={`preset-card ${activeScenario?.preset_id === key ? 'active' : ''}`}
              onClick={() => onRunScenario({ scenario: 'closure', preset_id: key })}
              style={{ padding: '10px 12px' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '3px' }}>
                <span style={{ fontWeight: '700', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>{p.icon}</span> {p.title}
                </span>
                <span className="badge badge-rose" style={{ fontSize: '0.62rem' }}>{p.segments_count} cuts</span>
              </div>
              <p style={{ fontSize: '0.7rem', color: 'var(--text-dim)', lineHeight: '1.3', margin: 0 }}>
                {p.description}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* TAB 2: ✂️ Custom Road Blockade (Map Click or Road Select) */}
      {studioTab === 'custom' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {/* Sub-selector: Point-to-Point vs By Road Name */}
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              type="button"
              onClick={() => {
                setCustomSubMode('map');
                setNodeClosureMode(true);
              }}
              style={{
                flex: 1,
                fontSize: '0.7rem',
                fontWeight: '600',
                padding: '6px 4px',
                borderRadius: '6px',
                border: '1px solid',
                borderColor: customSubMode === 'map' ? 'var(--accent-rose)' : 'var(--border-subtle)',
                background: customSubMode === 'map' ? 'rgba(244, 63, 94, 0.15)' : 'transparent',
                color: customSubMode === 'map' ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >
              📍 Pick on Map (2 Points)
            </button>
            <button
              type="button"
              onClick={() => {
                setCustomSubMode('road');
                setNodeClosureMode(false);
              }}
              style={{
                flex: 1,
                fontSize: '0.7rem',
                fontWeight: '600',
                padding: '6px 4px',
                borderRadius: '6px',
                border: '1px solid',
                borderColor: customSubMode === 'road' ? 'var(--accent-cyan)' : 'var(--border-subtle)',
                background: customSubMode === 'road' ? 'rgba(6, 182, 212, 0.15)' : 'transparent',
                color: customSubMode === 'road' ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >
              🛣️ Pick by Road Name
            </button>
          </div>

          {/* Sub-Mode 1: Interactive Point-to-Point */}
          {customSubMode === 'map' && (
            <div style={{
              background: 'rgba(244, 63, 94, 0.06)',
              border: '1px solid rgba(244, 63, 94, 0.25)',
              borderRadius: '8px',
              padding: '10px',
            }}>
              <div style={{ fontSize: '0.72rem', color: '#cbd5e1', marginBottom: '8px', lineHeight: '1.3' }}>
                {!pointA
                  ? '👉 Step 1: Click the starting point of the road closure on the map.'
                  : !pointB
                  ? '👉 Step 2: Click the ending point of the road closure.'
                  : '✅ Road stretch selected! Ready to simulate disruption.'}
              </div>

              {/* Status Points */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: '0.68rem',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: pointA ? 'rgba(245, 158, 11, 0.15)' : 'rgba(0,0,0,0.2)',
                  color: pointA ? 'var(--accent-amber)' : 'var(--text-dim)',
                }}>
                  <span>🅰️ Start Point: {pointA ? `${pointA.lat.toFixed(4)}, ${pointA.lng.toFixed(4)}` : 'Click on map'}</span>
                  {pointA && <span style={{ fontWeight: '700' }}>✓</span>}
                </div>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: '0.68rem',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: pointB ? 'rgba(244, 63, 94, 0.15)' : 'rgba(0,0,0,0.2)',
                  color: pointB ? 'var(--accent-rose)' : 'var(--text-dim)',
                }}>
                  <span>🅱️ End Point: {pointB ? `${pointB.lat.toFixed(4)}, ${pointB.lng.toFixed(4)}` : 'Click on map'}</span>
                  {pointB && <span style={{ fontWeight: '700' }}>✓</span>}
                </div>
              </div>

              {isResolvingNodes && (
                <div style={{ fontSize: '0.68rem', color: 'var(--accent-cyan)', textAlign: 'center', marginBottom: '6px' }}>
                  Finding connecting road corridor...
                </div>
              )}

              {nodeClosureResolved && (
                <div style={{
                  fontSize: '0.68rem',
                  color: 'var(--accent-emerald)',
                  marginBottom: '8px',
                  background: 'rgba(16, 185, 129, 0.1)',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  display: 'flex',
                  justifyContent: 'space-between',
                }}>
                  <span>🛣️ Corridor Identified:</span>
                  <span style={{ fontWeight: '700' }}>{nodeClosureResolved.edge_count} road segments</span>
                </div>
              )}

              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  type="button"
                  className="btn-primary"
                  style={{
                    flex: 1,
                    fontSize: '0.72rem',
                    padding: '6px 8px',
                    background: nodeClosureResolved ? 'var(--accent-rose)' : undefined,
                    borderColor: nodeClosureResolved ? 'var(--accent-rose)' : undefined,
                  }}
                  disabled={!nodeClosureResolved || loading}
                  onClick={onRunNodeClosure}
                >
                  ⛔ Simulate Blockade
                </button>
                {(pointA || pointB || nodeClosureResolved) && (
                  <button
                    type="button"
                    className="btn-secondary"
                    style={{ fontSize: '0.72rem', padding: '6px 8px' }}
                    onClick={onClearNodeClosure}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Sub-Mode 2: Targeted Road Dropdown */}
          {customSubMode === 'road' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <select
                className="chat-input"
                style={{ width: '100%', fontSize: '0.78rem' }}
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
                style={{ width: '100%', fontSize: '0.75rem' }}
                disabled={!selectedRoad || loading}
                onClick={() => onRunScenario({ scenario: 'closure', road: selectedRoad })}
              >
                <Play size={14} /> Simulate Road Closure
              </button>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: 💬 Natural Language AI */}
      {studioTab === 'nl' && (
        <form onSubmit={(e) => handleNlSubmit(e)} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '6px' }}>
            <input
              type="text"
              className="chat-input"
              style={{ fontSize: '0.75rem', padding: '7px 10px', flex: 1 }}
              placeholder='e.g. "Close Dakshin Marg"'
              value={nlQuery}
              onChange={(e) => setNlQuery(e.target.value)}
              disabled={isNlLoading}
            />
            <button
              type="submit"
              className="btn-primary"
              style={{ padding: '7px 10px' }}
              disabled={isNlLoading || !nlQuery.trim()}
            >
              <Sparkles size={14} className={isNlLoading ? 'animate-spin' : ''} />
            </button>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            {[
              'Dakshin Marg closure',
              'Monsoon flood',
              'VIP lockdown',
              'Reset to normal',
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
                  fontSize: '0.64rem',
                  color: 'var(--text-dim)',
                  cursor: 'pointer',
                }}
              >
                {chip}
              </button>
            ))}
          </div>

          {parsedIntent && (
            <div style={{
              fontSize: '0.68rem',
              padding: '5px 8px',
              borderRadius: '4px',
              background: 'rgba(6, 182, 212, 0.1)',
              border: '1px solid rgba(6, 182, 212, 0.2)',
              color: 'var(--accent-cyan)',
            }}>
              ⚡ Action: <strong>{parsedIntent.scenario_title || parsedIntent.road || parsedIntent.action}</strong>
            </div>
          )}
        </form>
      )}

      {/* 4. Collapsible Settings (Threshold & Map Layers) */}
      <div style={{
        marginTop: 'auto',
        background: 'rgba(0, 0, 0, 0.2)',
        borderRadius: '8px',
        border: '1px solid var(--border-subtle)',
        overflow: 'hidden',
      }}>
        <button
          type="button"
          onClick={() => setShowSettings(!showSettings)}
          style={{
            width: '100%',
            background: 'transparent',
            border: 'none',
            padding: '8px 10px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '0.72rem',
            fontWeight: '600',
            color: 'var(--text-dim)',
            cursor: 'pointer',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Sliders size={13} /> Golden Hour & Layer Settings
          </span>
          {showSettings ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {showSettings && (
          <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Emergency Threshold</span>
                <span style={{ color: 'var(--accent-cyan)', fontWeight: '700' }}>{threshold} Minutes</span>
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

            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={showAltRoute}
                  onChange={(e) => setShowAltRoute && setShowAltRoute(e.target.checked)}
                  style={{ accentColor: 'var(--accent-emerald)' }}
                />
                Show Detour Routes
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={showIsochrones}
                  onChange={(e) => setShowIsochrones(e.target.checked)}
                  style={{ accentColor: 'var(--accent-cyan)' }}
                />
                Show Isochrone Rings
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={showRiskiest}
                  onChange={(e) => setShowRiskiest(e.target.checked)}
                  style={{ accentColor: 'var(--accent-cyan)' }}
                />
                Show Riskiest Corridors
              </label>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
