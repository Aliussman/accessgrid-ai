import React, { useState, useEffect } from 'react';
import {
  Activity,
  ShieldAlert,
  Bot,
  Zap,
  Clock,
  RotateCcw,
  Sliders,
  Layers,
  FileDown,
  Navigation,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';

import MapComponent from './components/MapComponent';
import ScenarioStudio from './components/ScenarioStudio';
import HospitalSurgePanel from './components/HospitalSurgePanel';
import InterventionsPanel from './components/InterventionsPanel';
import CopilotPanel from './components/CopilotPanel';

export default function App() {
  const [overview, setOverview] = useState(null);
  const [presets, setPresets] = useState({});
  const [roads, setRoads] = useState([]);
  const [threshold, setThreshold] = useState(15);
  const [activeScenario, setActiveScenario] = useState(null);
  const [selectedIntervention, setSelectedIntervention] = useState(null);
  const [activeTab, setActiveTab] = useState('surge');
  const [showIsochrones, setShowIsochrones] = useState(true);
  const [showRiskiest, setShowRiskiest] = useState(true);
  const [loading, setLoading] = useState(false);

  // Initial Load
  useEffect(() => {
    fetchOverview(threshold);
    fetch('/api/presets')
      .then((r) => r.json())
      .then((data) => setPresets(data))
      .catch((e) => console.error('Error fetching presets:', e));
    fetch('/api/roads')
      .then((r) => r.json())
      .then((data) => setRoads(data))
      .catch((e) => console.error('Error fetching roads:', e));
  }, []);

  const fetchOverview = async (thresh) => {
    try {
      const res = await fetch(`/api/overview?threshold=${thresh}`);
      const data = await res.json();
      setOverview(data);
    } catch (e) {
      console.error('Error fetching overview:', e);
    }
  };

  const handleThresholdChange = (val) => {
    setThreshold(val);
    fetchOverview(val);
    if (activeScenario) {
      handleRunScenario({ ...activeScenario.params, threshold: val });
    }
  };

  const handleRunScenario = async (params) => {
    setLoading(true);
    setSelectedIntervention(null);
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...params, threshold }),
      });
      const data = await res.json();
      setActiveScenario({ ...data, params });
      if (data.candidates && data.candidates.length > 0) {
        setActiveTab('surge');
      }
    } catch (err) {
      console.error('Simulation error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setActiveScenario(null);
    setSelectedIntervention(null);
    fetchOverview(threshold);
  };

  // Determine HUD Values
  const isDisrupted = activeScenario && activeScenario.status === 'disrupted';
  const totalPop = overview?.total_pop || 0;
  const coveredPop = isDisrupted
    ? totalPop - (activeScenario?.pop_lost_coverage || 0)
    : overview?.covered_pop || 0;
  const avgTime = isDisrupted ? activeScenario?.avg_access_after : overview?.avg_access_min || 0;
  const timeDelta = isDisrupted ? (activeScenario?.avg_access_after - activeScenario?.avg_access_before) : 0;
  const debt = isDisrupted ? activeScenario?.debt_pop_minutes : 0;
  const lostPop = isDisrupted ? activeScenario?.pop_lost_coverage : 0;

  // Map Data Setup
  const isochronesData = isDisrupted
    ? activeScenario.isochrone_sample || overview?.isochrone_sample || []
    : overview?.isochrone_sample || [];

  const closedGeoms = selectedIntervention?.boost_edges
    ? [] // when previewing, display adjusted geometry
    : activeScenario?.closed_geometries || [];

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <header className="app-header">
        <div className="logo-container">
          <div className="logo-badge">
            <Navigation size={22} color="#ffffff" />
          </div>
          <div>
            <div className="brand-title">AccessGrid AI</div>
            <div className="brand-subtitle">Emergency Urban Access Digital Twin · Mohali / Chandigarh Metro</div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {isDisrupted ? (
            <div className="badge badge-rose" style={{ padding: '6px 12px', fontSize: '0.8rem' }}>
              <span className="pulse-dot" style={{ background: '#f43f5e' }}></span>
              Disruption Active: {activeScenario.scenario_title}
            </div>
          ) : (
            <div className="badge badge-emerald" style={{ padding: '6px 12px', fontSize: '0.8rem' }}>
              <span className="pulse-dot" style={{ background: '#10b981' }}></span>
              Digital Twin Online: Baseline Normal
            </div>
          )}

          {isDisrupted && (
            <button onClick={handleReset} className="btn-secondary">
              <RotateCcw size={14} /> Clear Scenario
            </button>
          )}
        </div>
      </header>

      {/* Main Cockpit */}
      <div className="app-container">
        {/* Left Control Studio */}
        <ScenarioStudio
          presets={presets}
          roads={roads}
          threshold={threshold}
          onThresholdChange={handleThresholdChange}
          onRunScenario={handleRunScenario}
          onReset={handleReset}
          loading={loading}
          activeScenario={activeScenario}
          showIsochrones={showIsochrones}
          setShowIsochrones={setShowIsochrones}
          showRiskiest={showRiskiest}
          setShowRiskiest={setShowRiskiest}
        />

        {/* Center Interactive Map & Floating HUD */}
        <div className="map-canvas-container">
          {/* Floating HUD */}
          <div className="floating-hud">
            <div className="hud-card">
              <div className="hud-label">
                <Clock size={14} color={isDisrupted ? 'var(--accent-rose)' : 'var(--accent-cyan)'} />
                {isDisrupted ? 'Avg Zone Delay' : 'Avg Access Time'}
              </div>
              <div className="hud-value" style={{ color: isDisrupted ? '#f87171' : '#ffffff' }}>
                {isDisrupted
                  ? `+${(activeScenario?.per_capita_debt_min || timeDelta).toFixed(1)} min`
                  : `${avgTime?.toFixed(1)} min`}
              </div>
              {isDisrupted ? (
                <div className="hud-delta danger">
                  {activeScenario?.pop_affected?.toLocaleString()} affected (City: {avgTime?.toFixed(1)}m)
                </div>
              ) : (
                <div className="hud-delta success">Optimal Baseline Coverage</div>
              )}
            </div>

            <div className="hud-card">
              <div className="hud-label">
                <Zap size={14} color="var(--accent-amber)" />
                Accessibility Debt
              </div>
              <div className="hud-value">{debt ? debt.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '0'}</div>
              <div className="hud-delta warn">
                {isDisrupted ? `${activeScenario?.per_capita_debt_min?.toFixed(1)}m / person` : '0 pop-minutes'}
              </div>
            </div>

            <div className="hud-card">
              <div className="hud-label">
                <CheckCircle2 size={14} color="var(--accent-emerald)" />
                In-Threshold Pop
              </div>
              <div className="hud-value">{coveredPop?.toLocaleString()}</div>
              <div className="hud-delta success">
                {totalPop ? ((coveredPop / totalPop) * 100).toFixed(1) : 0}% of metro
              </div>
            </div>

            <div className="hud-card">
              <div className="hud-label">
                <ShieldAlert size={14} color="var(--accent-rose)" />
                Lost Access
              </div>
              <div className="hud-value" style={{ color: lostPop > 0 ? '#f87171' : '#ffffff' }}>
                {lostPop ? lostPop.toLocaleString() : '0'}
              </div>
              <div className={`hud-delta ${lostPop > 0 ? 'danger' : 'success'}`}>
                {lostPop > 0 ? 'Severe Care Cutoff' : 'Full In-Budget Coverage'}
              </div>
            </div>
          </div>

          {/* Floating Map Legend */}
          <div className="floating-legend">
            <span style={{ fontWeight: '700', fontSize: '0.75rem', color: '#ffffff', marginBottom: '2px' }}>
              Travel-Time Isochrones
            </span>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#10b981' }}></span>
              <span>&lt; 5 min (Rapid Care)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#3b82f6' }}></span>
              <span>5–10 min (Standard Response)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#f59e0b' }}></span>
              <span>10–15 min (Threshold Limit)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#f97316' }}></span>
              <span>15–20 min (Delayed)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#ef4444' }}></span>
              <span>&gt; 20 min / Isolated</span>
            </div>
          </div>

          {/* Leaflet Map */}
          <div className="map-wrapper">
            <MapComponent
              centre={overview?.centre}
              hospitals={overview?.hospitals || []}
              isochrones={isochronesData}
              closedGeoms={closedGeoms}
              boostGeoms={activeScenario?.boost_geometries || []}
              riskiest={overview?.riskiest_corridors || []}
              facilityCoord={activeScenario?.facility_coord}
              showIsochrones={showIsochrones}
              showRiskiest={showRiskiest}
            />
          </div>
        </div>

        {/* Right Tabbed Analytics & AI Copilot Panel */}
        <div className="right-panel glass-panel" style={{ padding: '16px' }}>
          <div className="tab-nav">
            <button
              className={`tab-btn ${activeTab === 'surge' ? 'active' : ''}`}
              onClick={() => setActiveTab('surge')}
            >
              <Activity size={14} /> Hospital Surge
            </button>
            <button
              className={`tab-btn ${activeTab === 'interventions' ? 'active' : ''}`}
              onClick={() => setActiveTab('interventions')}
            >
              <Zap size={14} /> Interventions
            </button>
            <button
              className={`tab-btn ${activeTab === 'copilot' ? 'active' : ''}`}
              onClick={() => setActiveTab('copilot')}
            >
              <Bot size={14} /> AI Copilot
            </button>
          </div>

          {activeTab === 'surge' && (
            <HospitalSurgePanel
              surge={activeScenario?.surge || []}
              equity={activeScenario?.equity || {}}
              impact={activeScenario}
            />
          )}

          {activeTab === 'interventions' && (
            <InterventionsPanel
              candidates={activeScenario?.candidates || []}
              activeIntervention={selectedIntervention?.name}
              onSelectIntervention={(cand) => setSelectedIntervention(cand)}
              impact={activeScenario}
            />
          )}

          {activeTab === 'copilot' && (
            <CopilotPanel
              impact={activeScenario}
              candidates={activeScenario?.candidates || []}
            />
          )}
        </div>
      </div>
    </div>
  );
}
