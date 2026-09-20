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
  const [destCategory, setDestCategory] = useState('all');
  const [showAltRoute, setShowAltRoute] = useState(true);
  const [clickedRoute, setClickedRoute] = useState(null);
  const [originCoord, setOriginCoord] = useState(null);
  const [activeScenario, setActiveScenario] = useState(null);
  const [selectedIntervention, setSelectedIntervention] = useState(null);
  const [activeTab, setActiveTab] = useState('surge');
  const [showIsochrones, setShowIsochrones] = useState(true);
  const [showRiskiest, setShowRiskiest] = useState(true);
  const [loading, setLoading] = useState(false);

  // Initial Load
  useEffect(() => {
    fetchOverview(threshold, destCategory);
    fetch('/api/presets')
      .then((r) => r.json())
      .then((data) => setPresets(data))
      .catch((e) => console.error('Error fetching presets:', e));
    fetch('/api/roads')
      .then((r) => r.json())
      .then((data) => setRoads(data))
      .catch((e) => console.error('Error fetching roads:', e));
  }, []);

  const fetchOverview = async (thresh, cat = 'all') => {
    try {
      const res = await fetch(`/api/overview?threshold=${thresh}&category=${cat}`);
      const data = await res.json();
      setOverview(data);
    } catch (e) {
      console.error('Error fetching overview:', e);
    }
  };

  const handleThresholdChange = (val) => {
    setThreshold(val);
    fetchOverview(val, destCategory);
    if (activeScenario) {
      handleRunScenario({ ...activeScenario.params, threshold: val, category: destCategory });
    }
  };

  const handleDestCategoryChange = (cat) => {
    setDestCategory(cat);
    fetchOverview(threshold, cat);
    if (originCoord) {
      // Re-calculate route for new destination category
      handleMapClick(originCoord.lat, originCoord.lng, cat);
    }
  };

  const handleRunScenario = async (params) => {
    setLoading(true);
    setSelectedIntervention(null);
    setClickedRoute(null);
    setOriginCoord(null);
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...params, threshold, category: destCategory }),
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

  const handleMapClick = async (lat, lng, targetCategory = destCategory) => {
    setOriginCoord({ lat, lng });
    try {
      const routePayload = {
        origin_lat: lat,
        origin_lng: lng,
        category: targetCategory === 'all' ? 'hospital' : targetCategory,
      };

      if (activeScenario?.params?.preset_id) {
        routePayload.preset_id = activeScenario.params.preset_id;
      } else if (activeScenario?.params?.road) {
        routePayload.road = activeScenario.params.road;
      } else if (activeScenario?.closed_edges) {
        routePayload.closed_edges = activeScenario.closed_edges;
      }

      const res = await fetch('/api/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(routePayload),
      });
      const data = await res.json();
      setClickedRoute(data);
    } catch (err) {
      console.error('Point routing error:', err);
    }
  };

  const handleClearRoute = () => {
    setClickedRoute(null);
    setOriginCoord(null);
  };

  const handleReset = () => {
    setActiveScenario(null);
    setSelectedIntervention(null);
    setClickedRoute(null);
    setOriginCoord(null);
    fetchOverview(threshold, destCategory);
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

  const closedGeoms = selectedIntervention
    ? (selectedIntervention.closed_geometries || [])
    : (activeScenario?.closed_geometries || []);

  const boostGeoms = (selectedIntervention && selectedIntervention.boost_geometries?.length)
    ? selectedIntervention.boost_geometries
    : (activeScenario?.boost_geometries || []);

  const facilityCoord = selectedIntervention?.facility_coord || activeScenario?.facility_coord || null;

  const currentAltRoute = clickedRoute || (showAltRoute ? activeScenario?.alternative_route : null);

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
          destCategory={destCategory}
          onDestCategoryChange={handleDestCategoryChange}
          showAltRoute={showAltRoute}
          setShowAltRoute={setShowAltRoute}
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

          {/* Active Intervention Preview Banner */}
          {selectedIntervention && (
            <div
              style={{
                position: 'absolute',
                top: '12px',
                left: '50%',
                transform: 'translateX(-50%)',
                zIndex: 1000,
                background: 'rgba(15, 23, 42, 0.94)',
                border: '1px solid var(--accent-cyan)',
                boxShadow: '0 8px 32px rgba(6, 182, 212, 0.3)',
                borderRadius: '8px',
                padding: '8px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                backdropFilter: 'blur(8px)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Zap size={15} color="var(--accent-cyan)" />
                <span style={{ fontSize: '0.78rem', fontWeight: '700', color: '#ffffff' }}>
                  Preview: {selectedIntervention.name}
                </span>
              </div>
              <span className="badge badge-emerald" style={{ fontSize: '0.7rem' }}>
                -{selectedIntervention.debt_reduction_pct?.toFixed(1)}% Debt
              </span>
              <span className="badge badge-cyan" style={{ fontSize: '0.7rem' }}>
                +{selectedIntervention.population_restored?.toLocaleString()} Restored
              </span>
              <button
                onClick={() => setSelectedIntervention(null)}
                style={{
                  background: 'rgba(255,255,255,0.1)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  color: '#ffffff',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.7rem',
                  padding: '2px 8px',
                  marginLeft: '4px',
                }}
              >
                ✕ Exit Preview
              </button>
            </div>
          )}

          {/* Leaflet Map */}
          <div className="map-wrapper">
            <MapComponent
              centre={overview?.centre}
              hospitals={overview?.hospitals || []}
              destinations={overview?.destinations || []}
              destCategory={destCategory}
              isochrones={isochronesData}
              closedGeoms={closedGeoms}
              boostGeoms={boostGeoms}
              riskiest={overview?.riskiest_corridors || []}
              facilityCoord={facilityCoord}
              alternativeRoute={currentAltRoute}
              originCoord={originCoord}
              onMapClick={handleMapClick}
              onClearRoute={handleClearRoute}
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
